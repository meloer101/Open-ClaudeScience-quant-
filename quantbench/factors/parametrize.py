from __future__ import annotations

import ast
from typing import Any


def _iter_perturbable_constants(tree: ast.AST):
    """Yield perturbable Constant nodes in one fixed, depth-first,
    left-to-right (pre-order) traversal.

    extract_parameters() and apply_overrides() both call this - and only this
    - to enumerate literals, so a parameter's index always refers to the same
    literal on both sides. Previously extraction used ast.walk() (breadth-
    first) while replacement used ast.NodeTransformer (depth-first); those
    orders disagree as soon as a factor has more than one perturbable literal
    at different tree depths (e.g. `close.rolling(20).mean() - close.shift(5)`),
    silently overriding the wrong literal instead of the one the caller named.
    """
    if _is_perturbable_constant(tree):
        yield tree
    for child in ast.iter_child_nodes(tree):
        yield from _iter_perturbable_constants(child)


def extract_parameters(code: str) -> list[dict[str, Any]]:
    """Return numeric literals that Phase 2 already treats as perturbable.

    Names are best-effort: assignment targets and keyword arguments get stable
    names; positional literals fall back to p1/p2 so they can still be edited.
    """
    tree = ast.parse(code)
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent

    params: list[dict[str, Any]] = []
    for node in _iter_perturbable_constants(tree):
        index = len(params) + 1
        value = float(node.value)
        params.append(
            {
                "name": _infer_name(node, parents) or f"p{index}",
                "value": value,
                "lineno": getattr(node, "lineno", 0),
                "index": index,
            }
        )
    return params


def apply_overrides(code: str, overrides: dict[str, str | int | float]) -> str:
    params = extract_parameters(code)
    if not overrides:
        return code
    known = {param["name"] for param in params} | {f"p{param['index']}" for param in params}
    unknown = set(overrides) - known
    if unknown:
        raise ValueError(f"unknown factor parameter(s): {', '.join(sorted(unknown))}")

    replacements: dict[int, Any] = {}
    by_name = {param["name"]: param for param in params}
    by_pos = {f"p{param['index']}": param for param in params}
    for key, value in overrides.items():
        param = by_name.get(key) or by_pos[key]
        replacements[int(param["index"])] = _coerce_like(value, param["value"])

    # Fresh tree (not the one extract_parameters already parsed) mutated
    # in place via the same _iter_perturbable_constants order - not a second,
    # independent traversal mechanism that could drift out of sync again.
    tree = ast.parse(code)
    for index, node in enumerate(_iter_perturbable_constants(tree), start=1):
        if index in replacements:
            node.value = replacements[index]
    ast.fix_missing_locations(tree)
    return ast.unparse(tree)


def parse_param_overrides(values: list[str] | tuple[str, ...]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for item in values:
        if "=" not in item:
            raise ValueError(f"parameter override must be name=value: {item}")
        key, _, value = item.partition("=")
        if not key:
            raise ValueError(f"parameter override has empty name: {item}")
        overrides[key] = value
    return overrides


def _is_perturbable_constant(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and abs(float(node.value)) >= 2


def _infer_name(node: ast.Constant, parents: dict[ast.AST, ast.AST]) -> str | None:
    parent = parents.get(node)
    if isinstance(parent, ast.Assign) and parent.value is node and len(parent.targets) == 1:
        target = parent.targets[0]
        if isinstance(target, ast.Name):
            return target.id
    if isinstance(parent, ast.AnnAssign) and parent.value is node and isinstance(parent.target, ast.Name):
        return parent.target.id
    if isinstance(parent, ast.keyword) and parent.value is node and parent.arg:
        return parent.arg
    return None


def _coerce_like(value: str | int | float, original: float) -> int | float:
    text = str(value)
    if float(original).is_integer() and "." not in text:
        return int(text)
    return float(text)
