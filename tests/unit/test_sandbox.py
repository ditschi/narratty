"""Sandbox overrides, policy, consent and container flags."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from narratty.errors import UsageError
from narratty.sandbox import (
    Policy,
    allowlist_network,
    apply_overrides,
    check_policy,
    container_access,
    describe,
    ensure_consent,
    load_policy,
)
from narratty.spec.model import Sandbox


def _sandbox(**fields: object) -> Sandbox:
    return Sandbox.model_validate(fields)


def test_overrides() -> None:
    base = _sandbox()
    assert apply_overrides(base) is base
    assert apply_overrides(base, network="full").network == "full"
    widened = apply_overrides(base, allow_hosts=["cache.example.com:443"])
    assert (widened.network, widened.allow_hosts) == ("allowlist", ["cache.example.com:443"])
    narrowed = apply_overrides(_sandbox(network="allowlist", allow_hosts=["a:1"]), network="none")
    assert (narrowed.network, narrowed.allow_hosts) == ("none", [])
    with pytest.raises(UsageError, match="invalid sandbox override"):
        apply_overrides(base, network="allowlist")


def test_policy_file(tmp_path: Path) -> None:
    assert load_policy(tmp_path) == Policy()
    (tmp_path / "config.toml").write_text(
        '[sandbox]\nmax_network = "allowlist"\nallow_env = ["LM_LICENSE_FILE"]\nallow_ssh_agent = false\n',
        encoding="utf-8",
    )
    policy = load_policy(tmp_path)
    assert policy == Policy("allowlist", ("LM_LICENSE_FILE",), True, False)
    (tmp_path / "config.toml").write_text('[sandbox]\nmax_network = "lots"\n', encoding="utf-8")
    with pytest.raises(UsageError, match="max_network"):
        load_policy(tmp_path)


def test_policy_caps() -> None:
    policy = Policy("allowlist", ("LM_LICENSE_FILE",), allow_mounts=False, allow_ssh_agent=False)
    check_policy(
        _sandbox(network="allowlist", allow_hosts=["a:1"], env_passthrough=["LM_LICENSE_FILE"]), policy
    )
    too_much = _sandbox(
        network="full",
        env_passthrough=["AWS_SECRET_ACCESS_KEY"],
        extra_mounts=[{"host": "~/.netrc", "container": "~/.netrc"}],
        ssh_agent=True,
    )
    with pytest.raises(UsageError) as raised:
        check_policy(too_much, policy)
    for part in ("network: full", "AWS_SECRET_ACCESS_KEY", "extra_mounts", "ssh_agent"):
        assert part in raised.value.message


def test_describe() -> None:
    lines = describe(
        _sandbox(network="allowlist", allow_hosts=["lic:27000"], env_passthrough=["A"], ssh_agent=True)
    )
    assert lines == ["network access to lic:27000", "your environment variables A", "your SSH agent"]


def test_consent_is_asked_once_per_spec_and_sandbox(tmp_path: Path) -> None:
    spec = tmp_path / "demo.narratty.yaml"
    spec.write_text("x", encoding="utf-8")
    asked: list[str] = []

    def confirm(question: str) -> bool:
        asked.append(question)
        return True

    ensure_consent(spec, _sandbox(), confirm=confirm, directory=tmp_path)
    assert asked == [], "the default sandbox needs no approval"
    full = _sandbox(network="full")
    ensure_consent(spec, full, confirm=confirm, directory=tmp_path)
    ensure_consent(spec, full, confirm=confirm, directory=tmp_path)
    assert len(asked) == 1 and "full network access" in asked[0]
    ensure_consent(spec, _sandbox(network="full", ssh_agent=True), confirm=confirm, directory=tmp_path)
    assert len(asked) == 2, "a changed sandbox asks again"


def test_consent_refused_or_unavailable(tmp_path: Path) -> None:
    spec = tmp_path / "demo.narratty.yaml"
    full = _sandbox(network="full")
    with pytest.raises(UsageError, match="not approved"):
        ensure_consent(spec, full, confirm=lambda _q: False, directory=tmp_path)
    with pytest.raises(UsageError, match="full network access") as raised:
        ensure_consent(spec, full, interactive=False, directory=tmp_path)
    assert "--yes" in (raised.value.hint or "")
    ensure_consent(spec, full, assume_yes=True, interactive=False, directory=tmp_path)
    ensure_consent(spec, full, interactive=False, directory=tmp_path)  # remembered


def test_container_access(tmp_path: Path) -> None:
    (tmp_path / "license.dat").write_text("x", encoding="utf-8")
    sandbox = _sandbox(
        network="full",
        env={"TZ": "UTC"},
        env_passthrough=["TOKEN", "UNSET"],
        extra_mounts=[{"host": "license.dat", "container": "~/license.dat"}],
        ssh_agent=True,
    )
    access = container_access(
        sandbox,
        spec_dir=tmp_path,
        caches={"bazel": "~/.cache/bazel"},
        cache_root=tmp_path / "cache",
        environ={"TOKEN": "s3cret", "SSH_AUTH_SOCK": "/run/agent.sock"},
    )
    assert access.network == "bridge"
    assert access.env == {"TZ": "UTC", "TOKEN": "s3cret", "SSH_AUTH_SOCK": "/run/ssh-agent.sock"}
    assert f"{tmp_path / 'license.dat'}:/home/narratty/license.dat:ro" in access.volumes
    assert f"{tmp_path / 'cache' / 'build-caches' / 'bazel'}:/home/narratty/.cache/bazel" in access.volumes
    assert "/run/agent.sock:/run/ssh-agent.sock" in access.volumes
    assert (tmp_path / "cache" / "build-caches" / "bazel").is_dir()


def test_container_access_errors(tmp_path: Path) -> None:
    with pytest.raises(UsageError, match="does not exist"):
        container_access(
            _sandbox(extra_mounts=[{"host": "nope", "container": "/x"}]),
            spec_dir=tmp_path,
            caches={},
            cache_root=tmp_path,
            environ={},
        )
    with pytest.raises(UsageError, match="SSH_AUTH_SOCK"):
        container_access(
            _sandbox(ssh_agent=True), spec_dir=tmp_path, caches={}, cache_root=tmp_path, environ={}
        )


def test_allowlist_network_lifecycle() -> None:
    calls: list[list[str]] = []

    def engine(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "", "")

    hosts = ["cache.example.com:443", "lic.example.com:27000", "cache.example.com:9092"]
    resolved = {"cache.example.com": "203.0.113.1", "lic.example.com": "203.0.113.2"}
    with allowlist_network("docker", "img", hosts, resolver=resolved.__getitem__, run=engine) as network:
        assert network.startswith("narratty-")
        assert calls[0] == ["docker", "network", "create", "--internal", network]
        runs = [c for c in calls if c[1] == "run"]
        assert len(runs) == 2, "one forwarder per host"
        assert runs[0][-2:] == ["443=203.0.113.1:443", "9092=203.0.113.1:9092"]
        assert runs[1][-1] == "27000=203.0.113.2:27000"
        connects = [c for c in calls if c[1:3] == ["network", "connect"]]
        assert [c[c.index("--alias") + 1] for c in connects] == ["cache.example.com", "lic.example.com"]
    assert calls[-1] == ["docker", "network", "rm", network]
    assert sum(1 for c in calls if c[1] == "rm") == 2
