import unittest

from road_damage.class_mapping import (
    UnknownDamageClassError,
    build_class_registry,
    normalize_label,
)


class ClassMappingTests(unittest.TestCase):
    def test_normalizes_canonical_labels_and_spacing(self):
        self.assertEqual(normalize_label(" Potholes "), "pothole")
        self.assertEqual(normalize_label("LONGITUDINAL-crack"), "longitudinal_crack")
        self.assertEqual(normalize_label("alligator   crack"), "alligator_crack")

    def test_supports_road_damage_dataset_class_codes(self):
        expected = {
            0: "longitudinal_crack",
            1: "transverse_crack",
            2: "alligator_crack",
            3: "pothole",
        }
        self.assertEqual(build_class_registry({0: "D00", 1: "D10", 2: "D20", 3: "D40"}), expected)
        self.assertEqual(normalize_label("D40 pothole"), "pothole")

    def test_builds_registry_from_sequence(self):
        self.assertEqual(
            build_class_registry(["D00", "D10", "D20", "D40"]),
            {0: "longitudinal_crack", 1: "transverse_crack", 2: "alligator_crack", 3: "pothole"},
        )

    def test_rejects_empty_or_unknown_labels(self):
        for label in ("", "  ", "road debris", None):
            with self.subTest(label=label), self.assertRaises(UnknownDamageClassError):
                normalize_label(label)

    def test_rejects_negative_or_empty_registry(self):
        with self.assertRaisesRegex(ValueError, "non-negative"):
            build_class_registry({-1: "pothole"})
        with self.assertRaisesRegex(ValueError, "no class names"):
            build_class_registry([])


if __name__ == "__main__":
    unittest.main()
