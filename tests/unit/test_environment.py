"""Project environments: overrides, image inspection, the container's lifecycle."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest

from narratty.env_provide import provide
from narratty.environment import (
    EnvironmentOptions,
    ImageInfo,
    Session,
    agent_dir,
    check_policy,
    inspect_image,
    resolve,
)
from narratty.errors import MissingDependencyError, NarrattyError, UsageError
from narratty.runtime import release_tag
from narratty.spec.model import Environment, Sandbox, Spec
from narratty.workspace import PreparedWorkspace

IMAGE = {
    "Id": "sha256:" + "ab" * 32,
    "Architecture": "arm64",
    "Config": {"User": "dev", "Env": ["PATH=/usr/bin", "HOME=/home/dev"]},
}


class FakeEngine:
    """Records commands; answers from ``replies`` (first matching argv prefix wins)."""

    def __init__(self, replies: dict[tuple[str, ...], tuple[int, str]] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.replies = replies or {}

    def __call__(self, argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        for prefix, (code, out) in self.replies.items():
            if tuple(argv[: len(prefix)]) == prefix:
                return subprocess.CompletedProcess(argv, code, out, "boom" if code else "")
        return subprocess.CompletedProcess(argv, 0, "", "")

    def called(self, *prefix: str) -> list[list[str]]:
        return [call for call in self.calls if tuple(call[: len(prefix)]) == prefix]


def test_spec_needs_exactly_one_source() -> None:
    assert Environment(image="acme/dev:1").source == "image"
    with pytest.raises(ValueError, match="exactly one of: image, compose, container"):
        Environment()
    with pytest.raises(ValueError, match="exactly one of"):
        Environment(image="x", container="dev")
    with pytest.raises(ValueError, match="packages"):
        Environment(image="x", packages=["jq; rm -rf /"])
    with pytest.raises(ValueError, match="user"):
        Environment(image="x", user="Me Myself")
    assert Environment(image="x", user="vscode").user == "vscode"
    assert Environment(image="x", user="1000:1000").user == "1000:1000"


def test_resolve_applies_overrides() -> None:
    spec_env = Environment(image="acme/dev:1", workdir="/src")
    assert resolve(spec_env, EnvironmentOptions()) is spec_env
    assert resolve(spec_env, EnvironmentOptions(disabled=True)) is None
    override = resolve(spec_env, EnvironmentOptions(image="other:2"))
    assert override is not None
    assert (override.image, override.workdir) == ("other:2", "/src")
    assert resolve(None, EnvironmentOptions(image="other:2")) == Environment(image="other:2")


def test_policy_limits_sources_and_packages() -> None:
    from narratty.sandbox import Policy

    check_policy(Environment(image="x"), Policy())
    check_policy(Environment(image="x"), Policy(allow_environment=("image",)))
    with pytest.raises(UsageError, match="does not allow"):
        check_policy(Environment(image="x"), Policy(allow_environment=("compose",)))
    check_policy(Environment(image="x"), Policy(allow_packages=False))
    with pytest.raises(UsageError, match="adds packages"):
        check_policy(Environment(image="x", packages=["jq"]), Policy(allow_packages=False))


def test_inspect_pulls_missing_images() -> None:
    engine = FakeEngine({("docker", "image", "inspect"): (1, "")})

    def run(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        if argv[1] == "pull":
            engine.replies = {("docker", "image", "inspect"): (0, json.dumps([IMAGE]))}
        return engine(argv)

    info = inspect_image("docker", "acme/dev:1", run=run)
    assert engine.called("docker", "pull") == [["docker", "pull", "acme/dev:1"]]
    assert info == ImageInfo("acme/dev:1", info.id, "arm64", "dev", {"PATH": "/usr/bin", "HOME": "/home/dev"})
    assert info.id != IMAGE["Id"], "keyed by content, not by the (attestation-dependent) Id"
    rebuilt = FakeEngine({("docker", "image", "inspect"): (0, json.dumps([{**IMAGE, "Id": "sha256:other"}]))})
    assert inspect_image("docker", "acme/dev:1", run=rebuilt).id == info.id
    assert info.home == "/home/dev"
    assert ImageInfo("x", "i", "amd64").home == "/root"
    assert ImageInfo("x", "i", "amd64", user="1000").home == "/"


def test_inspect_rejects_other_architectures() -> None:
    engine = FakeEngine(
        {("docker", "image", "inspect"): (0, json.dumps([{**IMAGE, "Architecture": "s390x"}]))}
    )
    with pytest.raises(UsageError, match="s390x"):
        inspect_image("docker", "x", run=engine)


def test_agent_is_extracted_once_per_image(tmp_path: Path) -> None:
    engine = FakeEngine({("docker", "image", "inspect"): (0, "sha256:0123456789abcdef0123\n")})

    def run(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        if argv[1] == "cp":  # docker cp NAME:/opt/narratty/agent/. DEST
            (Path(argv[3]) / "amd64").mkdir(parents=True)
            (Path(argv[3]) / "amd64" / "narratty-agent").write_text("", encoding="utf-8")
        return engine(argv)

    first = agent_dir("docker", "narratty:1", "amd64", cache=tmp_path, run=run, env={})
    assert first == tmp_path / "agent" / "0123456789abcdef" / "amd64"
    assert engine.called("docker", "cp")[0][2].endswith(":/opt/narratty/agent/.")
    assert len(engine.called("docker", "rm")) == 1
    agent_dir("docker", "narratty:1", "amd64", cache=tmp_path, run=run, env={})
    assert len(engine.called("docker", "cp")) == 1, "cached"
    with pytest.raises(MissingDependencyError, match="arm64"):
        agent_dir("docker", "narratty:1", "arm64", cache=tmp_path, run=run, env={})


def test_agent_dir_override(tmp_path: Path) -> None:
    (tmp_path / "amd64").mkdir()
    (tmp_path / "amd64" / "narratty-agent").write_text("", encoding="utf-8")
    engine = FakeEngine()
    env = {"NARRATTY_AGENT_DIR": str(tmp_path)}
    assert agent_dir("docker", "img", "amd64", cache=tmp_path, run=engine, env=env) == tmp_path / "amd64"
    assert engine.calls == []


def _spec(tmp_path: Path, **env: object) -> Spec:
    return Spec.model_validate(
        {
            "environment": {"image": "acme/dev:1", **env},
            "workspace": {"caches": {"pip": "~/.cache/pip"}},
            "sandbox": {"env": {"TZ": "UTC"}},
            "scenes": [{"id": "a"}],
        }
    )


def _provide(
    tmp_path: Path, spec: Spec, engine: FakeEngine, *, with_agent: bool, keep: bool = False
) -> tuple[Session, list[list[str]]]:
    workspace = PreparedWorkspace(tmp_path / "ws", "ro", tmp_path / "ws")
    assert spec.environment is not None
    with provide(
        spec.environment,
        spec,
        spec_dir=tmp_path,
        sandbox=spec.sandbox,
        workspace=workspace,
        engine="docker",
        narratty_image="narratty:1",
        with_agent=with_agent,
        keep=keep,
        run=engine,
    ) as session:
        during = list(engine.calls)
    return session, during


@pytest.fixture
def image_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeEngine:
    agents = tmp_path / "agents"
    (agents / "arm64").mkdir(parents=True)
    (agents / "arm64" / "narratty-agent").write_text("", encoding="utf-8")
    monkeypatch.setenv("NARRATTY_AGENT_DIR", str(agents))
    return FakeEngine({("docker", "image", "inspect"): (0, json.dumps([IMAGE]))})


def test_container_is_hardened_and_removed(tmp_path: Path, image_engine: FakeEngine) -> None:
    session, during = _provide(tmp_path, _spec(tmp_path), image_engine, with_agent=False)
    run = next(call for call in during if call[1] == "run")
    assert run[:6] == ["docker", "run", "--detach", "--interactive", "--tty", "--init"]
    for flag, value in (("--network", "none"), ("--cap-drop", "ALL"), ("--workdir", "/work")):
        assert run[run.index(flag) + 1] == value
    assert "--rm" in run
    volumes = [run[i + 1] for i, arg in enumerate(run) if arg == "--volume"]
    assert f"{tmp_path / 'ws'}:/work:ro" in volumes
    assert any(v.endswith(":/home/narratty/.cache/pip") for v in volumes), "~ is the environment's HOME"
    assert "TZ=UTC" in run and "HOME=/home/narratty" in run
    assert run[-3:] == ["--entrypoint", "bash", "acme/dev:1"]
    assert not image_engine.called("docker", "volume"), "no agent, no volume"
    assert session.exec_bridge()[-1] == session.container
    assert image_engine.calls[-1] == ["docker", "rm", "--force", session.container]


def test_image_user_keeps_the_image_home(tmp_path: Path, image_engine: FakeEngine) -> None:
    _, during = _provide(
        tmp_path, _spec(tmp_path, user="image", read_only=True), image_engine, with_agent=False
    )
    run = next(call for call in during if call[1] == "run")
    assert "--user" not in run and "HOME=/home/narratty" not in run
    assert any(run[i + 1].endswith(":/home/dev/.cache/pip") for i, arg in enumerate(run) if arg == "--volume")
    assert "--read-only" in run


def test_agent_serves_on_a_shared_volume(tmp_path: Path, image_engine: FakeEngine) -> None:
    session, during = _provide(tmp_path, _spec(tmp_path), image_engine, with_agent=True)
    volume = session.volume
    assert volume is not None
    assert image_engine.called("docker", "volume", "create")[0][-1] == volume
    run = next(call for call in during if call[1] == "run")
    assert f"{volume}:/.narratty/run" in run
    assert f"{tmp_path / 'agents' / 'arm64'}:/.narratty/agent:ro" in run
    serve = image_engine.called("docker", "exec", "--detach")[0]
    assert serve[-5:] == ["serve", "--socket", "/.narratty/run/agent.sock", "--workdir", "/work"]
    assert session.recorder_flags() == ([f"{volume}:/run/narratty"], None)
    assert session.agent_bridge()[:2] == ["narratty-agent", "connect"]
    removed = [call[1:3] for call in image_engine.calls[len(during) :]]
    assert removed == [["rm", "--force"], ["volume", "rm"]]


def test_keep_leaves_everything(tmp_path: Path, image_engine: FakeEngine) -> None:
    _, during = _provide(tmp_path, _spec(tmp_path), image_engine, with_agent=True, keep=True)
    assert "--rm" not in next(call for call in during if call[1] == "run")
    assert image_engine.calls == during


def test_agent_that_does_not_start(tmp_path: Path, image_engine: FakeEngine) -> None:
    def run(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        if argv[1] == "exec" and "ping" in argv:
            return subprocess.CompletedProcess(argv, 1, "", "connection refused")
        return image_engine(argv)

    spec = _spec(tmp_path)
    assert spec.environment is not None
    with (
        pytest.raises(NarrattyError, match="did not start"),
        provide(
            spec.environment,
            spec,
            spec_dir=tmp_path,
            sandbox=Sandbox(),
            workspace=PreparedWorkspace(tmp_path, "rw", tmp_path),
            engine="docker",
            narratty_image="n",
            with_agent=True,
            run=run,
        ),
    ):
        pass
    assert image_engine.called("docker", "rm"), "cleaned up after the failure"


def test_allowlist_network_for_the_environment(
    tmp_path: Path, image_engine: FakeEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from contextlib import contextmanager

    used: list[str] = []

    @contextmanager
    def fake_network(engine: str, image: str, hosts: Sequence[str]):  # type: ignore[no-untyped-def]
        used.append(image)
        yield "narratty-net"

    monkeypatch.setattr("narratty.sandbox.allowlist_network", fake_network)
    spec = _spec(tmp_path)
    assert spec.environment is not None
    sandbox = Sandbox(network="allowlist", allow_hosts=["example.com:443"])
    with provide(
        spec.environment,
        spec,
        spec_dir=tmp_path,
        sandbox=sandbox,
        workspace=PreparedWorkspace(tmp_path, "rw", tmp_path),
        engine="docker",
        narratty_image="narratty:1",
        with_agent=False,
        run=image_engine,
    ):
        pass
    run = image_engine.called("docker", "run")[0]
    assert run[run.index("--network") + 1] == "narratty-net"
    assert used == ["narratty:1"]


# ── the demo toolkit ──────────────────────────────────────────────────────────


def test_toolkit_is_mounted_and_put_first_on_path(tmp_path: Path, image_engine: FakeEngine) -> None:
    def run(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        if argv[1] == "cp":  # docker cp NAME:/. DEST
            Path(argv[3], "bin").mkdir(parents=True)
        return image_engine(argv)

    spec = _spec(tmp_path)
    assert spec.environment is not None
    workspace = PreparedWorkspace(tmp_path, "rw", tmp_path)
    with provide(
        spec.environment, spec, spec_dir=tmp_path, sandbox=spec.sandbox, workspace=workspace,
        engine="docker", narratty_image="narratty:1", with_agent=False, run=run,
    ):  # fmt: skip
        pass
    started = image_engine.called("docker", "run", "--detach")[0]
    assert any(volume.endswith(":/.narratty/toolkit:ro") for volume in _volume_flags(started))
    assert "PATH=/.narratty/toolkit/bin:/usr/bin" in started
    assert image_engine.called("docker", "create", "--platform", "linux/arm64")


def test_toolkit_off_or_missing(tmp_path: Path, image_engine: FakeEngine) -> None:
    _, during = _provide(tmp_path, _spec(tmp_path, toolkit="off"), image_engine, with_agent=False)
    assert not any("narratty-toolkit" in arg for call in during for arg in call)
    toolkit = f"ghcr.io/ditschi/narratty-toolkit:{release_tag()}"
    missing = FakeEngine(
        {
            ("docker", "image", "inspect", "--format", "{{.Id}}", toolkit): (1, ""),
            ("docker", "image", "inspect"): (0, json.dumps([IMAGE])),
        }
    )
    _, during = _provide(tmp_path, _spec(tmp_path), missing, with_agent=False)
    assert missing.called("docker", "pull", "--platform", "linux/arm64", toolkit)
    started = next(call for call in during if call[1] == "run")
    assert not any(".narratty/toolkit" in arg for arg in started)


def _volume_flags(argv: list[str]) -> list[str]:
    return [argv[i + 1] for i, arg in enumerate(argv) if arg == "--volume"]


def test_toolkit_env_prefers_or_falls_back() -> None:
    from narratty.env_toolkit import toolkit_env

    assert toolkit_env("prefer", "/bin")["PATH"] == "/.narratty/toolkit/bin:/bin"
    assert toolkit_env("fallback", None)["PATH"].endswith(":/.narratty/toolkit/bin")


# ── Compose ───────────────────────────────────────────────────────────────────

COMPOSE_CONFIG: dict[str, Any] = {"services": {"dev": {"image": "acme/dev:1"}, "db": {"image": "postgres"}}}


def _compose_engine() -> FakeEngine:
    return FakeEngine(
        {
            ("docker", "compose"): (0, ""),
            ("docker", "image", "inspect"): (0, json.dumps([IMAGE])),
        }
    )


def _compose_run(
    engine: FakeEngine, config: dict[str, Any] = COMPOSE_CONFIG
) -> tuple[Callable[[Sequence[str]], subprocess.CompletedProcess[str]], list[dict[str, Any]]]:
    overrides: list[dict[str, Any]] = []

    def run(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        result = engine(argv)
        if argv[1] == "compose" and "config" in argv:
            return subprocess.CompletedProcess(argv, 0, json.dumps(config), "")
        if argv[1] == "compose" and "up" in argv:
            files = [argv[i + 1] for i, arg in enumerate(argv) if arg == "--file"]
            overrides.append(json.loads(Path(files[-1]).read_text(encoding="utf-8")))
        if argv[1] == "compose" and "ps" in argv:
            return subprocess.CompletedProcess(argv, 0, "c0ffee\n", "")
        return result

    return run, overrides


def _compose_spec(tmp_path: Path, **env: object) -> tuple[Spec, PreparedWorkspace]:
    source = tmp_path / "src"
    snapshot = tmp_path / "snap"
    for root in (source, snapshot):
        root.mkdir()
        (root / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    spec = Spec.model_validate(
        {"environment": {"compose": {"service": "dev"}, **env}, "scenes": [{"id": "a"}]}
    )
    return spec, PreparedWorkspace(snapshot, "snapshot", source)


def test_compose_service_runs_from_the_workspace_copy(tmp_path: Path, image_engine: FakeEngine) -> None:
    engine = _compose_engine()
    run, overrides = _compose_run(engine)
    spec, workspace = _compose_spec(tmp_path, toolkit="off")
    assert spec.environment is not None
    with provide(
        spec.environment, spec, spec_dir=tmp_path / "src", sandbox=spec.sandbox, workspace=workspace,
        engine="docker", narratty_image="narratty:1", with_agent=True, run=run,
    ) as session:  # fmt: skip
        assert session.container == "c0ffee"
        assert session.recorder_flags() == ([f"{session.volume}:/run/narratty"], None)
    up = next(call for call in engine.calls if "up" in call)
    assert up[up.index("--project-directory") + 1] == str(tmp_path / "snap")
    assert up[-4:] == ["up", "--detach", "--wait", "dev"]
    service = overrides[0]["services"]["dev"]
    assert f"{session.volume}" == overrides[0]["volumes"]["narratty_run"]["name"]
    assert "narratty_run:/.narratty/run" in service["volumes"]
    assert "image" not in service, "no packages, no derived image"
    serve = engine.called("docker", "exec", "--detach")[0]
    assert serve[:5] == ["docker", "exec", "--detach", "--user", serve[4]] and "c0ffee" in serve
    downs = [call for call in engine.calls if "down" in call]
    assert downs and "--volumes" in downs[0]


def test_compose_layered_image_is_used(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("narratty.env_image.build_layer", lambda *a, **k: "narratty-env:123")
    engine = _compose_engine()
    run, overrides = _compose_run(engine)
    spec, workspace = _compose_spec(tmp_path, toolkit="off", packages=["jq"])
    assert spec.environment is not None
    with provide(
        spec.environment, spec, spec_dir=tmp_path / "src", sandbox=spec.sandbox, workspace=workspace,
        engine="docker", narratty_image="narratty:1", with_agent=False, run=run,
    ):  # fmt: skip
        pass
    service = overrides[0]["services"]["dev"]
    assert (service["image"], service["pull_policy"]) == ("narratty-env:123", "never")


def test_compose_errors(tmp_path: Path) -> None:
    from narratty.env_compose import compose_files

    spec, workspace = _compose_spec(tmp_path)
    assert spec.environment is not None
    with pytest.raises(UsageError, match="outside the workspace"):
        compose_files(spec.environment, tmp_path, workspace)
    run, _ = _compose_run(_compose_engine(), {"services": {"db": {"image": "postgres"}}})
    with pytest.raises(UsageError, match="no service 'dev'"), provide(
        spec.environment, spec, spec_dir=tmp_path / "src", sandbox=spec.sandbox, workspace=workspace,
        engine="docker", narratty_image="narratty:1", with_agent=False, run=run,
    ):  # fmt: skip
        pass


# ── a running container ───────────────────────────────────────────────────────


def _container_engine(running: bool = True) -> FakeEngine:
    state = {"State": {"Running": running}, "Image": "sha256:img"}
    return FakeEngine(
        {
            ("docker", "inspect"): (0, json.dumps(state)),
            ("docker", "image", "inspect"): (0, "arm64\n"),
        }
    )


def _attach(tmp_path: Path, engine: FakeEngine, *, with_agent: bool, user: str = "image") -> Session:
    spec = Spec.model_validate(
        {
            "environment": {"container": "dev", "user": user},
            "workspace": {"mode": "rw"},
            "scenes": [{"id": "a"}],
        }
    )
    assert spec.environment is not None
    with provide(
        spec.environment, spec, spec_dir=tmp_path, sandbox=spec.sandbox,
        workspace=PreparedWorkspace(tmp_path, "rw", tmp_path), engine="docker",
        narratty_image="narratty:1", with_agent=with_agent, run=engine,
    ) as session:  # fmt: skip
        return session


def test_container_natively_is_docker_exec(tmp_path: Path) -> None:
    engine = _container_engine()
    session = _attach(tmp_path, engine, with_agent=False, user="1000")
    assert session.exec_bridge()[-3:] == ["--user", "1000", "dev"]
    assert not engine.called("docker", "cp")


def test_container_sandboxed_serves_one_shell(tmp_path: Path, image_engine: FakeEngine) -> None:
    engine = _container_engine()
    session = _attach(tmp_path, engine, with_agent=True)
    assert session.socket is not None and session.socket.startswith("@narratty-")
    assert session.recorder_flags() == ([], "container:dev")
    assert session.agent_bridge()[3] == session.socket
    copied = engine.called("docker", "cp")[0]
    target = copied[-1].removeprefix("dev:")
    serve = engine.called("docker", "exec", "--detach")[0]
    assert serve[-5:] == [target, "serve", "--socket", session.socket, "--once"]
    assert engine.calls[-2][-5:] == ["connect", "--socket", session.socket, "--", "true"]
    assert engine.calls[-1][-3:] == ["rm", "-f", target]


def test_container_must_run(tmp_path: Path) -> None:
    with pytest.raises(UsageError, match="not running"):
        _attach(tmp_path, _container_engine(running=False), with_agent=False)


def test_container_needs_rw_and_no_packages() -> None:
    with pytest.raises(ValueError, match="rw"):
        Spec.model_validate({"environment": {"container": "dev"}, "scenes": [{"id": "a"}]})
    with pytest.raises(ValueError, match="running container"):
        Environment(container="dev", packages=["jq"])


def test_grants_name_what_the_sandbox_does_not_cover() -> None:
    from narratty.env_provide import grants

    assert grants(Environment(image="x")) == []
    assert "dev" in grants(Environment(container="dev"))[0]
    assert "Compose service web" in grants(Environment(compose={"service": "web"}))[0]


# ── env up / down ─────────────────────────────────────────────────────────────


def test_running_and_down_find_kept_environments(tmp_path: Path) -> None:
    from narratty.environment import down, running, spec_key

    spec_path = tmp_path / "demo.narratty.yaml"
    labels = {
        "narratty.workdir": "/work",
        "narratty.volume": "narratty-env-x-run",
        "narratty.workspace": str(tmp_path / "ws"),
        "narratty.snapshot": str(tmp_path / "snap"),
    }
    (tmp_path / "snap").mkdir()
    engine = FakeEngine({("docker", "ps"): (0, "abc\n"), ("docker", "inspect"): (0, json.dumps(labels))})
    found = running("docker", spec_path, run=engine)
    assert found is not None
    session, workspace = found
    assert (session.container, session.workdir, session.volume, workspace) == (
        "abc", "/work", "narratty-env-x-run", tmp_path / "ws"
    )  # fmt: skip
    assert engine.calls[0][-1] == f"label=narratty.spec={spec_key(spec_path)}"
    assert down("docker", spec_path, run=engine) == 1
    assert ["docker", "rm", "--force", "abc"] in engine.calls
    assert ["docker", "volume", "rm", "--force", "narratty-env-x-run"] in engine.calls
    assert not (tmp_path / "snap").exists()
    assert running("docker", spec_path, run=FakeEngine({("docker", "ps"): (0, "")})) is None
