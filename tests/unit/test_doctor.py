"""Which tools ``doctor`` checks for each runtime."""

from __future__ import annotations

from narratty.doctor import NATIVE_TOOLS, run_checks
from narratty.runtime import ResolvedRuntime, Runtime


def test_native_checks_every_pipeline_tool() -> None:
    resolved = ResolvedRuntime(Runtime.NATIVE, "test", False)
    results = run_checks(resolved, which=lambda name: None if name == "vhs" else f"/bin/{name}")
    assert [r.tool.name for r in results] == [t.name for t in NATIVE_TOOLS]
    assert [r.tool.name for r in results if not r.ok] == ["vhs"]


def test_container_runtime_only_needs_its_binary() -> None:
    resolved = ResolvedRuntime(Runtime.PODMAN, "test", True)
    results = run_checks(resolved, which=lambda name: f"/bin/{name}")
    assert [r.tool.name for r in results] == ["podman"]
    assert results[0].ok
