"""Portable command-line entry point: python -m research_lab."""

import argparse
import json
import sqlite3
import sys
from dataclasses import asdict
from pathlib import Path

from .corpus import SUPPORTED_INPUTS, Corpus
from .evaluation import evaluate_bundle, oracle_for
from .fixtures import CASES
from .playbooks import dissect
from .runtime import compare, configuration, find_run, run_fixture, verify_run
from .serde import write_json


def parser() -> argparse.ArgumentParser:
    app = argparse.ArgumentParser(description="Offline equity research experiment lab")
    app.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Local storage root (defaults to the working directory)",
    )
    app.add_argument("--config", type=Path, help="Fixture configuration TOML")
    commands = app.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "doctor", help="Check local runtime and supported routes without credentials"
    )
    ingest = commands.add_parser(
        "ingest", help="Hash, copy, inventory, and extract native text/CSV"
    )
    ingest.add_argument("--input", type=Path, required=True)
    ingest.add_argument(
        "--role",
        choices=["discovery", "development", "locked_evaluation", "archive"],
        required=True,
    )
    ingest.add_argument("--published-at")
    ingest.add_argument("--available-at")
    ingest.add_argument(
        "--availability-evidence", default="User-supplied metadata; not independently reviewed"
    )
    for name in ("inspect", "dissect"):
        sub = commands.add_parser(name)
        sub.add_argument("--document", required=True)
    run = commands.add_parser("run", help="Run one deterministic synthetic assignment")
    run.add_argument("--case", choices=CASES, default="clean")
    run.add_argument("--variant", choices=["generic", "candidate"], default="generic")
    comparison = commands.add_parser(
        "compare", help="Compare generic and synthetic candidate workflows"
    )
    comparison.add_argument("--cases", nargs="+", choices=CASES, default=["clean"])
    commands.add_parser("demo", help="Build the complete six-case, two-variant review bundle")
    for name in ("replay", "evaluate"):
        sub = commands.add_parser(name)
        sub.add_argument("--run", required=True)
    return app


def output(value) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    root = args.root.resolve()
    try:
        if args.command == "doctor":
            config = configuration(args.config)
            compatible = (3, 12) <= sys.version_info[:2] < (3, 15)
            output(
                {
                    "python": sys.version.split()[0],
                    "python_supported": compatible,
                    "sqlite": sqlite3.sqlite_version,
                    "mode": config["mode"],
                    "model_route": config["model_id"],
                    "data_handling": config["data_handling"],
                    "runtime_dependencies": [],
                    "input_directory": str(root / "data" / "incoming"),
                    "native_extraction": [".txt", ".md", ".csv"],
                    "pdf": "Immutable intake only; parser study pending",
                    "live_model": "Not implemented; no credentials required for fixture mode",
                }
            )
            return 0 if compatible else 1
        if args.command == "ingest":
            corpus = Corpus(root)
            paths = (
                sorted(
                    p
                    for p in args.input.rglob("*")
                    if p.is_file() and p.suffix.lower() in SUPPORTED_INPUTS
                )
                if args.input.is_dir()
                else [args.input]
            )
            documents = [
                corpus.ingest(
                    p,
                    role=args.role,
                    available_at=args.available_at,
                    published_at=args.published_at,
                    availability_evidence=args.availability_evidence,
                )
                for p in paths
            ]
            output({"documents": [asdict(d) for d in documents], "count": len(documents)})
        elif args.command == "inspect":
            corpus = Corpus(root)
            output(
                {
                    "document": asdict(corpus.document(args.document)),
                    "spans": [asdict(s) for s in corpus.spans(args.document)],
                }
            )
        elif args.command == "dissect":
            output(dissect(Corpus(root), args.document))
        elif args.command == "run":
            result = run_fixture(
                root, case=args.case, variant=args.variant, config=configuration(args.config)
            )
            output(
                {
                    "run_id": result["run_id"],
                    "status": result["status"],
                    "evaluation_status": result["evaluation"]["status"],
                    "review": str(Path(result["run_dir"]) / "review.html"),
                }
            )
            return 0 if result["status"] == "completed" else 1
        elif args.command in ("compare", "demo"):
            result = compare(
                root,
                cases=CASES if args.command == "demo" else args.cases,
                config=configuration(args.config),
            )
            output(
                {
                    "experiment_id": result["experiment_id"],
                    "review": result["review"],
                    "attempts": len(result["results"]),
                    "expected_outcomes_observed": sum(
                        r["expected_behavior_observed"] for r in result["results"]
                    ),
                    "research_quality": "unassessed; synthetic fixture only",
                }
            )
            return 0 if all(r["expected_behavior_observed"] for r in result["results"]) else 1
        elif args.command == "replay":
            path = find_run(root, args.run)
            manifest = verify_run(path)
            output(
                {
                    "mode": "artifact_replay",
                    "integrity": "verified",
                    "run_id": args.run,
                    "status": manifest["status"],
                    "review": str(path / "review.html"),
                    "external_calls": 0,
                }
            )
        elif args.command == "evaluate":
            path = find_run(root, args.run)
            manifest = verify_run(path)
            result = evaluate_bundle(path, oracle_for(root, manifest["task_id"]))
            # Regrading never edits the sealed run. The export is a separate derivative.
            destination = root / "exports" / f"{args.run}.evaluation.json"
            write_json(destination, result)
            output({"status": result["status"], "evaluation": str(destination)})
            return 0 if result["status"] == "passed_automated_checks" else 1
        return 0
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(f"lab: {exc}", file=sys.stderr)
        return 2
