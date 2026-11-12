"""Container launcher: image selection and the docker/podman command line."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from narratty import container
from narratty.build import WorkspaceOptions
from narratty.container import ContainerSpec, Mount, SandboxRequest, delegate, image_ref, run_argv
from narratty.container import ensure_image as real_ensure_image
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


def test_rootless_docker_runs_as_container_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """Rootless Docker maps container root to the host user; other ids cannot write its files."""
    monkeypatch.setattr("narratty.runtime.docker_is_rootless", lambda: True)
    argv = run_argv(ContainerSpec(Runtime.DOCKER, "img", [], []))
    assert argv[argv.index("--user") + 1] == "0:0"


@pytest.mark.parametrize(
    ("output", "rootless"),
    [("[name=seccomp,profile=builtin name=rootless name=cgroupns]", True), ("[name=seccomp]", False)],
)
def test_rootless_docker_is_detected(monkeypatch: pytest.MonkeyPatch, output: str, rootless: bool) -> None:
    import subprocess

    from narratty import runtime

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, output, ""))
    assert runtime._detect_rootless() is rootless


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
    lexicon = next(a for a in argv if a.startswith("NARRATTY_LEXICON="))
    assert lexicon.startswith("NARRATTY_LEXICON=/cache/lexicons/"), "host lexicon levels travel via the cache"


def test_scene_cache_container_has_stable_hostname_and_relative_exclusions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    monkeypatch.setattr(container, "_which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(container, "_ensure_voice", lambda *args: None)
    monkeypatch.setenv("NARRATTY_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(container, "_image_id", lambda engine, image: f"sha256:{engine.value}-{image}")
    spec = _write_spec(tmp_path)
    calls: list[list[str]] = []
    delegate(
        "build",
        spec,
        runtime=Runtime.DOCKER,
        image="img:test",
        output=spec.with_suffix(".mp4"),
        extra_args=["--scene-cache"],
        sandbox=SandboxRequest(WorkspaceOptions(mode="rw")),
        runner=lambda argv: calls.append(list(argv)) or 0,
    )
    argv = calls[0]
    assert argv[argv.index("--hostname") + 1] == "narratty"
    exclusion = next(item for item in argv if item.startswith("NARRATTY_SCENE_CACHE_EXCLUSIONS="))
    names = json.loads(exclusion.partition("=")[2])
    assert "proj/demo.narratty.yaml" in names and "proj/demo.narratty.mp4" in names
    assert "NARRATTY_IMAGE_ID=sha256:docker-img:test" in argv, "the scene cache keys footage to the image"


def test_draft_fetches_no_voice(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(container, "_which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("narratty.tts.piper.PiperProvider.is_installed", lambda self, voice: False)
    monkeypatch.setattr("narratty.tts.piper.PiperProvider.install", lambda *a, **k: pytest.fail("fetched"))
    spec = _write_spec(tmp_path)
    code = delegate(
        "plan", spec, runtime=Runtime.DOCKER, image="img:test", extra_args=["--draft"], runner=lambda argv: 0
    )
    assert code == 0


def _mounted_spec(argv: Sequence[str]) -> tuple[Path, str]:
    mounted = next(argv[i + 1] for i, arg in enumerate(argv) if arg == "--volume" and "/spec/" in argv[i + 1])
    host, target, _ = mounted.rsplit(":", 2)
    return Path(host), target


def test_markdown_specs_are_mounted_expanded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The container gets no Markdown docs, so it gets the compiled spec instead."""
    monkeypatch.setattr(container, "_which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setenv("NARRATTY_CACHE_DIR", str(tmp_path / "cache"))
    (tmp_path / "doc.md").write_text("# Doc\n\nHello.\n", encoding="utf-8")
    spec = tmp_path / "demo.narratty.yaml"
    spec.write_text("scenes:\n  - markdown: doc.md\n", encoding="utf-8")
    calls: list[list[str]] = []
    texts: list[str] = []
    delegate(
        "plan",
        spec,
        runtime=Runtime.DOCKER,
        image="img:test",
        extra_args=["--draft"],
        runner=lambda argv: calls.append(list(argv)) or texts.append(_mounted_spec(argv)[0].read_text()) or 0,
    )
    host, target = _mounted_spec(calls[0])
    assert target == "/spec/demo.narratty.yaml"
    assert host.parent == tmp_path / "cache" / "compiled"
    assert "id: doc-1" in texts[0]
    assert not host.exists(), "the compiled copy (with hidden commands) is removed after the run"

    calls.clear()
    monkeypatch.setattr(container, "_ensure_voice", lambda provider, voice: None)
    sandbox = SandboxRequest(WorkspaceOptions(mode="rw"))
    delegate("render", spec, runtime=Runtime.DOCKER, image="img:test", sandbox=sandbox, runner=calls.append)
    volumes = {calls[0][i + 1] for i, arg in enumerate(calls[0]) if arg == "--volume"}
    assert f"{tmp_path}:/work" in volumes, "the workspace is relative to the spec, not its compiled copy"


def test_a_doc_is_mounted_as_its_compiled_spec(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(container, "_which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setenv("NARRATTY_CACHE_DIR", str(tmp_path / "cache"))
    doc = tmp_path / "guide.md"
    doc.write_text("# Guide\n\nHello.\n", encoding="utf-8")
    calls: list[list[str]] = []
    modes: list[int] = []

    def runner(argv: Sequence[str]) -> int:
        calls.append(list(argv))
        host = _mounted_spec(argv)[0]
        assert "id: guide-1" in host.read_text(encoding="utf-8")
        modes.append(host.stat().st_mode & 0o777)
        return 0

    delegate("check", doc, runtime=Runtime.DOCKER, image="img:test", voice=False, runner=runner)
    argv = calls[0]
    assert _mounted_spec(argv)[1] == "/spec/guide.narratty.yaml", (
        "inside, the compiled YAML is read as a spec"
    )
    assert modes == [0o600]
    sources = next(a for a in argv if a.startswith("NARRATTY_SCENE_SOURCES="))
    assert "guide.md:" in sources, "errors inside name the doc's lines"
    assert argv[argv.index("img:test") + 1 : argv.index("img:test") + 3] == [
        "check",
        "/spec/guide.narratty.yaml",
    ]


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


def test_run_argv_adds_groups() -> None:
    argv = run_argv(ContainerSpec(Runtime.DOCKER, "img", [], [], groups=["998"]))
    assert argv[argv.index("--group-add") + 1] == "998"


def test_engine_socket_and_host_paths(
    tmp_path: Path, docker_calls: list[list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    from narratty.engine_access import EngineAccess

    spec = _write_spec(tmp_path)
    text = spec.read_text(encoding="utf-8")
    spec.write_text(text.replace("scenes:", "sandbox: {docker: true}\nscenes:"), encoding="utf-8")
    monkeypatch.setattr(
        "narratty.engine_access.engine_access", lambda engine: EngineAccess("/run/d.sock", ("998",))
    )
    delegate(
        "render",
        spec,
        runtime=Runtime.DOCKER,
        image="img",
        sandbox=SandboxRequest(WorkspaceOptions("rw"), assume_yes=True),
    )
    argv = docker_calls[-1]
    assert "/run/d.sock:/run/docker.sock" in _volumes(argv)
    assert argv[argv.index("--group-add") + 1] == "998"
    assert "DOCKER_HOST=unix:///run/docker.sock" in argv
    assert f"{tmp_path}:{tmp_path}" in _volumes(argv), "the workspace keeps its host path"
    assert f"NARRATTY_WORKSPACE={tmp_path}" in argv


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

    monkeypatch.setattr("narratty.env_provide.provide", fake_provide)
    monkeypatch.setattr("narratty.environment.running", lambda engine, spec_path: None)
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


def test_a_kept_environment_is_reused(
    tmp_path: Path,
    docker_calls: list[list[str]],
    provided: list[dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from narratty.environment import Session

    kept = Session("docker", "dev", socket="@narratty-x")
    monkeypatch.setattr("narratty.environment.running", lambda engine, spec_path: (kept, tmp_path))
    spec = _write_env_spec(tmp_path)
    assert delegate("render", spec, runtime=Runtime.DOCKER, image="img", sandbox=SandboxRequest()) == 0
    assert provided == []
    argv = docker_calls[0]
    assert argv[argv.index("--network") + 1] == "container:dev"
    assert any(volume.startswith(f"{tmp_path}:/work") for volume in _volumes(argv))


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


def test_the_host_checks_exit_codes_logged_in_the_environment(
    tmp_path: Path,
    docker_calls: list[list[str]],
    provided: list[dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from narratty.build import REMOTE_EXIT_LOG_ENV
    from narratty.errors import CommandError

    read: list[tuple[list[str], str]] = []

    def fake_read(argv: list[str], remote: str) -> str:
        read.append((list(argv), remote))
        return "2\tmake all\n"

    monkeypatch.setattr("narratty.build.read_remote_exit_log", fake_read)
    spec = _write_env_spec(tmp_path)
    spec.write_text(
        spec.read_text(encoding="utf-8").replace(
            "narration: Hi.", "narration: Hi.\n    actions: [{run: make all}]"
        ),
        encoding="utf-8",
    )
    with pytest.raises(CommandError, match="`make all` exited with 2"):
        delegate("render", spec, runtime=Runtime.DOCKER, image="img", sandbox=SandboxRequest())
    [(argv, remote)] = read
    assert argv[:2] == ["docker", "exec"] and argv[-1] == "narratty-env-1"
    assert f"{REMOTE_EXIT_LOG_ENV}={remote}" in docker_calls[0], "the recorder logs to the same file"
    assert (
        delegate(
            "render", spec, runtime=Runtime.DOCKER, image="img", sandbox=SandboxRequest(), ignore_exit=True
        )
        == 0
    )


def test_a_missing_image_is_announced_and_pulled(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import subprocess

    calls: list[list[str]] = []
    monkeypatch.setattr(container, "_image_id", lambda engine, image: "")

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        assert kwargs["stdout"] is not subprocess.PIPE, "the engine's progress stays visible"
        return subprocess.CompletedProcess(argv, 0, None, "")

    monkeypatch.setattr(container.subprocess, "run", fake_run)
    real_ensure_image(Runtime.DOCKER, "ghcr.io/ditschi/narratty:edge")
    assert calls == [["docker", "pull", "ghcr.io/ditschi/narratty:edge"]]
    assert "pulling ghcr.io/ditschi/narratty:edge (this can take a while)" in capsys.readouterr().err


def test_a_present_image_is_not_pulled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(container, "_image_id", lambda engine, image: "sha256:abc")
    monkeypatch.setattr(container.subprocess, "run", lambda *a, **k: pytest.fail("pulled"))
    real_ensure_image(Runtime.PODMAN, "img:test")


def test_a_failed_pull_is_a_narratty_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    monkeypatch.setattr(container, "_image_id", lambda engine, image: "")
    denied = "Error response from daemon: pull access denied for img, repository does not exist"
    monkeypatch.setattr(
        container.subprocess, "run", lambda argv, **k: subprocess.CompletedProcess(argv, 1, None, denied)
    )
    with pytest.raises(
        MissingDependencyError, match="could not pull img:test: .*pull access denied"
    ) as raised:
        real_ensure_image(Runtime.DOCKER, "img:test")
    assert (
        raised.value.hint
        and "NARRATTY_IMAGE" in raised.value.hint
        and "--runtime native" in raised.value.hint
    )
