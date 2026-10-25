import unittest

from temporal_monitoring.matching import haversine_distance_m


class HaversineDistanceTests(unittest.TestCase):
    def test_same_coordinate_has_zero_distance(self):
        self.assertAlmostEqual(haversine_distance_m(28.6139, 77.2090, 28.6139, 77.2090), 0.0)

    def test_one_degree_of_longitude_at_equator_is_about_111_km(self):
        distance = haversine_distance_m(0, 0, 0, 1)
        self.assertGreater(distance, 111_000)
        self.assertLess(distance, 111_300)

    def test_distance_is_symmetric(self):
        forward = haversine_distance_m(28.6139, 77.2090, 28.7041, 77.1025)
        reverse = haversine_distance_m(28.7041, 77.1025, 28.6139, 77.2090)
        self.assertAlmostEqual(forward, reverse, places=6)

    def test_invalid_latitudes_longitudes_and_non_finite_inputs_are_rejected(self):
        invalid_pairs = (
            (91, 0, 0, 0),
            (0, 181, 0, 0),
            (0, 0, -91, 0),
            (0, 0, 0, -181),
            (float("nan"), 0, 0, 0),
            (0, float("inf"), 0, 0),
        )
        for coordinates in invalid_pairs:
            with self.subTest(coordinates=coordinates), self.assertRaises(ValueError):
                haversine_distance_m(*coordinates)

    def test_numeric_strings_are_supported(self):
        self.assertAlmostEqual(haversine_distance_m("0", "0", "0", "1"), 111_195, delta=250)


if __name__ == "__main__":
    unittest.main()
