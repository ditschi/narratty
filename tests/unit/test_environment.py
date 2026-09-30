"""Project environments: overrides, image inspection, the container's lifecycle."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from narratty.environment import (
    EnvironmentOptions,
    ImageInfo,
    Session,
    agent_dir,
    check_policy,
    inspect_image,
    provide,
    resolve,
)
from narratty.errors import MissingDependencyError, NarrattyError, UsageError
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
    with pytest.raises(ValueError, match="exactly one of: image, build"):
        Environment()
    with pytest.raises(ValueError, match="exactly one of"):
        Environment(image="x", build={"context": "."})
    with pytest.raises(ValueError, match="packages"):
        Environment(image="x", packages=["jq; rm -rf /"])
    with pytest.raises(ValueError, match="user"):
        Environment(image="x", user="me")
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
    assert session.recorder_volume() == f"{volume}:/run/narratty"
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
