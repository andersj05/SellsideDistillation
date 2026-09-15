"""Sequential orchestration, frozen run bundles, and provider-free artifact replay."""

from dataclasses import asdict
from pathlib import Path
import random
import re
import sys
import tomllib
import uuid

from .adapter import Findings, FixtureAdapter
from .budget import BudgetExceeded, BudgetMeter
from .corpus import Corpus, now
from .evaluation import evaluate_bundle, oracle_for
from .evidence import EvidenceView, build_packet
from .fixtures import CASES, PROJECT, prepare_case
from .playbooks import load_playbook
from .rendering import render_comparison, render_run, report_markdown
from .schemas import BudgetLimits, Issue, RunRecord
from .serde import atomic_write, digest, from_dict, object_hash, read_json, write_json, write_jsonl


def configuration(path: Path | None = None) -> dict:
    config = tomllib.loads((path or PROJECT / "configs" / "lab.toml").read_text(encoding="utf-8"))
    if (config.get("schema_version") != "1.0" or config.get("mode") != "fixture"
            or config.get("model_provider") != "offline" or config.get("model_id") != FixtureAdapter.model_id):
        raise ValueError("This milestone supports only the offline deterministic fixture route")
    from_dict(BudgetLimits, config["budget"])
    return config


def code_hash() -> str:
    return digest(b"".join(str(p.relative_to(PROJECT)).encode() + b"\0" + p.read_bytes()
                           for p in sorted((PROJECT / "research_lab").glob("*.py"))))


def save_findings(run_dir: Path, findings: Findings) -> None:
    write_json(run_dir / "findings.json", asdict(findings))
    write_jsonl(run_dir / "claims.jsonl", findings.claims)
    write_jsonl(run_dir / "calculations.jsonl", findings.calculations)


def seal(run_dir: Path) -> None:
    if (run_dir / "freeze.json").exists():
        raise ValueError("A frozen run cannot be overwritten")
    files = {p.relative_to(run_dir).as_posix(): digest(p.read_bytes())
             for p in sorted(run_dir.rglob("*")) if p.is_file()}
    write_json(run_dir / "freeze.json", {"schema_version": "1.0", "files": files})


def verify_run(run_dir: Path) -> dict:
    frozen = read_json(run_dir / "freeze.json")
    if frozen.get("schema_version") != "1.0":
        raise ValueError("Unsupported frozen-run schema")
    actual = {p.relative_to(run_dir).as_posix() for p in run_dir.rglob("*") if p.is_file() and p.name != "freeze.json"}
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


def run_fixture(root: Path, *, case="clean", variant="generic", config=None, protocol=None) -> dict:
    config = config or configuration()
    limits = from_dict(BudgetLimits, config["budget"])
    corpus = Corpus(root)
    task = prepare_case(corpus, case)
    playbook = load_playbook(corpus, variant)
    protocol = protocol or {**read_json(PROJECT / "configs" / "experiments" / "fixture_smoke.json"),
                            "cases": [case], "variants": [variant], "budget": asdict(limits)}
    run_id = "run_" + uuid.uuid4().hex
    run_dir = root.resolve() / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    started = now()
    meter = BudgetMeter(limits)
    packet = build_packet(corpus, task)
    write_json(run_dir / "protocol.json", protocol)
    write_json(run_dir / "task.json", task)
    write_json(run_dir / "playbook.json", playbook)
    write_json(run_dir / "evidence.json", asdict(packet))
    write_jsonl(run_dir / "source_register.jsonl", packet.documents)
    findings = Findings()
    events = []

    def event(name, details):
        events.append({"schema_version": "1.0", "run_id": run_id, "task_id": task.task_id,
                       "sequence": len(events) + 1, "time": now(), "event": name,
                       "details": details, "usage": meter.usage()})
        write_jsonl(run_dir / "trace.jsonl", events)
        save_findings(run_dir, findings)

    event("run_started", {"protocol_hash": object_hash(protocol), "task_hash": object_hash(task),
                          "adapter": config["model_id"], "information_cutoff": task.as_of})
    status, stopping_reason = "completed", "Material fixture questions addressed"
    adapter = FixtureAdapter()
    try:
        meter.reserve()
        actions = {a for rule in playbook["rules"] for a in rule["actions"]}
        adapter.generate(task, EvidenceView(packet, meter), actions, meter, findings, event)
        if findings.issues or packet.issues:
            status, stopping_reason = "incomplete", "Remaining material inputs are unavailable or incompatible"
    except BudgetExceeded as exc:
        status, stopping_reason = "budget_exhausted", str(exc)
        findings.issues.append(Issue(code="budget_exhausted", message=str(exc), stage="runtime"))
    except Exception as exc:
        status, stopping_reason = "failed", "Infrastructure failure; partial results preserved"
        findings.issues.append(Issue(code="infrastructure", message=f"{type(exc).__name__}: {exc}", stage="runtime"))
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
        status, stopping_reason = "incomplete", "Independent evaluation found unresolved material questions"
    write_json(run_dir / "evaluation.json", evaluation)
    event("run_stopped", {"status": status, "stopping_reason": stopping_reason, "evaluation_status": evaluation["status"]})
    manifest = RunRecord(run_id=run_id, task_id=task.task_id, variant=variant,
        started_at=started, ended_at=now(), status=status, stopping_reason=stopping_reason,
        protocol_hash=object_hash(protocol), task_hash=object_hash(task), playbook_hash=object_hash(playbook),
        code_hash=code_hash(), dependency_lock_hash=digest((PROJECT / "uv.lock").read_bytes()),
        provider=adapter.provider, model_id=adapter.model_id, budget=limits, usage=meter.usage(),
        source_manifest_hash=object_hash(task.allowed_sources), generation_parameters={"python": sys.version.split()[0]})
    write_json(run_dir / "manifest.json", manifest)
    render_run(run_dir, asdict(manifest), task, asdict(packet), asdict(findings), evaluation, playbook)
    seal(run_dir)
    return {"run_id": run_id, "run_dir": str(run_dir), "status": status, "evaluation": evaluation,
            "manifest": asdict(manifest), "case": case, "variant": variant}


def compare(root: Path, *, cases=None, config=None) -> dict:
    cases = list(cases or ["clean"])
    if not cases or len(set(cases)) != len(cases) or set(cases) - set(CASES):
        raise ValueError("Comparison cases must be a nonempty, unique selection of known fixtures")
    config = config or configuration()
    limits = from_dict(BudgetLimits, config["budget"])
    protocol = {**read_json(PROJECT / "configs" / "experiments" / "fixture_smoke.json"),
                "cases": cases, "budget": asdict(limits)}
    experiment_id = "experiment_" + uuid.uuid4().hex
    experiment_dir = root.resolve() / "runs" / "experiments" / experiment_id
    experiment_dir.mkdir(parents=True, exist_ok=False)
    write_json(experiment_dir / "protocol.json", protocol)  # Predeclare before the first run.
    labels = ["A", "B"]
    random.Random(17).shuffle(labels)
    assignments = dict(zip(protocol["variants"], labels))
    results = []
    oracle = read_json(PROJECT / "fixtures" / "evaluator" / "answers.json")
    for case in cases:
        for variant in protocol["variants"]:
            result = run_fixture(root, case=case, variant=variant, config=config, protocol=protocol)
            evaluation = result["evaluation"]
            score = evaluation["scorecards"]["research"]
            issue_codes = sorted({i["code"] for i in evaluation["issues"]})
            expected_code = oracle["expected_degradation"][case]
            results.append({"case": case, "variant": variant, "label": assignments[variant],
                "run_id": result["run_id"], "status": result["status"], "evaluation_status": evaluation["status"],
                "numeric_correct": score["correct_numeric_outputs"], "questions_answered": len(score["answered_questions"]),
                "issue_codes": issue_codes, "tool_calls": result["manifest"]["usage"]["tool_calls"],
                "source_manifest_hash": result["manifest"]["source_manifest_hash"],
                "expected_behavior_observed": expected_code in issue_codes if expected_code else evaluation["status"] == "passed_automated_checks"})
            write_json(experiment_dir / "comparison.json", {"experiment_id": experiment_id, "protocol": protocol,
                                                            "assignments": assignments, "results": results})
    for case in cases:
        paired = [r for r in results if r["case"] == case]
        if len({r["source_manifest_hash"] for r in paired}) != 1:
            raise ValueError("Comparison evidence parity failed")
    review = render_comparison(experiment_dir, results, assignments, protocol)
    return {"experiment_id": experiment_id, "review": str(review), "results": results}
