"""Every documented way to run the demo in a project environment, recorded with VHS.

docs/user-guide/environments.md: the sources (image, compose, a list of Compose files,
a running container), the editor layout and ``diff`` with each, ``terminal.shell: sh``,
``user``, ``env``, ``read_only``, ``packages``/``setup`` (also with Compose), the
toolkit modes, ``workspace.caches``, the sandbox network, the policy and the command
line overrides. Natively, and through the narratty image when ``NARRATTY_IMAGE`` is
set (the Docker workflow).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from typer.testing import CliRunner

from narratty.build import CastOutputs, WorkspaceOptions, build, build_cast
from narratty.cli.app import app
from narratty.container import SandboxRequest
from narratty.environment import EnvironmentOptions
from narratty.render import media

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not shutil.which("docker"), reason="needs docker"),
    pytest.mark.skipif(not all(shutil.which(t) for t in ("ffmpeg", "ffprobe")), reason="needs ffmpeg"),
]

IMAGE = os.environ.get("NARRATTY_TEST_ENV_IMAGE", "debian:trixie-slim")
TOOLKIT = "ghcr.io/ditschi/narratty-toolkit:edge"
NATIVE_VIDEO = all(shutil.which(t) for t in ("vhs", "ttyd"))
NATIVE_EDITOR = NATIVE_VIDEO and all(shutil.which(t) for t in ("tmux", "yazi", "ya", "git"))
CONTAINER_RUNTIME = bool(os.environ.get("NARRATTY_IMAGE"))

# What the demo shell reports about itself: in a container, which shell, which user.
PROBE = (
    'printf "%s %s %s\\n" "$(test -e /.dockerenv && echo container)" "$(readlink /proc/$$/exe)" "$(id -u)"'
)

PLAIN = """\
      - type_command: '{probe} > made-in-env; echo in-$((6*7))'
      - enter
      - wait: {{screen: "in-42|uid-[0-9]+", timeout_ms: 20000}}
"""
EDITOR = """\
      - type_command: '{probe} > made-in-env; echo in-$((6*7))'
      - enter
      - wait: {{screen: "in-42|uid-[0-9]+", timeout_ms: 20000}}
      - reveal: made-in-env
      - focus: explorer
      - diff
      - wait: {{screen: "made-in-env", timeout_ms: 20000}}
"""
SOURCES = ["image", "compose", "compose-files", "container"]


def _spec_text(environment: str, *, layout: str = "plain", shell: str = "bash", head: str = "") -> str:
    actions = (EDITOR if layout == "editor" else PLAIN).format(probe=PROBE)
    return (
        f"{head}meta: {{title: Environment}}\n"
        f"terminal: {{layout: {layout}, shell: {shell}, width: 1200, height: 700, typing_speed_ms: 5}}\n"
        f"environment: {environment}\n"
        "end_card: {enabled: true, duration_ms: 1000}\n"
        f"scenes:\n  - id: run\n    actions:\n{actions}"
    )


@contextmanager
def _source(tmp_path: Path, source: str) -> Iterator[tuple[str, str]]:
    """The spec's ``environment`` for ``source`` and the lines before it, with what it needs."""
    service = f"services:\n  dev:\n    image: {IMAGE}\n    command: sleep infinity\n"
    if source == "image":
        yield f'{{image: "{IMAGE}"}}', ""
    elif source == "compose":
        (tmp_path / "compose.yaml").write_text(
            service + "    volumes: ['.:/src']\n    working_dir: /src\n", encoding="utf-8"
        )
        yield "{compose: {service: dev}}", ""
    elif source == "compose-files":
        (tmp_path / "compose.yaml").write_text(service, encoding="utf-8")
        (tmp_path / "compose.dev.yaml").write_text(
            "services:\n  dev:\n    volumes: ['.:/src']\n    working_dir: /src\n", encoding="utf-8"
        )
        yield "{compose: {file: [compose.yaml, compose.dev.yaml], service: dev}}", ""
    else:
        name = f"narratty-test-{uuid.uuid4().hex[:8]}"
        subprocess.run(
            ["docker", "run", "--detach", "--name", name, "--volume", f"{tmp_path}:/src", "--workdir", "/src",
             IMAGE, "sleep", "infinity"],
            check=True, capture_output=True,
        )  # fmt: skip
        try:
            yield f"{{container: {name}, user: image}}", "workspace: {mode: rw}\n"
        finally:
            subprocess.run(["docker", "rm", "--force", name], check=False, capture_output=True)


def _write(tmp_path: Path, text: str) -> Path:
    spec = tmp_path / "demo.narratty.yaml"
    spec.write_text(text, encoding="utf-8")
    return spec


def _probe(tmp_path: Path) -> list[str]:
    return (tmp_path / "made-in-env").read_text(encoding="utf-8").split()


def _video(spec: Path) -> Path:
    request = SandboxRequest(assume_yes=True)
    result = build(spec, workspace=WorkspaceOptions(mode="rw"), sandbox=request, max_drift=10)
    return result.output


def _video_in_container(spec: Path) -> Path:
    out = spec.parent / "out" / "demo.mp4"
    args = ["build", str(spec), "--runtime", "docker", "--workspace-mode", "rw", "--yes", "--max-drift", "10"]
    args += ["-o", str(out)]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    return out


def _cast(spec: Path, sandbox: SandboxRequest | None = None, mode: str = "rw") -> str:
    request = sandbox or SandboxRequest(assume_yes=True)
    result = build_cast(spec, workspace=WorkspaceOptions(mode=mode), sandbox=request)
    events = [json.loads(line) for line in CastOutputs(result.output).cast.read_text().splitlines()[1:]]
    return "".join(e[2] for e in events if e[1] == "o")


def _assert_video(path: Path) -> None:
    info = media.probe(path)
    assert info.has_video and info.duration_ms > 0


def _assert_ran_in_container(tmp_path: Path, shell: str = "bash") -> None:
    where, exe, _ = _probe(tmp_path)
    assert where == "container"
    assert Path(exe).name == ("dash" if shell == "sh" else shell)


# ── Sources × layouts, recorded with VHS ───────────────────────────────────────


@pytest.mark.skipif(not NATIVE_VIDEO, reason="needs vhs and ttyd")
@pytest.mark.parametrize("source", SOURCES)
def test_video_natively(tmp_path: Path, source: str) -> None:
    with _source(tmp_path, source) as (environment, head):
        _assert_video(_video(_write(tmp_path, _spec_text(environment, head=head))))
    _assert_ran_in_container(tmp_path)


@pytest.mark.skipif(not NATIVE_EDITOR, reason="needs vhs, ttyd, tmux, yazi and git")
@pytest.mark.parametrize("source", ["image", "compose", "compose-files"])
def test_editor_video_natively(tmp_path: Path, source: str) -> None:
    with _source(tmp_path, source) as (environment, head):
        _assert_video(_video(_write(tmp_path, _spec_text(environment, layout="editor", head=head))))
    _assert_ran_in_container(tmp_path)


@pytest.mark.skipif(not NATIVE_VIDEO, reason="needs vhs and ttyd")
@pytest.mark.parametrize("layout", ["plain", "editor"])
def test_sh_as_the_demo_shell(tmp_path: Path, layout: str) -> None:
    if layout == "editor" and not NATIVE_EDITOR:
        pytest.skip("needs tmux, yazi and git")
    _assert_video(_video(_write(tmp_path, _spec_text(f'{{image: "{IMAGE}"}}', layout=layout, shell="sh"))))
    _assert_ran_in_container(tmp_path, shell="sh")


@pytest.mark.skipif(not CONTAINER_RUNTIME, reason="needs NARRATTY_IMAGE")
@pytest.mark.parametrize("layout", ["plain", "editor"])
@pytest.mark.parametrize("source", SOURCES)
def test_video_from_the_narratty_image(tmp_path: Path, source: str, layout: str) -> None:
    if source == "container" and layout == "editor":
        pytest.skip("the editor layout in a running container needs its tools there (tested below)")
    with _source(tmp_path, source) as (environment, head):
        spec = _write(tmp_path, _spec_text(environment, layout=layout, head=head))
        _assert_video(_video_in_container(spec))
    _assert_ran_in_container(tmp_path)


# ── Settings of the environment ────────────────────────────────────────────────


@pytest.mark.parametrize(("user", "expected"), [("host", str(os.getuid())), ("image", "0"), ("1234", "1234")])
def test_user(tmp_path: Path, user: str, expected: str) -> None:
    spec = _write(tmp_path, _spec_text(f'{{image: "{IMAGE}", user: "{user}"}}'))
    spec.write_text(spec.read_text().replace("echo in-$((6*7))", "echo uid-$(id -u)"), encoding="utf-8")
    assert f"uid-{expected}" in _cast(spec).replace("\r", "").split("uid-$(id -u)")[-1]


def test_env_read_only_and_workdir(tmp_path: Path) -> None:
    settings = "user: image, workdir: /project, read_only: true, env: {GREETING: hi}"
    environment = f'{{image: "{IMAGE}", {settings}}}'
    spec = _write(tmp_path, _spec_text(environment))
    spec.write_text(
        spec.read_text().replace(
            "made-in-env; echo",
            "made-in-env; echo $GREETING $PWD > env-seen; "
            "touch /etc/x 2>/dev/null || echo ro >> env-seen; echo",
        ),
        encoding="utf-8",
    )
    _cast(spec)
    assert (tmp_path / "env-seen").read_text().split() == ["hi", "/project", "ro"]


def test_network_is_off_by_default(tmp_path: Path) -> None:
    spec = _write(tmp_path, _spec_text(f'{{image: "{IMAGE}"}}'))
    spec.write_text(
        spec.read_text().replace(
            "made-in-env; echo", "made-in-env; getent hosts github.com >/dev/null || echo offline > net; echo"
        ),
        encoding="utf-8",
    )
    _cast(spec)
    assert (tmp_path / "net").read_text().strip() == "offline"


def test_caches_survive_runs(tmp_path: Path) -> None:
    head = "workspace: {caches: {demo: /var/cache/demo}}\n"
    spec = _write(tmp_path, _spec_text(f'{{image: "{IMAGE}", user: image}}', head=head))
    keep = "cat /var/cache/demo/n > seen 2>/dev/null; date +%s%N > /var/cache/demo/n"
    text = spec.read_text().replace("made-in-env; echo", f"made-in-env; {keep}; echo")
    spec.write_text(text, encoding="utf-8")
    _cast(spec)
    assert not (tmp_path / "seen").read_text().strip(), "empty on the first run"
    _cast(spec)
    assert (tmp_path / "seen").read_text().strip(), "the second run sees what the first left"


@pytest.mark.parametrize("source", ["image", "compose"])
def test_packages_setup_and_diff(tmp_path: Path, source: str) -> None:
    """``packages`` adds git, so ``diff`` outside the editor layout works in the environment."""
    with _source(tmp_path, source) as (environment, head):
        layered = environment[:-1] + ", packages: [git], setup: ['echo made > /etc/demo']}"
        spec = _write(tmp_path, _spec_text(layered, head=head))
        text = spec.read_text().replace("made-in-env; echo", "made-in-env; cat /etc/demo > setup-ran; echo")
        spec.write_text(text.replace("      - wait:", "      - diff\n      - wait:", 1), encoding="utf-8")
        output = _cast(spec)
    assert (tmp_path / "setup-ran").read_text().strip() == "made"
    assert "+container" in output, "the diff, run in the environment, shows the new file"


@pytest.mark.parametrize(("mode", "first"), [("prefer", True), ("fallback", True), ("off", False)])
def test_toolkit_modes(tmp_path: Path, mode: str, first: bool) -> None:
    pulled = subprocess.run(["docker", "pull", "--quiet", TOOLKIT], capture_output=True, check=False)
    if pulled.returncode != 0:
        pytest.skip(f"{TOOLKIT} is not available")
    spec = _write(tmp_path, _spec_text(f'{{image: "{IMAGE}", toolkit: {mode}}}'))
    spec.write_text(
        spec.read_text().replace(
            "made-in-env; echo", 'made-in-env; echo "$PATH" > path; command -v eza >> path; echo'
        ),
        encoding="utf-8",
    )
    _cast(spec)
    path, *eza = (tmp_path / "path").read_text().split()
    entries = path.split(":")
    if not first:
        assert not any(e.startswith("/.narratty/toolkit") for e in entries) and not eza
        return
    toolkit = next(i for i, e in enumerate(entries) if e.startswith("/.narratty/toolkit"))
    assert toolkit == (0 if mode == "prefer" else len(entries) - 1)
    assert eza and eza[0].startswith("/.narratty/toolkit")


# ── Policy and command line ────────────────────────────────────────────────────


def test_policy_limits_the_sources(tmp_path: Path) -> None:
    from narratty.errors import NarrattyError

    config = Path(os.environ["NARRATTY_CONFIG_DIR"])
    config.mkdir(parents=True, exist_ok=True)
    (config / "config.toml").write_text('[sandbox]\nallow_environment = ["image"]\n', encoding="utf-8")
    with _source(tmp_path, "compose") as (environment, head), pytest.raises(NarrattyError, match="policy"):
        _cast(_write(tmp_path, _spec_text(environment, head=head)))


def test_env_image_and_no_env_override_the_spec(tmp_path: Path) -> None:
    spec = _write(tmp_path, _spec_text('{image: "narratty-test/does-not-exist"}'))
    _cast(spec, SandboxRequest(assume_yes=True, environment=EnvironmentOptions(image=IMAGE)))
    assert _probe(tmp_path)[0] == "container"
    _cast(spec, SandboxRequest(assume_yes=True, environment=EnvironmentOptions(disabled=True)))
    assert _probe(tmp_path)[0] != "container" or Path("/.dockerenv").exists(), "the shell ran here"


def test_keep_env_keeps_the_container(tmp_path: Path) -> None:
    spec = _write(tmp_path, _spec_text(f'{{image: "{IMAGE}"}}'))
    _cast(spec, SandboxRequest(assume_yes=True, environment=EnvironmentOptions(keep=True)))
    kept = subprocess.run(
        ["docker", "ps", "--quiet", "--filter", "label=narratty.environment=1"],
        capture_output=True,
        text=True,
    ).stdout.split()
    try:
        assert kept, "--keep-env leaves the container running"
    finally:
        if kept:
            subprocess.run(["docker", "rm", "--force", *kept], check=False, capture_output=True)
