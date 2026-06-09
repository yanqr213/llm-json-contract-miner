import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from llm_json_contract_miner.analyzer import analyze_samples, child_path, json_type, stable_scalar, walk_value
from llm_json_contract_miner.cli import main, parse_formats
from llm_json_contract_miner.contract import compare_expected_contract, flatten_schema, normalize_schema_type
from llm_json_contract_miner.io import read_json, read_json_object, read_jsonl, read_samples
from llm_json_contract_miner.models import DriftFinding, FieldStats
from llm_json_contract_miner.reports import render_csv, render_fix_plan, render_junit, render_markdown, write_reports
from llm_json_contract_miner.schema import build_schema, direct_children, enum_candidates, required_children, schema_for_path


class TempProject(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")
        return path


def samples():
    return [
        {"id": "a", "status": "ok", "score": 1.0, "answer": {"text": "yes", "citations": [{"source": "a.md", "line": 1}]}},
        {"id": "b", "status": "ok", "score": 0.8, "answer": {"text": "no", "citations": [{"source": "b.md", "line": 2}]}},
        {"id": "c", "status": "review", "score": 0.3, "answer": {"text": None, "citations": []}, "extra": True},
    ]


class JsonTypeTests(unittest.TestCase):
    def test_json_type_none(self):
        self.assertEqual(json_type(None), "null")

    def test_json_type_bool(self):
        self.assertEqual(json_type(True), "boolean")

    def test_json_type_int(self):
        self.assertEqual(json_type(3), "integer")

    def test_json_type_float(self):
        self.assertEqual(json_type(3.2), "number")

    def test_json_type_string(self):
        self.assertEqual(json_type("x"), "string")

    def test_json_type_array(self):
        self.assertEqual(json_type([]), "array")

    def test_json_type_object(self):
        self.assertEqual(json_type({}), "object")

    def test_stable_scalar_true(self):
        self.assertEqual(stable_scalar(True), "true")

    def test_stable_scalar_false(self):
        self.assertEqual(stable_scalar(False), "false")

    def test_stable_scalar_none(self):
        self.assertEqual(stable_scalar(None), "null")

    def test_stable_scalar_string(self):
        self.assertEqual(stable_scalar("ok"), "ok")

    def test_child_path_plain(self):
        self.assertEqual(child_path("$", "answer"), "$.answer")

    def test_child_path_quoted(self):
        self.assertEqual(child_path("$", "bad key"), "$['bad key']")


class IoTests(TempProject):
    def test_read_json_object(self):
        path = self.write("one.json", '{"a":1}')
        loaded = read_json(path)
        self.assertEqual(loaded.samples[0]["a"], 1)

    def test_read_json_array(self):
        path = self.write("many.json", '[{"a":1},{"a":2}]')
        self.assertEqual(len(read_json(path).samples), 2)

    def test_read_json_invalid(self):
        path = self.write("bad.json", '{"a"')
        loaded = read_json(path)
        self.assertEqual(len(loaded.invalid_records), 1)

    def test_read_jsonl(self):
        path = self.write("out.jsonl", '{"a":1}\n{"a":2}\n')
        self.assertEqual(len(read_jsonl(path).samples), 2)

    def test_read_jsonl_skips_blank_and_comment(self):
        path = self.write("out.jsonl", '\n# comment\n{"a":1}\n')
        self.assertEqual(len(read_jsonl(path).samples), 1)

    def test_read_jsonl_invalid_line(self):
        path = self.write("out.jsonl", '{"a":1}\nnope\n')
        loaded = read_jsonl(path)
        self.assertEqual(len(loaded.samples), 1)
        self.assertEqual(loaded.invalid_records[0]["line"], 2)

    def test_read_samples_multiple(self):
        a = self.write("a.json", '{"a":1}')
        b = self.write("b.jsonl", '{"b":2}\n')
        loaded = read_samples([str(a), str(b)])
        self.assertEqual(len(loaded.samples), 2)

    def test_read_samples_rejects_suffix(self):
        path = self.write("a.txt", "{}")
        with self.assertRaises(ValueError):
            read_samples([str(path)])

    def test_read_json_object_helper(self):
        path = self.write("contract.json", '{"type":"object"}')
        self.assertEqual(read_json_object(str(path))["type"], "object")

    def test_read_json_object_helper_rejects_array(self):
        path = self.write("contract.json", "[]")
        with self.assertRaises(ValueError):
            read_json_object(str(path))


class AnalyzerTests(unittest.TestCase):
    def test_walk_records_root(self):
        fields = {}
        seen = set()
        walk_value({"a": 1}, "$", 0, fields, seen, 20)
        self.assertIn("$", fields)

    def test_walk_records_child(self):
        fields = {}
        seen = set()
        walk_value({"a": 1}, "$", 0, fields, seen, 20)
        self.assertIn("$.a", fields)

    def test_walk_records_array_item(self):
        fields = {}
        seen = set()
        walk_value({"a": [{"b": 1}]}, "$", 0, fields, seen, 20)
        self.assertIn("$.a[]", fields)
        self.assertIn("$.a[].b", fields)

    def test_analyze_sample_count(self):
        report = analyze_samples(samples())
        self.assertEqual(report.sample_count, 3)

    def test_analyze_fields(self):
        report = analyze_samples(samples())
        self.assertIn("$.answer.text", report.fields)

    def test_missing_count(self):
        report = analyze_samples(samples())
        self.assertEqual(report.fields["$.extra"].missing_count, 2)

    def test_null_count(self):
        report = analyze_samples(samples())
        self.assertEqual(report.fields["$.answer.text"].null_count, 1)

    def test_type_counts(self):
        report = analyze_samples(samples())
        self.assertEqual(report.fields["$.score"].dominant_type, "number")

    def test_mixed_type_anomaly(self):
        report = analyze_samples([{"a": 1}, {"a": "x"}])
        self.assertTrue(any(f.kind == "mixed_types" for f in report.anomalies))

    def test_required_with_nulls_anomaly(self):
        report = analyze_samples([{"a": None}, {"a": 1}])
        self.assertTrue(any(f.kind == "required_with_nulls" for f in report.anomalies))

    def test_near_required_missing(self):
        report = analyze_samples([{"a": 1}, {"a": 2}, {"a": 3}, {"a": 4}, {}])
        self.assertTrue(any(f.kind == "near_required_missing" for f in report.anomalies))

    def test_empty_samples_high_risk(self):
        report = analyze_samples([])
        self.assertGreaterEqual(report.risk_score, 80)

    def test_expected_contract_drift(self):
        expected = {"properties": {"id": {"type": "integer"}}}
        report = analyze_samples(samples(), expected)
        self.assertTrue(any(f.kind == "type_mismatch" for f in report.drift_findings))


class SchemaTests(unittest.TestCase):
    def setUp(self):
        self.report = analyze_samples(samples())

    def test_direct_children_root(self):
        children = direct_children("$", self.report.fields)
        self.assertIn("id", children)

    def test_required_children_root(self):
        required = required_children("$", self.report.fields, 3, 1.0)
        self.assertIn("id", required)

    def test_schema_root_type(self):
        self.assertEqual(self.report.schema["type"], "object")

    def test_schema_has_properties(self):
        self.assertIn("answer", self.report.schema["properties"])

    def test_schema_nested_required(self):
        answer = self.report.schema["properties"]["answer"]
        self.assertIn("citations", answer["required"])

    def test_schema_array_items(self):
        answer = self.report.schema["properties"]["answer"]
        citations = answer["properties"]["citations"]
        self.assertEqual(citations["type"], "array")

    def test_schema_for_string(self):
        schema = schema_for_path("$.id", self.report.fields, 3, 1.0)
        self.assertEqual(schema["type"], "string")

    def test_schema_nullable(self):
        schema = schema_for_path("$.answer.text", self.report.fields, 3, 1.0)
        self.assertIn("null", schema["type"])

    def test_enum_candidates_small(self):
        field = FieldStats(path="$.status", enum_counts={"ok": 2, "review": 1})
        self.assertEqual(enum_candidates(field), ["ok", "review"])

    def test_enum_candidates_too_many(self):
        field = FieldStats(path="$.x", enum_counts={str(i): 1 for i in range(20)})
        self.assertEqual(enum_candidates(field), [])

    def test_build_schema_required_ratio(self):
        schema = build_schema(self.report.fields, 3, 0.3)
        self.assertIn("extra", schema["required"])


class ContractTests(unittest.TestCase):
    def test_normalize_schema_type_none(self):
        self.assertEqual(normalize_schema_type(None), set())

    def test_normalize_schema_type_string(self):
        self.assertEqual(normalize_schema_type("string"), {"string"})

    def test_normalize_schema_type_list(self):
        self.assertEqual(normalize_schema_type(["string", "null"]), {"string", "null"})

    def test_flatten_schema(self):
        schema = {"properties": {"a": {"type": "object", "properties": {"b": {"type": "string"}}}}}
        flat = flatten_schema(schema)
        self.assertIn("$.a", flat)
        self.assertIn("$.a.b", flat)

    def test_flatten_array_items(self):
        schema = {"properties": {"a": {"type": "array", "items": {"type": "object", "properties": {"b": {"type": "string"}}}}}}
        flat = flatten_schema(schema)
        self.assertIn("$.a[]", flat)
        self.assertIn("$.a[].b", flat)

    def test_compare_missing_expected(self):
        report = analyze_samples([{"a": 1}])
        findings = compare_expected_contract({"properties": {"b": {"type": "string"}}}, report.fields, report.schema, 1)
        self.assertTrue(any(f.kind == "missing_expected_field" for f in findings))

    def test_compare_type_mismatch(self):
        report = analyze_samples([{"a": 1}])
        findings = compare_expected_contract({"properties": {"a": {"type": "string"}}}, report.fields, report.schema, 1)
        self.assertTrue(any(f.kind == "type_mismatch" for f in findings))

    def test_compare_enum_drift(self):
        report = analyze_samples([{"a": "x"}])
        findings = compare_expected_contract({"properties": {"a": {"type": "string", "enum": ["y"]}}}, report.fields, report.schema, 1)
        self.assertTrue(any(f.kind == "enum_drift" for f in findings))

    def test_compare_new_field(self):
        report = analyze_samples([{"a": 1}])
        findings = compare_expected_contract({"properties": {}}, report.fields, report.schema, 1)
        self.assertTrue(any(f.kind == "new_observed_field" for f in findings))


class ReportTests(TempProject):
    def setUp(self):
        super().setUp()
        self.report = analyze_samples(samples())

    def test_report_to_dict(self):
        data = self.report.to_dict()
        self.assertIn("schema", data)

    def test_field_to_dict(self):
        data = self.report.fields["$.id"].to_dict(3)
        self.assertTrue(data["required"])

    def test_drift_to_dict(self):
        finding = DriftFinding(path="$.x", severity="warning", kind="k", message="m")
        self.assertEqual(finding.to_dict()["path"], "$.x")

    def test_markdown_contains_header(self):
        self.assertIn("LLM JSON Contract Report", render_markdown(self.report))

    def test_markdown_contains_path(self):
        self.assertIn("$.answer.text", render_markdown(self.report))

    def test_csv_contains_header(self):
        self.assertIn("path,required,dominant_type", render_csv(self.report))

    def test_junit_is_xml(self):
        ET.fromstring(render_junit(self.report))

    def test_junit_has_testsuite(self):
        self.assertIn("testsuite", render_junit(self.report))

    def test_fix_plan_contains_agent_prompt(self):
        expected = {"properties": {"id": {"type": "integer"}}}
        report = analyze_samples(samples(), expected)
        text = render_fix_plan(report)
        self.assertIn("LLM JSON Contract Fix Plan", text)
        self.assertIn("Prompt Or Decoder Repairs", text)
        self.assertIn("Agent Repair Prompt", text)

    def test_write_reports_all(self):
        outputs = write_reports(self.report, self.root / "reports", ["all", "csv"])
        self.assertTrue((self.root / "reports" / "contract-report.json").exists())
        self.assertTrue((self.root / "reports" / "schema.draft.json").exists())
        self.assertTrue((self.root / "reports" / "contract-fix-plan.md").exists())

    def test_write_reports_selected(self):
        outputs = write_reports(self.report, self.root / "reports", ["csv"])
        self.assertIn("csv", outputs)
        self.assertFalse((self.root / "reports" / "contract-report.json").exists())


class CliTests(TempProject):
    def make_input(self):
        return self.write("out.jsonl", '{"id":"a","status":"ok"}\n{"id":"b","status":"review"}\n')

    def test_parse_formats(self):
        self.assertEqual(parse_formats("json,markdown"), ["json", "markdown"])

    def test_parse_formats_rejects_unknown(self):
        with self.assertRaises(ValueError):
            parse_formats("html")

    def test_main_no_inputs_errors(self):
        with self.assertRaises(SystemExit) as raised:
            main([])
        self.assertEqual(raised.exception.code, 2)

    def test_main_no_fail(self):
        path = self.make_input()
        code = main([str(path), "--out", str(self.root / "reports"), "--no-fail"])
        self.assertEqual(code, 0)

    def test_main_writes_reports(self):
        path = self.make_input()
        code = main([str(path), "--out", str(self.root / "reports"), "--formats", "json,markdown,junit,schema,csv,fix-plan", "--no-fail"])
        self.assertEqual(code, 0)
        self.assertTrue((self.root / "reports" / "fields.csv").exists())
        self.assertTrue((self.root / "reports" / "contract-fix-plan.md").exists())

    def test_main_expected_mismatch_fails(self):
        path = self.make_input()
        expected = self.write("expected.json", '{"properties":{"id":{"type":"integer"}}}')
        code = main([str(path), "--expected", str(expected), "--out", str(self.root / "reports"), "--fail-score", "1"])
        self.assertEqual(code, 1)

    def test_main_bad_required_ratio(self):
        path = self.make_input()
        with self.assertRaises(SystemExit):
            main([str(path), "--required-ratio", "2"])

    def test_main_missing_file_returns_two(self):
        code = main([str(self.root / "missing.jsonl")])
        self.assertEqual(code, 2)

    def test_main_summary(self):
        path = self.make_input()
        code = main([str(path), "--summary", "--no-fail"])
        self.assertEqual(code, 0)

    def test_module_help(self):
        result = subprocess.run([sys.executable, "-m", "llm_json_contract_miner", "--version"], cwd=ROOT, env={"PYTHONPATH": str(ROOT / "src")}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)


class UtilityCoverageTests(unittest.TestCase):
    def test_enum_boolean_values(self):
        field = FieldStats(path="$.flag", enum_counts={"true": 2, "false": 1})
        self.assertEqual(enum_candidates(field), [False, True])

    def test_enum_null_value(self):
        field = FieldStats(path="$.x", enum_counts={"null": 1})
        self.assertEqual(enum_candidates(field), [None])

    def test_analysis_exit_code_for_error(self):
        expected = {"properties": {"missing": {"type": "string"}}}
        report = analyze_samples([{"a": 1}], expected)
        self.assertEqual(report.exit_code, 1)

    def test_analysis_exit_code_pass(self):
        report = analyze_samples([{"a": 1}])
        self.assertEqual(report.exit_code, 0)

    def test_schema_in_report_dict(self):
        self.assertEqual(analyze_samples([{"a": 1}]).to_dict()["schema"]["type"], "object")

    def test_invalid_count_mutable(self):
        report = analyze_samples([{"a": 1}])
        report.invalid_count = 2
        self.assertEqual(report.to_dict()["invalid_count"], 2)

    def test_examples_exist(self):
        self.assertTrue((ROOT / "examples" / "outputs.jsonl").exists())
        self.assertTrue((ROOT / "examples" / "expected.schema.json").exists())

    def test_readme_exists(self):
        self.assertTrue((ROOT / "README.md").exists())


if __name__ == "__main__":
    unittest.main()
