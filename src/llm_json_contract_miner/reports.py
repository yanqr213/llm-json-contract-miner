"""Report renderers."""

from __future__ import annotations

import csv
import html
import io
from pathlib import Path
from typing import Iterable, List

from .io import write_json, write_text
from .models import AnalysisReport, DriftFinding


def write_reports(report: AnalysisReport, out_dir: Path, formats: Iterable[str]) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    requested = set(formats)
    if "all" in requested:
        requested = {"json", "markdown", "junit", "schema", "csv", "fix-plan"}
    outputs = {}
    if "json" in requested:
        path = out_dir / "contract-report.json"
        write_json(path, report.to_dict())
        outputs["json"] = str(path)
    if "markdown" in requested or "md" in requested:
        path = out_dir / "contract-report.md"
        write_text(path, render_markdown(report))
        outputs["markdown"] = str(path)
    if "junit" in requested:
        path = out_dir / "junit.xml"
        write_text(path, render_junit(report))
        outputs["junit"] = str(path)
    if "schema" in requested:
        path = out_dir / "schema.draft.json"
        write_json(path, report.schema)
        outputs["schema"] = str(path)
    if "csv" in requested:
        path = out_dir / "fields.csv"
        write_text(path, render_csv(report))
        outputs["csv"] = str(path)
    if "fix-plan" in requested or "fix_plan" in requested:
        path = out_dir / "contract-fix-plan.md"
        write_text(path, render_fix_plan(report))
        outputs["fix_plan"] = str(path)
    return outputs


def render_markdown(report: AnalysisReport) -> str:
    lines = [
        "# LLM JSON Contract Report",
        "",
        f"- Samples: {report.sample_count}",
        f"- Invalid records: {report.invalid_count}",
        f"- Fields: {len(report.fields)}",
        f"- Risk score: {report.risk_score}/100",
        f"- Gate: {'PASS' if report.exit_code == 0 else 'FAIL'}",
        "",
        "## Fields",
        "",
        "| Path | Required | Dominant type | Missing | Null | Types |",
        "| --- | --- | --- | ---: | ---: | --- |",
    ]
    for path in sorted(report.fields):
        field = report.fields[path]
        data = field.to_dict(report.sample_count)
        lines.append(
            f"| `{path}` | {data['required']} | {field.dominant_type} | {field.missing_count} | "
            f"{field.null_count} | {escape_pipe(', '.join(sorted(field.type_counts)))} |"
        )
    findings = report.anomalies + report.drift_findings
    lines.extend(["", "## Findings", "", "| Severity | Kind | Path | Message |", "| --- | --- | --- | --- |"])
    if not findings:
        lines.append("| info | none | `$` | No contract drift findings. |")
    for finding in findings:
        lines.append(f"| {finding.severity} | {finding.kind} | `{finding.path}` | {escape_pipe(finding.message)} |")
    lines.append("")
    return "\n".join(lines)


def render_csv(report: AnalysisReport) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["path", "required", "dominant_type", "observed_count", "missing_count", "null_count", "type_counts", "enum_values"])
    for path in sorted(report.fields):
        field = report.fields[path]
        data = field.to_dict(report.sample_count)
        writer.writerow([
            path,
            data["required"],
            field.dominant_type,
            field.observed_count,
            field.missing_count,
            field.null_count,
            ";".join(f"{key}:{value}" for key, value in sorted(field.type_counts.items())),
            "|".join(str(value) for value in data["enum_values"]),
        ])
    return buffer.getvalue()


def render_junit(report: AnalysisReport) -> str:
    findings = report.anomalies + report.drift_findings
    failures = [finding for finding in findings if finding.severity in {"error", "warning"}]
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<testsuite name="llm-json-contract-miner" tests="{max(1, len(findings))}" failures="{len(failures)}">',
    ]
    if not findings:
        lines.append('  <testcase classname="llm_json_contract_miner" name="contract_stable" />')
    for finding in findings:
        lines.append(f'  <testcase classname="llm_json_contract_miner" name="{html.escape(finding.kind + ":" + finding.path)}">')
        if finding in failures:
            lines.append(
                f'    <failure message="{html.escape(finding.message)}" type="{html.escape(finding.severity)}">'
                f"{html.escape(finding.message)}</failure>"
            )
        lines.append("  </testcase>")
    lines.append("</testsuite>")
    return "\n".join(lines) + "\n"


def render_fix_plan(report: AnalysisReport) -> str:
    findings = report.anomalies + report.drift_findings
    grouped = _group_findings(findings)
    lines = [
        "# LLM JSON Contract Fix Plan",
        "",
        "## Summary",
        "",
        f"- Samples: {report.sample_count}",
        f"- Invalid records: {report.invalid_count}",
        f"- Observed paths: {len(report.fields)}",
        f"- Risk score: {report.risk_score}/100",
        f"- Gate: {'PASS' if report.exit_code == 0 else 'FAIL'}",
        f"- Findings: {len(findings)}",
        "",
        "## Recommended Order",
        "",
        "1. Fix invalid input records and parser issues first.",
        "2. Repair prompt, decoder, or tool output behavior for type mismatches and missing expected fields.",
        "3. Review enum drift and new observed fields before updating the formal schema.",
        "4. Regenerate the draft schema and rerun this miner before merging.",
        "",
    ]
    for title, key in [
        ("Schema Updates To Review", "schema"),
        ("Prompt Or Decoder Repairs", "behavior"),
        ("Sample Hygiene Work", "samples"),
        ("Human Review Queue", "review"),
    ]:
        lines.extend([f"## {title}", ""])
        items = grouped[key]
        if not items:
            lines.append("- None.")
        for finding in items:
            lines.extend(_finding_block(finding))
        lines.append("")

    lines.extend(
        [
            "## High-Signal Fields",
            "",
            "| Path | Required | Dominant type | Missing | Null | Types |",
            "| --- | --- | --- | ---: | ---: | --- |",
        ]
    )
    for path in _important_paths(report):
        field = report.fields[path]
        data = field.to_dict(report.sample_count)
        lines.append(
            f"| `{path}` | {data['required']} | {field.dominant_type} | {field.missing_count} | "
            f"{field.null_count} | {escape_pipe(', '.join(sorted(field.type_counts)))} |"
        )

    lines.extend(
        [
            "",
            "## Agent Repair Prompt",
            "",
            "```text",
            "You are repairing an LLM structured-output contract.",
            "Use contract-report.json for exact evidence, schema.draft.json as the observed-schema draft, and this fix plan as the work order.",
            "First fix invalid records and behavior-level drift. Do not blindly copy schema.draft.json over the product contract.",
            "For each finding, decide whether the correct action is prompt/decoder repair, expected schema update, eval fixture cleanup, or documented acceptance of new behavior.",
            "After changes, rerun llm-json-contract-miner with the same inputs and expected schema, then summarize remaining risk score and unresolved findings.",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def _group_findings(findings: List[DriftFinding]) -> dict:
    grouped = {"schema": [], "behavior": [], "samples": [], "review": []}
    for finding in findings:
        if finding.kind in {"new_observed_field", "enum_drift", "near_required_missing"}:
            grouped["schema"].append(finding)
        elif finding.kind in {"missing_expected_field", "type_mismatch", "mixed_types", "required_with_nulls"}:
            grouped["behavior"].append(finding)
        elif finding.kind in {"invalid_record"}:
            grouped["samples"].append(finding)
        else:
            grouped["review"].append(finding)
    return grouped


def _finding_block(finding: DriftFinding) -> List[str]:
    lines = [
        f"- `{finding.path}` **{finding.kind}** ({finding.severity}): {finding.message}",
    ]
    guidance = _guidance_for(finding)
    if guidance:
        lines.append(f"  - Suggested action: {guidance}")
    if finding.expected is not None:
        lines.append(f"  - Expected: `{_compact(finding.expected)}`")
    if finding.actual is not None:
        lines.append(f"  - Actual: `{_compact(finding.actual)}`")
    return lines


def _guidance_for(finding: DriftFinding) -> str:
    guidance = {
        "missing_expected_field": "restore the field in model/tool output, or remove it from the expected contract after review.",
        "type_mismatch": "repair serializer, parser, or prompt instructions so the emitted JSON type matches the contract.",
        "enum_drift": "decide whether new enum values are valid product behavior before expanding the schema.",
        "new_observed_field": "review whether the field is useful; add it to the contract only if downstream consumers should rely on it.",
        "mixed_types": "normalize this path to one JSON type, or explicitly make the schema nullable/union typed.",
        "required_with_nulls": "avoid nulls for required fields, or make the field optional/nullable with product approval.",
        "near_required_missing": "either make the field consistently present or document it as optional.",
    }
    return guidance.get(finding.kind, "review the evidence and decide whether behavior or contract should change.")


def _important_paths(report: AnalysisReport) -> List[str]:
    finding_paths = {finding.path for finding in report.anomalies + report.drift_findings if finding.path in report.fields}
    ranked = sorted(
        report.fields,
        key=lambda path: (
            0 if path in finding_paths else 1,
            -report.fields[path].missing_count,
            -report.fields[path].null_count,
            path,
        ),
    )
    return ranked[:12]


def _compact(value) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def escape_pipe(value: str) -> str:
    return str(value).replace("|", "\\|")
