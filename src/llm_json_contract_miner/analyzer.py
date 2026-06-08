"""Mine observed JSON contracts from model outputs."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Set, Tuple

from .contract import compare_expected_contract
from .models import AnalysisReport, DriftFinding, FieldStats
from .schema import build_schema


SCALAR_ENUM_TYPES = {"string", "integer", "number", "boolean", "null"}


def json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) and not isinstance(value, bool):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "unknown"


def analyze_samples(
    samples: Iterable[Any],
    expected_contract: Dict[str, Any] = None,
    enum_limit: int = 20,
    anomaly_sample_limit: int = 12,
    required_ratio: float = 1.0,
) -> AnalysisReport:
    sample_list = list(samples)
    total = len(sample_list)
    fields: Dict[str, FieldStats] = {}
    sample_paths: List[Set[str]] = []

    for index, sample in enumerate(sample_list):
        paths_for_sample: Set[str] = set()
        walk_value(sample, "$", index, fields, paths_for_sample, enum_limit)
        sample_paths.append(paths_for_sample)

    for path, stats in fields.items():
        stats.missing_count = sum(1 for paths in sample_paths if path not in paths)

    anomalies = detect_anomalies(fields, total, anomaly_sample_limit, required_ratio)
    schema = build_schema(fields, total, required_ratio)
    drift_findings = compare_expected_contract(expected_contract or {}, fields, schema, total) if expected_contract else []
    risk_score = score_risk(total, anomalies, drift_findings)
    exit_code = 1 if risk_score >= 70 or any(f.severity == "error" for f in anomalies + drift_findings) else 0
    return AnalysisReport(
        sample_count=total,
        invalid_count=0,
        fields=fields,
        anomalies=anomalies,
        schema=schema,
        drift_findings=drift_findings,
        risk_score=risk_score,
        exit_code=exit_code,
    )


def walk_value(
    value: Any,
    path: str,
    sample_index: int,
    fields: Dict[str, FieldStats],
    paths_for_sample: Set[str],
    enum_limit: int,
) -> None:
    value_type = json_type(value)
    stats = fields.setdefault(path, FieldStats(path=path))
    if path not in paths_for_sample:
        stats.observed_count += 1
        paths_for_sample.add(path)
        if len(stats.examples) < 5:
            stats.examples.append(sample_index)
    stats.type_counts[value_type] = stats.type_counts.get(value_type, 0) + 1
    if value_type == "null":
        stats.null_count += 1
    if value_type in SCALAR_ENUM_TYPES and len(stats.enum_counts) <= enum_limit:
        key = stable_scalar(value)
        stats.enum_counts[key] = stats.enum_counts.get(key, 0) + 1

    if isinstance(value, dict):
        for key in sorted(value):
            walk_value(value[key], child_path(path, key), sample_index, fields, paths_for_sample, enum_limit)
    elif isinstance(value, list):
        item_path = f"{path}[]"
        if not value:
            fields.setdefault(item_path, FieldStats(path=item_path))
        for item in value:
            walk_value(item, item_path, sample_index, fields, paths_for_sample, enum_limit)


def child_path(parent: str, key: str) -> str:
    if key.replace("_", "").replace("-", "").isalnum():
        return f"{parent}.{key}"
    escaped = key.replace("'", "\\'")
    return f"{parent}['{escaped}']"


def stable_scalar(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    return str(value)


def detect_anomalies(fields: Dict[str, FieldStats], total: int, limit: int, required_ratio: float) -> List[DriftFinding]:
    findings: List[DriftFinding] = []
    for path in sorted(fields):
        if path == "$":
            continue
        stats = fields[path]
        if stats.type_count > 1:
            findings.append(
                DriftFinding(
                    path=path,
                    severity="warning",
                    kind="mixed_types",
                    message=f"{path} has {stats.type_count} observed JSON types",
                    actual=dict(sorted(stats.type_counts.items())),
                )
            )
        if total and stats.observed_count / float(total) >= required_ratio and stats.null_count:
            findings.append(
                DriftFinding(
                    path=path,
                    severity="warning",
                    kind="required_with_nulls",
                    message=f"{path} appears required but contains null values",
                    actual={"null_count": stats.null_count},
                )
            )
        if total and stats.missing_count and stats.observed_count / float(total) >= 0.8:
            findings.append(
                DriftFinding(
                    path=path,
                    severity="info",
                    kind="near_required_missing",
                    message=f"{path} is present in most samples but missing in {stats.missing_count}",
                    actual={"missing_count": stats.missing_count},
                )
            )
    return findings[:limit]


def score_risk(sample_count: int, anomalies: List[DriftFinding], drift_findings: List[DriftFinding]) -> int:
    score = 0
    if sample_count == 0:
        score += 80
    for finding in anomalies + drift_findings:
        if finding.severity == "error":
            score += 30
        elif finding.severity == "warning":
            score += 12
        else:
            score += 4
    return min(score, 100)

