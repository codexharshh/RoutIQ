import unittest
from datetime import datetime, timedelta, timezone
import csv
import tempfile
from pathlib import Path

from temporal_monitoring.evaluation import REQUIRED_COLUMNS, evaluate_rows, validate_csv


def labelled_pair(*, label="same_damage", offset=0.00001, confidence=0.9, accuracy=4):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    row = {
        "label": label,
        "damage_class_a": "pothole", "damage_class_b": "pothole",
        "latitude_a": "28.6139", "longitude_a": "77.2090",
        "latitude_b": "28.6139", "longitude_b": str(77.2090 + offset),
        "observed_at_a": now.isoformat(), "observed_at_b": (now + timedelta(days=1)).isoformat(),
        "confidence_a": str(confidence), "confidence_b": str(confidence),
        "gps_accuracy_m_a": str(accuracy), "gps_accuracy_m_b": str(accuracy),
        "image_width_a": "1280", "image_height_a": "720",
        "image_width_b": "1280", "image_height_b": "720",
    }
    assert set(row) == REQUIRED_COLUMNS
    return row


class TemporalEvaluationTests(unittest.TestCase):
    def test_quality_aware_evaluation_and_baseline_report_metrics(self):
        rows = [labelled_pair(), labelled_pair(label="different_damage", offset=0.001)]
        result = evaluate_rows(rows)
        self.assertEqual(result["quality_aware_rule"]["pairs"], 2)
        self.assertIn("candidate_match_precision", result["quality_aware_rule"])
        self.assertIn("false_match_rate", result["baseline_class_and_distance_only"])
        self.assertIn("high", result["quality_strata"])
        self.assertIn("not calibrated probabilities", result["interpretation"])

    def test_invalid_labels_and_missing_columns_are_rejected(self):
        row = labelled_pair(label="repaired")
        with self.assertRaisesRegex(ValueError, "label must be"):
            evaluate_rows([row])
        with self.assertRaisesRegex(ValueError, "missing required columns"):
            evaluate_rows([{"label": "same_damage"}])

    def test_low_quality_pair_abstains_instead_of_claiming_repair(self):
        result = evaluate_rows([labelled_pair(confidence=0.2, accuracy=80)])
        self.assertEqual(result["quality_aware_rule"]["abstention_rate"], 1.0)
        self.assertEqual(result["quality_aware_rule"]["coverage"], 0.0)

    def test_empty_dataset_reports_undefined_metrics_as_null(self):
        result = evaluate_rows([])
        metrics = result["quality_aware_rule"]
        self.assertEqual(metrics["pairs"], 0)
        for metric in ("candidate_match_precision", "candidate_match_recall", "false_match_rate",
                       "abstention_rate", "coverage", "error_rate_non_abstained"):
            self.assertIsNone(metrics[metric], metric)

    def test_perfect_and_imperfect_predictions_have_expected_metrics(self):
        close_positive = labelled_pair()
        far_negative = labelled_pair(label="different_damage", offset=0.01)
        perfect = evaluate_rows([close_positive, far_negative])["quality_aware_rule"]
        self.assertEqual(perfect["candidate_match_precision"], 1.0)
        self.assertEqual(perfect["candidate_match_recall"], 1.0)
        self.assertEqual(perfect["false_match_rate"], 0.0)
        self.assertEqual(perfect["error_rate_non_abstained"], 0.0)
        wrong = evaluate_rows([labelled_pair(label="different_damage")])["quality_aware_rule"]
        self.assertEqual(wrong["false_match_rate"], 1.0)
        self.assertEqual(wrong["error_rate_non_abstained"], 1.0)

    def test_missing_invalid_and_non_finite_values_are_rejected(self):
        for key, value in (("confidence_a", ""), ("confidence_b", "NaN"),
                           ("latitude_a", "91"), ("gps_accuracy_m_a", "-1"),
                           ("image_width_a", "0"), ("observed_at_a", "")):
            row = labelled_pair()
            row[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                evaluate_rows([row])

    def test_coordinate_and_image_pairs_can_be_absent_for_abstention(self):
        row = labelled_pair()
        for suffix in ("a", "b"):
            row[f"latitude_{suffix}"] = ""
            row[f"longitude_{suffix}"] = ""
            row[f"image_width_{suffix}"] = ""
            row[f"image_height_{suffix}"] = ""
        result = evaluate_rows([row])["quality_aware_rule"]
        self.assertEqual(result["abstention_rate"], 1.0)
        self.assertEqual(result["coverage"], 0.0)

    def test_undefined_denominator_metrics_remain_null(self):
        result = evaluate_rows([labelled_pair(label="same_damage", confidence=0.2, accuracy=80)])
        metrics = result["quality_aware_rule"]
        self.assertIsNone(metrics["candidate_match_precision"])
        self.assertIsNone(metrics["false_match_rate"])
        self.assertIsNone(metrics["error_rate_non_abstained"])

    def test_validation_only_checks_schema_and_values_without_metrics(self):
        row = labelled_pair()
        with tempfile.TemporaryDirectory(prefix="routiq-evaluation-test-") as directory:
            source = Path(directory) / "labelled.csv"
            with source.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=sorted(REQUIRED_COLUMNS))
                writer.writeheader()
                writer.writerow(row)
            result = validate_csv(source)
        self.assertTrue(result["valid"])
        self.assertEqual(result["rows"], 1)
        self.assertEqual(len(result["input_sha256"]), 64)
        self.assertNotIn("quality_aware_rule", result)

    def test_validation_only_rejects_rows_with_more_values_than_header(self):
        with tempfile.TemporaryDirectory(prefix="routiq-evaluation-test-") as directory:
            source = Path(directory) / "malformed.csv"
            source.write_text(",".join(sorted(REQUIRED_COLUMNS)) + "\n" + ",".join(["x"] * (len(REQUIRED_COLUMNS) + 1)), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "more values than the header"):
                validate_csv(source)


if __name__ == "__main__":
    unittest.main()
