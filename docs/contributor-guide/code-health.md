# Code health

`nox -s code-health` scores every Python file from 1 to 10, modelled on CodeScene's
[Code Health](https://codescene.io/docs/guides/technical/code-health.html): green ≥ 9.0,
yellow 4.0–8.9, red < 4.0. CodeScene's research ("AI-Ready Code", Tornhill 2026) found
that AI-assisted changes to unhealthy code carry at least 60 % more defects, so we hold
changed code to 9.5. The score does not replace tests, coverage or review.

We do not use CodeScene itself (its score needs a paid token). The checker in
`tools/code_health/` rebuilds the smells from Python's AST with the standard library
only; its cyclomatic numbers match [lizard](https://github.com/terryyin/lizard) and its
cognitive complexity follows SonarSource (close to
[complexipy](https://github.com/rohaquinlop/complexipy)).

## Usage

```bash
nox -s code-health                          # every file, gate against the baseline
nox -s code-health -- --changed             # files changed since origin/main, uncommitted ones included
nox -s code-health -- --changed v0.4.0      # ... since another base
nox -s code-health -- --json --changed      # the same as JSON, for agents
nox -s code-health -- src/narratty/build.py # these files (what the pre-commit hook does)
nox -s code-health -- --update-baseline     # record improved scores (ratchet)
```

The table lists files with smells, worst first, each smell with its line, the function
or class, the measured value and what it costs. The JSON has the same data under
`reports`, plus `repo_score`, `worst_file` and `gate.violations`.

## Score

Every file starts at 10.0. Each smell deducts a weight, which grows with how far the value
is over its threshold and is capped per occurrence; one kind of smell deducts at most 3.0
per file, and no file drops below 1.0. The repository score is the mean of the file
scores weighted by their code lines (no blank lines, comments or docstrings).

Thresholds and weights live in [`code-health.toml`](https://github.com/ditschi/narratty/blob/main/code-health.toml),
which also marks each one as a CodeScene default or as our own assumption. Scores are only
comparable within one `version` of that file.

| Level | Smell | Starts at |
|---|---|---|
| Function | Complex Method | cyclomatic complexity > 9 (`and`/`or` count) |
| | Cognitive complexity | > 15 (SonarSource) |
| | Large Method | > 70 code lines |
| | Brain Method | ≥ 60 lines, CC ≥ 15 and nesting ≥ 3 at once |
| | Many arguments | ≥ 5 parameters; `self`/`cls`, typer options and pytest fixtures excluded |
| | Nested complexity | if/for/while/except/match nested 4 deep (`elif`, `with` and `try:` do not nest) |
| | Bumpy Road | ≥ 2 separate top-level blocks nested ≥ 2 deep |
| | Complex Conditional | ≥ 4 `and`/`or` in one condition |
| | Duplication (DRY) | ≥ 6 identical normalised lines elsewhere (test files excluded) |
| Module | Large File | > 1000 code lines |
| | Many functions | > 60 functions and methods |
| | God Class | ≥ 300 lines, ≥ 20 methods and summed CC ≥ 80 |
| | Low Cohesion | LCOM4 ≥ 2 in a class with ≥ 4 methods (dunders and methods not using `self` left out) |
| | Primitive Obsession | ≥ 70 % of ≥ 20 annotated parameters are `str`/`int`/`float`/`bool`/`bytes` |
| Tests | Large Assertion Block | ≥ 6 consecutive asserts |
| | Duplicated Assertion Block | the same 3 consecutive asserts in more than one test of a file |

## Gate

Pre-commit (`code-health` hook) and CI (`nox -s code-health -- --changed origin/main`) fail when

- a changed file scores below 9.5, unless it is listed in the baseline and has not
  dropped below the score recorded there,
- a changed file scores lower than it did at the base revision (`HEAD` for pre-commit,
  the merge base for `--changed`),
- the repository score drops below the one recorded in the baseline.

`code-health-baseline.json` is the ratchet while the repository is below its target: it
records the files below 9.5 with their scores and the repository score. After improving
code, run `nox -s code-health -- --update-baseline` and commit the file; the update is
refused while the gate fails, so the recorded scores only go up. Start a new baseline only
when `code-health.toml` gets a new `version`.

## Fix smells, do not suppress them

Refactor rather than suppress: extract functions, return early, replace branches with
lookup tables, group parameters into a dataclass, split modules by responsibility.
Behaviour must not change, and the tests must stay green.

When a smell really is the clearest way to write something, suppress it on its line, or
in a comment right above it (decorators may sit in between), and say why:

```python
# code-health: ignore[complex-method] one flat branch per Docker error keeps the mapping readable
def classify(error: str) -> ExitCode:
    ...
```

A suppression without a reason is ignored and costs 0.5 itself. Module smells
(`large-file`, `many-functions`, `primitive-obsession`) are suppressed in the file's
leading comment block.
