"""Building the environment's image: the project's Dockerfile and the package layer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from narratty.env_image import (
    build_layer,
    detect_package_manager,
    grants,
    layer_dockerfile,
    layer_tag,
)
from narratty.environment import prepare_image
from narratty.errors import UsageError
from narratty.spec.model import Environment
from tests.unit.test_environment import IMAGE, FakeEngine


def test_package_manager_is_detected_once(tmp_path: Path) -> None:
    engine = FakeEngine({("docker", "run"): (0, "apt-get\n")})
    assert detect_package_manager("docker", "img", "sha256:1", cache=tmp_path, run=engine) == "apt"
    assert detect_package_manager("docker", "img", "sha256:1", cache=tmp_path, run=engine) == "apt"
    assert len(engine.calls) == 1
    none = FakeEngine({("docker", "run"): (1, "")})
    with pytest.raises(UsageError, match="no package manager"):
        detect_package_manager("docker", "distroless", "sha256:2", cache=tmp_path, run=none)


def test_layer_dockerfile() -> None:
    dockerfile = layer_dockerfile("acme/dev:1", "dev", "apk", ["jq", "bat"], ["echo hi > /etc/motd"])
    assert dockerfile.splitlines() == [
        "FROM acme/dev:1",
        "USER root",
        "RUN apk add --no-cache jq bat",
        "RUN echo hi > /etc/motd",
        "USER dev",
    ]
    assert "USER" not in layer_dockerfile("x", "", None, [], ["true"]).splitlines()[-1]
    assert "rm -rf /var/lib/apt/lists/*" in layer_dockerfile("x", "", "apt", ["jq"], [])


def test_layer_tag_changes_with_its_inputs() -> None:
    base = layer_tag("sha256:1", "apt", ["jq"], [])
    assert base.startswith("narratty-env:")
    assert base == layer_tag("sha256:1", "apt", ["jq"], [])
    assert base != layer_tag("sha256:2", "apt", ["jq"], [])
    assert base != layer_tag("sha256:1", "apt", ["jq", "bat"], [])


def test_layer_is_built_only_when_missing(tmp_path: Path) -> None:
    environment = Environment(image="acme/dev:1", packages=["jq"], package_manager="apk")
    missing = FakeEngine({("docker", "image", "inspect"): (1, "")})
    tag = build_layer(
        environment, "acme/dev:1", "sha256:1", "dev", engine="docker", cache=tmp_path, run=missing
    )
    build = missing.called("docker", "build")
    assert build and build[0][:4] == ["docker", "build", "--tag", tag]
    present = FakeEngine()
    build_layer(environment, "acme/dev:1", "sha256:1", "dev", engine="docker", cache=tmp_path, run=present)
    assert not present.called("docker", "build")


def test_prepare_image_layers_packages(tmp_path: Path) -> None:
    engine = FakeEngine(
        {("docker", "image", "inspect"): (0, json.dumps([IMAGE])), ("docker", "run"): (0, "apk\n")}
    )
    environment = Environment(image="acme/dev:1", packages=["jq"])
    image = prepare_image(environment, spec_dir=tmp_path, engine="docker", rebuild=True, run=engine)
    assert image.ref.startswith("narratty-env:")
    assert engine.called("docker", "build")


def test_grants() -> None:
    assert grants(Environment(image="x")) == []
    (line,) = grants(Environment(image="x", packages=["jq", "bat"], setup=["a", "b"]))
    assert "root with network access" in line and "jq, bat" in line and "2 setup commands" in line
