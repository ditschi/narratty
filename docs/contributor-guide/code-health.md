# Code health

Code health is scored from 1 to 10 per file and for the repository, modelled on CodeScene's
[Code Health](https://codescene.io/docs/guides/technical/code-health.html): healthy ≥ 9,
warning 4–9, alert < 4. CodeScene's research ("AI-Ready Code", Tornhill 2026) found that
AI-assisted changes to unhealthy code carry at least 60 % more defects. Our target is 10,
no finding at all, with 9.5 as the minimum to reach on the way. The gate itself enforces
"no degradation" (see [Gate](#gate)), not a fixed score. The score does not replace tests,
coverage or review.

The scores come from [aihealth](https://github.com/epatel/ai-health) (MIT), the same tool
in all of the owner's Python repositories. Its core is deterministic and needs no AI. It
also scores the Go helper in `agent/` and the shell scripts.

## Usage

```bash
nox -s code-health                          # aihealth scan: scores, worst files
nox -s code-health -- delta                 # your uncommitted changes against HEAD
nox -s code-health -- delta --staged        # what the pre-commit hooks check
nox -s code-health -- delta --format json   # the same for agents (also: markdown)
```

Every command runs twice, once per config (see [Profile](#profile)): first for production
code (`.` with `.aihealth.toml`, which leaves out `tests/`), then for the tests (`tests`
with `tests/.aihealth.toml`). With `--format json` that prints two JSON documents.

`delta` names every new or worsened smell with `path:line` and a fix hint, and exits with
1 when health got worse. The session always passes `--config`: `aihealth scan <folder>`
otherwise looks for the file in that folder and silently falls back to its defaults. For a
single file or a report, run aihealth directly with the matching config, e.g.
`uv run --locked --isolated --only-group code-health aihealth scan src/narratty/build.py
--config .aihealth.toml` or `... scan . --report --config .aihealth.toml` (writes
`AI-HEALTH.md`, which git ignores).

aihealth is pinned once, in the `code-health` dependency group of `pyproject.toml` (a git
commit, locked in `uv.lock`), so every run comes from uv's cache. On first use it
downloads its tree-sitter grammars (about 30 MB) to `~/.cache/tree-sitter-language-pack`.

## Profile

The profile "strict" lives in two files, which must be **kept in sync**:

- [`.aihealth.toml`](https://github.com/ditschi/narratty/blob/main/.aihealth.toml) for
  production code; it excludes `tests/`.
- [`tests/.aihealth.toml`](https://github.com/ditschi/narratty/blob/main/tests/.aihealth.toml)
  for the tests: the same values, plus `[weights] primitive_obsession = 0`, because test
  code is exempt from Primitive Obsession (owner decision Q18.1).

aihealth applies one config to every path of a run; per-path overrides are requested
upstream in [epatel/ai-health#4](https://github.com/epatel/ai-health/issues/4). Once they
exist, the two files merge into one.

| Key | Value | aihealth default |
|---|---|---|
| `thresholds.large_file` | 600 code lines | 1000 |
| `thresholds.primitive_obsession` | 30 % of typed parameters (production code only) | 60 % |
| `score.decay` | 8 | 15 |
| `score.symbol_cap` | 4 | 4 |
| `score.density_loc` | 100000 (large files get no relief from a low smell density) | 300 |
| `delta.tolerance` | 0.0 (any degradation fails) | 0.1 |

The other thresholds are aihealth's CodeScene-style defaults: more than 4 parameters,
cyclomatic complexity above 9, functions above 70 code lines, nesting 4 deep, 2 bumps, 2
`and`/`or` in one condition, cognitive complexity above 15, LCOM4 of 3.

## Gate

- **pre-commit**: `aihealth delta --staged`, once per config, fails when staged changes
  make code health worse; new files may not have any smell. Another hook rejects
  suppressions without a reason.
- **Pull requests**: `aihealth delta` from the merge base to `HEAD`, once per config. In a pull request
  `HEAD` is GitHub's test merge commit, and its merge base with the base branch is the base
  tip it was built on, so the delta covers exactly the pull request's changes. Then no
  component (`src/narratty`, `tests`, `agent`, `docker`, `examples`) may score lower than
  at the merge base: a short shell loop in the workflow scans each component there and
  passes its score to aihealth's own `scan --fail-under` (`tests` with its own config).
  That loop is the only logic of our own; aihealth compares files, not components. `aihealth scan` writes the report into the
  job summary. The tree-sitter grammars are cached.
- The delta tolerance of 0 is the ratchet: nothing may get worse, so the score only rises.
  No gate fails on a score below 9.5 yet; `scan --fail-under 9.5` can join once the
  repository is there.

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

## Steckbrief Code Health

The profile below follows the outline shared by all repositories whose code health
approaches are compared; it is kept in German like that outline.

### 1. Messumfang

aihealth bewertet alle Dateien in seinen Sprachen: Python unter `src/`, `tests/`
und `noxfile.py`, Go in `agent/`, Shell-Skripte in `docker/` und `examples/` (200 Dateien,
22.979 Codezeilen). Ausgeschlossen (`[scan] exclude`): das generierte
`src/narratty/_version.py`, die mkdocs-Ausgabe `site/`, `.nox/` und fremde Agent-Skills
unter `.claude/skills/` (unveränderte Kopien laut `skills-lock.json`). Nicht bewertet werden
YAML-Specs, Markdown, Dockerfiles und CI-Workflows; dafür hat aihealth keine Sprache, und
dort entstehen die Defekte, um die es geht, kaum. Tests werden mit einer eigenen Config
bewertet (`tests/.aihealth.toml`, ohne Primitive Obsession) und deshalb in der Haupt-Config
ausgeschlossen.

### 2. Tools und Versionen

| Sprache | Tool | Version |
|---|---|---|
| Python, Go, Shell | aihealth (tree-sitter 0.26, tree-sitter-language-pack 1.25) | v0.4.0, gepinnt auf Commit `033d1867` |
| alle | uv (dependency group `code-health`, `uv.lock`), nox, pre-commit | wie im Repo |
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
aihealth noch nicht; der frühere eigene Prototyp-Checker hatte sie, sein Modul
`tools/code_health/assertions.py` existierte zuletzt in Commit `d6b4a6b` von #70 und dient
von dort als Vorlage für einen Upstream-Beitrag), God Class als eigener Smell (über Large File, Low Cohesion und
Brain Method abgedeckt), Many Functions per Module (über Large File abgedeckt). Change
Coupling und Hotspots aus der Git-Historie sind keine Datei-Smells und dienen nur der
Priorisierung.

### 4. Schwellen, Gewichte und Score-Formel

Profil "strict" in `.aihealth.toml` und für Tests in `tests/.aihealth.toml` (synchron zu
halten, siehe [Profile](#profile)), vom Owner bestätigt:
`large_file = 600`, `primitive_obsession = 0.3`, `decay = 8`, `symbol_cap = 4`,
`density_loc = 100000`, `tolerance = 0.0`. Übrige Schwellen und die Gewichte sind die
Defaults von aihealth v0.4.0 (`src/aihealth/config.py`); in der Test-Config ist zusätzlich
`[weights] primitive_obsession = 0` (Owner-Entscheidung Q18.1). Zwei Configs, weil aihealth
keine Überschreibung je Pfad kennt (angefragt in epatel/ai-health#4); danach wird
zusammengeführt. Die Score-Formel ist die von
aihealth: Abzüge der Smells, je Symbol gedeckelt (`symbol_cap`), über eine Abklingkurve
(`decay`) auf 1–10 abgebildet; der Score je Config ist der mit Codezeilen gewichtete
Mittelwert. Es gibt damit zwei Scores, Produktivcode und Tests.

### 5. Bedienung

`nox -s code-health` (Standard `scan`) und `nox -s code-health -- delta [--staged |
--base REV --head REV]`, jeweils einmal je Config (`.` mit `.aihealth.toml`, `tests` mit
`tests/.aihealth.toml`) und mit `uv run --locked`. Ausgabe als Text,
`--format markdown` für Agents und Berichte oder `--format json` (Dateien mit `findings`:
`smell`, `line`, `symbol`, `value`, `threshold`, `hint`, `penalty`). Der Modus für geänderte
Dateien ist `delta`. Laufzeit: `aihealth --version` 0,3 s aus dem Cache, `delta` über den
Branch wenige Sekunden, `scan .` 6–15 s, der Komponenten-Vergleich etwa 10 s (zehn `scan`-Läufe). aihealth
bietet zusätzlich einen MCP-Server und Claude-Code-Hooks; beides ist hier nicht
eingerichtet.

### 6. Gate

pre-commit: `code-health` und `code-health-tests` (je `delta --staged` mit der passenden
Config) und `aihealth-disable-reason` (pygrep, Regex
`aihealth:[ \t]*disable=(?![\w, \t]+-- .{10})`). PR-Workflow: `delta` von der Merge-Base
zu `HEAD` je Config, Komponenten-Vergleich (Shell-Schleife: Score je Komponente an der Merge-Base, dann
`aihealth scan <Komponente> --fail-under <Score>`), `scan` als
Bericht in der Job-Zusammenfassung (läuft auch, wenn das Delta scheitert) und Cache für
die Grammatiken. Ratchet: Toleranz 0, also keine Verschlechterung; ein Mindest-Score von 9.5
wird noch nicht erzwungen. Eine Baseline-Datei braucht aihealth dafür nicht.
Suppressions: nur dateiweit als `# aihealth: disable=<smell> -- <Grund>`.

### 7. Ergebnis

Vorher (aihealth v0.4.0, strict, Branch `feat/code-health`): Repo-Score **7.12**
(warning), 130 Dateien healthy, 65 warning, 5 alert, 366 Funde in 85 Dateien. Häufigste
Funde: Complex Method (85), Complex Conditional (69), Primitive Obsession (59), Excess
Arguments (57), Cognitive Complexity (35), Code Duplication (33). Schlechteste Dateien:
`src/narratty/build.py` 1.64, `spec/markdown/scenes.py` 1.67, `spec/model.py` 3.24,
`render/scene_cache.py` 3.50, `spec/markdown/shell.py` 3.83. Zum Vergleich: main hatte
mit der Default-Kurve 8.28 und mit strict 7.11; der frühere eigene Prototyp-Checker kam auf 7.91.

Mit zwei Configs (PR #71, Testcode ohne Primitive Obsession): Produktivcode **5.93**
(111 Dateien, 13.781 Codezeilen; 57 healthy, 49 warning, 5 alert), Tests **9.35**
(85 Dateien, 9.119 Codezeilen; 77 healthy, 8 warning).

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
installiert, danach das offizielle `typer`-Skill (fastapi/typer); deren npm-Teile
(`find-polluter.sh`) gelten hier nicht, und typer-Befehle werden nur bei Änderungen auf
`Annotated` umgestellt. Installiert sind damit fünf Skills, alle in `skills-lock.json`. Abgelehnt u. a.
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
Merge-Base, Komponenten-Vergleich über `scan --fail-under` statt eigenem Skript,
pygrep-Hook für Begründungen. Grundsatz: keine eigene Logik, wo aihealth es selbst kann;
übrig ist nur die Shell-Schleife für die Komponenten. Projektspezifisch: die
Komponentenliste. Der eigene Prototyp-Checker (stdlib-AST, etwa 1.000 Zeilen) und ein
kurzzeitiges Python-Skript für den Komponenten-Vergleich wurden wieder entfernt; beide
bleiben in der Git-Historie von #70.
