"""String templates: text with `{{ <JMESPath> }}` placeholders.

    "Order {{ input.id }} for {{ upper(input.customer.name) }}"   -> interpolated text
    "{{ input.items }}"                                          -> the raw list, not text

A string that is exactly one placeholder (surrounding whitespace allowed) evaluates to the raw
value, so templates can pass numbers, lists and objects between nodes without quoting.
Otherwise values are interpolated: null becomes empty, booleans `true`/`false`, objects
and arrays compact JSON. `\\{{` writes a literal `{{`.

The scanner tracks braces and quotes inside a placeholder, so JMESPath multiselect hashes
such as `{{ {id: input.id, total: input.total} }}` work.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Any

import orjson

from workflow_engine.engine.expressions import ExpressionError, compile_expression, evaluate

MAX_TEMPLATE_LENGTH = 20_000
_STEP_REFERENCE = re.compile(r"\bsteps\s*\.\s*([a-z][a-z0-9_]*)")
_OPEN = "{{"
_CLOSE = "}}"


class TemplateError(ValueError):
    def __init__(self, message: str, position: int | None = None) -> None:
        super().__init__(message)
        self.position = position


@dataclass(frozen=True, slots=True)
class Placeholder:
    source: str
    start: int


Segment = str | Placeholder


@dataclass(frozen=True, slots=True)
class Template:
    segments: tuple[Segment, ...]

    @property
    def is_single_placeholder(self) -> bool:
        meaningful = [s for s in self.segments if not (isinstance(s, str) and not s.strip())]
        return len(meaningful) == 1 and isinstance(meaningful[0], Placeholder)

    @property
    def placeholders(self) -> list[Placeholder]:
        return [s for s in self.segments if isinstance(s, Placeholder)]


def _find_close(text: str, start: int) -> int:
    """Index of the `}}` that closes the placeholder opened just before `start`."""
    depth = 0
    quote: str | None = None
    index = start
    while index < len(text):
        char = text[index]
        if quote is not None:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = None
        elif char in "'\"`":
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            if depth == 0 and text.startswith(_CLOSE, index):
                return index
            depth = max(0, depth - 1)
        index += 1
    return -1


@lru_cache(maxsize=8192)
def parse_template(text: str) -> Template:
    if len(text) > MAX_TEMPLATE_LENGTH:
        raise TemplateError(f"the template is longer than {MAX_TEMPLATE_LENGTH} characters")
    segments: list[Segment] = []
    literal: list[str] = []
    index = 0
    while index < len(text):
        if text.startswith("\\" + _OPEN, index):
            literal.append(_OPEN)
            index += 3
            continue
        if text.startswith(_OPEN, index):
            close = _find_close(text, index + 2)
            if close == -1:
                raise TemplateError("a '{{' is never closed with '}}'", position=index)
            source = text[index + 2 : close].strip()
            if not source:
                raise TemplateError("an empty '{{ }}' placeholder", position=index)
            try:
                compile_expression(source)
            except ExpressionError as exc:
                raise TemplateError(str(exc), position=index) from exc
            if literal:
                segments.append("".join(literal))
                literal = []
            segments.append(Placeholder(source=source, start=index))
            index = close + 2
            continue
        literal.append(text[index])
        index += 1
    if literal:
        segments.append("".join(literal))
    return Template(tuple(segments))


def has_placeholders(text: str) -> bool:
    return _OPEN in text


def stringify(value: Any) -> str:
    if value is None:
        return ""
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e16:
        return str(int(value))
    if isinstance(value, int | float | str):
        return str(value)
    return orjson.dumps(value).decode()


def render_string(text: str, context: dict[str, Any], *, now: datetime | None = None) -> Any:
    if not has_placeholders(text):
        return text
    template = parse_template(text)
    if template.is_single_placeholder:
        return _evaluate(template.placeholders[0], context, now)
    parts: list[str] = []
    for segment in template.segments:
        if isinstance(segment, str):
            parts.append(segment)
        else:
            parts.append(stringify(_evaluate(segment, context, now)))
    return "".join(parts)


def _evaluate(placeholder: Placeholder, context: dict[str, Any], now: datetime | None) -> Any:
    try:
        return evaluate(placeholder.source, context, now=now)
    except ExpressionError as exc:
        raise TemplateError(f"{{{{ {placeholder.source} }}}}: {exc}", placeholder.start) from exc


def render(value: Any, context: dict[str, Any], *, now: datetime | None = None) -> Any:
    """Render every string inside a JSON value; keys are rendered too, other types kept."""
    if isinstance(value, str):
        return render_string(value, context, now=now)
    if isinstance(value, list):
        return [render(item, context, now=now) for item in value]
    if isinstance(value, dict):
        rendered: dict[str, Any] = {}
        for key, item in value.items():
            new_key = render_string(key, context, now=now) if has_placeholders(key) else key
            rendered[stringify(new_key)] = render(item, context, now=now)
        return rendered
    return value


def iter_strings(value: Any, path: str = "") -> Iterator[tuple[str, str]]:
    """Every string in a JSON value with its JSON path (`headers[0].value`)."""
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from iter_strings(item, f"{path}[{index}]")
    elif isinstance(value, dict):
        for key, item in value.items():
            child = f"{path}.{key}" if path else str(key)
            if isinstance(key, str) and has_placeholders(key):
                yield child, key
            yield from iter_strings(item, child)


def check(value: Any, path: str = "") -> list[tuple[str, str]]:
    """Syntax problems in every template inside `value`, as (path, message) pairs."""
    problems: list[tuple[str, str]] = []
    for where, text in iter_strings(value, path):
        if not has_placeholders(text):
            continue
        try:
            parse_template(text)
        except TemplateError as exc:
            problems.append((where, str(exc)))
    return problems


def step_references(value: Any) -> set[str]:
    """Node ids referenced as `steps.<id>` anywhere in templates or expressions inside `value`.

    Used to load only the outputs a step needs, instead of every earlier output.
    """
    found: set[str] = set()
    for _, text in iter_strings(value):
        found.update(_STEP_REFERENCE.findall(text))
    return found
