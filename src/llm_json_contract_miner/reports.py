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
        requested = {"json", "markdown", "junit", "schema"}
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


def escape_pipe(value: str) -> str:
    return str(value).replace("|", "\\|")

