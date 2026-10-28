"""Detect likely extraction defects and export flagged pages as PNGs.

This script scans extracted PDFs in a run folder (tests/runs/<run_tag>) and:
1) flags pages with suspicious text/layout patterns,
2) captures problematic text snippets,
3) exports flagged pages to PNG for fast visual review,
4) writes JSON + Markdown reports.

Usage examples:
  python tests/monitor_extraction_defects.py
  python tests/monitor_extraction_defects.py --run-tag 2026-04-03
  python tests/monitor_extraction_defects.py --run-tag 2026-04-03 --dpi 190
    python tests/monitor_extraction_defects.py --run-tag 2026-04-03 --skip-first-pages 4
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import statistics
import subprocess
from dataclasses import asdict, dataclass
import math
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNS_ROOT = REPO_ROOT / "tests" / "runs"


@dataclass
class Finding:
    kind: str
    detail: str
    snippet: str
    measurement: dict | None = None


def paragraph_glyph_anomalies(page, threshold: float = 0.25,
                             include_all: bool = False) -> list[Finding]:
    """Measure visible x-height in PDF text-block paragraph candidates.

    Requires a usable character layer. At least twenty reference glyphs and
    three comparable lowercase glyphs per word are needed. Separate blocks,
    short phrases, uppercase-only text and page-crossing paragraphs are not
    inferred or joined. Bold weight alone is not treated as a size change.
    """
    import fitz

    raw = page.get_text("rawdict")
    scale = 4
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale),
                          colorspace=fitz.csGRAY, alpha=False)
    pixels = pix.samples
    findings: list[Finding] = []
    for block in raw.get("blocks", []):
        if block.get("type") != 0:
            continue
        words = []
        paragraph_text = []
        for line in block.get("lines", []):
            if tuple(line.get("dir", (1, 0))) != (1, 0):
                continue
            word_chars = []
            for span in line.get("spans", []):
                for char in span.get("chars", []):
                    if char["c"].isspace():
                        if word_chars:
                            words.append(word_chars)
                            word_chars = []
                    else:
                        word_chars.append(char)
            if word_chars:
                words.append(word_chars)
        samples = []
        for word in words:
            text = "".join(char["c"] for char in word)
            paragraph_text.append(text)
            heights = []
            for char in word:
                if char["c"] not in "acemnorsuvwxz":
                    continue
                left, top, right, bottom = char["bbox"]
                left = max(0, math.ceil(left * scale) - pix.x)
                right = min(pix.width, math.floor(right * scale) - pix.x)
                top = max(0, math.ceil(top * scale) - pix.y)
                bottom = min(pix.height, math.floor(bottom * scale) - pix.y)
                ink_rows = [row for row in range(top, bottom)
                            if any(value < 128 for value in
                                   pixels[row * pix.stride + left:
                                          row * pix.stride + right])]
                if ink_rows:
                    heights.append((ink_rows[-1] - ink_rows[0] + 1) / scale)
            if heights:
                samples.append((word, text, heights))
        all_heights = [height for _, _, heights in samples for height in heights]
        if len(all_heights) < 20:
            continue
        reference = statistics.median(all_heights)
        for word, text, heights in samples:
            if len(heights) < 3:
                continue
            measured = statistics.median(heights)
            ratio = measured / reference
            if not include_all and 1 / (1 + threshold) <= ratio <= 1 + threshold:
                continue
            bbox = [min(char["bbox"][0] for char in word),
                    min(char["bbox"][1] for char in word),
                    max(char["bbox"][2] for char in word),
                    max(char["bbox"][3] for char in word)]
            findings.append(Finding(
                kind="paragraph-glyph-size",
                detail=f"rendered x-height {measured:.2f}pt vs paragraph {reference:.2f}pt ({ratio:.2f}x)",
                snippet=text,
                measurement={
                    "method": "rendered-lowercase-x-height",
                    "paragraph_scope": "pdf-text-block-candidate",
                    "paragraph_text": " ".join(paragraph_text),
                    "paragraph_bbox": list(block["bbox"]),
                    "bbox": bbox,
                    "glyph_count": len(heights),
                    "reference_glyph_count": len(all_heights),
                    "height_pt": measured,
                    "reference_height_pt": reference,
                    "ratio": ratio,
                }))
    return findings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=
        "Monitor extraction defects and export flagged pages as PNGs")
    parser.add_argument(
        "--runs-root",
        type=Path,
        default=RUNS_ROOT,
        help="Root path for run folders (default: tests/runs)",
    )
    parser.add_argument(
        "--run-tag",
        default=None,
        help="Run tag under tests/runs. If omitted, newest run folder is used.",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=170,
        help="PNG export resolution (default: 170)",
    )
    parser.add_argument(
        "--max-pages-per-pdf",
        type=int,
        default=0,
        help="Optional cap of pages analyzed per PDF (0 = all pages).",
    )
    parser.add_argument(
        "--skip-first-pages",
        type=int,
        default=4,
        help="Skip this many leading pages in each PDF (default: 4)",
    )
    parser.add_argument(
        "--exclude-figures",
        dest="exclude_figures",
        action="store_true",
        default=True,
        help=
        "Exclude figure/table-like content from detection (default: enabled)",
    )
    parser.add_argument(
        "--include-figures",
        dest="exclude_figures",
        action="store_false",
        help="Disable figure exclusion and analyze all content",
    )
    parser.add_argument(
        "--include-baseline-extracted",
        action="store_true",
        help=
        "Include *_baseline_extracted.pdf files in scans (default: excluded)",
    )
    parser.add_argument(
        "--keep-old-pngs",
        action="store_true",
        help=
        "Keep existing PNGs in defect_review/png (default: clean before export)",
    )
    return parser.parse_args()


def newest_run_tag(runs_root: Path) -> str:
    candidates = [p for p in runs_root.iterdir() if p.is_dir()]
    if not candidates:
        raise FileNotFoundError(f"No run directories found under {runs_root}")
    newest = max(candidates, key=lambda p: p.stat().st_mtime)
    return newest.name


def extracted_pdfs(run_dir: Path,
                   include_baseline_extracted: bool) -> list[Path]:
    pdfs = sorted(run_dir.rglob("*_extracted.pdf"))
    if not include_baseline_extracted:
        pdfs = [
            p for p in pdfs if not p.name.endswith("_baseline_extracted.pdf")
        ]
    if not pdfs:
        raise FileNotFoundError(
            f"No *_extracted.pdf files found under {run_dir}")
    return pdfs


def page_text_via_pdftotext(pdf_path: Path, page_num: int) -> str:
    cmd = [
        "pdftotext",
        "-f",
        str(page_num),
        "-l",
        str(page_num),
        "-layout",
        str(pdf_path),
        "-",
    ]
    res = subprocess.run(cmd, check=False, capture_output=True, text=True)
    return res.stdout or ""


def is_figure_or_table_line(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    # Caption lines
    if re.match(r"^(figure|fig\.?|table)\s*\d+[:\.]?", s, flags=re.IGNORECASE):
        return True
    # Plot/axis/tick-ish lines
    if re.search(r"^[\d\s\.,\-\+%]+$", s):
        return True
    if re.search(r"\b(x-axis|y-axis|legend|accuracy|f1|auc)\b",
                 s,
                 flags=re.IGNORECASE):
        return True
    return False


def find_spacing_anomalies(text: str, exclude_figures: bool) -> list[Finding]:
    findings: list[Finding] = []
    lines = [ln.rstrip("\n") for ln in text.splitlines() if ln.strip()]

    for ln in lines:
        if exclude_figures and is_figure_or_table_line(ln):
            continue
        # Excessive intra-line gaps often signal bad justification/reflow.
        if re.search(r"\S {4,}\S", ln):
            findings.append(
                Finding(
                    kind="spacing",
                    detail="large intra-line gap",
                    snippet=ln.strip()[:220],
                ))

        # Bullet + awkward continuation can appear as compressed fragments.
        if re.search(r"^[\u2022\-\*]\s+\S+", ln):
            if len(ln.split()) <= 5:
                findings.append(
                    Finding(
                        kind="bullet",
                        detail=
                        "very short bullet line (possible wrap artifact)",
                        snippet=ln.strip()[:220],
                    ))

    return findings


def page_is_figure_heavy(page_dict: dict, page_area: float) -> bool:
    if page_area <= 0:
        return False
    image_area = 0.0
    text_chars = 0
    for block in page_dict.get("blocks", []):
        btype = block.get("type", 0)
        bbox = block.get("bbox") or [0, 0, 0, 0]
        if len(bbox) == 4:
            w = max(0.0, float(bbox[2]) - float(bbox[0]))
            h = max(0.0, float(bbox[3]) - float(bbox[1]))
            area = w * h
        else:
            area = 0.0
        if btype == 1:
            image_area += area
        elif btype == 0:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text_chars += len((span.get("text") or "").strip())
    image_ratio = image_area / page_area
    return image_ratio > 0.30 and text_chars < 500


def maybe_import_fitz():
    try:
        import fitz  # type: ignore

        return fitz
    except Exception:
        return None


def median_body_font_size(page_dict: dict) -> float | None:
    sizes: list[float] = []
    for block in page_dict.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                txt = (span.get("text") or "").strip()
                if len(txt) < 10:
                    continue
                alpha = sum(1 for ch in txt if ch.isalpha())
                if alpha < 6:
                    continue
                sz = float(span.get("size", 0.0))
                if 4.0 <= sz <= 40.0:
                    sizes.append(sz)
    if not sizes:
        return None
    return statistics.median(sizes)


def font_size_anomalies(page_dict: dict, median_size: float) -> list[Finding]:
    findings: list[Finding] = []
    upper = median_size * 1.40
    lower = median_size * 0.70

    for block in page_dict.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                txt = (span.get("text") or "").strip()
                if len(txt) < 12:
                    continue
                sz = float(span.get("size", 0.0))
                if sz > upper or sz < lower:
                    findings.append(
                        Finding(
                            kind="font-size",
                            detail=
                            f"span size {sz:.2f} vs median {median_size:.2f}",
                            snippet=txt[:220],
                        ))
    return findings


def page_count_via_pdfinfo(pdf_path: Path) -> int:
    cmd = ["pdfinfo", str(pdf_path)]
    res = subprocess.run(cmd, check=False, capture_output=True, text=True)
    m = re.search(r"^Pages:\s*(\d+)", res.stdout or "", flags=re.MULTILINE)
    if not m:
        return 0
    return int(m.group(1))


def export_page_png(pdf_path: Path, page_num: int, out_png: Path,
                    dpi: int) -> None:
    out_png.parent.mkdir(parents=True, exist_ok=True)
    prefix = out_png.with_suffix("")
    cmd = [
        "pdftoppm",
        "-f",
        str(page_num),
        "-l",
        str(page_num),
        "-singlefile",
        "-png",
        "-r",
        str(dpi),
        str(pdf_path),
        str(prefix),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def unique_findings(findings: Iterable[Finding]) -> list[Finding]:
    out: list[Finding] = []
    seen: set[tuple] = set()
    for f in findings:
        bbox = tuple(f.measurement["bbox"]) if f.measurement else ()
        key = (f.kind, f.detail, f.snippet, bbox)
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out


def analyze_pdf(pdf_path: Path, max_pages: int, skip_first_pages: int,
                exclude_figures: bool,
                use_fitz: bool) -> tuple[list[dict], int]:
    results: list[dict] = []
    skipped_figure_pages = 0
    n_pages = page_count_via_pdfinfo(pdf_path)
    if n_pages <= 0:
        return results, skipped_figure_pages

    page_limit = n_pages if max_pages <= 0 else min(n_pages, max_pages)

    fitz = maybe_import_fitz() if use_fitz else None
    doc = None
    if fitz is not None:
        try:
            doc = fitz.open(str(pdf_path))
        except Exception:
            doc = None

    start_page = max(1, skip_first_pages + 1)
    if start_page > page_limit:
        if doc is not None:
            doc.close()
        return results, skipped_figure_pages

    for page_num in range(start_page, page_limit + 1):
        findings: list[Finding] = []

        txt = page_text_via_pdftotext(pdf_path, page_num)
        findings.extend(find_spacing_anomalies(txt, exclude_figures))

        if doc is not None:
            try:
                page = doc[page_num - 1]
                p_dict = page.get_text("dict")
                if exclude_figures:
                    page_area = float(page.rect.width) * float(
                        page.rect.height)
                    if page_is_figure_heavy(p_dict, page_area):
                        skipped_figure_pages += 1
                        continue
                med = median_body_font_size(p_dict)
                if med is not None:
                    findings.extend(font_size_anomalies(p_dict, med))
                findings.extend(paragraph_glyph_anomalies(page))
            except Exception:
                pass

        findings = unique_findings(findings)
        if findings:
            results.append({
                "page":
                page_num,
                "findings": [{key: value for key, value in asdict(f).items()
                              if value is not None} for f in findings],
            })

    if doc is not None:
        doc.close()
    return results, skipped_figure_pages


def write_reports(report_dir: Path, run_tag: str, report: dict) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "defect_report.json"
    md_path = report_dir / "defect_report.md"

    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    lines = [
        f"# Defect Monitor Report ({run_tag})",
        "",
        f"Flagged PDFs: {report['summary']['pdfs_with_findings']} / {report['summary']['pdfs_scanned']}",
        f"Flagged pages: {report['summary']['flagged_pages']}",
        "",
    ]
    for pdf_item in report["pdfs"]:
        if not pdf_item["pages"]:
            continue
        lines.append(
            f"## {pdf_item['pdf']} ({len(pdf_item['pages'])} flagged pages)")
        for page_item in pdf_item["pages"]:
            kinds = ", ".join(
                sorted({f['kind']
                        for f in page_item['findings']}))
            lines.append(f"- Page {page_item['page']}: {kinds}")
            ordered = sorted(page_item["findings"],
                             key=lambda finding: finding["kind"] != "paragraph-glyph-size")
            for f in ordered[:3]:
                lines.append(f"  - {f['detail']} | `{f['snippet']}`")
                if f.get("measurement"):
                    lines.append(f"    - Word box (PDF points): {f['measurement']['bbox']}; scope: PDF text-block candidate")
        lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    runs_root = args.runs_root
    run_tag = args.run_tag or newest_run_tag(runs_root)
    run_dir = runs_root / run_tag
    if not run_dir.exists():
        raise FileNotFoundError(f"Run dir not found: {run_dir}")

    pdfs = extracted_pdfs(run_dir, args.include_baseline_extracted)
    review_dir = run_dir / "defect_review"
    png_dir = review_dir / "png"

    if not args.keep_old_pngs and png_dir.exists():
        shutil.rmtree(png_dir)

    all_items: list[dict] = []
    flagged_pages = 0
    skipped_figure_pages = 0

    print(f"Run tag: {run_tag}")
    print(f"Scanning {len(pdfs)} extracted PDFs...")

    for pdf in pdfs:
        rel_pdf = str(pdf.relative_to(run_dir)).replace("\\", "/")
        page_results, skipped_fig = analyze_pdf(pdf,
                                                args.max_pages_per_pdf,
                                                args.skip_first_pages,
                                                args.exclude_figures,
                                                use_fitz=True)
        skipped_figure_pages += skipped_fig

        for page_item in page_results:
            page_num = page_item["page"]
            out_png = png_dir / pdf.parent.name / f"{pdf.stem}_p{page_num:04d}.png"
            export_page_png(pdf, page_num, out_png, args.dpi)
            page_item["png"] = str(out_png.relative_to(run_dir)).replace(
                "\\", "/")

        flagged_pages += len(page_results)
        all_items.append({"pdf": rel_pdf, "pages": page_results})

    report = {
        "run_tag": run_tag,
        "summary": {
            "pdfs_scanned": len(pdfs),
            "pdfs_with_findings": sum(1 for i in all_items if i["pages"]),
            "flagged_pages": flagged_pages,
            "skipped_figure_pages": skipped_figure_pages,
        },
        "pdfs": all_items,
    }

    write_reports(review_dir, run_tag, report)

    print("Done.")
    print(f"Flagged pages: {flagged_pages}")
    print(f"Skipped first pages per PDF: {args.skip_first_pages}")
    print(f"Skipped figure-heavy pages: {skipped_figure_pages}")
    print(f"Exclude figures: {args.exclude_figures}")
    print(f"Include baseline extracted: {args.include_baseline_extracted}")
    print(f"Keep old PNGs: {args.keep_old_pngs}")
    print(
        f"Report: {(review_dir / 'defect_report.md').relative_to(REPO_ROOT)}")
    print(f"PNGs:   {png_dir.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
