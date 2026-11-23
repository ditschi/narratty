# Code health

Code health is scored from 1 to 10 per file and for the repository, modelled on CodeScene's
[Code Health](https://codescene.io/docs/guides/technical/code-health.html): healthy ≥ 9,
warning 4–9, alert < 4. CodeScene's research ("AI-Ready Code", Tornhill 2026) found that
AI-assisted changes to unhealthy code carry at least 60 % more defects. Our target is 10,
no finding at all; 9.5 is only the floor on the way there. The score does not replace
tests, coverage or review.

The scores come from [aihealth](https://github.com/epatel/ai-health) (MIT), the same tool
in all of the owner's Python repositories. Its core is deterministic and needs no AI. It
also scores the Go helper in `agent/` and the shell scripts.

## Usage

```bash
nox -s code-health                          # aihealth scan .: project score, worst files
nox -s code-health -- delta                 # your uncommitted changes against HEAD
nox -s code-health -- delta --staged        # what the pre-commit hook checks
nox -s code-health -- delta --format json   # the same for agents (also: markdown)
nox -s code-health -- scan . --report       # full report in AI-HEALTH.md
nox -s code-health-components -- main       # component scores, merge base vs working tree
```

`delta` names every new or worsened smell with `path:line` and a fix hint, and exits with
1 when health got worse. The session always passes `--config .aihealth.toml`: aihealth
otherwise looks for the file in the scanned folder and silently falls back to its
defaults. Run aihealth directly with
`uv run --isolated --only-group code-health aihealth ... --config .aihealth.toml`.

aihealth is pinned once, in the `code-health` dependency group of `pyproject.toml` (a git
commit, locked in `uv.lock`), so every run comes from uv's cache. On first use it
downloads its tree-sitter grammars (about 30 MB) to `~/.cache/tree-sitter-language-pack`.

## Profile

[`.aihealth.toml`](https://github.com/ditschi/narratty/blob/main/.aihealth.toml) holds the
profile "strict", the only place to change it:

| Key | Value | aihealth default |
|---|---|---|
| `thresholds.large_file` | 600 code lines | 1000 |
| `thresholds.primitive_obsession` | 30 % of typed parameters | 60 % |
| `score.decay` | 8 | 15 |
| `score.symbol_cap` | 4 | 4 |
| `score.density_loc` | 100000 (large files get no relief from a low smell density) | 300 |
| `delta.tolerance` | 0.0 (any degradation fails) | 0.1 |

The other thresholds are aihealth's CodeScene-style defaults: more than 4 parameters,
cyclomatic complexity above 9, functions above 70 code lines, nesting 4 deep, 2 bumps, 2
`and`/`or` in one condition, cognitive complexity above 15, LCOM4 of 3.

## Gate

- **pre-commit**: `aihealth delta --staged` fails when staged changes make code health
  worse; new files may not have any smell. A second hook rejects suppressions without a
  reason.
- **Pull requests**: `aihealth delta` from the merge base to `HEAD` (not `origin/main`:
  newer commits on main are not the branch's doing), then
  `tools/aihealth_components.py`, which fails when the score of a component
  (`src/narratty`, `tests`, `agent`, `tools`, `docker`, `examples`) drops against the merge
  base. `aihealth scan` writes the report into the job summary. The tree-sitter grammars are
  cached.
- The delta tolerance of 0 is the ratchet: nothing may get worse, so the score only rises.

Linters no longer judge structure: ruff's `C90` and pylint's duplicate check are off, so
each smell has one source, aihealth.

## Fix smells, do not suppress them

Refactor rather than suppress: extract functions, return early, replace branches with
lookup tables, name complex conditions, group parameters into a dataclass, introduce small
domain types instead of raw strings and numbers, split modules by responsibility.
Behaviour must not change, and the tests must stay green.

aihealth suppressions apply to a whole file and must give a reason after ` -- ` (without
it aihealth reads the text as part of the smell name and ignores the comment without a
word; a pre-commit hook enforces it):

```python
# aihealth: disable=primitive_obsession -- typer command: options are plain values by design
```

## The earlier own checker

Before aihealth was chosen, `tools/code_health/` scored the repository with its own AST
checks (`code-health.toml`, `code-health-baseline.json`, `nox -s code-health-own`). It
stays as a cross-check, in CI as well, until the aihealth gate runs green. Its test smells
(`tools/code_health/assertions.py`: large and duplicated assertion blocks, which aihealth
does not have yet) are meant as a template for a contribution to aihealth.

## Steckbrief Code Health

The profile below follows the outline shared by all repositories whose code health
approaches are compared; it is kept in German like that outline.

### 1. Messumfang

aihealth bewertet alle Dateien in seinen Sprachen: Python unter `src/`, `tests/`, `tools/`
und `noxfile.py`, Go in `agent/`, Shell-Skripte in `docker/` und `examples/` (218 Dateien,
24.186 Codezeilen). Ausgeschlossen (`[scan] exclude`): das generierte
`src/narratty/_version.py`, die mkdocs-Ausgabe `site/` und `.nox/`. Nicht bewertet werden
YAML-Specs, Markdown, Dockerfiles und CI-Workflows; dafür hat aihealth keine Sprache, und
dort entstehen die Defekte, um die es geht, kaum. Tests zählen voll mit.

### 2. Tools und Versionen

| Sprache | Tool | Version |
|---|---|---|
| Python, Go, Shell | aihealth (tree-sitter 0.26, tree-sitter-language-pack 1.25) | v0.4.0, gepinnt auf Commit `033d1867` |
| alle | uv (dependency group `code-health`, `uv.lock`), nox, pre-commit | wie im Repo |
| Python | eigener Checker `tools/code_health/` (nur stdlib) | Gegenprobe, Config-Version 1 |
| Python | ruff (ohne `C90`), mypy strict, vulture, fawltydeps, pylint (nur zyklische Imports) | unverändert, ohne Strukturregeln |

Eingebunden als uv dependency group statt als Extra: Sie landet nie in den veröffentlichten
Paket-Metadaten, die keine Git-URLs enthalten dürfen, und `uv run --isolated --only-group`
braucht keine eigene Umgebung neben `.venv`. Das passt zu den vorhandenen Hooks, die ruff
und mypy genauso starten.

### 3. Abgebildete Smells

aihealth deckt ab: Brain Method, Large Method, Complex Method, Cognitive Complexity, Deep
Nesting, Bumpy Road, Excess Arguments, Complex Conditional, Large File, Low Cohesion
(LCOM4), Primitive Obsession und Code Duplication (Deep Widget Tree und Missing Phony
betreffen hier nichts). Nicht abgebildet: Large und Duplicated Assertion Blocks (hat
aihealth noch nicht; der eigene Checker misst sie als Gegenprobe und dient als Vorlage für
einen Upstream-Beitrag), God Class als eigener Smell (über Large File, Low Cohesion und
Brain Method abgedeckt), Many Functions per Module (über Large File abgedeckt). Change
Coupling und Hotspots aus der Git-Historie sind keine Datei-Smells und dienen nur der
Priorisierung.

### 4. Schwellen, Gewichte und Score-Formel

Profil "strict" in `.aihealth.toml` (siehe [Profile](#profile)), vom Owner bestätigt:
`large_file = 600`, `primitive_obsession = 0.3`, `decay = 8`, `symbol_cap = 4`,
`density_loc = 100000`, `tolerance = 0.0`. Übrige Schwellen und die Gewichte sind die
Defaults von aihealth v0.4.0 (`src/aihealth/config.py`). Die Score-Formel ist die von
aihealth: Abzüge der Smells, je Symbol gedeckelt (`symbol_cap`), über eine Abklingkurve
(`decay`) auf 1–10 abgebildet; der Repo-Score ist der mit Codezeilen gewichtete Mittelwert.

### 5. Bedienung

`nox -s code-health` (Standard `scan .`) und `nox -s code-health -- delta [--staged |
--base REV --head REV]`, jeweils mit `--config .aihealth.toml`. Ausgabe als Text,
`--format markdown` für Agents und Berichte oder `--format json` (Dateien mit `findings`:
`smell`, `line`, `symbol`, `value`, `threshold`, `hint`, `penalty`). Der Modus für geänderte
Dateien ist `delta`. Laufzeit: `aihealth --version` 0,3 s aus dem Cache, `delta` über den
Branch wenige Sekunden, `scan .` 6–15 s, der Komponenten-Vergleich etwa 10 s. aihealth
bietet zusätzlich einen MCP-Server und Claude-Code-Hooks; beides ist hier nicht
eingerichtet.

### 6. Gate

pre-commit: `code-health` (`delta --staged`) und `aihealth-disable-reason` (pygrep, Regex
`aihealth:[ \t]*disable=(?![\w, \t]+-- .{10})`). PR-Workflow: `delta` von der Merge-Base
zu `HEAD`, Komponenten-Vergleich (`tools/aihealth_components.py`, Toleranz 0), `scan` als
Bericht in der Job-Zusammenfassung, Cache für die Grammatiken und bis zur Ablösung die
Gegenprobe mit dem eigenen Checker. Ratchet: Toleranz 0, also keine Verschlechterung; eine
Baseline-Datei braucht aihealth dafür nicht (die des eigenen Checkers bleibt für die
Gegenprobe). Suppressions: nur dateiweit als `# aihealth: disable=<smell> -- <Grund>`.

### 7. Ergebnis

Vorher (aihealth v0.4.0, strict, Branch `feat/code-health`): Repo-Score **7.26**
(warning), 148 Dateien healthy, 65 warning, 5 alert, 366 Funde in 85 Dateien. Häufigste
Funde: Complex Method (85), Complex Conditional (69), Primitive Obsession (59), Excess
Arguments (57), Cognitive Complexity (35), Code Duplication (33). Schlechteste Dateien:
`src/narratty/build.py` 1.64, `spec/markdown/scenes.py` 1.67, `spec/model.py` 3.24,
`render/scene_cache.py` 3.50, `spec/markdown/shell.py` 3.83. Zum Vergleich: main hatte
mit der Default-Kurve 8.28 und mit strict 7.11; der eigene Checker kam auf 7.91.

Nachher: offen, die Refactorings in Richtung 10 warten auf die Freigabe des Owners.

### 8. Skills

Geprüft (SKILL.md gelesen): l-mb/python-refactoring-skills (`py-refactor`,
`py-complexity`, `py-code-health`), kucherenko/jscpd@dry-refactoring,
github/awesome-copilot@refactor-method-complexity-reduce und @refactor,
wondelai/skills@refactoring-patterns, wshobson/agents@python-design-patterns,
addyosmani/agent-skills@code-review-and-quality, mryll/skills@low-complexity,
anthropics/knowledge-work-plugins@tech-debt. Ausgeschlossen: `*@codehealth-mcp`
(kostenpflichtiges Token). Installiert (vom Owner, projektlokal): `py-complexity` und
`py-code-health` (`.claude/skills/`, Commit `b083571` in `skills-lock.json`). Übernommen
werden ihre Refactoring-Muster, gemessen wird mit aihealth. Ihre Anweisungen, radon,
lizard, xenon und wily als Abhängigkeiten aufzunehmen und `py-quality-setup` laufen zu
lassen, gelten hier nicht (Hinweis in AGENTS.md). In einer zweiten Runde (21 Stichwörter,
22 SKILL.md gelesen, u. a. TDD, Tests, Typing, Review, typer, pydantic, Go) hat der Owner
zusätzlich `systematic-debugging` und `verification-before-completion` aus obra/superpowers
installiert; deren npm-Teile (`find-polluter.sh`) gelten hier nicht. Abgelehnt u. a.
trailofbits@modern-python (ersetzt mypy durch `ty` und pre-commit durch `prek`, CC-BY-SA).

### 9. Erfahrungen

Gut: Der eigene Prototyp zeigte früh dieselben Hotspots wie aihealth (`build.py`,
`scenes.py`, `scene_cache.py`) und lag im Repo-Score nah dran (7.91 gegen 7.11 mit
strict); mit ihm ließen sich Gate-Logik und Ratchet erproben. aihealth bringt Go und Shell
mit und braucht keine Baseline-Datei, weil `delta` gegen die Basisrevision rechnet.
Weniger gut: aihealth unterdrückt nur dateiweit, und ein Formfehler im
Suppression-Kommentar fällt nicht auf (daher der pygrep-Hook). Unter strict scheitern auch
frisch geschriebene kleine Hilfsmodule an Primitive Obsession (30 %); typer-Befehle und
Test-Helfer haben naturgemäß viele `str`- und `int`-Parameter. Übertragbar: Pin auf einen
Commit in einer uv dependency group, `--config` immer ausdrücklich, Delta gegen die
Merge-Base, Komponenten-Vergleich als kleines Skript, pygrep-Hook für Begründungen.
Projektspezifisch: die Komponentenliste und die Gegenprobe mit dem eigenen Checker.
