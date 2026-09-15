"""Sequential orchestration, frozen run bundles, and provider-free artifact replay."""

import random
import re
import sys
import tomllib
import uuid
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

from .adapter import Findings, FixtureAdapter
from .budget import BudgetExceeded, BudgetMeter
from .corpus import Corpus, now
from .evaluation import evaluate_bundle, oracle_for
from .evidence import EvidenceView, build_packet
from .fixtures import CASES, PROJECT, prepare_case
from .playbooks import load_playbook
from .rendering import render_comparison, render_run, report_markdown
from .schemas import BudgetLimits, Issue, LabConfig, RunRecord, sha256
from .serde import atomic_write, digest, from_dict, object_hash, read_json, write_json, write_jsonl


def configuration(path: Path | None = None) -> dict:
    config = tomllib.loads((path or PROJECT / "configs" / "lab.toml").read_text(encoding="utf-8"))
    return asdict(from_dict(LabConfig, config))


def code_hash() -> str:
    return digest(
        b"".join(
            p.relative_to(PROJECT).as_posix().encode() + b"\0" + p.read_bytes()
            for p in sorted((PROJECT / "research_lab").glob("*.py"))
        )
    )


def save_findings(run_dir: Path, findings: Findings) -> None:
    write_json(run_dir / "findings.json", asdict(findings))
    write_jsonl(run_dir / "claims.jsonl", findings.claims)
    write_jsonl(run_dir / "calculations.jsonl", findings.calculations)


def seal(run_dir: Path) -> None:
    if (run_dir / "freeze.json").exists():
        raise ValueError("A frozen run cannot be overwritten")
    files = {
        p.relative_to(run_dir).as_posix(): digest(p.read_bytes())
        for p in sorted(run_dir.rglob("*"))
        if p.is_file()
    }
    write_json(run_dir / "freeze.json", {"schema_version": "1.0", "files": files})


def verify_run(run_dir: Path) -> dict:
    frozen = read_json(run_dir / "freeze.json")
    if (
        not isinstance(frozen, dict)
        or set(frozen) != {"schema_version", "files"}
        or frozen["schema_version"] != "1.0"
        or not isinstance(frozen["files"], dict)
    ):
        raise ValueError("Unsupported frozen-run schema")
    for name, expected in frozen["files"].items():
        if not isinstance(name, str) or not isinstance(expected, str):
            raise ValueError("Invalid frozen artifact inventory")
        sha256(expected)
    actual = {
        p.relative_to(run_dir).as_posix()
        for p in run_dir.rglob("*")
        if p.is_file() and p != run_dir / "freeze.json"
    }
    if actual != set(frozen["files"]):
        raise ValueError("Frozen run file inventory changed")
    for name, expected in frozen["files"].items():
        path = (run_dir / name).resolve()
        if not path.is_relative_to(run_dir.resolve()) or digest(path.read_bytes()) != expected:
            raise ValueError(f"Frozen artifact integrity check failed: {name}")
    return read_json(run_dir / "manifest.json")


def find_run(root: Path, run_id: str) -> Path:
    if not re.fullmatch(r"run_[a-f0-9]{32}", run_id):
        raise ValueError("Expected a run ID printed by the run or compare command")
    return root.resolve() / "runs" / run_id


def run_fixture(
    root: Path,
    *,
    case: str = "clean",
    variant: str = "generic",
    config: dict | None = None,
    protocol: dict | None = None,
    run_id: str | None = None,
) -> dict:
    config = configuration() if config is None else asdict(from_dict(LabConfig, config))
    if case not in CASES or variant not in ("generic", "candidate"):
        raise ValueError("Unknown fixture case or variant")
    protocol = (
        protocol
        if protocol is not None
        else {
            **read_json(PROJECT / "configs" / "experiments" / "fixture_smoke.json"),
            "cases": [case],
            "variants": [variant],
            "budget": config["budget"],
        }
    )
    run_id = run_id or "run_" + uuid.uuid4().hex
    run_dir = find_run(root, run_id)
    run_dir.mkdir(parents=True, exist_ok=False)
    started = now()
    attempt = {
        "schema_version": "1.0",
        "run_id": run_id,
        "case": case,
        "variant": variant,
        "started_at": started,
        "status": "started",
    }
    write_json(run_dir / "attempt.json", attempt)
    write_json(run_dir / "protocol.json", protocol)
    try:
        result = execute_fixture(root, run_dir, run_id, started, case, variant, config, protocol)
        write_json(
            run_dir / "attempt.json", {**attempt, "status": result["status"], "ended_at": now()}
        )
        seal(run_dir)
        return result
    except (Exception, KeyboardInterrupt) as exc:
        # Recovery artifacts are best effort if the storage device itself has failed.
        failure = {
            **attempt,
            "status": "failed",
            "ended_at": now(),
            "error_type": type(exc).__name__,
            "message": str(exc),
        }
        write_json(run_dir / "failure.json", failure)
        write_json(run_dir / "attempt.json", failure)
        if isinstance(exc, KeyboardInterrupt):
            raise
        return {
            "run_id": run_id,
            "run_dir": str(run_dir),
            "status": "failed",
            "case": case,
            "variant": variant,
            "review_available": False,
            "evaluation": {"status": "unassessed"},
            "failure": failure,
        }


def execute_fixture(
    root: Path,
    run_dir: Path,
    run_id: str,
    started: str,
    case: str,
    variant: str,
    config: dict,
    protocol: dict,
) -> dict:
    limits = from_dict(BudgetLimits, config["budget"])
    corpus = Corpus(root)
    task = prepare_case(corpus, case)
    playbook = load_playbook(corpus, variant)
    meter = BudgetMeter(limits)
    packet = build_packet(corpus, task)
    write_json(run_dir / "protocol.json", protocol)
    write_json(run_dir / "task.json", task)
    write_json(run_dir / "playbook.json", playbook)
    write_json(run_dir / "evidence.json", asdict(packet))
    write_jsonl(run_dir / "source_register.jsonl", packet.documents)
    findings = Findings()
    events: list[dict[str, Any]] = []

    def event(name, details):
        events.append(
            {
                "schema_version": "1.0",
                "run_id": run_id,
                "task_id": task.task_id,
                "sequence": len(events) + 1,
                "time": now(),
                "event": name,
                "details": details,
                "usage": meter.usage(),
            }
        )
        write_jsonl(run_dir / "trace.jsonl", events)
        save_findings(run_dir, findings)

    event(
        "run_started",
        {
            "protocol_hash": object_hash(protocol),
            "task_hash": object_hash(task),
            "adapter": config["model_id"],
            "information_cutoff": task.as_of,
        },
    )
    status: Literal["completed", "incomplete", "failed", "budget_exhausted"] = "completed"
    stopping_reason = "Material fixture questions addressed"
    adapter = FixtureAdapter()
    try:
        meter.reserve()
        actions = {a for rule in playbook["rules"] for a in rule["actions"]}
        adapter.generate(task, EvidenceView(packet, meter), actions, meter, findings, event)
        if findings.issues or packet.issues:
            status, stopping_reason = (
                "incomplete",
                "Remaining material inputs are unavailable or incompatible",
            )
    except BudgetExceeded as exc:
        status, stopping_reason = "budget_exhausted", str(exc)
        findings.issues.append(Issue(code="budget_exhausted", message=str(exc), stage="runtime"))
    except Exception as exc:
        status, stopping_reason = "failed", "Infrastructure failure; partial results preserved"
        findings.issues.append(
            Issue(code="infrastructure", message=f"{type(exc).__name__}: {exc}", stage="runtime")
        )
    save_findings(run_dir, findings)
    report = report_markdown(task, findings.claims)
    if case == "unsupported_sentence":
        report += "\nManagement confirmed that demand will double next year.\n"
    atomic_write(run_dir / "report.md", report.encode("utf-8"))
    # Evaluator access starts only after the adapter has returned its frozen analytical output.
    oracle = oracle_for(root, task.task_id)
    evaluation = evaluate_bundle(run_dir, oracle)
    if evaluation["status"] == "failed":
        status, stopping_reason = "failed", "Independent final evaluation found a critical defect"
    elif evaluation["status"] == "incomplete" and status == "completed":
        status, stopping_reason = (
            "incomplete",
            "Independent evaluation found unresolved material questions",
        )
    write_json(run_dir / "evaluation.json", evaluation)
    event(
        "run_stopped",
        {
            "status": status,
            "stopping_reason": stopping_reason,
            "evaluation_status": evaluation["status"],
        },
    )
    manifest = RunRecord(
        run_id=run_id,
        task_id=task.task_id,
        variant=variant,
        started_at=started,
        ended_at=now(),
        status=status,
        stopping_reason=stopping_reason,
        protocol_hash=object_hash(protocol),
        task_hash=object_hash(task),
        playbook_hash=object_hash(playbook),
        code_hash=code_hash(),
        dependency_lock_hash=digest((PROJECT / "uv.lock").read_bytes()),
        provider=adapter.provider,
        model_id=adapter.model_id,
        budget=limits,
        usage=meter.usage(),
        source_manifest_hash=object_hash(task.allowed_sources),
        generation_parameters={"python": sys.version.split()[0]},
    )
    write_json(run_dir / "manifest.json", manifest)
    render_run(
        run_dir, asdict(manifest), task, asdict(packet), asdict(findings), evaluation, playbook
    )
    return {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "review_available": True,
        "status": status,
        "evaluation": evaluation,
        "manifest": asdict(manifest),
        "case": case,
        "variant": variant,
    }


def compare(root: Path, *, cases: Sequence[str] | None = None, config: dict | None = None) -> dict:
    cases = list(["clean"] if cases is None else cases)
    if not cases or len(set(cases)) != len(cases) or set(cases) - set(CASES):
        raise ValueError("Comparison cases must be a nonempty, unique selection of known fixtures")
    config = configuration() if config is None else asdict(from_dict(LabConfig, config))
    protocol = {
        **read_json(PROJECT / "configs" / "experiments" / "fixture_smoke.json"),
        "cases": cases,
        "budget": config["budget"],
    }
    experiment_id = "experiment_" + uuid.uuid4().hex
    experiment_dir = root.resolve() / "runs" / "experiments" / experiment_id
    experiment_dir.mkdir(parents=True, exist_ok=False)
    write_json(experiment_dir / "protocol.json", protocol)
    labels = ["A", "B"]
    random.Random(17).shuffle(labels)
    assignments = dict(zip(protocol["variants"], labels, strict=True))
    attempts = [
        {"case": case, "variant": variant, "run_id": "run_" + uuid.uuid4().hex, "status": "planned"}
        for case in cases
        for variant in protocol["variants"]
    ]
    write_json(experiment_dir / "attempts.json", attempts)
    results = []
    oracle = read_json(PROJECT / "fixtures" / "evaluator" / "answers.json")
    for attempt in attempts:
        case, variant = attempt["case"], attempt["variant"]
        attempt["status"] = "started"
        write_json(experiment_dir / "attempts.json", attempts)
        try:
            result = run_fixture(
                root,
                case=case,
                variant=variant,
                config=config,
                protocol=protocol,
                run_id=attempt["run_id"],
            )
        except Exception as exc:
            result = {
                "status": "failed",
                "review_available": False,
                "failure": {"error_type": type(exc).__name__, "message": str(exc)},
            }
        row = {
            **attempt,
            "status": result["status"],
            "label": assignments[variant],
            "review_available": result.get("review_available", False),
        }
        if "failure" in result:
            row.update(
                evaluation_status="unassessed",
                numeric_correct=0,
                questions_answered=0,
                issue_codes=["infrastructure"],
                tool_calls="unavailable",
                source_manifest_hash=None,
                expected_behavior_observed=False,
                failure=result["failure"],
            )
        else:
            evaluation = result["evaluation"]
            score = evaluation["scorecards"]["research"]
            issue_codes = sorted({i["code"] for i in evaluation["issues"]})
            expected_code = oracle["expected_degradation"][case]
            expected_status = (
                "failed"
                if case == "unsupported_sentence"
                else "incomplete"
                if expected_code
                else "completed"
            )
            observed = (
                result["status"] == expected_status
                and "infrastructure" not in issue_codes
                and (
                    expected_code in issue_codes
                    if expected_code
                    else evaluation["status"] == "passed_automated_checks"
                )
            )
            row.update(
                evaluation_status=evaluation["status"],
                numeric_correct=score["correct_numeric_outputs"],
                questions_answered=len(score["answered_questions"]),
                issue_codes=issue_codes,
                tool_calls=result["manifest"]["usage"]["tool_calls"],
                source_manifest_hash=result["manifest"]["source_manifest_hash"],
                expected_behavior_observed=observed,
            )
        attempt["status"] = result["status"]
        results.append(row)
        write_json(experiment_dir / "attempts.json", attempts)
        write_json(
            experiment_dir / "comparison.json",
            {
                "experiment_id": experiment_id,
                "protocol": protocol,
                "assignments": assignments,
                "results": results,
            },
        )
    for case in cases:
        paired = [r for r in results if r["case"] == case]
        hashes = {r["source_manifest_hash"] for r in paired}
        if None not in hashes and len(hashes) != 1:
            for row in paired:
                row["expected_behavior_observed"] = False
                row["issue_codes"].append("comparison_evidence_mismatch")
    write_json(
        experiment_dir / "comparison.json",
        {
            "experiment_id": experiment_id,
            "protocol": protocol,
            "assignments": assignments,
            "results": results,
        },
    )
    review = render_comparison(experiment_dir, results, assignments, protocol)
    return {"experiment_id": experiment_id, "review": str(review), "results": results}
