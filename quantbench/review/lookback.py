from __future__ import annotations

import ast
import math
from dataclasses import dataclass


DEFAULT_MIN_LOOKBACK_BARS = 21


@dataclass(frozen=True)
class LookbackEstimate:
    lookback_bars: int
    source: str


def estimate_lookback_bars(code: str, total_observations: int | None = None) -> LookbackEstimate:
    declared = _declared_lookback(code)
    if declared is not None:
        return LookbackEstimate(max(0, declared), "declared")

    inferred = _infer_lookback_from_ast(code)
    if inferred is not None:
        return LookbackEstimate(max(0, inferred), "inferred")

    fallback = DEFAULT_MIN_LOOKBACK_BARS
    if total_observations is not None and total_observations > 0:
        fallback = max(fallback, int(math.ceil(total_observations * 0.02)))
    return LookbackEstimate(fallback, "default")


def _declared_lookback(code: str) -> int | None:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "lookback_bars":
                    value = _literal_int(node.value)
                    if value is not None:
                        return value
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "lookback_bars":
            value = _literal_int(node.value)
            if value is not None:
                return value
    return None


def _infer_lookback_from_ast(code: str) -> int | None:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    windows: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        attr = node.func.attr if isinstance(node.func, ast.Attribute) else ""
        if attr in {"rolling", "shift", "pct_change"}:
            value = _first_window_argument(node, "window")
            if value is not None:
                windows.append(value)
        elif attr == "ewm":
            value = _first_window_argument(node, "span")
            if value is not None:
                windows.append(value)
    return max(windows) if windows else None


def _first_window_argument(node: ast.Call, keyword_name: str) -> int | None:
    if node.args:
        value = _literal_int(node.args[0])
        if value is not None:
            return value
    for keyword in node.keywords:
        if keyword.arg == keyword_name:
            value = _literal_int(keyword.value)
            if value is not None:
                return value
    return None


def _literal_int(node: ast.AST | None) -> int | None:
    if node is None:
        return None
    try:
        value = ast.literal_eval(node)
    except (ValueError, SyntaxError):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None
