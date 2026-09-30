"""Shims that start the demo shell through a bridge, and the remote end card."""

from __future__ import annotations

import json
import os
from pathlib import Path

from narratty import bridge
from narratty.render.cast import record
from narratty.render.script import build_script
from narratty.render.tape import generate_tape
from narratty.spec.loader import parse_spec
from narratty.timeline import build_timeline


def test_encode_and_current() -> None:
    argv = ["narratty-agent", "connect", "--socket", "/run/narratty/agent.sock", "--"]
    assert bridge.current({bridge.BRIDGE_ENV: bridge.encode(argv)}) == argv
    assert bridge.current({}) is None


def test_shims_go_first_on_path(tmp_path: Path) -> None:
    env = bridge.shim_env(tmp_path / "shims", ["docker", "exec", "-it", "my env"], {"PATH": "/usr/bin"})
    assert env["PATH"] == f"{tmp_path / 'shims'}{os.pathsep}/usr/bin"
    for shell in bridge.SHELLS:
        shim = tmp_path / "shims" / shell
        assert os.access(shim, os.X_OK)
        lines = shim.read_text(encoding="utf-8").splitlines()
        assert lines[2] == f"docker exec -it 'my env' {shell} \"$@\""
        assert lines[3] == "PATH=/usr/bin exec sh", "the local shell must not find the shims"


SPEC = """\
timing: {lead_in_ms: 0, tail_ms: 0, narration_buffer_ms: 0}
terminal: {typing_speed_ms: 5}
end_card: {enabled: true, duration_ms: 1000, qr: false}
scenes:
  - id: show
    actions: [{type_command: "echo where=$WHERE"}, enter, {wait: {screen: "where=remote"}}]
"""


def test_remote_shell_and_local_end_card(tmp_path: Path) -> None:
    """A stand-in bridge (``env WHERE=remote …``) runs the demo; the card is drawn locally."""
    spec = parse_spec(SPEC, tmp_path / "t.narratty.yaml")
    stand_in = ["env", "WHERE=remote", f"PATH={os.environ['PATH']}"]  # finds the real shell
    env = bridge.shim_env(tmp_path / "shims", stand_in, os.environ)
    recording = record(
        build_script(spec, build_timeline(spec, {}), remote=True),
        terminal=spec.terminal,
        cwd=tmp_path,
        env=env,
        title="T",
    )
    output = "".join(json.loads(line)[2] for line in recording.cast.splitlines()[1:])
    assert "where=remote" in output
    assert output.index("where=remote") < output.index("Created with narratty")


def test_remote_tape_leaves_the_environment_for_the_card() -> None:
    spec = parse_spec(SPEC, Path("t.narratty.yaml"))
    tape = generate_tape(spec, build_timeline(spec, {}), Path("/out/v.mp4"), python="py", remote=True)
    card = tape.split("# end card\n", 1)[1].splitlines()
    assert card[:5] == [
        "Hide",
        'Type@1ms "exit"',
        "Enter@1ms",
        "Sleep 500ms",
        "Type@1ms \"PS1=''; clear; 'py' -m narratty.end_card --no-qr\"",
    ]
