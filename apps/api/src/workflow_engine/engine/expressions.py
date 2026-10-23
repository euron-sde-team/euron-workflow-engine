"""JMESPath with a small, fixed set of extra functions.

JMESPath is a query language over JSON values: it can select, filter, project and reshape,
but it has no way to call Python, import modules, read files or open sockets. That is what
makes it safe to accept from anyone who can edit a workflow (ADR-0004).

Extra functions, on top of the JMESPath standard library:

    upper(s) lower(s) trim(s) replace(s, old, new) split(s, sep)
    format_number(n, digits) round(n, digits) default(value, fallback)
    to_json(v) from_json(s) url_encode(s) base64_encode(s) base64_decode(s) sha256(s)
    now() format_date(iso, fmt) date_add(iso, seconds) unique(array) group_by(array, &key)
"""

from __future__ import annotations

import base64
import binascii
import hashlib
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any
from urllib.parse import quote

import jmespath
import orjson
from jmespath import exceptions as jp_exceptions
from jmespath import functions
from jmespath.parser import ParsedResult

MAX_EXPRESSION_LENGTH = 4000


class ExpressionError(ValueError):
    """An expression failed to compile or to evaluate; the message is safe to show."""


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ExpressionError(f"{name}() expected a number, got a boolean")
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", ""))
        except ValueError as exc:
            raise ExpressionError(f"{name}() expected a number, got '{value}'") from exc
    raise ExpressionError(f"{name}() expected a number")


def _digits(value: Any) -> int:
    digits = int(_number(value, "digits"))
    if not 0 <= digits <= 10:
        raise ExpressionError("digits must be between 0 and 10")
    return digits


def _parse_instant(value: str, name: str) -> datetime:
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ExpressionError(f"{name}() expected an ISO 8601 date, got '{value}'") from exc
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


class _Functions(functions.Functions):
    """The extra functions. A fresh instance per evaluation carries that evaluation's `now`."""

    def __init__(self, now: datetime) -> None:
        super().__init__()
        self._now = now

    @functions.signature({"types": ["string"]})
    def _func_upper(self, value: str) -> str:
        return value.upper()

    @functions.signature({"types": ["string"]})
    def _func_lower(self, value: str) -> str:
        return value.lower()

    @functions.signature({"types": ["string"]})
    def _func_trim(self, value: str) -> str:
        return value.strip()

    @functions.signature({"types": ["string"]}, {"types": ["string"]}, {"types": ["string"]})
    def _func_replace(self, value: str, old: str, new: str) -> str:
        return value.replace(old, new)

    @functions.signature({"types": ["string"]}, {"types": ["string"]})
    def _func_split(self, value: str, separator: str) -> list[str]:
        return value.split(separator) if separator else list(value)

    @functions.signature({"types": ["number", "string"]}, {"types": ["number", "string"]})
    def _func_format_number(self, value: Any, digits: Any) -> str:
        return f"{_number(value, 'format_number'):,.{_digits(digits)}f}"

    @functions.signature({"types": ["number", "string"]}, {"types": ["number", "string"]})
    def _func_round(self, value: Any, digits: Any) -> float | int:
        places = _digits(digits)
        rounded = round(_number(value, "round"), places)
        return int(rounded) if places == 0 else rounded

    @functions.signature({"types": []}, {"types": []})
    def _func_default(self, value: Any, fallback: Any) -> Any:
        return value if truthy(value) or value is False else fallback

    @functions.signature({"types": []})
    def _func_to_json(self, value: Any) -> str:
        return orjson.dumps(value).decode()

    @functions.signature({"types": ["string"]})
    def _func_from_json(self, value: str) -> Any:
        try:
            return orjson.loads(value)
        except orjson.JSONDecodeError as exc:
            raise ExpressionError(f"from_json() could not parse: {exc}") from exc

    @functions.signature({"types": ["string"]})
    def _func_url_encode(self, value: str) -> str:
        return quote(value, safe="")

    @functions.signature({"types": ["string"]})
    def _func_base64_encode(self, value: str) -> str:
        return base64.b64encode(value.encode()).decode()

    @functions.signature({"types": ["string"]})
    def _func_base64_decode(self, value: str) -> str:
        try:
            return base64.b64decode(value, validate=True).decode()
        except (binascii.Error, UnicodeDecodeError) as exc:
            raise ExpressionError("base64_decode() got invalid input") from exc

    @functions.signature({"types": ["string"]})
    def _func_sha256(self, value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    @functions.signature()
    def _func_now(self) -> str:
        return iso(self._now)

    @functions.signature({"types": ["string"]}, {"types": ["string"]})
    def _func_format_date(self, value: str, fmt: str) -> str:
        return _parse_instant(value, "format_date").strftime(fmt)

    @functions.signature({"types": ["string"]}, {"types": ["number", "string"]})
    def _func_date_add(self, value: str, seconds: Any) -> str:
        moment = _parse_instant(value, "date_add")
        return iso(moment + timedelta(seconds=_number(seconds, "date_add")))

    @functions.signature({"types": ["array"]})
    def _func_unique(self, values: list[Any]) -> list[Any]:
        seen: set[bytes] = set()
        result = []
        for value in values:
            key = orjson.dumps(value, option=orjson.OPT_SORT_KEYS)
            if key not in seen:
                seen.add(key)
                result.append(value)
        return result

    @functions.signature({"types": ["array"]}, {"types": ["expref"]})
    def _func_group_by(self, values: list[Any], expref: Any) -> dict[str, list[Any]]:
        groups: dict[str, list[Any]] = {}
        for value in values:
            key = expref.visit(expref.expression, value)
            label = key if isinstance(key, str) else orjson.dumps(key).decode()
            groups.setdefault(label, []).append(value)
        return groups


@lru_cache(maxsize=4096)
def compile_expression(source: str) -> ParsedResult:
    """Parse once; the parsed form is reused across steps and executions."""
    text = source.strip()
    if not text:
        raise ExpressionError("the expression is empty")
    if len(text) > MAX_EXPRESSION_LENGTH:
        raise ExpressionError(f"the expression is longer than {MAX_EXPRESSION_LENGTH} characters")
    try:
        return jmespath.compile(text)
    except (jp_exceptions.ParseError, jp_exceptions.LexerError) as exc:
        raise ExpressionError(_describe_parse_error(exc)) from exc
    except jp_exceptions.JMESPathError as exc:  # pragma: no cover - defensive
        raise ExpressionError(str(exc)) from exc


def _describe_parse_error(exc: Exception) -> str:
    position = getattr(exc, "lex_position", None)
    token = getattr(exc, "token_value", None)
    message = getattr(exc, "msg", None) or str(exc).splitlines()[0]
    where = f" at position {position}" if isinstance(position, int) else ""
    near = f" near '{token}'" if token not in (None, "") else ""
    return f"invalid expression{where}{near}: {message}"


def evaluate(source: str, data: Any, *, now: datetime | None = None) -> Any:
    """Evaluate a JMESPath expression against JSON data."""
    compiled = compile_expression(source)
    options = jmespath.Options(dict_cls=dict, custom_functions=_Functions(now or datetime.now(UTC)))
    try:
        return compiled.search(data, options=options)
    except ExpressionError:
        raise
    except jp_exceptions.JMESPathError as exc:
        raise ExpressionError(str(exc).splitlines()[0]) from exc
    except (TypeError, ValueError, OverflowError) as exc:
        raise ExpressionError(f"the expression could not be evaluated: {exc}") from exc


def truthy(value: Any) -> bool:
    """JMESPath truthiness: false, null, empty strings, arrays and objects are false.

    Zero is true, unlike Python, so the checks are explicit rather than `bool(value)`.
    """
    if value is None or value is False:
        return False
    return not (isinstance(value, str | list | dict) and len(value) == 0)
