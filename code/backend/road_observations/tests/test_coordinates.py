import unittest
from io import BytesIO
from types import SimpleNamespace

from PIL import Image
from road_observations.coordinates import extract_photo_gps, parse_coordinate_pair


class CoordinateValidationTests(unittest.TestCase):
    def test_finite_boundary_coordinates_are_accepted(self):
        latitude, longitude = parse_coordinate_pair("90", "-180")
        self.assertEqual(str(latitude), "90")
        self.assertEqual(str(longitude), "-180")

    def test_missing_non_finite_and_out_of_range_coordinates_are_rejected(self):
        for pair in ((None, 10), ("NaN", 10), (91, 10), (10, 181)):
            with self.subTest(pair=pair), self.assertRaises(ValueError):
                parse_coordinate_pair(*pair)

    def test_photo_gps_metadata_is_converted_with_hemispheres_and_accuracy(self):
        gps_info = {
            1: "S", 2: (28, 36, 50),
            3: "W", 4: (77, 12, 30),
            31: 4.5,
        }

        class Exif:
            def get_ifd(self, tag):
                self.assert_tag = tag
                return gps_info

        image = SimpleNamespace(getexif=lambda: Exif())
        result = extract_photo_gps(image)
        self.assertAlmostEqual(float(result[0]), -(28 + 36 / 60 + 50 / 3600))
        self.assertAlmostEqual(float(result[1]), -(77 + 12 / 60 + 30 / 3600))
        self.assertEqual(result[2], 4.5)

    def test_absent_or_malformed_photo_gps_is_not_reported(self):
        class Exif:
            def get_ifd(self, tag):
                return {}

        self.assertIsNone(extract_photo_gps(SimpleNamespace(getexif=lambda: Exif())))

    def _jpeg_with_gps(self, *, latitude_ref="N", latitude=(28, 36, 50), longitude_ref="E", longitude=(77, 12, 30), accuracy=4.5):
        exif = Image.Exif()
        exif[34853] = {
            1: latitude_ref, 2: latitude, 3: longitude_ref, 4: longitude, 31: accuracy,
        }
        output = BytesIO()
        Image.new("RGB", (12, 8), "white").save(output, format="JPEG", exif=exif)
        output.seek(0)
        return Image.open(output)

    def test_serialized_jpeg_exif_gps_supports_hemispheres_and_decimal_conversion(self):
        cases = (
            ("N", "E", 1, 1), ("S", "E", -1, 1),
            ("N", "W", 1, -1), ("S", "W", -1, -1),
        )
        expected_latitude = 28 + 36 / 60 + 50 / 3600
        expected_longitude = 77 + 12 / 60 + 30 / 3600
        for latitude_ref, longitude_ref, latitude_sign, longitude_sign in cases:
            with self.subTest(latitude_ref=latitude_ref, longitude_ref=longitude_ref):
                with self._jpeg_with_gps(latitude_ref=latitude_ref, longitude_ref=longitude_ref) as image:
                    result = extract_photo_gps(image)
                self.assertAlmostEqual(float(result[0]), latitude_sign * expected_latitude)
                self.assertAlmostEqual(float(result[1]), longitude_sign * expected_longitude)
                self.assertEqual(result[2], 4.5)

    def test_serialized_jpeg_missing_and_malformed_gps_are_rejected(self):
        with BytesIO() as output:
            Image.new("RGB", (8, 8), "white").save(output, format="JPEG")
            output.seek(0)
            with Image.open(output) as image:
                self.assertIsNone(extract_photo_gps(image))
        with self._jpeg_with_gps(latitude_ref="Q") as image:
            self.assertIsNone(extract_photo_gps(image))
        with self._jpeg_with_gps(latitude=(91, 0, 0)) as image:
            self.assertIsNone(extract_photo_gps(image))

    def test_serialized_jpeg_coordinate_bounds_include_poles_and_dateline(self):
        with self._jpeg_with_gps(latitude=(90, 0, 0), longitude=(180, 0, 0)) as image:
            result = extract_photo_gps(image)
        self.assertEqual(float(result[0]), 90.0)
        self.assertEqual(float(result[1]), 180.0)


if __name__ == "__main__":
    unittest.main()
