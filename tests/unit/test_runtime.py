"""Runtime resolution rules for ``--runtime auto``."""

from __future__ import annotations

import pytest

from narratty.runtime import IN_CONTAINER_ENV, Runtime, resolve_runtime


def _which(*available: str):  # type: ignore[no-untyped-def]
    return lambda name: f"/usr/bin/{name}" if name in available else None


@pytest.mark.parametrize("runtime", [Runtime.NATIVE, Runtime.DOCKER, Runtime.PODMAN])
def test_explicit_runtime_is_kept(runtime: Runtime) -> None:
    resolved = resolve_runtime(runtime, which=_which(), env={})
    assert resolved.runtime is runtime
    assert resolved.sandboxed is (runtime is not Runtime.NATIVE)


def test_auto_prefers_docker() -> None:
    resolved = resolve_runtime(Runtime.AUTO, which=_which("docker", "podman"), env={})
    assert resolved.runtime is Runtime.DOCKER
    assert resolved.sandboxed


def test_auto_falls_back_to_podman() -> None:
    assert resolve_runtime(Runtime.AUTO, which=_which("podman"), env={}).runtime is Runtime.PODMAN


def test_auto_falls_back_to_native_without_container_runtime() -> None:
    resolved = resolve_runtime(Runtime.AUTO, which=_which(), env={})
    assert resolved.runtime is Runtime.NATIVE
    assert not resolved.sandboxed
    assert "not sandboxed" in resolved.reason


def test_auto_is_native_inside_the_container() -> None:
    resolved = resolve_runtime(Runtime.AUTO, which=_which("docker"), env={IN_CONTAINER_ENV: "1"})
    assert resolved.runtime is Runtime.NATIVE


def test_container_engine() -> None:
    from narratty.errors import MissingDependencyError
    from narratty.runtime import container_engine

    assert container_engine(which=lambda name: f"/bin/{name}") == "docker"
    assert container_engine(which=lambda name: "/bin/podman" if name == "podman" else None) == "podman"
    with pytest.raises(MissingDependencyError, match="Docker or Podman"):
        container_engine(which=lambda name: None)
