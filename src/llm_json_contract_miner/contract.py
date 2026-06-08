"""Expected contract comparison."""

from __future__ import annotations

from typing import Any, Dict, List

from .models import DriftFinding, FieldStats


def compare_expected_contract(
    expected: Dict[str, Any],
    fields: Dict[str, FieldStats],
    schema: Dict[str, Any],
    total_samples: int,
) -> List[DriftFinding]:
    findings: List[DriftFinding] = []
    expected_paths = flatten_schema(expected)
    for path, spec in sorted(expected_paths.items()):
        stats = fields.get(path)
        if not stats:
            findings.append(
                DriftFinding(
                    path=path,
                    severity="error",
                    kind="missing_expected_field",
                    message=f"Expected field {path} was not observed",
                    expected=spec,
                    actual=None,
                )
            )
            continue
        expected_type = normalize_schema_type(spec.get("type"))
        actual_types = set(stats.type_counts)
        if "null" in actual_types and len(actual_types) > 1:
            actual_types = set(actual_types)
        if expected_type and not actual_types.intersection(expected_type):
            findings.append(
                DriftFinding(
                    path=path,
                    severity="error",
                    kind="type_mismatch",
                    message=f"{path} type does not match expected contract",
                    expected=sorted(expected_type),
                    actual=sorted(actual_types),
                )
            )
        if spec.get("enum"):
            observed_values = set(stats.enum_counts)
            expected_values = {str(value).lower() if isinstance(value, bool) else "null" if value is None else str(value) for value in spec["enum"]}
            unexpected = sorted(value for value in observed_values if value not in expected_values)
            if unexpected:
                findings.append(
                    DriftFinding(
                        path=path,
                        severity="warning",
                        kind="enum_drift",
                        message=f"{path} contains values outside the expected enum",
                        expected=sorted(expected_values),
                        actual=unexpected,
                    )
                )
    for path in sorted(fields):
        if path != "$" and path not in expected_paths and path.count(".") <= 2:
            findings.append(
                DriftFinding(
                    path=path,
                    severity="info",
                    kind="new_observed_field",
                    message=f"{path} is observed but not declared in the expected contract",
                    actual=fields[path].dominant_type,
                )
            )
    return findings


def normalize_schema_type(value: Any) -> set:
    if value is None:
        return set()
    if isinstance(value, list):
        return set(str(item) for item in value)
    return {str(value)}


def flatten_schema(schema: Dict[str, Any], base: str = "$") -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}
    if not isinstance(schema, dict):
        return result
    properties = schema.get("properties", {})
    if isinstance(properties, dict):
        for key, child in properties.items():
            path = f"{base}.{key}"
            if isinstance(child, dict):
                result[path] = child
                result.update(flatten_schema(child, path))
                if child.get("type") == "array" and isinstance(child.get("items"), dict):
                    result[f"{path}[]"] = child["items"]
                    result.update(flatten_schema(child["items"], f"{path}[]"))
    return result

