"""Export an annotated paragraph crop and its measured glyph-size findings."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path

import fitz

from monitor_extraction_defects import paragraph_glyph_anomalies


def spectrum_color(ratio):
    strength = min(1.0, abs(ratio - 1) / 0.5)
    target = (0.85, 0.08, 0.08) if ratio >= 1 else (0.05, 0.3, 0.95)
    return tuple(0.94 + (channel - 0.94) * strength for channel in target)


def export_spectrum(document, page, args):
    findings = paragraph_glyph_anomalies(page, include_all=True)
    for finding in findings:
        color = spectrum_color(finding.measurement["ratio"])
        page.draw_rect(fitz.Rect(finding.measurement["bbox"]),
                       color=None, fill=color, fill_opacity=0.32)
    with fitz.open() as preview:
        width = 900
        header_height = 130
        height = header_height + page.rect.height * (width - 30) / page.rect.width
        canvas = preview.new_page(width=width, height=height)
        canvas.insert_text((18, 24), f"{args.pdf.parent.name} | PDF page {args.page}", fontsize=15)
        canvas.insert_text((18, 46), "Rendered lowercase ink height relative to each paragraph candidate", fontsize=12)
        for index in range(120):
            ratio = 0.5 + index / 119
            canvas.draw_rect(fitz.Rect(20 + index * 5, 58, 25 + index * 5, 74),
                             color=None, fill=spectrum_color(ratio))
        for position, label in ((20, "0.50x smaller"), (285, "1.00x reference"), (550, "1.50x larger")):
            canvas.insert_text((position, 91), label, fontsize=11)
        canvas.insert_text((18, 112), "Uncolored: insufficient glyph evidence. Color is a measurement, not a confirmed defect.", fontsize=11)
        canvas.show_pdf_page(fitz.Rect(15, header_height, width - 15, height - 5),
                             document, args.page - 1)
        image = args.output / "paragraph_glyph_spectrum.png"
        canvas.get_pixmap(matrix=fitz.Matrix(1.5, 1.5)).save(image)
    report = {"pdf": str(args.pdf), "page": args.page,
              "color_scale": {"blue": 0.5, "neutral": 1.0, "red": 1.5},
              "measurements": [asdict(finding) for finding in findings]}
    (args.output / "paragraph_glyph_spectrum.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8")
    print(image)
    print(f"Measured words: {len(findings)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--page", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--spectrum", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with fitz.open(args.pdf) as document:
        page = document[args.page - 1]
        if args.spectrum:
            export_spectrum(document, page, args)
            return
        findings = paragraph_glyph_anomalies(page)
        if not findings:
            raise SystemExit("No paragraph glyph-size candidates on this page.")
        selected = max(findings, key=lambda finding: finding.measurement["ratio"])
        paragraph = selected.measurement["paragraph_bbox"]
        same_paragraph = [finding for finding in findings
                          if finding.measurement["paragraph_bbox"] == paragraph]
        page.draw_rect(fitz.Rect(paragraph), color=(0, 0.35, 0.8), width=0.5)
        for finding in same_paragraph:
            page.draw_rect(fitz.Rect(finding.measurement["bbox"]),
                           color=(0.85, 0.1, 0.1), width=0.65)
        clip = (fitz.Rect(paragraph) + (-3, -3, 3, 3)) & page.rect
        header_height = 100 + 16 * len(same_paragraph)
        with fitz.open() as preview:
            canvas = preview.new_page(width=800, height=header_height + clip.height * 3)
            canvas.insert_text((20, 24), f"PDF page {args.page} | rendered glyph-size candidates", fontsize=14)
            canvas.insert_text((20, 45), "Red: measured word outliers. Blue: PDF text-block paragraph candidate.", fontsize=11)
            canvas.insert_text((20, 63), "Ink-height measurement, not font-size metadata; candidates require visual review.", fontsize=11)
            for index, finding in enumerate(same_paragraph):
                canvas.insert_text((20, 85 + index * 16),
                                   f"{finding.snippet}: {finding.detail}", fontsize=11)
            canvas.show_pdf_page(fitz.Rect(15, header_height, 785, canvas.rect.height - 10),
                                 document, args.page - 1, clip=clip)
            image = args.output / "paragraph_glyph_showcase.png"
            canvas.get_pixmap(matrix=fitz.Matrix(1.5, 1.5)).save(image)
        report = {"pdf": str(args.pdf), "page": args.page,
                  "findings": [asdict(finding) for finding in same_paragraph]}
        (args.output / "paragraph_glyph_showcase.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8")
        print(image)
        for finding in same_paragraph:
            print(f"{finding.snippet}: {finding.detail}")


if __name__ == "__main__":
    main()