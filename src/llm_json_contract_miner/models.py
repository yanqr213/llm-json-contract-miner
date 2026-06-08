"""Data models used by the miner."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class FieldStats:
    path: str
    observed_count: int = 0
    null_count: int = 0
    missing_count: int = 0
    type_counts: Dict[str, int] = field(default_factory=dict)
    enum_counts: Dict[str, int] = field(default_factory=dict)
    examples: List[int] = field(default_factory=list)

    @property
    def dominant_type(self) -> str:
        if not self.type_counts:
            return "unknown"
        return sorted(self.type_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]

    @property
    def type_count(self) -> int:
        return len(self.type_counts)

    def to_dict(self, total_samples: int) -> Dict[str, Any]:
        required = self.observed_count == total_samples and self.null_count == 0
        enum_values = [key for key, _ in sorted(self.enum_counts.items(), key=lambda item: (-item[1], item[0]))]
        return {
            "path": self.path,
            "observed_count": self.observed_count,
            "missing_count": self.missing_count,
            "null_count": self.null_count,
            "required": required,
            "dominant_type": self.dominant_type,
            "type_counts": dict(sorted(self.type_counts.items())),
            "enum_values": enum_values,
            "examples": list(self.examples),
        }


@dataclass
class DriftFinding:
    path: str
    severity: str
    kind: str
    message: str
    expected: Any = None
    actual: Any = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "severity": self.severity,
            "kind": self.kind,
            "message": self.message,
            "expected": self.expected,
            "actual": self.actual,
        }


@dataclass
class AnalysisReport:
    sample_count: int
    invalid_count: int
    fields: Dict[str, FieldStats]
    anomalies: List[DriftFinding]
    schema: Dict[str, Any]
    drift_findings: List[DriftFinding] = field(default_factory=list)
    risk_score: int = 0
    exit_code: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sample_count": self.sample_count,
            "invalid_count": self.invalid_count,
            "risk_score": self.risk_score,
            "exit_code": self.exit_code,
            "summary": {
                "field_count": len(self.fields),
                "anomaly_count": len(self.anomalies),
                "drift_count": len(self.drift_findings),
                "required_count": sum(1 for field in self.fields.values() if field.observed_count == self.sample_count and field.null_count == 0),
            },
            "fields": [self.fields[path].to_dict(self.sample_count) for path in sorted(self.fields)],
            "anomalies": [finding.to_dict() for finding in self.anomalies],
            "drift_findings": [finding.to_dict() for finding in self.drift_findings],
            "schema": self.schema,
        }


@dataclass
class LoadedSamples:
    samples: List[Any]
    invalid_records: List[Dict[str, Any]]
    source_files: List[str]

