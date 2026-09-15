"""Versioned JSON records and atomic artifact writes; no implicit coercion."""

import hashlib
import json
import os
import time
import uuid
from collections.abc import Iterable
from dataclasses import asdict, fields, is_dataclass
from functools import lru_cache
from pathlib import Path
from types import UnionType
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_default(value: object) -> dict:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")


def encode(value: object) -> bytes:
    return (
        json.dumps(
            value,
            default=json_default,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def object_hash(value: object) -> str:
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


def write_json(path: Path, value: object) -> None:
    atomic_write(path, encode(value))


def write_jsonl(path: Path, values: Iterable[object]) -> None:
    atomic_write(
        path,
        b"".join(
            json.dumps(
                v,
                default=json_default,
                sort_keys=True,
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
            + b"\n"
            for v in values
        ),
    )


def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def reject_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON number: {value}")


def load_json(text: str) -> Any:
    return json.loads(text, object_pairs_hook=unique_pairs, parse_constant=reject_constant)


def read_json(path: Path) -> Any:
    return load_json(path.read_text(encoding="utf-8"))


def decode(annotation: Any, value: Any) -> Any:
    origin, args = get_origin(annotation), get_args(annotation)
    if origin in (Union, UnionType):
        for choice in args:
            try:
                return decode(choice, value)
            except (TypeError, ValueError):
                pass
        raise ValueError(f"Value does not match {annotation}")
    if origin is Literal:
        if not any(type(value) is type(choice) and value == choice for choice in args):
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
    if isinstance(annotation, type) and is_dataclass(annotation):
        if isinstance(value, annotation):
            validate_record(value)
            return value
        return from_dict(annotation, value)
    if annotation is type(None) and value is None:
        return None
    if type(value) is not annotation:
        raise ValueError(f"Expected {annotation}, got {type(value).__name__}")
    return value


@lru_cache(maxsize=64)
def record_hints(cls: type) -> dict[str, Any]:
    return get_type_hints(cls)


def validate_record(value: Any) -> None:
    for name, annotation in record_hints(value.__class__).items():
        decode(annotation, getattr(value, name))


def from_dict[T](cls: type[T], value: Any) -> T:
    if not is_dataclass(cls):
        raise TypeError("Expected a dataclass type")
    if not isinstance(value, dict):
        raise ValueError(f"{cls.__name__} requires an object")
    unknown = set(value) - {f.name for f in fields(cls)}
    if unknown:
        raise ValueError(f"Unknown {cls.__name__} fields: {sorted(unknown)}")
    hints = record_hints(cls)
    try:
        return cls(**{k: decode(hints[k], v) for k, v in value.items()})
    except TypeError as exc:
        raise ValueError(f"Invalid {cls.__name__}: {exc}") from exc
