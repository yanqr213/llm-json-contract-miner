"""Command-line interface."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List

from . import __version__
from .analyzer import analyze_samples
from .io import read_json_object, read_samples, write_json
from .reports import render_markdown, write_reports


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="llm-json-contract-miner", description="Mine and compare contracts for LLM JSON outputs.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("inputs", nargs="*", help="JSON or JSONL model output files")
    parser.add_argument("--expected", help="expected JSON Schema / contract JSON")
    parser.add_argument("--out", default="reports", help="output directory")
    parser.add_argument("--formats", default="markdown,json,junit,schema", help="comma-separated: markdown,json,junit,schema,csv,all")
    parser.add_argument("--enum-limit", type=int, default=20)
    parser.add_argument("--required-ratio", type=float, default=1.0)
    parser.add_argument("--fail-score", type=int, default=70, help="fail when risk score is at or above this value")
    parser.add_argument("--no-fail", action="store_true", help="always exit 0 after writing reports")
    parser.add_argument("--summary", action="store_true", help="print a short Markdown summary to stdout")
    return parser


def main(argv: List[str] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.inputs:
        parser.error("at least one JSON or JSONL input is required")
    if not 0 < args.required_ratio <= 1:
        parser.error("--required-ratio must be in (0, 1]")
    if not 0 <= args.fail_score <= 100:
        parser.error("--fail-score must be between 0 and 100")
    try:
        loaded = read_samples(args.inputs)
        expected = read_json_object(args.expected) if args.expected else None
        report = analyze_samples(loaded.samples, expected, enum_limit=args.enum_limit, required_ratio=args.required_ratio)
        report.invalid_count = len(loaded.invalid_records)
        if report.invalid_count:
            report.risk_score = min(100, report.risk_score + report.invalid_count * 20)
        report.exit_code = 1 if report.risk_score >= args.fail_score else report.exit_code
        outputs = write_reports(report, Path(args.out), parse_formats(args.formats))
        if args.summary:
            print(render_markdown(report))
        else:
            print(
                f"LLM JSON Contract Miner: {report.sample_count} samples, {len(report.fields)} paths, "
                f"risk {report.risk_score}/100. Reports: {Path(args.out)}"
            )
        return 0 if args.no_fail else report.exit_code
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"llm-json-contract-miner: {exc}")
        return 2


def parse_formats(value: str) -> List[str]:
    result = [item.strip().lower() for item in value.split(",") if item.strip()]
    allowed = {"markdown", "md", "json", "junit", "schema", "csv", "all"}
    unknown = [item for item in result if item not in allowed]
    if unknown:
        raise ValueError(f"unknown report format(s): {', '.join(unknown)}")
    return result or ["markdown", "json", "junit", "schema"]

