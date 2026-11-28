"""Strict record machinery shared by the Prediction and Risk-Assessment contracts.

Every record is a frozen dataclass whose FIELDS map each field to a kind. Construction validates every field
(no silent coercion); from_dict() requires the exact key set and converts only the documented JSON forms
(decimal STRING -> Decimal, ISO-8601 string WITH offset -> UTC datetime, list -> tuple, mapping -> nested record).
JSON floats, NaN and Infinity are rejected before any record is built. Serialization is deterministic
(Step 2 canonical_json: sorted keys, compact, ASCII, float-rejecting).
"""
from __future__ import annotations

import json
import re
from dataclasses import fields as dc_fields
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from types import MappingProxyType
from typing import Any, ClassVar, Dict, Mapping, Tuple, Type

from ..charts.hashing import canonical_json, is_sha256_hex, sha256_of_payload
from ..instruments.identity import normalize_decimal_str
from .exceptions import PredictionContractError
from .reason_codes import ValidationFailureCode as V

UTC = timezone.utc
_DECIMAL_STR_RE = re.compile(r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?$")


class Kind:
    """Field kinds. Optional / tuple / nested wrap another kind."""

    def __init__(self, tag: str, inner: Any = None) -> None:
        self.tag, self.inner = tag, inner


STR, INT, BOOL, DEC, DT, SHA = Kind("str"), Kind("int"), Kind("bool"), Kind("dec"), Kind("dt"), Kind("sha")


def ENUM(cls: Type[Enum]) -> Kind:  # noqa: N802
    return Kind("enum", cls)


def OPT(k: Kind) -> Kind:  # noqa: N802
    return Kind("opt", k)


def TUP(k: Kind) -> Kind:  # noqa: N802
    return Kind("tuple", k)


def REC(cls: type) -> Kind:  # noqa: N802
    return Kind("rec", cls)


SCALAR_MAP = Kind("scalar_map")   # str -> (str | int | bool | None), deep-frozen; used for Step 1 spec snapshots


def fail(code: Enum, msg: str) -> PredictionContractError:
    return PredictionContractError(code, msg)


def _check(kind: Kind, v: Any, name: str) -> Any:
    t = kind.tag
    if t == "opt":
        return None if v is None else _check(kind.inner, v, name)
    if v is None:
        raise fail(V.MISSING_FIELD, f"{name} is required")
    if t == "str":
        if not isinstance(v, str) or not v.strip():
            raise fail(V.INVALID_TYPE, f"{name} must be a non-empty string (got {type(v).__name__})")
        return v
    if t == "int":
        if isinstance(v, bool) or not isinstance(v, int):
            raise fail(V.INVALID_TYPE, f"{name} must be an int (got {type(v).__name__})")
        return v
    if t == "bool":
        if not isinstance(v, bool):
            raise fail(V.INVALID_TYPE, f"{name} must be a bool (got {type(v).__name__})")
        return v
    if t == "dec":
        if isinstance(v, (bool, float, int)) or not isinstance(v, Decimal):
            raise fail(V.INVALID_TYPE, f"{name} must be a Decimal (got {type(v).__name__}); floats are never accepted")
        if not v.is_finite():
            raise fail(V.NON_FINITE_NUMBER, f"{name} must be finite (got {v})")
        return v
    if t == "dt":
        if not isinstance(v, datetime) or v.tzinfo is None or v.utcoffset() is None:
            raise fail(V.INVALID_TIMESTAMP, f"{name} must be a timezone-aware datetime")
        return v.astimezone(UTC)
    if t == "sha":
        if not is_sha256_hex(v):
            raise fail(V.INVALID_PROVENANCE, f"{name} must be a lowercase 64-character SHA-256 hex digest")
        return v
    if t == "enum":
        cls = kind.inner
        if isinstance(v, cls):
            return v
        if isinstance(v, str) and v in {m.value for m in cls}:
            return cls(v)
        raise fail(V.INVALID_ENUM, f"{name} must be one of {[m.value for m in cls]} (got {v!r})")
    if t == "tuple":
        if isinstance(v, (str, bytes)) or not isinstance(v, (tuple, list)):
            raise fail(V.INVALID_TYPE, f"{name} must be a list/tuple (got {type(v).__name__}); strings are not split")
        return tuple(_check(kind.inner, x, f"{name}[{i}]") for i, x in enumerate(v))
    if t == "rec":
        if not isinstance(v, kind.inner):
            raise fail(V.INVALID_TYPE, f"{name} must be a {kind.inner.__name__} (got {type(v).__name__})")
        return v
    if t == "scalar_map":
        if not isinstance(v, Mapping):
            raise fail(V.INVALID_TYPE, f"{name} must be a mapping")
        out = {}
        for k, x in v.items():
            if not isinstance(k, str) or not k:
                raise fail(V.INVALID_TYPE, f"{name} keys must be non-empty strings")
            if x is not None and (isinstance(x, float) or not isinstance(x, (str, int, bool))):
                raise fail(V.INVALID_TYPE, f"{name}.{k} must be a JSON scalar string/int/bool/null (got {type(x).__name__})")
            out[k] = x
        return MappingProxyType(dict(sorted(out.items())))
    raise AssertionError(t)


def _from_json(kind: Kind, v: Any, name: str) -> Any:
    t = kind.tag
    if t == "opt":
        return None if v is None else _from_json(kind.inner, v, name)
    if v is None:
        raise fail(V.MISSING_FIELD, f"{name} must not be null")
    if t == "dec":
        if not isinstance(v, str):
            raise fail(V.INVALID_TYPE, f"{name} must be a decimal string in JSON (got {type(v).__name__})")
        if not _DECIMAL_STR_RE.match(v):
            code = V.NON_FINITE_NUMBER if v.lower().lstrip("+-") in ("nan", "inf", "infinity", "snan") else V.INVALID_TYPE
            raise fail(code, f"{name} is not a plain decimal string: {v!r}")
        try:
            return Decimal(v)
        except InvalidOperation:
            raise fail(V.INVALID_TYPE, f"{name} is not a decimal: {v!r}") from None
    if t == "dt":
        if not isinstance(v, str):
            raise fail(V.INVALID_TIMESTAMP, f"{name} must be an ISO-8601 string in JSON")
        try:
            dt = datetime.fromisoformat(v)
        except ValueError:
            raise fail(V.INVALID_TIMESTAMP, f"{name} is not ISO-8601: {v!r}") from None
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise fail(V.INVALID_TIMESTAMP, f"{name} must carry an explicit UTC offset: {v!r}")
        return dt
    if t == "tuple":
        if not isinstance(v, list):
            raise fail(V.INVALID_TYPE, f"{name} must be a JSON array (got {type(v).__name__})")
        return tuple(_from_json(kind.inner, x, f"{name}[{i}]") for i, x in enumerate(v))
    if t == "rec":
        return kind.inner.from_dict(v)
    return v  # str / int / bool / sha / enum: validated by the constructor without coercion


def _to_json(kind: Kind, v: Any) -> Any:
    t = kind.tag
    if t == "opt":
        return None if v is None else _to_json(kind.inner, v)
    if t == "dec":
        return normalize_decimal_str(v)
    if t == "dt":
        return v.astimezone(UTC).isoformat()
    if t == "enum":
        return v.value
    if t == "tuple":
        return [_to_json(kind.inner, x) for x in v]
    if t == "rec":
        return v.to_dict()
    if t == "scalar_map":
        return dict(v)
    return v


def _reject_float(s: str) -> Any:
    raise fail(V.INVALID_TYPE, f"JSON floats are not accepted (got {s}); use decimal strings")


def _reject_constant(s: str) -> Any:
    raise fail(V.NON_FINITE_NUMBER, f"JSON constant {s} is not accepted")


def strict_json_loads(payload: Any) -> Any:
    if not isinstance(payload, (str, bytes)):
        raise fail(V.MALFORMED_PAYLOAD, "payload must be a JSON string")
    try:
        return json.loads(payload, parse_float=_reject_float, parse_constant=_reject_constant)
    except json.JSONDecodeError as exc:
        raise fail(V.MALFORMED_PAYLOAD, f"malformed JSON: {exc}") from None


class Record:
    """Base for frozen contract records. Subclasses: @dataclass(frozen=True) with FIELDS matching their fields."""

    FIELDS: ClassVar[Dict[str, Kind]] = {}

    def __post_init__(self) -> None:
        cls = type(self).__name__
        names = [f.name for f in dc_fields(self)]  # type: ignore[arg-type]
        if names != list(self.FIELDS):
            raise AssertionError(f"{cls}.FIELDS does not match its dataclass fields")
        for name, kind in self.FIELDS.items():
            object.__setattr__(self, name, _check(kind, getattr(self, name), f"{cls}.{name}"))
        self._validate()

    def _validate(self) -> None:  # invariants beyond field kinds
        pass

    def to_dict(self) -> Dict[str, Any]:
        return {name: _to_json(kind, getattr(self, name)) for name, kind in self.FIELDS.items()}

    def to_json(self) -> str:
        return canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, data: Any) -> Any:
        if not isinstance(data, Mapping):
            raise fail(V.MALFORMED_PAYLOAD, f"{cls.__name__} must be a JSON object (got {type(data).__name__})")
        keys = set(data)
        unknown, missing = sorted(keys - set(cls.FIELDS)), sorted(set(cls.FIELDS) - keys)
        if unknown:
            raise fail(V.UNKNOWN_FIELD, f"{cls.__name__} has unknown fields {unknown}")
        if missing:
            raise fail(V.MISSING_FIELD, f"{cls.__name__} is missing fields {missing}")
        kwargs = {n: _from_json(k, data[n], f"{cls.__name__}.{n}") for n, k in cls.FIELDS.items()}
        return cls(**kwargs)  # type: ignore[call-arg]

    @classmethod
    def from_json(cls, payload: Any) -> Any:
        return cls.from_dict(strict_json_loads(payload))


def content_id(record: Record, id_field: str) -> str:
    """SHA-256 of the record's canonical JSON without its own id field (content-addressed identity)."""
    d = record.to_dict()
    d.pop(id_field)
    return sha256_of_payload(d)


def decimal_places(d: Decimal) -> int:
    exp = d.as_tuple().exponent
    return -exp if isinstance(exp, int) and exp < 0 else 0


__all__ = ["BOOL", "DEC", "DT", "ENUM", "INT", "Kind", "OPT", "REC", "Record", "SCALAR_MAP", "SHA", "STR", "TUP", "UTC",
           "content_id", "decimal_places", "fail", "strict_json_loads"]
