"""2.0 tools MOTH uses while answering, so it does not have to guess.

* ``calculate`` — exact arithmetic for a question such as "what is 1234 * 5678?" or "(17 + 5) / 4". A safe
  evaluator (numbers and + − × ÷ % ** and brackets only; no names, no calls) computes the value, which goes to
  the model as a fact to use.
"""

from __future__ import annotations

import ast
import operator
import re
from fractions import Fraction

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow}
_EXPR = re.compile(r"(?<![\w.])([-+(]*\s*\d[\d,_.]*(?:\s*(?:\*\*|[-+*/x×÷%^])\s*[-+(]*\s*\d[\d,_.]*\)*)+\)*)")


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return Fraction(str(node.value))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        v = _eval(node.operand)
        return v if isinstance(node.op, ast.UAdd) else -v
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        a, b = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow):
            if b.denominator != 1 or abs(b) > 64 or abs(a) > 10**6:
                raise ValueError("power too large")
            return a ** int(b)
        if isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)) and b == 0:
            raise ZeroDivisionError
        if isinstance(node.op, ast.Div):
            return a / b
        return Fraction(_OPS[type(node.op)](a, b))
    raise ValueError("not plain arithmetic")


def _fmt(v: Fraction) -> str:
    if v.denominator == 1:
        return str(v.numerator)
    f = float(v)
    return f"{f:.10g}"


def calculate(text: str) -> tuple[str, str] | None:
    """(expression, exact value) for the arithmetic in a message, or None."""
    best = None
    for m in _EXPR.finditer(text or ""):
        raw = m.group(1).strip()
        if len(raw) > 200:
            continue
        expr = raw.replace(",", "").replace("_", "").replace("×", "*").replace("x", "*").replace("÷", "/").replace("^", "**")
        # unbalanced brackets from the surrounding sentence
        while expr.count("(") > expr.count(")") and expr.startswith("("):
            expr = expr[1:].strip()
        while expr.count(")") > expr.count("(") and expr.endswith(")"):
            expr = expr[:-1].strip()
        if re.fullmatch(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", expr) or re.fullmatch(r"\d+(\.\d+){2,}", expr):
            continue  # a date or a version number, not a sum
        try:
            value = _eval(ast.parse(expr, mode="eval"))
        except (SyntaxError, ValueError, ZeroDivisionError, OverflowError, RecursionError):
            continue
        if best is None or len(expr) > len(best[0]):
            best = (expr.replace("**", "^"), _fmt(value))
    return best
