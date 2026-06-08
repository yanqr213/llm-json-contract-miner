"""Offline contract mining for LLM JSON outputs."""

from .analyzer import analyze_samples
from .contract import compare_expected_contract
from .schema import build_schema

__version__ = "0.1.0"

__all__ = ["__version__", "analyze_samples", "build_schema", "compare_expected_contract"]

