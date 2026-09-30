"""Local OCR adapters. No network calls; OCR words are unverified observations."""

import csv
import io
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .serde import digest, load_json, write_json

WINDOWS_SCRIPT = Path(__file__).parent / "resources" / "windows_ocr.ps1"


def invoke(arguments: list[str], *, timeout: int = 60) -> str:
    result = subprocess.run(
        arguments,
        check=True,
        capture_output=True,
        timeout=timeout,
        creationflags=0x08000000 if os.name == "nt" else 0,
    )
    return result.stdout.decode("utf-8-sig")


def windows_command() -> list[str]:
    executable = Path(os.environ.get("SystemRoot", "C:/Windows")) / (
        "System32/WindowsPowerShell/v1.0/powershell.exe"
    )
    return [
        str(executable),
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "RemoteSigned",
        "-File",
        str(WINDOWS_SCRIPT),
    ]


def select_engine(mode: str) -> dict[str, Any] | None:
    if mode not in ("auto", "none", "windows", "tesseract"):
        raise ValueError("Unknown OCR mode")
    if mode == "none":
        return None
    candidates = [mode] if mode != "auto" else ["windows", "tesseract"]
    errors = []
    for candidate in candidates:
        try:
            if candidate == "windows":
                if platform.system() != "Windows":
                    raise ValueError("Windows OCR requires Windows")
                details = load_json(invoke([*windows_command(), "-Info"], timeout=20))
                return {
                    "name": "windows",
                    "version": details["os_version"],
                    "language": details["language"],
                    "max_dimension": details["max_dimension"],
                    "script_sha256": digest(WINDOWS_SCRIPT.read_bytes()),
                    "model_version": None,
                    "model_version_note": "Windows does not expose the language-pack model version.",
                }
            executable = shutil.which("tesseract")
            if executable is None:
                raise ValueError("Tesseract executable is unavailable")
            languages = invoke([executable, "--list-langs"])
            if "eng" not in languages.split():
                raise ValueError("Tesseract English traineddata is unavailable")
            return {
                "name": "tesseract",
                "version": invoke([executable, "--version"]).splitlines()[0],
                "language": "eng",
                "max_dimension": 4000,
                "model_version": None,
                "model_version_note": "Installed traineddata is host-managed, not bundled.",
                "host": platform.platform(),
            }
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            errors.append(str(exc))
    if mode != "auto":
        raise ValueError("OCR unavailable: " + "; ".join(errors))
    return None


def tesseract_words(text: str) -> list[dict[str, Any]]:
    words = []
    for row in csv.DictReader(io.StringIO(text), delimiter="\t"):
        if row["level"] != "5" or not row["text"].strip():
            continue
        left, top, width, height = (int(row[key]) for key in ("left", "top", "width", "height"))
        words.append(
            {
                "text": row["text"],
                "line": ":".join(row[k] for k in ("block_num", "par_num", "line_num")),
                "bbox": [left, top, left + width, top + height],
                "confidence": float(row["conf"]),
            }
        )
    return words


def recognize(
    jobs: list[dict[str, Any]], engine: dict[str, Any], work_dir: Path
) -> list[dict[str, Any]]:
    if engine["name"] == "windows":
        path = work_dir / "ocr_jobs.json"
        write_json(path, jobs)
        try:
            output = load_json(invoke([*windows_command(), "-InputPath", str(path)]))
            if not isinstance(output, list):
                raise ValueError("OCR result must be a list")
            return output
        finally:
            path.unlink(missing_ok=True)
    results = []
    for job in jobs:
        try:
            output = invoke(["tesseract", job["path"], "stdout", "-l", "eng", "--psm", "3", "tsv"])
            results.append({"id": job["id"], "words": tesseract_words(output), "error": None})
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            results.append({"id": job["id"], "words": [], "error": str(exc)})
    return results
