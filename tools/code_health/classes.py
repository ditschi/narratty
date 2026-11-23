"""Class smells: God Class and Low Cohesion (LCOM4)."""

from __future__ import annotations

import ast
from typing import TypeGuard

from .config import Config
from .metrics import FunctionNode, cyclomatic
from .model import Smell
from .source import Source


def class_smells(source: Source, config: Config) -> list[Smell]:
    """God Class and Low Cohesion findings for every class in ``source``."""
    smells: list[Smell] = []
    for node in ast.walk(source.tree):
        if isinstance(node, ast.ClassDef):
            smells += _god_class(node, source, config)
            smells += _low_cohesion(node, config)
    return smells


def _methods(node: ast.ClassDef) -> list[FunctionNode]:
    return [child for child in node.body if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _god_class(node: ast.ClassDef, source: Source, config: Config) -> list[Smell]:
    rule = config.rule("god_class")
    methods = _methods(node)
    end = node.end_lineno or node.lineno
    loc = sum(1 for line in range(node.lineno, end + 1) if line in source.code_lines)
    complexity = sum(cyclomatic(method) for method in methods)
    limits = ((loc, "loc"), (len(methods), "methods"), (complexity, "cyclomatic"))
    if any(value < rule[key] for value, key in limits):
        return []
    message = f"god class: {loc} lines, {len(methods)} methods, cyclomatic complexity {complexity}"
    return [Smell("god_class", node.lineno, node.name, 1, message, rule.weight)]


def _low_cohesion(node: ast.ClassDef, config: Config) -> list[Smell]:
    rule = config.rule("low_cohesion")
    touched = {method.name: _touched(method) for method in _methods(node) if _counts_for_lcom(method)}
    members = {name: names for name, names in touched.items() if names is not None}
    if len(members) < rule["min_methods"]:
        return []
    components = lcom4(members)
    if components < rule.threshold:
        return []
    message = f"LCOM4 {components}: {len(members)} methods fall into {components} unrelated groups"
    return [Smell("low_cohesion", node.lineno, node.name, components, message, rule.deduction(components))]


def _counts_for_lcom(method: FunctionNode) -> bool:
    """Dunder methods (``__init__`` touches everything) and stubs stay out of LCOM4."""
    if method.name.startswith("__") and method.name.endswith("__"):
        return False
    return not _is_stub(method.body)


def _is_stub(body: list[ast.stmt]) -> bool:
    for stmt in body:
        if isinstance(stmt, (ast.Pass, ast.Raise)):
            continue
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            continue  # docstring or `...`
        return False
    return True


def _touched(method: FunctionNode) -> set[str] | None:
    """Attributes and methods reached through ``self``/``cls``; None if it never uses them."""
    args = [*method.args.posonlyargs, *method.args.args]
    if not args or args[0].arg not in {"self", "cls"}:
        return None
    receiver = args[0].arg
    names = {child.attr for child in ast.walk(method) if _is_member_of(child, receiver)}
    return names or None


def _is_member_of(node: ast.AST, receiver: str) -> TypeGuard[ast.Attribute]:
    """``receiver.something``."""
    if not isinstance(node, ast.Attribute):
        return False
    return isinstance(node.value, ast.Name) and node.value.id == receiver


def lcom4(members: dict[str, set[str]]) -> int:
    """Connected components among methods linked by shared attributes or calls."""
    parent = {name: name for name in members}

    def find(name: str) -> str:
        while parent[name] != name:
            name = parent[name]
        return name

    owners: dict[str, str] = {}
    for name, touched in members.items():
        for target in touched:
            linked = target if target in members else owners.setdefault(target, name)
            parent[find(linked)] = find(name)
    return len({find(name) for name in members})
