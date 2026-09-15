"""Versioned JSON records and atomic artifact writes; no implicit coercion."""

import hashlib
import json
import os
import time
import uuid
from dataclasses import asdict, fields, is_dataclass
from pathlib import Path
from types import UnionType
from typing import Literal, Union, get_args, get_origin, get_type_hints


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encode(value) -> bytes:
    return (
        json.dumps(
            value,
            default=lambda x: asdict(x) if is_dataclass(x) else str(x),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def object_hash(value) -> str:
    return digest(encode(value))


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(6):
            try:
                temporary.replace(path)
                break
            except PermissionError as exc:
                # Windows indexers can briefly open an artifact without delete sharing.
                # Retry only recognized sharing/access errors, with a bounded 0.62s delay.
                if getattr(exc, "winerror", None) not in (5, 32, 33) or attempt == 5:
                    raise
                time.sleep(0.02 * 2**attempt)
    finally:
        temporary.unlink(missing_ok=True)


def write_json(path: Path, value) -> None:
    atomic_write(path, encode(value))


def write_jsonl(path: Path, values) -> None:
    atomic_write(
        path,
        b"".join(
            json.dumps(
                asdict(v) if is_dataclass(v) else v,
                sort_keys=True,
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
            + b"\n"
            for v in values
        ),
    )


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def decode(annotation, value):
    origin, args = get_origin(annotation), get_args(annotation)
    if origin in (Union, UnionType):
        for choice in args:
            try:
                return decode(choice, value)
            except (TypeError, ValueError):
                pass
        raise ValueError(f"Value does not match {annotation}")
    if origin is Literal:
        if value not in args:
            raise ValueError(f"Expected one of {args}, got {value!r}")
        return value
    if origin is list:
        if not isinstance(value, list):
            raise ValueError("Expected a list")
        return [decode(args[0], item) for item in value]
    if origin is dict:
        if not isinstance(value, dict):
            raise ValueError("Expected an object")
        return {decode(args[0], k): decode(args[1], v) for k, v in value.items()}
    if is_dataclass(annotation):
        return from_dict(annotation, value)
    if annotation is type(None) and value is None:
        return None
    if type(value) is not annotation:
        raise ValueError(f"Expected {annotation}, got {type(value).__name__}")
    return value


def from_dict(cls, value):
    if not isinstance(value, dict):
        raise ValueError(f"{cls.__name__} requires an object")
    unknown = set(value) - {f.name for f in fields(cls)}
    if unknown:
        raise ValueError(f"Unknown {cls.__name__} fields: {sorted(unknown)}")
    hints = get_type_hints(cls)
    try:
        return cls(**{k: decode(hints[k], v) for k, v in value.items()})
    except TypeError as exc:
        raise ValueError(f"Invalid {cls.__name__}: {exc}") from exc
