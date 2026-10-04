"""Functional checks for the CSV example's data conversion and batching."""
import csv
import hashlib
import importlib.util
import io
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sdk" / "python"))
spec = importlib.util.spec_from_file_location("batch_example", ROOT / "examples" / "batch_data_workflow.py")
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)


def execute_template(source, parameters, inputs):
    outputs = {}
    runtime = types.ModuleType("aperture")
    runtime.parameters = lambda: dict(parameters)
    def read_csv(name, *, delimiter=",", required_columns=()):
        reader = csv.DictReader(io.StringIO(inputs[name]), delimiter=delimiter)
        if any(column not in reader.fieldnames for column in required_columns):
            raise ValueError("Selected columns are missing")
        return reader
    runtime.read_csv = read_csv
    runtime.read_json = lambda name: json.loads(inputs[name])
    runtime.write_json = lambda name, value: outputs.update({name: json.dumps(value, allow_nan=False)})

    def write_csv(name, rows, columns):
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
        outputs[name] = buffer.getvalue()

    runtime.write_csv = write_csv
    with patch.dict(sys.modules, {"aperture": runtime}), patch("sys.stdout", new=io.StringIO()):
        exec(compile(source, "batch-template.py", "exec"), {})
    return outputs


class BatchTemplateTests(unittest.TestCase):
    def test_numeric_values_must_match_selected_separators(self):
        result = execute_template(pipeline.BATCH_SOURCE,
            {"input_name": "data.csv", "output_name": "batch.json", "delimiter": ";", "decimal_separator": ","},
            {"data.csv": "category;amount\na;1,25\na;1.25\na;1_000\n"})
        report = json.loads(result["batch.json"])
        self.assertEqual(report["valid_rows"], 1)
        self.assertEqual(report["quality"]["invalid_reasons"], {"invalid_amount": 2})

    def test_custom_regional_export_and_quality_reasons(self):
        parameters = {"input_name": "data.csv", "output_name": "batch.json", "category_column": "Department",
            "amount_column": "Revenue", "delimiter": ";", "decimal_separator": ",", "thousands_separator": ".",
            "missing_category": "reject", "csv_output": False}
        outputs = execute_template(pipeline.BATCH_SOURCE, parameters, {"data.csv":
            'Department;Revenue\nSales;1.234,56\nSales;0,10\nSales;0,20\n;4,00\nSales;bad\nSales;\nSales;NaN\nSales;12.34,56\n'})
        report = json.loads(outputs["batch.json"])
        self.assertEqual(report["groups"]["Sales"]["total_decimal"], "1234.86")
        self.assertEqual(report["valid_rows"], 3)
        self.assertEqual(report["invalid_rows"], 5)
        self.assertEqual(report["quality"]["invalid_reasons"],
            {"missing_category": 1, "invalid_amount": 2, "missing_amount": 1, "non_finite_amount": 1})
        self.assertEqual(sum(report["quality"]["invalid_reasons"].values()), report["invalid_rows"])

    def test_decimal_totals_survive_hierarchical_merges_without_float_rounding(self):
        reports = []
        for _ in range(17):
            reports.append(self.batch("category,amount\nservices,0.1\nservices,0.2\n"))
        names = [str(index) + ".json" for index in range(17)]
        partial = execute_template(pipeline.MERGE_SOURCE,
            {"input_names": names[:16], "output_name": "partial.json", "final": False},
            {name: json.dumps(value) for name, value in zip(names, reports)})
        final = execute_template(pipeline.MERGE_SOURCE,
            {"input_names": ["partial.json", names[-1]], "output_name": "report.json", "final": True},
            {"partial.json": partial["partial.json"], names[-1]: json.dumps(reports[-1])})
        report = json.loads(final["report.json"])
        self.assertEqual(report["groups"]["services"]["total_decimal"], "5.1")
        self.assertEqual(report["valid_rows"], 34)
        self.assertIn("quality.csv", final)

    def batch(self, text):
        outputs = execute_template(pipeline.BATCH_SOURCE,
            {"input_name": "data.csv", "output_name": "batch.json"}, {"data.csv": text})
        return json.loads(outputs["batch.json"])

    def test_missing_amount_is_counted_as_invalid(self):
        result = self.batch("category,amount\nservices,2.5\nmissing\nservices,3.5\n")
        self.assertEqual(result["valid_rows"], 2)
        self.assertEqual(result["invalid_rows"], 1)
        self.assertEqual(result["groups"]["services"]["total"], 6)

    def test_missing_category_is_uncategorized(self):
        result = self.batch("amount,category\n2.5,services\n10\ninvalid,ignored\n3.5,services\n")
        self.assertEqual(result["valid_rows"], 3)
        self.assertEqual(result["invalid_rows"], 1)
        self.assertEqual(result["groups"]["uncategorized"]["total"], 10)

    def test_hierarchical_plan_produces_one_complete_report(self):
        references = [{"object_id": "obj-" + f"{index:032x}", "name": f"input-{index}.csv",
                       "sha256": "ab" * 32, "size_bytes": 24} for index in range(17)]
        plan = pipeline.build_plan(references)
        self.assertGreater(len(plan), len(references) + 1)
        outputs = {}
        for step in plan:
            inputs = {item.get("name", item.get("artifact")):
                      outputs[item["from_step"]][item["artifact"]] if "from_step" in item
                      else "category,amount\nservices,1.25\nservices,bad\n" for item in step["inputs"]}
            self.assertLessEqual(len(inputs), 16)
            outputs[step["id"]] = execute_template(step["source"], step["parameters"], inputs)
        final = json.loads(outputs["report"]["report.json"])
        self.assertEqual(final["valid_rows"], 17)
        self.assertEqual(final["invalid_rows"], 17)
        self.assertEqual(final["groups"]["services"],
                         {"rows": 17, "total": 21.25, "total_decimal": "21.25", "minimum": 1.25, "maximum": 1.25})
        rows = list(csv.DictReader(io.StringIO(outputs["report"]["categories.csv"])))
        self.assertEqual(rows[0]["average"], "1.25")


class BatchUploadTests(unittest.TestCase):
    def test_duplicate_headers_are_rejected_before_upload(self):
        client = types.SimpleNamespace(upload_input=lambda *_args, **_options: self.fail("No batch should be uploaded"))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "records.csv"
            path.write_text("category,amount,amount\nservices,1,100\n", encoding="utf-8", newline="")
            with self.assertRaisesRegex(ValueError, "unique"):
                pipeline.upload_csv_batches(client, path)

    def test_extra_fields_report_the_csv_line_before_upload(self):
        client = types.SimpleNamespace(upload_input=lambda *_args, **_options: self.fail("No batch should be uploaded"))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "records.csv"
            path.write_text("category,amount\nservices,1,extra\n", encoding="utf-8", newline="")
            with self.assertRaisesRegex(ValueError, "line 2.*more fields"):
                pipeline.upload_csv_batches(client, path)

    def test_bom_quoted_records_and_upload_resume(self):
        class Uploads:
            def __init__(self):
                self.payloads = []

            def upload_input(self, data, *, name):
                self.payloads.append(data)
                return {"object_id": "obj-" + f"{len(self.payloads):032x}", "name": name,
                        "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)}

        client = Uploads()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "records.csv"
            path.write_text('\ufeffcategory,amount\n"tools, cloud",1.5\n"two\nlines",2\nservices,3\n', encoding="utf-8", newline="")
            references, count = pipeline.upload_csv_batches(client, path, batch_rows=2)
            self.assertEqual(count, 3)
            self.assertEqual(len(references), 2)
            first = list(csv.DictReader(io.StringIO(client.payloads[0].decode())))
            self.assertEqual(first[0]["category"], "tools, cloud")
            self.assertEqual(first[1]["category"], "two\nlines")
            resumed, resumed_count = pipeline.upload_csv_batches(client, path, batch_rows=2, uploaded=references)
            self.assertEqual((resumed, resumed_count), (references, count))
            self.assertEqual(len(client.payloads), 2)


if __name__ == "__main__":
    unittest.main()
