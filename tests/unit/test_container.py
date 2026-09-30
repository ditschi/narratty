"""Container launcher: image selection and the docker/podman command line."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from narratty import container
from narratty.build import WorkspaceOptions
from narratty.container import ContainerSpec, Mount, SandboxRequest, delegate, image_ref, run_argv
from narratty.errors import MissingDependencyError
from narratty.runtime import Runtime


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("1.2.3", "ghcr.io/ditschi/narratty:1.2.3"),
        ("0.1.1.dev4+gabc", "ghcr.io/ditschi/narratty:edge"),
    ],
)
def test_image_ref(version: str, expected: str) -> None:
    assert image_ref(version=version) == expected


def test_image_override(monkeypatch: pytest.MonkeyPatch) -> None:
    assert image_ref(override="me/img:1") == "me/img:1"
    monkeypatch.setenv("NARRATTY_IMAGE", "env/img:2")
    assert image_ref() == "env/img:2"


def test_run_argv_is_hardened() -> None:
    spec = ContainerSpec(
        Runtime.DOCKER,
        "img:1",
        ["build", "/spec/d.narratty.yaml"],
        [Mount(Path("/h/spec.yaml"), "/spec/d.narratty.yaml", read_only=True), Mount(Path("/h/w"), "/work")],
        {"B": "2", "A": "1"},
    )
    argv = run_argv(spec)
    assert argv[:4] == ["docker", "run", "--rm", "--init"]
    for flag in (["--network", "none"], ["--cap-drop", "ALL"], ["--security-opt", "no-new-privileges"]):
        index = argv.index(flag[0])
        assert argv[index : index + 2] == flag
    assert "--read-only" in argv
    assert "/h/spec.yaml:/spec/d.narratty.yaml:ro" in argv
    assert "/h/w:/work" in argv
    assert argv.index("A=1") < argv.index("B=2")
    assert argv[-3:] == ["img:1", "build", "/spec/d.narratty.yaml"]


def test_podman_keeps_the_user_id() -> None:
    argv = run_argv(ContainerSpec(Runtime.PODMAN, "img", [], []))
    assert argv[0] == "podman"
    assert argv[argv.index("--userns") + 1] == "keep-id"
    assert "--user" not in argv


def _write_spec(tmp_path: Path) -> Path:
    spec = tmp_path / "proj" / "demo.narratty.yaml"
    spec.parent.mkdir()
    spec.write_text(
        "tts: {provider: piper}\nworkspace: {source: ..}\nscenes:\n  - id: a\n    narration: Hi.\n",
        encoding="utf-8",
    )
    return spec


def test_native_runtime_does_not_delegate(tmp_path: Path) -> None:
    assert delegate("build", _write_spec(tmp_path), runtime=Runtime.NATIVE) is None


def test_missing_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(container, "_which", lambda name: None)
    with pytest.raises(MissingDependencyError, match="podman is not installed"):
        delegate("build", _write_spec(tmp_path), runtime=Runtime.PODMAN)


def test_delegate_mounts_and_arguments(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    installed: list[str] = []
    monkeypatch.setattr(container, "_which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("narratty.tts.piper.PiperProvider.is_installed", lambda self, voice: False)
    monkeypatch.setattr(
        "narratty.tts.piper.PiperProvider.install", lambda self, voice, **_: installed.append(voice)
    )
    calls: list[list[str]] = []

    def runner(argv: Sequence[str]) -> int:
        calls.append(list(argv))
        return 7

    spec = _write_spec(tmp_path)
    code = delegate(
        "build",
        spec,
        runtime=Runtime.DOCKER,
        image="img:test",
        output=tmp_path / "videos" / "demo.mp4",
        work_dir=tmp_path / "keep",
        extra_args=["--max-drift", "0.1"],
        sandbox=SandboxRequest(WorkspaceOptions(mode="rw")),
        runner=runner,
    )
    assert code == 7
    assert installed == ["en_US-lessac-medium"], "voices are fetched on the host"
    argv = calls[0]
    volumes = {argv[i + 1] for i, arg in enumerate(argv) if arg == "--volume"}
    assert f"{spec}:/spec/demo.narratty.yaml:ro" in volumes
    assert f"{tmp_path}:/work" in volumes, "workspace.source is resolved relative to the spec"
    assert f"{tmp_path / 'videos'}:/out" in volumes
    assert f"{tmp_path / 'keep'}:/keep" in volumes
    assert any(v.endswith(":/data:ro") for v in volumes)
    tail = argv[argv.index("img:test") + 1 :]
    assert tail[:5] == ["build", "/spec/demo.narratty.yaml", "--runtime", "native", "--offline"]
    assert tail[tail.index("--output") + 1] == "/out/demo.mp4"
    assert "--max-drift" in tail
    assert "NARRATTY_WORKSPACE=/work" in argv


@pytest.fixture
def docker_calls(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    monkeypatch.setattr(container, "_which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("narratty.tts.piper.PiperProvider.is_installed", lambda self, voice: True)
    calls: list[list[str]] = []

    def runner(argv: Sequence[str]) -> int:
        calls.append(list(argv))
        volumes = [argv[i + 1] for i, arg in enumerate(argv) if arg == "--volume"]
        work = next((v.split(":")[0] for v in volumes if v.split(":")[1] == "/work"), None)
        calls[-1].append(f"WORK_EXISTS={work is not None and Path(work).is_dir()}")
        return 0

    monkeypatch.setattr(container, "_run", runner)
    return calls


def _volumes(argv: list[str]) -> list[str]:
    return [argv[i + 1] for i, arg in enumerate(argv) if arg == "--volume"]


def test_snapshot_is_mounted_and_removed(tmp_path: Path, docker_calls: list[list[str]]) -> None:
    spec = _write_spec(tmp_path)
    (tmp_path / "file.txt").write_text("x", encoding="utf-8")
    assert delegate("render", spec, runtime=Runtime.DOCKER, image="img", sandbox=SandboxRequest()) == 0
    argv = docker_calls[0]
    work = next(v for v in _volumes(argv) if v.endswith(":/work")).removesuffix(":/work")
    assert "/cache/workspaces/" in work
    assert argv[-1] == "WORK_EXISTS=True"
    assert not Path(work).exists(), "the snapshot is removed afterwards"
    assert "--network" in argv and argv[argv.index("--network") + 1] == "none"


def test_ro_mode_mounts_read_only(tmp_path: Path, docker_calls: list[list[str]]) -> None:
    spec = _write_spec(tmp_path)
    delegate(
        "render", spec, runtime=Runtime.DOCKER, image="img", sandbox=SandboxRequest(WorkspaceOptions("ro"))
    )
    assert f"{tmp_path}:/work:ro" in _volumes(docker_calls[0])


def test_commands_without_the_demo_get_no_workspace(tmp_path: Path, docker_calls: list[list[str]]) -> None:
    delegate("tts", _write_spec(tmp_path), runtime=Runtime.DOCKER, image="img")
    assert not any(v.endswith(":/work") for v in _volumes(docker_calls[0]))


def test_full_network_needs_consent(tmp_path: Path, docker_calls: list[list[str]]) -> None:
    from narratty.errors import UsageError

    spec = _write_spec(tmp_path)
    with pytest.raises(UsageError, match="full network access"):
        delegate("render", spec, runtime=Runtime.DOCKER, image="img", sandbox=SandboxRequest(network="full"))
    delegate(
        "render",
        spec,
        runtime=Runtime.DOCKER,
        image="img",
        sandbox=SandboxRequest(network="full", assume_yes=True),
    )
    argv = docker_calls[-1]
    assert argv[argv.index("--network") + 1] == "bridge"


def _write_env_spec(tmp_path: Path) -> Path:
    spec = _write_spec(tmp_path)
    spec.write_text(
        spec.read_text(encoding="utf-8") + "environment: {image: acme/dev:1}\nsandbox: {env: {TZ: UTC}}\n",
        encoding="utf-8",
    )
    return spec


@pytest.fixture
def provided(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    from contextlib import contextmanager

    from narratty.environment import Session

    calls: list[dict[str, object]] = []

    @contextmanager
    def fake_provide(environment: object, spec: object, **kwargs: object):  # type: ignore[no-untyped-def]
        calls.append({"environment": environment, **kwargs})
        yield Session("docker", "narratty-env-1", "/work", "narratty-env-1-run")

    monkeypatch.setattr("narratty.environment.provide", fake_provide)
    return calls


def test_environment_runs_the_demo_elsewhere(
    tmp_path: Path, docker_calls: list[list[str]], provided: list[dict[str, object]]
) -> None:
    from narratty.bridge import BRIDGE_ENV

    spec = _write_env_spec(tmp_path)
    assert delegate("render", spec, runtime=Runtime.DOCKER, image="img", sandbox=SandboxRequest()) == 0
    assert provided[0]["with_agent"] is True
    assert provided[0]["narratty_image"] == "img"
    argv = docker_calls[0]
    assert "narratty-env-1-run:/run/narratty" in _volumes(argv)
    bridge = next(arg for arg in argv if arg.startswith(f"{BRIDGE_ENV}="))
    assert "narratty-agent" in bridge
    assert argv[argv.index("--network") + 1] == "none"
    assert "TZ=UTC" not in argv, "the sandbox applies to the environment, not the recorder"


def test_no_env_runs_the_demo_in_the_narratty_image(
    tmp_path: Path, docker_calls: list[list[str]], provided: list[dict[str, object]]
) -> None:
    from narratty.environment import EnvironmentOptions

    spec = _write_env_spec(tmp_path)
    request = SandboxRequest(environment=EnvironmentOptions(disabled=True))
    delegate("render", spec, runtime=Runtime.DOCKER, image="img", sandbox=request)
    assert provided == []
    assert "TZ=UTC" in docker_calls[0]


def test_policy_can_forbid_environments(
    tmp_path: Path, docker_calls: list[list[str]], provided: list[dict[str, object]]
) -> None:
    from narratty.errors import UsageError

    config = tmp_path / "config"
    config.mkdir()
    (config / "config.toml").write_text("[sandbox]\nallow_environment = []\n", encoding="utf-8")
    with pytest.raises(UsageError, match="does not allow"):
        delegate(
            "render", _write_env_spec(tmp_path), runtime=Runtime.DOCKER, image="img", sandbox=SandboxRequest()
        )
    assert docker_calls == []
