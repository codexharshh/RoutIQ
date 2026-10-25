import unittest

from road_damage.preprocessing.image_preprocessing import (
    ALLOWED_IMAGE_EXTENSIONS,
    MAX_IMAGE_BYTES,
    validate_image_upload,
)


class ImagePreprocessingValidationTests(unittest.TestCase):
    def test_accepts_supported_extensions_case_insensitively(self):
        for extension in ALLOWED_IMAGE_EXTENSIONS:
            with self.subTest(extension=extension):
                self.assertTrue(validate_image_upload(f"road{extension.upper()}", 1))

    def test_rejects_unsupported_or_missing_extension(self):
        for filename in ("road.bmp", "road", "road.jpg.exe", "../road.gif"):
            with self.subTest(filename=filename), self.assertRaises(ValueError):
                validate_image_upload(filename, 100)

    def test_rejects_empty_or_over_limit_upload(self):
        for size in (0, -1, MAX_IMAGE_BYTES + 1):
            with self.subTest(size=size), self.assertRaises(ValueError):
                validate_image_upload("road.jpg", size)

    def test_accepts_size_boundaries(self):
        self.assertTrue(validate_image_upload("road.jpeg", 1))
        self.assertTrue(validate_image_upload("road.jpeg", MAX_IMAGE_BYTES))


if __name__ == "__main__":
    unittest.main()
