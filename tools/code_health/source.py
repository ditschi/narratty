"""A parsed source file: AST, code lines and inline suppressions."""

from __future__ import annotations

import ast
import io
import re
import tokenize
from dataclasses import dataclass, field

_NOT_CODE = frozenset(
    {
        tokenize.COMMENT,
        tokenize.NL,
        tokenize.NEWLINE,
        tokenize.INDENT,
        tokenize.DEDENT,
        tokenize.ENCODING,
        tokenize.ENDMARKER,
    }
)
# `# code-health: ignore[large-method] reason` or `ignore[a, b] reason`.
_SUPPRESSION = re.compile(r"#\s*code-health:\s*ignore\[([a-z_,\s-]+)\]\s*(.*)")


@dataclass(frozen=True)
class Suppression:
    """An inline ``# code-health: ignore[...]`` comment."""

    line: int
    kinds: frozenset[str]
    reason: str


@dataclass
class Source:
    """Everything the checks need to know about one file."""

    path: str
    text: str
    tree: ast.Module
    code_lines: set[int] = field(default_factory=set)
    suppressions: list[Suppression] = field(default_factory=list)

    @classmethod
    def parse(cls, path: str, text: str) -> Source:
        """Parse ``text``; raises ``SyntaxError`` for files Python cannot read."""
        tree = ast.parse(text, filename=path)
        source = cls(path=path, text=text, tree=tree)
        source.code_lines = _code_lines(text) - _docstring_lines(tree)
        source.suppressions = _suppressions(text)
        return source

    @property
    def loc(self) -> int:
        """Lines holding code: no blank lines, comments or docstrings."""
        return len(self.code_lines)


def _code_lines(text: str) -> set[int]:
    lines: set[int] = set()
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        if token.type not in _NOT_CODE:
            lines.update(range(token.start[0], token.end[0] + 1))
    return lines


def _docstring_lines(tree: ast.Module) -> set[int]:
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if _is_docstring(first):
                assert first is not None  # narrowed by _is_docstring
                lines.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    return lines


def _is_docstring(stmt: ast.stmt | None) -> bool:
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and isinstance(stmt.value.value, str)
    )


def _suppressions(text: str) -> list[Suppression]:
    found = []
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        match = _SUPPRESSION.match(token.string) if token.type == tokenize.COMMENT else None
        if match:
            kinds = frozenset(kind.strip().replace("-", "_") for kind in match[1].split(","))
            found.append(Suppression(token.start[0], kinds, match[2].strip()))
    return found
