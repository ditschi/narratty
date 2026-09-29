"""Container launcher: image selection and the docker/podman command line."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from narratty import container
from narratty.container import ContainerSpec, Mount, delegate, image_ref, run_argv
from narratty.errors import MissingDependencyError
from narratty.runtime import Runtime


@pytest.mark.parametrize(
    ("version", "provider", "expected"),
    [
        ("1.2.3", "piper", "ghcr.io/ditschi/narratty:1.2.3"),
        ("1.2.3", "kokoro", "ghcr.io/ditschi/narratty:1.2.3-kokoro"),
        ("0.1.1.dev4+gabc", "piper", "ghcr.io/ditschi/narratty:edge"),
        ("0.1.1.dev4+gabc", "kokoro", "ghcr.io/ditschi/narratty:edge-kokoro"),
    ],
)
def test_image_ref(version: str, provider: str, expected: str) -> None:
    assert image_ref(provider, version=version) == expected


def test_image_override(monkeypatch: pytest.MonkeyPatch) -> None:
    assert image_ref("piper", override="me/img:1") == "me/img:1"
    monkeypatch.setenv("NARRATTY_IMAGE", "env/img:2")
    assert image_ref("piper") == "env/img:2"


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
    spec.write_text("workspace: {source: ..}\nscenes:\n  - id: a\n    narration: Hi.\n", encoding="utf-8")
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
