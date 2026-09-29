"""The ``.narratty.yaml`` spec: typed models and a loader with line-accurate errors."""

from narratty.spec.loader import SpecError, load_spec
from narratty.spec.model import Spec

__all__ = ["Spec", "SpecError", "load_spec"]
