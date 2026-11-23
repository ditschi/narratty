"""Raw per-function metrics from the AST.

Nested functions and classes are measured on their own and left out of the
function that contains them. Lambdas count towards the enclosing function.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from dataclasses import dataclass, field
from fnmatch import fnmatch

FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
_LOOPS = (ast.For, ast.AsyncFor, ast.While)
_PRIMITIVES = frozenset({"str", "int", "float", "bool", "bytes"})


@dataclass
class FunctionMetrics:
    """What we measure about one function."""

    name: str
    line: int
    loc: int = 0
    params: int = 0
    primitive_params: int = 0
    annotated_params: int = 0
    cyclomatic: int = 1
    cognitive: int = 0
    nesting: int = 0
    bumps: int = 0
    injected: bool = False
    conditions: list[tuple[int, int]] = field(default_factory=list)


def iter_functions(node: ast.AST, prefix: str = "") -> Iterator[tuple[str, FunctionNode]]:
    """Yield every function with its qualified name, nested ones included."""
    for child in own_nodes(node):
        if isinstance(child, _SCOPES):
            name = f"{prefix}{child.name}"
            if not isinstance(child, ast.ClassDef):
                yield name, child
            yield from iter_functions(child, f"{name}.")


def own_nodes(node: ast.AST) -> Iterator[ast.AST]:
    """Walk ``node``'s subtree without entering nested functions or classes."""
    for child in ast.iter_child_nodes(node):
        yield child
        if not isinstance(child, _SCOPES):
            yield from own_nodes(child)


@dataclass(frozen=True)
class Options:
    """Settings that change how functions are measured."""

    bump_depth: int = 2
    # Parameters with these defaults declare CLI options (typer) and are not counted.
    declared_defaults: tuple[str, ...] = ()


def measure(name: str, node: FunctionNode, code_lines: set[int], options: Options) -> FunctionMetrics:
    """All metrics of one function; ``code_lines`` are the file's lines that hold code."""
    metrics = FunctionMetrics(name=name, line=node.lineno)
    metrics.loc = _loc(node, code_lines)
    metrics.injected = _is_pytest_injected(node)
    _count_params(node, metrics, options.declared_defaults)
    metrics.cyclomatic = cyclomatic(node)
    metrics.cognitive = Cognitive.of(node)
    metrics.nesting = max_nesting(node.body)
    metrics.bumps = bumps(node.body, options.bump_depth)
    metrics.conditions = conditions(node)
    return metrics


def _loc(node: FunctionNode, code_lines: set[int]) -> int:
    end = node.end_lineno or node.lineno
    return sum(1 for line in range(node.lineno, end + 1) if line in code_lines)


def _is_pytest_injected(node: FunctionNode) -> bool:
    """Tests and fixtures, whose parameters are fixtures pytest injects."""
    decorators = [ast.unparse(decorator) for decorator in node.decorator_list]
    return node.name.startswith("test") or any("fixture" in decorator for decorator in decorators)


def _count_params(node: FunctionNode, metrics: FunctionMetrics, declared: tuple[str, ...]) -> None:
    positional = [*node.args.posonlyargs, *node.args.args]
    defaults = [None] * (len(positional) - len(node.args.defaults)) + list(node.args.defaults)
    pairs = [
        *zip(positional, defaults, strict=True),
        *zip(node.args.kwonlyargs, node.args.kw_defaults, strict=True),
    ]
    if pairs and pairs[0][0].arg in {"self", "cls"}:
        pairs = pairs[1:]
    args = [arg for arg, default in pairs if not _is_declared(default, declared)]
    metrics.params = len(args)
    annotated = [arg.annotation for arg in args if arg.annotation is not None]
    metrics.annotated_params = len(annotated)
    metrics.primitive_params = sum(1 for annotation in annotated if is_primitive(annotation))


def _is_declared(default: ast.expr | None, declared: tuple[str, ...]) -> bool:
    if default is None:
        return False
    target = default.func if isinstance(default, ast.Call) else default
    return any(fnmatch(ast.unparse(target), pattern) for pattern in declared)


def is_primitive(annotation: ast.expr) -> bool:
    """``str``, ``int | None``, ``Optional[bool]``, ``Annotated[float, ...]`` and the like."""
    if isinstance(annotation, ast.Name):
        return annotation.id in _PRIMITIVES
    named = [part for part in _unwrapped(annotation) if not _is_none(part)]
    return bool(named) and all(is_primitive(part) for part in named)


def _unwrapped(annotation: ast.expr) -> list[ast.expr]:
    """The types inside ``X | Y``, ``Optional[X]`` and ``Annotated[X, ...]``; [] otherwise."""
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        return [annotation.left, annotation.right]
    if not isinstance(annotation, ast.Subscript) or not isinstance(annotation.value, ast.Name):
        return []
    if annotation.value.id not in {"Optional", "Annotated"}:
        return []
    inner = annotation.slice
    return [inner.elts[0] if isinstance(inner, ast.Tuple) else inner]


def _is_none(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def cyclomatic(node: ast.AST) -> int:
    """McCabe complexity, counting ``and``/``or`` like CodeScene and lizard do."""
    return 1 + sum(_decisions(child) for child in own_nodes(node))


def _decisions(node: ast.AST) -> int:
    if isinstance(node, (ast.If, ast.IfExp, ast.ExceptHandler, ast.match_case, *_LOOPS)):
        return 1
    if isinstance(node, ast.BoolOp):
        return len(node.values) - 1
    if isinstance(node, ast.comprehension):
        return 1 + len(node.ifs)
    return 0


def _nested_blocks(stmt: ast.stmt) -> list[list[ast.stmt]]:
    """Statement lists one nesting level below a control statement."""
    if isinstance(stmt, ast.If):
        return [stmt.body] if _is_elif_chain(stmt) else [stmt.body, stmt.orelse]
    if isinstance(stmt, _LOOPS):
        return [stmt.body, stmt.orelse]
    if isinstance(stmt, (ast.Try, ast.TryStar)):
        return [handler.body for handler in stmt.handlers]
    if isinstance(stmt, ast.Match):
        return [case.body for case in stmt.cases]
    return []


def _flat_blocks(stmt: ast.stmt) -> list[list[ast.stmt]]:
    """Statement lists at the same nesting level as ``stmt`` (with bodies, try bodies, elif)."""
    if isinstance(stmt, (ast.With, ast.AsyncWith)):
        return [stmt.body]
    if isinstance(stmt, (ast.Try, ast.TryStar)):
        return [stmt.body, stmt.orelse, stmt.finalbody]
    if isinstance(stmt, ast.If) and _is_elif_chain(stmt):
        return [stmt.orelse]
    return []


def _is_elif_chain(stmt: ast.If) -> bool:
    return len(stmt.orelse) == 1 and isinstance(stmt.orelse[0], ast.If)


def _is_control(stmt: ast.stmt) -> bool:
    return isinstance(stmt, (ast.If, ast.Try, ast.TryStar, ast.Match, *_LOOPS))


def max_nesting(body: list[ast.stmt]) -> int:
    """Deepest nesting of if/for/while/except/match blocks (a lone ``if`` is 1)."""
    deepest = 0
    for stmt in body:
        if isinstance(stmt, _SCOPES):
            continue
        below = max((max_nesting(block) for block in _nested_blocks(stmt)), default=0)
        here = 1 + below if _is_control(stmt) else 0
        beside = max((max_nesting(block) for block in _flat_blocks(stmt)), default=0)
        deepest = max(deepest, here, beside)
    return deepest


def bumps(body: list[ast.stmt], depth: int = 2) -> int:
    """Top-level blocks whose nesting reaches ``depth`` (the bumps of a Bumpy Road).

    ``with`` and ``try`` bodies are looked through, so wrapping a function in them
    does not merge its bumps into one; each ``except`` block counts on its own.
    """
    count = 0
    for stmt in body:
        if _is_control(stmt) and not isinstance(stmt, (ast.Try, ast.TryStar)):
            count += max_nesting([stmt]) >= depth
            continue
        count += sum(bumps(block, depth) for block in _flat_blocks(stmt))
        count += sum(1 + max_nesting(block) >= depth for block in _nested_blocks(stmt))
    return count


def conditions(node: FunctionNode) -> list[tuple[int, int]]:
    """``(line, and/or operators)`` of every branch condition in the function."""
    found = []
    for child in own_nodes(node):
        for test in _tests(child):
            operators = _bool_operators(test)
            if operators:
                found.append((test.lineno, operators))
    return found


def _tests(node: ast.AST) -> list[ast.expr]:
    if isinstance(node, (ast.If, ast.While, ast.IfExp)):
        return [node.test]
    if isinstance(node, ast.comprehension):
        return list(node.ifs)
    if isinstance(node, ast.match_case) and node.guard is not None:
        return [node.guard]
    return []


def _bool_operators(test: ast.expr) -> int:
    nodes = [test, *own_nodes(test)]
    return sum(len(node.values) - 1 for node in nodes if isinstance(node, ast.BoolOp))


class Cognitive:
    """SonarSource cognitive complexity (structural increments plus nesting penalties)."""

    def __init__(self) -> None:
        self.total = 0

    @classmethod
    def of(cls, node: FunctionNode) -> int:
        """Cognitive complexity of one function."""
        counter = cls()
        counter.statements(node.body, 0)
        return counter.total

    def statements(self, body: list[ast.stmt], nesting: int) -> None:
        """Score a statement list at ``nesting``."""
        for stmt in body:
            if not isinstance(stmt, _SCOPES):
                self.statement(stmt, nesting)

    def statement(self, stmt: ast.stmt, nesting: int) -> None:
        """Score one statement: structural increment, then its parts."""
        if isinstance(stmt, ast.If):
            self.total += 1 + nesting
            self._if_rest(stmt, nesting)
            return
        if isinstance(stmt, (*_LOOPS, ast.Match)):
            self.total += 1 + nesting
        self._expressions(stmt, nesting)
        for block in _nested_blocks(stmt):
            self.statements(block, nesting + 1)
        for block in _flat_blocks(stmt):
            self.statements(block, nesting)
        if isinstance(stmt, (ast.Try, ast.TryStar)):
            self.total += sum(1 + nesting for _ in stmt.handlers)

    def _if_rest(self, stmt: ast.If, nesting: int) -> None:
        self.expression(stmt.test, nesting)
        self.statements(stmt.body, nesting + 1)
        if _is_elif_chain(stmt):
            elif_ = stmt.orelse[0]
            assert isinstance(elif_, ast.If)  # narrowed by _is_elif_chain
            self.total += 1
            self._if_rest(elif_, nesting)
        elif stmt.orelse:
            self.total += 1
            self.statements(stmt.orelse, nesting + 1)

    def _expressions(self, stmt: ast.stmt, nesting: int) -> None:
        for child in ast.iter_child_nodes(stmt):
            if isinstance(child, ast.expr):
                self.expression(child, nesting)

    def expression(self, expr: ast.AST, nesting: int) -> None:
        """Boolean operator sequences, conditional expressions, comprehensions, lambdas."""
        if isinstance(expr, ast.BoolOp):
            self.total += 1
        elif isinstance(expr, ast.IfExp):
            self.total += 1 + nesting
        elif isinstance(expr, ast.comprehension):
            self.total += 1 + len(expr.ifs)
        inner = nesting + 1 if isinstance(expr, (ast.Lambda, ast.IfExp)) else nesting
        for child in ast.iter_child_nodes(expr):
            if isinstance(child, (ast.expr, ast.comprehension)):
                self.expression(child, inner)
