"""JSON Schema draft generation from mined field statistics."""

from __future__ import annotations

from typing import Any, Dict

from .models import FieldStats


def build_schema(fields: Dict[str, FieldStats], total_samples: int, required_ratio: float = 1.0) -> Dict[str, Any]:
    root: Dict[str, Any] = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "properties": {}}
    children = direct_children("$", fields)
    for child_key, child_path in children.items():
        root["properties"][child_key] = schema_for_path(child_path, fields, total_samples, required_ratio)
    required = required_children("$", fields, total_samples, required_ratio)
    if required:
        root["required"] = required
    return root


def schema_for_path(path: str, fields: Dict[str, FieldStats], total_samples: int, required_ratio: float) -> Dict[str, Any]:
    stats = fields[path]
    json_type = stats.dominant_type
    if json_type == "integer":
        schema: Dict[str, Any] = {"type": "integer"}
    elif json_type == "number":
        schema = {"type": "number"}
    elif json_type == "boolean":
        schema = {"type": "boolean"}
    elif json_type == "array":
        schema = {"type": "array", "items": {}}
        item_path = f"{path}[]"
        if item_path in fields:
            schema["items"] = schema_for_path(item_path, fields, total_samples, required_ratio)
    elif json_type == "object":
        schema = {"type": "object", "properties": {}}
        for key, child_path in direct_children(path, fields).items():
            schema["properties"][key] = schema_for_path(child_path, fields, total_samples, required_ratio)
        required = required_children(path, fields, total_samples, required_ratio)
        if required:
            schema["required"] = required
    elif json_type == "null":
        schema = {"type": "null"}
    else:
        schema = {"type": "string"}
    enum_values = enum_candidates(stats)
    if enum_values:
        schema["enum"] = enum_values
    if stats.null_count and schema.get("type") != "null":
        current_type = schema.get("type", "string")
        schema["type"] = sorted(set([current_type, "null"]))
    return schema


def direct_children(parent: str, fields: Dict[str, FieldStats]) -> Dict[str, str]:
    prefix = parent + "."
    result: Dict[str, str] = {}
    for path in sorted(fields):
        if not path.startswith(prefix):
            continue
        remainder = path[len(prefix) :]
        if "." in remainder or "[]" in remainder:
            continue
        result[remainder] = path
    return result


def required_children(parent: str, fields: Dict[str, FieldStats], total_samples: int, required_ratio: float) -> list:
    required = []
    for key, child_path in direct_children(parent, fields).items():
        stats = fields[child_path]
        if total_samples and stats.observed_count / float(total_samples) >= required_ratio and stats.null_count == 0:
            required.append(key)
    return sorted(required)


def enum_candidates(stats: FieldStats, max_values: int = 12) -> list:
    if not stats.enum_counts or len(stats.enum_counts) > max_values:
        return []
    values = []
    for raw in sorted(stats.enum_counts):
        if raw == "true":
            values.append(True)
        elif raw == "false":
            values.append(False)
        elif raw == "null":
            values.append(None)
        else:
            values.append(raw)
    return values
