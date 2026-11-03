"""
Request-body validation with the same rules and messages as the previous API
(which used zod). A small, explicit schema builder:

    from app import schema as z

    create = z.object({
        "email": z.string().trim().email().max(255),
        "amount": z.number(required_error="Amount is required.").nonnegative("Amount cannot be negative."),
        "note": z.string().max(1000).optional(),
        "status": z.enum(["ACTIVE", "INACTIVE"]).default("ACTIVE"),
    }).refine(lambda b: len(b) > 0, "No fields to update")

    body = create.parse(raw_json)      # -> dict; raises AppError(400, VALIDATION_ERROR, "path: message; ...")

Absent keys stay absent in the result (like `undefined`), unknown keys are
dropped, `optional()` allows absence, `nullable()` allows null, `nullish()`
both. Error text is "<path>: <message>" joined with "; " (path "body" for the
root), exactly as before.
"""
from __future__ import annotations

import math
import re
from typing import Any, Callable

from .errors import AppError


class _Missing:
    def __repr__(self) -> str:  # pragma: no cover
        return "MISSING"


MISSING = _Missing()
_INVALID = object()


def type_name(v: Any) -> str:
    if v is MISSING:
        return "undefined"
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, (int, float)):
        if isinstance(v, float) and math.isnan(v):
            return "nan"
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    if isinstance(v, dict):
        return "object"
    return "unknown"


class Issue:
    __slots__ = ("path", "message")

    def __init__(self, path: list, message: str):
        self.path = path
        self.message = message


class ValidationFailed(Exception):
    def __init__(self, issues: list[Issue]):
        self.issues = issues
        super().__init__(format_issues(issues))


def format_issues(issues: list[Issue]) -> str:
    return "; ".join(f"{'.'.join(str(p) for p in i.path) or 'body'}: {i.message}" for i in issues)


class Schema:
    def __init__(self) -> None:
        self._optional = False
        self._nullable = False
        self._default: Any = MISSING
        self._catch: Any = MISSING
        self._refines: list[tuple[Callable[[Any], bool], str, list]] = []
        self._transforms: list[Callable[[Any], Any]] = []
        self.required_error = "Required"
        self.invalid_type_error: str | None = None

    # -- modifiers (return self: schemas are built once at import time) -------
    def _copy(self) -> "Schema":
        import copy

        return copy.copy(self)

    def optional(self) -> "Schema":
        s = self._copy()
        s._optional = True
        return s

    def nullable(self) -> "Schema":
        s = self._copy()
        s._nullable = True
        return s

    def nullish(self) -> "Schema":
        s = self._copy()
        s._optional = True
        s._nullable = True
        return s

    def default(self, v: Any) -> "Schema":
        s = self._copy()
        s._default = v
        return s

    def catch(self, v: Any) -> "Schema":
        s = self._copy()
        s._catch = v
        return s

    def refine(self, fn: Callable[[Any], bool], message: str = "Invalid input", path: list | None = None) -> "Schema":
        s = self._copy()
        s._refines = [*self._refines, (fn, message, path or [])]
        return s

    def transform(self, fn: Callable[[Any], Any]) -> "Schema":
        s = self._copy()
        s._transforms = [*self._transforms, fn]
        return s

    # -- parsing --------------------------------------------------------------
    def _check(self, v: Any, path: list, issues: list[Issue]) -> Any:  # pragma: no cover
        raise NotImplementedError

    def _invalid_type(self, expected: str, v: Any, path: list, issues: list[Issue]) -> Any:
        if v is MISSING:
            issues.append(Issue(path, self.required_error))
        else:
            issues.append(Issue(path, self.invalid_type_error or f"Expected {expected}, received {type_name(v)}"))
        return _INVALID

    def run(self, v: Any, path: list, issues: list[Issue]) -> Any:
        if self._catch is not MISSING:
            sub: list[Issue] = []
            r = self._run(v, path, sub)
            return self._catch if sub or r is _INVALID else r
        return self._run(v, path, issues)

    def _run(self, v: Any, path: list, issues: list[Issue]) -> Any:
        if v is MISSING and self._default is not MISSING:
            d = self._default
            v = d() if callable(d) else (list(d) if isinstance(d, list) else d)
        if v is MISSING:
            if self._optional:
                return MISSING
            return self._invalid_type(self._expected(), v, path, issues)
        if v is None:
            if self._nullable:
                return None
            return self._invalid_type(self._expected(), v, path, issues)
        # zod semantics: a wrong type / missing value / bad enum ABORTS (no
        # refinements run, parents abort too); a failed value check (min, max,
        # regex, ...) only makes the result DIRTY — refinements still run on
        # it (every one of them), transforms do not.
        before = len(issues)
        out = self._check(v, path, issues)
        if out is _INVALID:
            return _INVALID
        dirty = len(issues) > before
        for fn, msg, p in self._refines:
            try:
                passed = fn(out)
            except Exception:  # noqa: BLE001 - a refinement reading a dirty value
                passed = False
            if not passed:
                issues.append(Issue(path + p, msg))
                dirty = True
        if not dirty:
            for t in self._transforms:
                out = t(out)
        return out

    def _expected(self) -> str:
        return "unknown"

    def parse(self, v: Any) -> Any:
        issues: list[Issue] = []
        out = self.run(MISSING if v is MISSING else v, [], issues)
        if issues or out is _INVALID:
            raise AppError(400, "VALIDATION_ERROR", format_issues(issues) or "body: Invalid input")
        return None if out is MISSING else out

    def safe_parse(self, v: Any) -> tuple[bool, Any]:
        try:
            return True, self.parse(v)
        except AppError as e:
            return False, e.message


# ---------------------------------------------------------------------------
def js_pattern(pattern: str) -> str:
    """A JavaScript regex source (no flags) as a Python pattern: JS `$` matches only
    at the very end, Python's also before a trailing newline — so `$` becomes `\\Z`."""
    out: list[str] = []
    i, in_class = 0, False
    while i < len(pattern):
        c = pattern[i]
        if c == "\\":
            out.append(pattern[i:i + 2])
            i += 2
            continue
        if c == "[":
            in_class = True
        elif c == "]":
            in_class = False
        elif c == "$" and not in_class:
            out.append(r"\Z")
            i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


_EMAIL_RE = re.compile(
    r"^(?!\.)(?!.*\.\.)([A-Z0-9_'+\-\.]*)[A-Z0-9_+-]@([A-Z0-9][A-Z0-9\-]*\.)+[A-Z]{2,}\Z", re.I
)


class String(Schema):
    def __init__(self, required_error: str | None = None, invalid_type_error: str | None = None):
        super().__init__()
        self._ops: list[tuple] = []
        if required_error:
            self.required_error = required_error
        self.invalid_type_error = invalid_type_error

    def _expected(self) -> str:
        return "string"

    def _add(self, op: tuple) -> "String":
        s = self._copy()
        s._ops = [*self._ops, op]
        return s

    def min(self, n: int, message: str | None = None) -> "String":
        return self._add(("min", n, message or f"String must contain at least {n} character(s)"))

    def max(self, n: int, message: str | None = None) -> "String":
        return self._add(("max", n, message or f"String must contain at most {n} character(s)"))

    def length(self, n: int, message: str | None = None) -> "String":
        return self._add(("len", n, message or f"String must contain exactly {n} character(s)"))

    def email(self, message: str | None = None) -> "String":
        return self._add(("re", _EMAIL_RE, message or "Invalid email"))

    def regex(self, pattern: str | re.Pattern, message: str | None = None) -> "String":
        p = re.compile(js_pattern(pattern)) if isinstance(pattern, str) else pattern
        return self._add(("re", p, message or "Invalid"))

    def trim(self) -> "String":
        return self._add(("trim",))

    def to_upper(self) -> "String":
        return self._add(("upper",))

    def to_lower(self) -> "String":
        return self._add(("lower",))

    def _check(self, v: Any, path: list, issues: list[Issue]) -> Any:
        if not isinstance(v, str):
            return self._invalid_type("string", v, path, issues)
        for op in self._ops:
            kind = op[0]
            if kind == "trim":
                v = v.strip()
            elif kind == "upper":
                v = v.upper()
            elif kind == "lower":
                v = v.lower()
            elif kind == "min" and len(v) < op[1]:
                issues.append(Issue(path, op[2]))
            elif kind == "max" and len(v) > op[1]:
                issues.append(Issue(path, op[2]))
            elif kind == "len" and len(v) != op[1]:
                issues.append(Issue(path, op[2]))
            elif kind == "re" and not op[1].search(v):
                issues.append(Issue(path, op[2]))
        return v


class Number(Schema):
    def __init__(self, required_error: str | None = None, invalid_type_error: str | None = None):
        super().__init__()
        self._ops: list[tuple] = []
        if required_error:
            self.required_error = required_error
        self.invalid_type_error = invalid_type_error

    def _expected(self) -> str:
        return "number"

    def _add(self, op: tuple) -> "Number":
        s = self._copy()
        s._ops = [*self._ops, op]
        return s

    def int(self, message: str | None = None) -> "Number":
        return self._add(("int", message or "Expected integer, received float"))

    def positive(self, message: str | None = None) -> "Number":
        return self._add(("gt", 0, message or "Number must be greater than 0"))

    def nonnegative(self, message: str | None = None) -> "Number":
        return self._add(("gte", 0, message or "Number must be greater than or equal to 0"))

    def min(self, n: float, message: str | None = None) -> "Number":
        return self._add(("gte", n, message or f"Number must be greater than or equal to {_num(n)}"))

    def max(self, n: float, message: str | None = None) -> "Number":
        return self._add(("lte", n, message or f"Number must be less than or equal to {_num(n)}"))

    def finite(self, message: str | None = None) -> "Number":
        return self._add(("finite", message or "Number must be finite"))

    def _check(self, v: Any, path: list, issues: list[Issue]) -> Any:
        if isinstance(v, bool) or not isinstance(v, (int, float)) or (isinstance(v, float) and math.isnan(v)):
            return self._invalid_type("number", v, path, issues)
        for op in self._ops:
            kind = op[0]
            if kind == "int" and not float(v).is_integer():
                issues.append(Issue(path, op[1]))
            elif kind == "gt" and not v > op[1]:
                issues.append(Issue(path, op[2]))
            elif kind == "gte" and not v >= op[1]:
                issues.append(Issue(path, op[2]))
            elif kind == "lte" and not v <= op[1]:
                issues.append(Issue(path, op[2]))
            elif kind == "finite" and (math.isinf(v)):
                issues.append(Issue(path, op[1]))
        if isinstance(v, float) and v.is_integer() and any(o[0] == "int" for o in self._ops):
            return int(v)
        return v


def _num(n: float) -> str:
    return str(int(n)) if float(n).is_integer() else str(n)


class Boolean(Schema):
    def _expected(self) -> str:
        return "boolean"

    def _check(self, v: Any, path: list, issues: list[Issue]) -> Any:
        if not isinstance(v, bool):
            return self._invalid_type("boolean", v, path, issues)
        return v


class Enum(Schema):
    def __init__(self, values: list, message: str | None = None):
        super().__init__()
        self.values = list(values)
        self.message = message

    def _expected(self) -> str:
        return " | ".join(_lit(x) for x in self.values)

    def _check(self, v: Any, path: list, issues: list[Issue]) -> Any:
        joined = " | ".join(_lit(x) for x in self.values)
        all_str = all(isinstance(x, str) for x in self.values)
        ok_type = isinstance(v, str) if all_str else (isinstance(v, (str, int, float)) and not isinstance(v, bool))
        if not ok_type:
            return self._invalid_type(joined, v, path, issues)
        if not any(v == x and isinstance(v, str) == isinstance(x, str) for x in self.values):
            issues.append(Issue(path, self.message or f"Invalid enum value. Expected {joined}, received '{v}'"))
            return _INVALID
        return v


def _lit(v: Any) -> str:
    return f"'{v}'" if isinstance(v, str) else str(v)


class Literal(Schema):
    def __init__(self, value: Any):
        super().__init__()
        self.value = value

    def _check(self, v: Any, path: list, issues: list[Issue]) -> Any:
        if v != self.value or isinstance(v, bool) != isinstance(self.value, bool):
            issues.append(Issue(path, f"Invalid literal value, expected {_lit(self.value)}"))
            return _INVALID
        return v


class Array(Schema):
    def __init__(self, item: Schema):
        super().__init__()
        self.item = item
        self._min: tuple | None = None
        self._max: tuple | None = None

    def _expected(self) -> str:
        return "array"

    def min(self, n: int, message: str | None = None) -> "Array":
        s = self._copy()
        s._min = (n, message or f"Array must contain at least {n} element(s)")
        return s

    def max(self, n: int, message: str | None = None) -> "Array":
        s = self._copy()
        s._max = (n, message or f"Array must contain at most {n} element(s)")
        return s

    def _check(self, v: Any, path: list, issues: list[Issue]) -> Any:
        if not isinstance(v, list):
            return self._invalid_type("array", v, path, issues)
        out = []
        aborted = False
        if self._min and len(v) < self._min[0]:
            issues.append(Issue(path, self._min[1]))
        if self._max and len(v) > self._max[0]:
            issues.append(Issue(path, self._max[1]))
        for i, x in enumerate(v):
            r = self.item.run(MISSING if x is MISSING else x, path + [i], issues)
            aborted = aborted or r is _INVALID
            out.append(None if r is MISSING else r)
        return _INVALID if aborted else out


class Record(Schema):
    def __init__(self, key: Schema, value: Schema):
        super().__init__()
        self.key = key
        self.value = value

    def _expected(self) -> str:
        return "object"

    def _check(self, v: Any, path: list, issues: list[Issue]) -> Any:
        if not isinstance(v, dict):
            return self._invalid_type("object", v, path, issues)
        out = {}
        aborted = False
        for k, x in v.items():
            kk = self.key.run(k, path + [k], issues)
            vv = self.value.run(x, path + [k], issues)
            if kk is _INVALID or vv is _INVALID:
                aborted = True
            else:
                out[kk] = vv
        return _INVALID if aborted else out


class Object(Schema):
    def __init__(self, shape: dict[str, Schema]):
        super().__init__()
        self.shape = dict(shape)

    def _expected(self) -> str:
        return "object"

    def extend(self, more: dict[str, Schema]) -> "Object":
        s = Object({**self.shape, **more})
        s._refines = list(self._refines)
        return s

    def pick(self, *keys: str) -> "Object":
        return Object({k: self.shape[k] for k in keys})

    def partial(self) -> "Object":
        return Object({k: v.optional() for k, v in self.shape.items()})

    def _check(self, v: Any, path: list, issues: list[Issue]) -> Any:
        if not isinstance(v, dict):
            return self._invalid_type("object", v, path, issues)
        out: dict[str, Any] = {}
        aborted = False
        for k, sch in self.shape.items():
            r = sch.run(v[k] if k in v else MISSING, path + [k], issues)
            if r is _INVALID:
                aborted = True
            elif r is not MISSING:
                out[k] = r
        return _INVALID if aborted else out


class Any_(Schema):
    def _check(self, v: Any, path: list, issues: list[Issue]) -> Any:
        return v


# Public constructors, named like zod's.
def string(required_error: str | None = None, invalid_type_error: str | None = None) -> String:
    return String(required_error, invalid_type_error)


def number(required_error: str | None = None, invalid_type_error: str | None = None) -> Number:
    return Number(required_error, invalid_type_error)


def boolean() -> Boolean:
    return Boolean()


def enum(values: list | tuple, message: str | None = None) -> Enum:
    return Enum(list(values), message)


def literal(value: Any) -> Literal:
    return Literal(value)


def array(item: Schema) -> Array:
    return Array(item)


def record(key: Schema, value: Schema) -> Record:
    return Record(key, value)


def object(shape: dict[str, Schema]) -> Object:  # noqa: A001 - mirrors zod
    return Object(shape)


def any_() -> Any_:
    return Any_()


def parse(schema: Schema, body: Any) -> Any:
    return schema.parse(body)
