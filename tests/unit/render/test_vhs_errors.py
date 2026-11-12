"""VHS failures name the scene they happened in."""

from __future__ import annotations

from pathlib import Path

from narratty.render.media import failed_scene, vhs_timeout

TAPE = """\
Hide
Type "PS1='$ '; clear"
Enter
Wait+Screen@15000ms /ready/
Show
# scene: intro
Type "ls"
Enter
Wait+Line@30000ms /(?:^|\\S)\\$\\s*$/
# scene: api (hidden)
Type "export TOKEN=x"
Enter
# scene: call
Type "curl -s localhost"
Enter
Wait+Line@30000ms /(?:^|\\S)\\$\\s*$/
"""

LOG = """\
Type PS1='$ '; clear
Enter 1
Wait 15000ms Screen ready
Type ls
Enter 1
Wait 30000ms Line (?:^|\\S)\\$\\s*$
Type curl -s localhost
Enter 1
Wait 30000ms Line (?:^|\\S)\\$\\s*$
recording failed
failed to execute command: timeout waiting for "Line (?:^|\\\\S)\\\\$\\\\s*$" to match x; last value was: {"a"
"""


def test_failed_scene_counts_the_waits(tmp_path: Path) -> None:
    tape = tmp_path / "scene.tape"
    tape.write_text(TAPE, encoding="utf-8")
    assert failed_scene(tape, LOG) == "call"
    assert failed_scene(tape, LOG.split("Type ls")[0]) is None, "a setup wait has no scene"


def test_vhs_prompt_timeout(tmp_path: Path) -> None:
    tape = tmp_path / "scene.tape"
    tape.write_text(TAPE, encoding="utf-8")
    error = vhs_timeout(tape, LOG)
    assert error is not None
    assert error.message == "timed out after 30000 ms in scene 'call' waiting for the prompt to come back"
    assert error.scene == "call"
    assert error.hint is not None and "pattern" not in error.hint
    assert vhs_timeout(tape, "recording failed\nsomething else") is None


def test_vhs_screen_timeout(tmp_path: Path) -> None:
    tape = tmp_path / "scene.tape"
    tape.write_text(TAPE, encoding="utf-8")
    log = 'Wait 15000ms Screen ready\nfailed: timeout waiting for "Screen ready" to match ready'
    error = vhs_timeout(tape, log)
    assert error is not None and "/ready/" in error.message
    assert "waiting for the screen to match" in error.message and error.scene is None
