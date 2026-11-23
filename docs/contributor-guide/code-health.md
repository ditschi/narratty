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

## Steckbrief Code Health

The profile below follows the outline shared by all repositories whose code health
approaches are compared later; it is kept in German like that outline.

### 1. Messumfang

Gezählt werden alle Python-Dateien unter `src/`, `tests/` und `tools/` sowie `noxfile.py`
(`include` in `code-health.toml`). Nicht gezählt werden `src/narratty/_version.py`
(generiert), der Go-Helfer `agent/` (eigene Sprache, eigenes `go vet`), Shell-Skripte,
YAML-Specs, Docs und Docker-Dateien: Dort entstehen die Defekte, die das Whitepaper
meint, kaum, und Python-Werkzeuge messen sie nicht sinnvoll. Tests zählen mit, aber mit
Test-Smells statt Duplikaten. Codezeilen sind Zeilen ohne Leerzeilen, Kommentare und
Docstrings.

### 2. Tools und Versionen

| Sprache | Tool | Rolle |
|---|---|---|
| Python | eigener Checker `tools/code_health/` (Standardbibliothek: `ast`, `tokenize`, `tomllib`; Python ≥ 3.11, im Repo 3.12) | alle Metriken, Score, Gate |
| Python | nox (Session `code-health`), uv, pre-commit | Aufruf |
| Python | lizard 1.26.1, complexipy 9.0.0 (beide MIT) | nur Gegenprobe, keine Abhängigkeit |

Begründung: Das Repo setzt auf uv, nox, ruff und mypy. ruff liefert zwar C901,
PLR0913 und PLR1702, aber nur Ja/Nein-Treffer ohne `and`/`or` in der Komplexität, ohne
kognitive Komplexität, Bumpy Road, LCOM4 und Assertion-Blöcke. Ein Checker in reinem
Python braucht keine weitere Abhängigkeit, läuft als nox-Session, wird von ruff und mypy
geprüft wie der übrige Code und misst sich selbst. radon und xenon (letzte Releases 2023
und 2024) und jscpd (npm) passen schlechter zum Setup.

### 3. Abgebildete Smells

| CodeScene-Kriterium | Hier | Umsetzung |
|---|---|---|
| Complex Method | `complex_method` | McCabe inkl. `and`/`or` und Comprehensions (= lizard) |
| Large Method | `large_method` | Codezeilen je Funktion |
| Brain Method | `brain_method` | groß, komplex und verschachtelt zugleich |
| Excess Function Arguments | `many_arguments` | ohne `self`/`cls`, Typer-Optionen, pytest-Fixtures |
| Primitive Obsession | `primitive_obsession` | Anteil primitiver Annotationen je Modul |
| Code Duplication (DRY) | `duplication` | gleiche normalisierte 6-Zeilen-Fenster über alle Dateien |
| Deep, Nested Complexity | `nested_complexity` | if/for/while/except/match-Tiefe |
| Bumpy Road | `bumpy_road` | getrennte Top-Level-Blöcke mit Tiefe ≥ 2 |
| Complex Conditional | `complex_conditional` | `and`/`or` je Bedingung |
| (kognitive Komplexität, Sonar) | `cognitive_complexity` | SonarSource-Regeln |
| Lines of Code in a Single File | `large_file` | Codezeilen je Datei |
| Large Module / viele Funktionen | `many_functions` | Funktionen und Methoden je Datei |
| Brain/God Class | `god_class` | Zeilen, Methoden und Summe der Komplexität |
| Low Cohesion | `low_cohesion` | LCOM4 je Klasse |
| Large Assertion Blocks | `large_assertion_block` | aufeinanderfolgende `assert` |
| Duplicated Assertion Blocks | `duplicated_assertion_block` | gleiche 3er-Folgen in mehreren Tests |

Nicht abgebildet: Low Cohesion auf Modulebene (würde fast jedes Utility-Modul treffen),
String-Heavy Arguments (in Primitive Obsession enthalten), Overall Code Complexity und
Functions with many returns (durch zyklomatische und kognitive Komplexität abgedeckt),
Change Coupling und Hotspots aus der Git-Historie (kein Smell der Datei, sondern
Priorisierung; wird beim Refactoring von Hand genutzt).

### 4. Schwellen, Gewichte und Score-Formel

Alle Werte stehen versioniert in `code-health.toml` (`version = 1`) und sind dort als
CodeScene-Default oder Annahme markiert; siehe auch die Tabelle unter [Score](#score).
Formel je Datei: `score = max(1.0, 10 - Σ_Art min(3.0, Σ_Treffer min(max, weight + step · (Wert - Schwelle))))`.
Repo-Score: Mittelwert der Datei-Scores, gewichtet mit Codezeilen; die schlechteste Datei
wird mit ausgegeben. Bänder wie CodeScene: grün ≥ 9.0, gelb 4.0–8.9, rot < 4.0.

### 5. Bedienung

`nox -s code-health` (oder `python -m tools.code_health`) mit `--changed [BASE]` (Dateien
seit dem Merge-Base mit `origin/main`, inklusive nicht committeter), `--json` für Agents
(`repo_score`, `worst_file`, `gate.violations`, `reports[].smells[]` mit `kind`, `line`,
`symbol`, `value`, `deduction`), Dateien als Argumente (pre-commit), `--update-baseline`,
`--exit-zero`. Ausgabe sonst als Tabelle mit Datei, Score und Smells samt Zeile.
Laufzeit für 200 Dateien und 24.000 Codezeilen: etwa 1,7 s komplett, etwa 3,4 s mit
`--changed` (zweiter Durchlauf für die Basisrevision).

### 6. Gate

pre-commit-Hook `code-health` (gegen `HEAD`), Schritt "Code health (changed files)" im
PR-Workflow (`--changed origin/<base>`) und `code-health` in den Standard-Sessions von
`nox`. Geänderte Dateien brauchen ≥ 9.5 oder dürfen als Baseline-Datei nicht unter ihren
Baseline-Wert fallen; keine geänderte Datei darf schlechter werden als in der
Basisrevision; der Repo-Score darf nicht unter den Baseline-Wert fallen.
`code-health-baseline.json` ist die Ratchet; `--update-baseline` schreibt sie nur, wenn
das Gate grün ist (oder bei neuer Config-Version). Suppressions nur inline als
`# code-health: ignore[smell] Begründung`; ohne Begründung wirkungslos und selbst ein
Smell (−0.5).

### 7. Ergebnis

Vorher (Config-Version 1, Stand des Branches `feat/code-health`): Repo-Score **7.91**
(gelb), 200 Dateien, 23.851 Codezeilen, 44 Dateien unter 9.5. Schlechteste Dateien:
`src/narratty/build.py` 1.00, `src/narratty/spec/markdown/scenes.py` 1.00,
`render/scene_cache.py` 3.55, `render/browser.py` 4.52, `spec/model.py` 4.55. Häufigste
Smells: Complex Method (84), viele Argumente (70), kognitive Komplexität (34),
Duplikate (17), Large Assertion Block (16), Bumpy Road (13).

Nachher: offen, die Refactorings warten auf die Freigabe des Owners.

### 8. Skills

Geprüft (SKILL.md gelesen): l-mb/python-refactoring-skills (`py-refactor`,
`py-complexity`, `py-code-health`), kucherenko/jscpd@dry-refactoring,
github/awesome-copilot@refactor-method-complexity-reduce und @refactor,
wondelai/skills@refactoring-patterns, wshobson/agents@python-design-patterns,
addyosmani/agent-skills@code-review-and-quality, mryll/skills@low-complexity,
anthropics/knowledge-work-plugins@tech-debt. Ausgeschlossen: `*@codehealth-mcp`
(kostenpflichtiges Token). Empfohlen: `py-complexity` und `py-code-health`. Übernommen:
noch keiner, die Installation wartet auf die Zustimmung des Owners.

### 9. Erfahrungen

Gut: Ein reiner AST-Checker ist schnell, ohne Abhängigkeiten und prüft sich selbst; die
Werte stimmen mit lizard überein. Der Vergleich mit der Basisrevision macht "nicht
schlechter werden" ohne gespeicherte Datei-Scores möglich. Weniger gut: kognitive
Komplexität weicht in Randfällen (Comprehensions) um bis zu etwa 20 % von complexipy ab,
und ohne Ausnahmen für Typer-Optionen und pytest-Fixtures wäre fast jeder CLI-Befehl ein
Smell. Übertragbar: Score-Formel mit Deckel je Smell-Art, Ratchet-Baseline, die sich
nur bei grünem Gate aktualisieren lässt, Suppressions nur mit Begründung. Projektspezifisch:
die Typer-Ausnahme und die Wahl der Verzeichnisse.
