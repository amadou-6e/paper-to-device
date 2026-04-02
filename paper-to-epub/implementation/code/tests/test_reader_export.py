"""Tests for final reader export helpers."""

import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from PIL import Image

from src.reader_export import (
    export_reader_formats,
    images_to_cbz,
    resolve_reader_formats,
)


class ReaderExportTests(unittest.TestCase):
    def test_resolve_reader_formats_legacy_defaults_to_epub(self):
        formats = resolve_reader_formats(
            legacy_format="both",
            skip_epub=False,
            reader_formats=(),
        )
        self.assertEqual(formats, ["epub"])

    def test_resolve_reader_formats_explicit_supports_multiple(self):
        formats = resolve_reader_formats(
            legacy_format="pdf",
            skip_epub=False,
            reader_formats=("cbz", "epub", "cbz"),
        )
        self.assertEqual(formats, ["cbz", "epub"])

    def test_skip_epub_removes_epub_even_when_explicit(self):
        formats = resolve_reader_formats(
            legacy_format="both",
            skip_epub=True,
            reader_formats=("epub", "cbz"),
        )
        self.assertEqual(formats, ["cbz"])

    def test_images_to_cbz_creates_expected_pages(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "paper.cbz"
            images = [
                Image.new("RGB", (40, 60), color=(255, 255, 255)),
                Image.new("RGB", (40, 60), color=(200, 200, 200)),
            ]

            images_to_cbz(images, str(output_path))

            self.assertTrue(output_path.exists())
            with ZipFile(output_path, "r") as archive:
                names = sorted(archive.namelist())
                self.assertEqual(names, ["page_0000.png", "page_0001.png"])

    def test_export_reader_formats_writes_epub(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_base = Path(temp_dir) / "paper"
            images = [Image.new("RGB", (40, 60), color=(255, 255, 255))]

            exported = export_reader_formats(
                images=images,
                source_filename="paper.pdf",
                output_base_path=output_base,
                formats=("epub",),
            )

            self.assertIn("epub", exported)
            self.assertTrue(exported["epub"].exists())
            self.assertGreater(exported["epub"].stat().st_size, 0)

if __name__ == "__main__":
    unittest.main()
