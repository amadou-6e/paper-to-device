"""Tests for shared application service helpers."""

import tempfile
import unittest
from pathlib import Path

from app_service import build_output_paths, resolve_output_selection


class AppServiceTests(unittest.TestCase):
    def test_build_output_paths_defaults_to_input_directory(self):
        input_path = Path("C:/tmp/paper.pdf")

        paths = build_output_paths(input_path, output_dir=None)

        self.assertEqual(paths.output_dir, Path("C:/tmp"))
        self.assertEqual(paths.pdf_path.name, "paper_cropped.pdf")
        self.assertEqual(paths.reader_base_path.name, "paper")

    def test_build_output_paths_creates_custom_output_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "exports"
            input_path = Path(temp_dir) / "paper.pdf"

            paths = build_output_paths(input_path, output_dir=str(output_dir))

            self.assertTrue(output_dir.exists())
            self.assertEqual(paths.output_dir, output_dir)
            self.assertEqual(paths.pdf_path.parent, output_dir)

    def test_resolve_output_selection_handles_both_format(self):
        outputs = resolve_output_selection(
            legacy_format="both",
            skip_epub=False,
            reader_formats=(),
        )

        self.assertTrue(outputs.write_pdf)
        self.assertEqual(outputs.reader_formats, ("epub",))

    def test_resolve_output_selection_prefers_explicit_reader_formats(self):
        outputs = resolve_output_selection(
            legacy_format="pdf",
            skip_epub=False,
            reader_formats=("cbz", "epub", "cbz"),
        )

        self.assertTrue(outputs.write_pdf)
        self.assertEqual(outputs.reader_formats, ("cbz", "epub"))


if __name__ == "__main__":
    unittest.main()
