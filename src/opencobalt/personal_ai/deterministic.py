"""Bounded in-process deterministic operations for obvious micro-tasks.

This is not a tool framework and never launches a shell. Arithmetic and a
small unit-conversion table are evaluated with ``ast`` and explicit formulas.
Unrecognized prompts return None so routing can fall through to a model.
"""

from __future__ import annotations

import ast
import operator
import re
from dataclasses import dataclass
from typing import Any

_BINOPS: dict[type, Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARYOPS: dict[type, Any] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

_WORD_OPS = (
    (re.compile(r"\bmultiplied\s+by\b"), "*"),
    (re.compile(r"\btimes\b"), "*"),
    (re.compile(r"\bplus\b"), "+"),
    (re.compile(r"\bminus\b"), "-"),
    (re.compile(r"\bdivided\s+by\b"), "/"),
    (re.compile(r"\bx\b"), "*"),
)

_PREFIX = re.compile(
    r"^(?:what\s+is|what's|calculate|compute|convert)\s+",
    re.IGNORECASE,
)
_TRAILING = re.compile(r"[?!.]+\s*$")
_PERCENT_OF = re.compile(
    r"^(?P<pct>-?\d+(?:\.\d+)?)\s*(?:percent|%)\s+of\s+(?P<base>-?\d+(?:\.\d+)?)$",
    re.IGNORECASE,
)

_CONVERSIONS: dict[tuple[str, str], tuple[str, Any]] = {
    ("celsius", "fahrenheit"): ("°F", lambda c: c * 9 / 5 + 32),
    ("fahrenheit", "celsius"): ("°C", lambda f: (f - 32) * 5 / 9),
    ("km", "miles"): ("mi", lambda km: km * 0.621371192),
    ("kilometers", "miles"): ("mi", lambda km: km * 0.621371192),
    ("miles", "km"): ("km", lambda miles: miles / 0.621371192),
    ("miles", "kilometers"): ("km", lambda miles: miles / 0.621371192),
    ("kg", "pounds"): ("lb", lambda kg: kg * 2.20462262),
    ("kilograms", "pounds"): ("lb", lambda kg: kg * 2.20462262),
    ("pounds", "kg"): ("kg", lambda lb: lb / 2.20462262),
    ("pounds", "kilograms"): ("kg", lambda lb: lb / 2.20462262),
}

_CONVERT = re.compile(
    r"^(?:convert\s+)?(?P<value>-?\d+(?:\.\d+)?)\s*(?P<src>[a-z°]+)\s+"
    r"(?:to|in)\s+(?P<dst>[a-z°]+)$",
    re.IGNORECASE,
)

_UNIT_ALIASES = {
    "c": "celsius",
    "°c": "celsius",
    "celsius": "celsius",
    "f": "fahrenheit",
    "°f": "fahrenheit",
    "fahrenheit": "fahrenheit",
    "km": "km",
    "kilometer": "kilometers",
    "kilometers": "kilometers",
    "mi": "miles",
    "mile": "miles",
    "miles": "miles",
    "kg": "kg",
    "kilogram": "kilograms",
    "kilograms": "kilograms",
    "lb": "pounds",
    "lbs": "pounds",
    "pound": "pounds",
    "pounds": "pounds",
}


@dataclass(frozen=True)
class DeterministicResult:
    kind: str
    expression: str
    value: int | float
    display: str
    unit: str | None = None

    def render(self) -> str:
        return self.display


def try_deterministic(prompt: str) -> DeterministicResult | None:
    """Return a result only when the prompt is an obvious closed-form micro-task."""
    text = _normalize_prompt(prompt)
    if not text:
        return None
    conversion = _try_conversion(text)
    if conversion is not None:
        return conversion
    percent = _PERCENT_OF.fullmatch(text)
    if percent is not None:
        pct = float(percent.group("pct"))
        base = float(percent.group("base"))
        value = base * pct / 100.0
        return DeterministicResult(
            kind="percent",
            expression=f"{pct}% of {base}",
            value=value,
            display=_format_number(value),
        )
    expression = _to_expression(text)
    if expression is None:
        return None
    try:
        value = _eval_expression(expression)
    except (ValueError, ZeroDivisionError, OverflowError, TypeError):
        return None
    return DeterministicResult(
        kind="arithmetic",
        expression=expression,
        value=value,
        display=_format_number(value),
    )


def _normalize_prompt(prompt: str) -> str:
    text = _TRAILING.sub("", prompt.strip())
    text = _PREFIX.sub("", text).strip()
    return re.sub(r"\s+", " ", text)


def _try_conversion(text: str) -> DeterministicResult | None:
    match = _CONVERT.fullmatch(text)
    if match is None:
        return None
    src = _UNIT_ALIASES.get(match.group("src").casefold())
    dst = _UNIT_ALIASES.get(match.group("dst").casefold())
    if src is None or dst is None or src == dst:
        return None
    formula = _CONVERSIONS.get((src, dst))
    if formula is None:
        return None
    unit, fn = formula
    value = fn(float(match.group("value")))
    return DeterministicResult(
        kind="conversion",
        expression=text,
        value=value,
        display=f"{_format_number(value)} {unit}",
        unit=unit,
    )


def _to_expression(text: str) -> str | None:
    rewritten = text
    for pattern, replacement in _WORD_OPS:
        rewritten = pattern.sub(replacement, rewritten)
    rewritten = rewritten.replace("×", "*").replace("÷", "/")
    rewritten = re.sub(r"\s+", "", rewritten)
    if not rewritten or not re.fullmatch(r"[\d.+\-*/()%]+", rewritten):
        return None
    if not re.search(r"\d", rewritten):
        return None
    if rewritten.count("(") != rewritten.count(")"):
        return None
    return rewritten.replace("%", "/100")


def _eval_expression(expression: str) -> int | float:
    tree = ast.parse(expression, mode="eval")
    if _node_count(tree) > 32:
        raise ValueError("expression too large")
    value = _eval_ast(tree.body)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError("non-numeric result")
    if abs(value) > 1e12:
        raise OverflowError("result too large")
    return value


def _eval_ast(node: ast.AST) -> int | float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(
        node.value, bool
    ):
        return node.value
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARYOPS:
        return _UNARYOPS[type(node.op)](_eval_ast(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        left = _eval_ast(node.left)
        right = _eval_ast(node.right)
        if isinstance(node.op, ast.Pow):
            if abs(right) > 12 or abs(left) > 1_000_000:
                raise ValueError("exponent too large")
        if isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)) and right == 0:
            raise ZeroDivisionError("division by zero")
        return _BINOPS[type(node.op)](left, right)
    raise ValueError("unsupported expression")


def _node_count(node: ast.AST) -> int:
    return sum(1 for _ in ast.walk(node))


def _format_number(value: int | float) -> str:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, int):
        return str(value)
    text = f"{value:.10f}".rstrip("0").rstrip(".")
    return text or "0"
