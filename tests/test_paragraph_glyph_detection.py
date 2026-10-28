import unittest

import fitz

from monitor_extraction_defects import paragraph_glyph_anomalies


class ParagraphGlyphTests(unittest.TestCase):
    def measure(self, size=12, font="helv"):
        with fitz.open() as document:
            page = document.new_page()
            page.insert_text((40, 100), "numerous common reasons concern everyone ", fontsize=12)
            page.insert_text((310, 100), "reason", fontsize=size, fontname=font)
            page.insert_text((40, 116), "more common reasons concern numerous consumers", fontsize=12)
            return paragraph_glyph_anomalies(page)

    def test_uniform_paragraph(self):
        self.assertEqual(self.measure(), [])

    def test_spectrum_includes_reference_sized_words(self):
        with fitz.open() as document:
            page = document.new_page()
            page.insert_text((40, 100), "numerous common reasons concern everyone", fontsize=12)
            findings = paragraph_glyph_anomalies(page, include_all=True)
            self.assertGreater(len(findings), 2)
            self.assertTrue(any(abs(f.measurement["ratio"] - 1) < 0.1 for f in findings))

    def test_bold_is_not_enlargement(self):
        self.assertEqual(self.measure(font="hebo"), [])

    def test_enlarged_inline_word(self):
        findings = self.measure(size=18)
        self.assertTrue(any(f.snippet == "reason" for f in findings))
        measured = next(f.measurement for f in findings if f.snippet == "reason")
        self.assertGreater(measured["ratio"], 1.25)
        self.assertEqual(measured["method"], "rendered-lowercase-x-height")

    def test_separate_heading(self):
        with fitz.open() as document:
            page = document.new_page()
            page.insert_text((40, 40), "numerous reasons", fontsize=24)
            page.insert_text((40, 100), "numerous common reasons concern everyone", fontsize=12)
            self.assertEqual(paragraph_glyph_anomalies(page), [])

    def test_shrunken_inline_word(self):
        findings = self.measure(size=8)
        measured = next(f.measurement for f in findings if f.snippet == "reason")
        self.assertLess(measured["ratio"], 0.8)

    def test_larger_entire_line_in_paragraph(self):
        with fitz.open() as document:
            page = document.new_page()
            page.insert_text((40, 100), "numerous common reasons concern everyone", fontsize=12)
            page.insert_text((40, 117), "more reasons", fontsize=18)
            page.insert_text((40, 134), "numerous common reasons concern everyone", fontsize=12)
            findings = paragraph_glyph_anomalies(page)
            self.assertTrue(any(f.snippet == "reasons" for f in findings))


if __name__ == "__main__":
    unittest.main()