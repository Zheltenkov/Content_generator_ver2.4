"""Offline evaluation harness for generated educational projects."""

from .dataset import load_generated_outputs, load_golden_dataset
from .models import (
    EvalCaseResult,
    EvalMetricBreakdown,
    EvalRunSummary,
    EvalThresholds,
    GeneratedProjectOutput,
    GoldenDataset,
    GoldenProjectCase,
    GoldenProjectExpectations,
)
from .runner import EvaluationHarness

__all__ = [
    "EvalCaseResult",
    "EvalMetricBreakdown",
    "EvalRunSummary",
    "EvalThresholds",
    "EvaluationHarness",
    "GeneratedProjectOutput",
    "GoldenDataset",
    "GoldenProjectCase",
    "GoldenProjectExpectations",
    "load_generated_outputs",
    "load_golden_dataset",
]
