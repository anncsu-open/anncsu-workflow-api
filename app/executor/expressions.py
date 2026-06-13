"""Runtime-expression evaluator for the Arazzo executor.

Supports the finite expression surface used by the ANNCSU workflows:

- references: ``$inputs.<path>``, ``$steps.<id>.outputs.<path>``,
  ``$response.body.<path>``, ``$response.headers.<path>``, ``$statusCode``,
  and loop variables ``$<name>.<path>``;
- path navigation: dotted keys, ``[index]``, and the ``.length`` pseudo-property;
- conditions: ``<operand> <op> <operand>`` with ``==``/``!=``/``<``/``>``/``<=``/``>=``
  and literal operands (``true``/``false``/``null``, numbers, ``"quoted strings"``),
  or a bare reference treated as a boolean.

The evaluator is pure: it reads only from the :class:`ExecutionContext` and never
performs I/O. Missing references resolve to ``None`` rather than raising, so
expressions over branches that did not execute degrade gracefully.
"""

from __future__ import annotations

import operator
import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.executor.context import ExecutionContext

_LITERALS: dict[str, Any] = {"true": True, "false": False, "null": None}

# Two-character operators must be tried before their single-character prefixes.
_COMPARISONS: tuple[str, ...] = ("==", "!=", "<=", ">=", "<", ">")
_ORDERING = {"<": operator.lt, ">": operator.gt, "<=": operator.le, ">=": operator.ge}

_QUOTE_CHARS = "\"'"
_MIN_QUOTED_LENGTH = 2

_ROOT_RE = re.compile(r"\$([A-Za-z_]\w*)")
# A path token is either a ".key" (keys may contain hyphens, e.g. step ids /
# header names) or a "[index]".
_TOKEN_RE = re.compile(r"\.([A-Za-z_][\w-]*)|\[(\d+)\]")


def is_expression(value: Any) -> bool:
    """Return True if ``value`` is a runtime-expression string (starts with ``$``)."""
    return isinstance(value, str) and value.startswith("$")


def evaluate_expression(expr: str, ctx: ExecutionContext) -> Any:
    """Resolve a runtime expression to its value, or ``None`` if unresolvable."""
    expr = expr.strip()
    match = _ROOT_RE.match(expr)
    if match is None:
        return None

    value = _resolve_root(match.group(1), ctx)
    rest = expr[match.end() :]
    for key, index in _TOKEN_RE.findall(rest):
        if value is None:
            return None
        token: str | int = key if key else int(index)
        value = _navigate(value, token)
    return value


def evaluate_condition(condition: str, ctx: ExecutionContext) -> bool:
    """Evaluate a success/branch condition to a boolean."""
    left_expr, comparison, right_expr = _split_condition(condition)
    if comparison is None:
        return bool(_resolve_operand(left_expr, ctx))
    left = _resolve_operand(left_expr, ctx)
    right = _resolve_operand(right_expr, ctx)
    return _compare(left, comparison, right)


def resolve_value(value: Any, ctx: ExecutionContext) -> Any:
    """Recursively resolve any runtime expressions inside a request payload.

    A single-key object ``{"x-coalesce": [a, b, …]}`` resolves to the first
    non-null of its operands — the coalesce semantics of ``x-executor.coalesce``,
    usable inside a payload to merge caller input over a read step's outputs
    (see ADR 0012).
    """
    if isinstance(value, Mapping):
        if set(value) == {"x-coalesce"}:
            return _coalesce(value["x-coalesce"], ctx)
        return {key: resolve_value(item, ctx) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [resolve_value(item, ctx) for item in value]
    if is_expression(value):
        return evaluate_expression(value, ctx)
    return value


def _coalesce(operands: Any, ctx: ExecutionContext) -> Any:
    """First non-null among ``operands`` (each an expression or a literal value)."""
    for operand in operands:
        resolved = resolve_value(operand, ctx)
        if resolved is not None:
            return resolved
    return None


def _resolve_root(root: str, ctx: ExecutionContext) -> Any:
    if root == "inputs":
        return ctx.inputs
    if root == "steps":
        return ctx.steps
    if root == "response":
        return ctx.response
    if root == "statusCode":
        return ctx.response.status_code if ctx.response is not None else None
    # Anything else is a loop variable bound by `foreach`.
    return ctx.loop_vars.get(root)


def _navigate(value: Any, token: str | int) -> Any:
    if token == "length":
        try:
            return len(value)
        except TypeError:
            return None
    if isinstance(token, int):
        try:
            return value[token]
        except (IndexError, KeyError, TypeError):
            return None
    if isinstance(value, Mapping):
        return value.get(token)
    return getattr(value, token, None)


def _split_condition(condition: str) -> tuple[str, str | None, str]:
    for comparison in _COMPARISONS:
        index = condition.find(comparison)
        if index != -1:
            return (
                condition[:index].strip(),
                comparison,
                condition[index + len(comparison) :].strip(),
            )
    return condition.strip(), None, ""


def _resolve_operand(token: str, ctx: ExecutionContext) -> Any:
    token = token.strip()
    if token.startswith("$"):
        return evaluate_expression(token, ctx)
    if token in _LITERALS:
        return _LITERALS[token]
    if len(token) >= _MIN_QUOTED_LENGTH and token[0] in _QUOTE_CHARS and token[-1] == token[0]:
        return token[1:-1]
    return _as_number(token, default=token)


def _compare(left: Any, comparison: str, right: Any) -> bool:
    if comparison == "==":
        return left == right
    if comparison == "!=":
        return left != right
    left_num = _as_number(left)
    right_num = _as_number(right)
    if left_num is None or right_num is None:
        return False
    return _ORDERING[comparison](left_num, right_num)


def _as_number(value: Any, default: Any = None) -> Any:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return value
    try:
        text = str(value)
        return float(text) if "." in text else int(text)
    except (TypeError, ValueError):
        return default
