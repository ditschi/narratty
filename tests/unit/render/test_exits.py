"""Exit codes of recorded commands against each scene's ``expect_exit``."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from narratty.errors import CommandError, ExitCode
from narratty.render.cast import record
from narratty.render.exits import Exit, assign, check, exit_hook, parse_log, problems, typed_commands
from narratty.render.script import build_script, prompt_setup
from narratty.spec.loader import parse_spec
from narratty.spec.model import Spec
from narratty.timeline import build_timeline

SPEC = """\
end_card: false
scenes:
  - id: setup
    hidden: true
    actions: [{type_command: "cd demo"}, enter]
  - id: build
    actions:
      - type_command: "make "
      - type_command: "all"
      - enter
      - enter
  - id: broken
    expect_exit: failure
    actions: [{type_command: "cat missing"}, enter, {type_command: "oops"}, {ctrl_sequence: C-u}]
  - id: flaky
    expect_exit: any
    actions: [{type_command: "curl example.org"}, enter]
"""


def _spec(text: str = SPEC) -> Spec:
    return parse_spec(text, Path("t.narratty.yaml"))


def test_expect_exit_defaults_to_success() -> None:
    assert [s.expect_exit for s in _spec().scenes] == ["success", "success", "failure", "any"]


def test_typed_commands_are_the_lines_submitted_with_enter() -> None:
    assert typed_commands(_spec()) == [
        ("setup", "cd demo"),
        ("build", "make all"),
        ("broken", "cat missing"),
        ("flaky", "curl example.org"),
    ]


def test_parse_log_skips_malformed_rows() -> None:
    assert parse_log("0\tls -la \n\nnope\n2\tgrep x\tfile\n") == [Exit(0, "ls -la"), Exit(2, "grep x\tfile")]


def test_assign_ties_entries_to_scenes() -> None:
    entries = [Exit(0, "PS1=x; clear"), Exit(0, "cd demo"), Exit(0, "make all -j"), Exit(2, "make clean")]
    assert assign(_spec(), entries) == {
        None: [Exit(0, "PS1=x; clear")],
        "setup": [Exit(0, "cd demo")],
        "build": [Exit(0, "make all -j"), Exit(2, "make clean")],
    }, "a completed line matches its prefix; unmatched lines join the scene before"


def test_all_expectations_met() -> None:
    entries = [Exit(0, "cd demo"), Exit(0, "make all"), Exit(1, "cat missing"), Exit(6, "curl example.org")]
    assert problems(_spec(), entries) == []


def test_failures_are_reported_per_scene() -> None:
    entries = [Exit(1, "cd demo"), Exit(2, "make all"), Exit(0, "cat missing")]
    assert problems(_spec(), entries) == [
        "scene 'setup': `cd demo` exited with 1",
        "scene 'build': `make all` exited with 2",
        "scene 'broken' expects a command to fail, but `cat missing` succeeded",
    ]


def test_expected_failure_needs_a_command() -> None:
    assert problems(_spec(), []) == [
        "scene 'broken' expects a command to fail but ran none at the shell prompt"
    ]


def test_interrupted_commands_are_not_failures() -> None:
    entries = [Exit(130, "make all"), Exit(148, "make all"), Exit(130, "cat missing")]
    assert problems(_spec(), entries) == [
        "scene 'broken' expects a command to fail, but `cat missing` succeeded",
    ]


def test_failure_before_the_first_scene() -> None:
    assert problems(_spec(), [Exit(127, "setup-hook")]) == [
        "before the first scene: `setup-hook` exited with 127",
        "scene 'broken' expects a command to fail but ran none at the shell prompt",
    ]


def test_check_raises_with_its_own_exit_code(tmp_path: Path) -> None:
    log = tmp_path / "exits.log"
    log.write_text("0\tcd demo\n2\tmake all\n1\tcat missing\n", encoding="utf-8")
    with pytest.raises(CommandError, match="`make all` exited with 2") as raised:
        check(_spec(), log, output=tmp_path / "v.mp4")
    assert raised.value.exit_code == ExitCode.COMMAND == 7
    assert raised.value.hint and "expect_exit: any" in raised.value.hint and "v.mp4" in raised.value.hint


def test_check_skips_sh_and_missing_logs(tmp_path: Path) -> None:
    log = tmp_path / "exits.log"
    log.write_text("1\tmake all\n", encoding="utf-8")
    check(_spec(SPEC.replace("end_card: false", "end_card: false\nterminal: {shell: sh}")), log)
    check(_spec(), tmp_path / "absent.log")


def test_hook_goes_before_the_prompt(tmp_path: Path) -> None:
    log = tmp_path / "it's.log"
    assert exit_hook("sh", log) is None
    assert prompt_setup("sh", "$ ", log) == "PS1='$ '; clear"
    for shell in ("bash", "zsh", "fish"):
        setup = prompt_setup(shell, "$ ", log)
        assert setup.startswith(str(exit_hook(shell, log)) + "; ")
        assert setup.endswith("; clear")


RECORDED = """\
terminal: {{shell: {shell}, typing_speed_ms: 5}}
timing: {{lead_in_ms: 0, tail_ms: 0, narration_buffer_ms: 0}}
end_card: false
scenes:
  - id: fine
    actions: [{{type_command: "true"}}, enter, enter, {{type_command: "  "}}, enter]
  - id: broken
    actions: [{{type_command: "echo 'it''s'; false"}}, enter]
  - id: completed
    expect_exit: failure
    actions: [{{type_command: "grep -q x /dev/nul"}}, {{key: Tab}}, enter, {{hold: 300}}]
"""


def _as_bash_3(shell: str, log: Path) -> str | None:
    """The hook as bash 3.2 (macOS) takes it: from history instead of READLINE_LINE."""
    return str(exit_hook(shell, log)).replace(">= 4", ">= 99").replace("< 4", "< 99")


@pytest.mark.parametrize("shell", ["bash", "bash-3", "zsh", "fish"])
def test_hook_logs_real_shells(shell: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if shell == "bash-3":
        shell = "bash"
        monkeypatch.setattr("narratty.render.script.exit_hook", _as_bash_3)
    if not shutil.which(shell):
        pytest.skip(f"{shell} is not installed")
    spec = parse_spec(RECORDED.format(shell=shell), tmp_path / "t.narratty.yaml")
    log = tmp_path / "exit's.log"
    log.write_text("", encoding="utf-8")
    steps = build_script(spec, build_timeline(spec, {}), exit_log=log)
    record(steps, terminal=spec.terminal, cwd=tmp_path, env=os.environ, title="T")
    entries = parse_log(log.read_text(encoding="utf-8"))
    assert [e for e in entries if not e.line.startswith("function ")] == [
        Exit(0, "true"),
        Exit(1, "echo 'it''s'; false"),
        Exit(1, "grep -q x /dev/null"),
    ], "one entry per command line, none for empty lines"
    assert problems(spec, entries) == ["scene 'broken': `echo 'it''s'; false` exited with 1"]
