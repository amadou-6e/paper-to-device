from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

from pypdf import PdfReader, PdfWriter

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from layout_detector import run_docling_layout


def iter_source_pdfs(extract_dir: Path,
                     excluded_names: set[str]) -> list[Path]:
    pdfs: list[Path] = []
    for path in sorted(extract_dir.glob("*.pdf")):
        if path.name in excluded_names:
            continue
        if path.name.startswith("react_probe_"):
            continue
        if "_firstpage_" in path.name or "_k2opt" in path.name or path.name.endswith(
                "_cropped.pdf"):
            continue
        if path.name.endswith("_probe.pdf"):
            continue
        pdfs.append(path)
    return pdfs


def build_first_page_docling_pdf(source_pdf: Path, output_pdf: Path,
                                 dpi: int) -> dict[str, int]:
    first_page_tmp = output_pdf.with_name(
        f"{source_pdf.stem}_firstpage_only_tmp.pdf")
    docling_input_path = first_page_tmp
    try:
        docling_input_path = first_page_tmp.relative_to(REPO_ROOT)
    except ValueError:
        pass

    reader = PdfReader(str(source_pdf))
    writer = PdfWriter()
    writer.add_page(reader.pages[0])
    with first_page_tmp.open("wb") as handle:
        writer.write(handle)

    margins = run_docling_layout(
        str(docling_input_path),
        dpi=dpi,
        disable_ocr=True,
        disable_table_structure=True,
    )
    first_page_tmp.unlink(missing_ok=True)

    if not margins or margins[0] is None:
        raise RuntimeError(
            f"Docling did not return a first-page margin for {source_pdf.name}"
        )

    margin = margins[0]
    points_per_pixel = 72.0 / dpi
    full_reader = PdfReader(str(source_pdf))
    out_writer = PdfWriter()
    for index, page in enumerate(full_reader.pages):
        if index == 0:
            left = margin["left"] * points_per_pixel
            top = margin["top"] * points_per_pixel
            right = margin["right"] * points_per_pixel
            bottom = margin["bottom"] * points_per_pixel
            original_height = float(page.mediabox.height)
            pdf_bottom = original_height - bottom
            pdf_top = original_height - top
            page.cropbox.lower_left = (left, pdf_bottom)
            page.cropbox.upper_right = (right, pdf_top)
        out_writer.add_page(page)

    with output_pdf.open("wb") as handle:
        out_writer.write(handle)

    return margin


def run_k2pdfopt(k2pdfopt_path: Path, input_pdf: Path, output_pdf: Path,
                 extra_args: list[str]) -> tuple[int, float]:
    digest = hashlib.sha1(str(output_pdf).encode("utf-8")).hexdigest()[:12]
    temp_output_pdf = output_pdf.parent / f"__k2tmp_{digest}.pdf"
    temp_output_pdf.unlink(missing_ok=True)

    command = [
        str(k2pdfopt_path),
        str(input_pdf),
        "-fc-",
        "-x",
        "-ui-",
        "-y",
        "-ow",
        *extra_args,
        "-o",
        str(temp_output_pdf),
    ]
    subprocess.run(command,
                   check=True,
                   stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)
    if not temp_output_pdf.exists():
        raise FileNotFoundError(f"k2pdfopt did not produce {temp_output_pdf}")
    temp_output_pdf.replace(output_pdf)
    page_count = len(PdfReader(str(output_pdf)).pages)
    size_mb = output_pdf.stat().st_size / (1024 * 1024)
    return page_count, size_mb


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--extract-dir",
                        type=Path,
                        default=REPO_ROOT / "extract")
    parser.add_argument("--k2pdfopt",
                        type=Path,
                        default=REPO_ROOT / "k2pdfopt.exe")
    parser.add_argument("--dpi", type=int, default=150)
    parser.add_argument("--exclude", action="append", default=None)
    parser.add_argument("--medium-odpi", type=int, default=220)
    parser.add_argument("--more-odpi", type=int, default=200)
    parser.add_argument(
        "--stretch",
        action="store_true",
        help="Enable k2pdfopt reflow stretch mode",
    )
    parser.add_argument(
        "--stretchr",
        type=float,
        default=1.15,
        help="Value passed to k2pdfopt -stretchr when --stretch is enabled",
    )
    parser.add_argument(
        "--stretchmax",
        type=float,
        default=1.35,
        help="Value passed to k2pdfopt -stretchmax when --stretch is enabled",
    )
    parser.add_argument(
        "--variant",
        action="append",
        choices=["baseline", "medium", "more"],
        default=None,
        help="Repeat to control which k2pdfopt variants are generated",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.stretch:
        if args.stretchr < 1.0:
            raise ValueError("--stretchr must be >= 1.0")
        if args.stretchmax < 1.0:
            raise ValueError("--stretchmax must be >= 1.0")

    stretch_args: list[str] = []
    if args.stretch:
        stretch_args = [
            "-stretch",
            "-stretchr",
            str(args.stretchr),
            "-stretchmax",
            str(args.stretchmax),
        ]

    excluded_names = set(args.exclude or [])
    excluded_names.add("2210.03629_ReAct.pdf")
    selected_variants = args.variant or ["baseline", "medium", "more"]
    source_pdfs = iter_source_pdfs(args.extract_dir, excluded_names)
    if not source_pdfs:
        print("No remaining source PDFs found.")
        return 0

    failures: list[str] = []
    print(f"Found {len(source_pdfs)} remaining source PDFs")
    for source_pdf in source_pdfs:
        try:
            print(f"=== {source_pdf.name} ===", flush=True)
            docling_pdf = args.extract_dir / f"{source_pdf.stem}_firstpage_docling_only.pdf"
            baseline_pdf = args.extract_dir / f"{source_pdf.stem}_firstpage_docling_only_k2opt.pdf"
            medium_pdf = args.extract_dir / f"{source_pdf.stem}_firstpage_docling_only_k2opt_smaller_medium.pdf"
            more_pdf = args.extract_dir / f"{source_pdf.stem}_firstpage_docling_only_k2opt_smaller_more.pdf"

            margin = build_first_page_docling_pdf(source_pdf,
                                                  docling_pdf,
                                                  dpi=args.dpi)
            print(f"  first-page margin: {margin}", flush=True)
            print(f"  wrote {docling_pdf.name}", flush=True)

            outputs = []
            if "baseline" in selected_variants:
                outputs.append((baseline_pdf, [*stretch_args]))
            if "medium" in selected_variants:
                outputs.append(
                    (medium_pdf,
                     [*stretch_args, "-odpi",
                      str(args.medium_odpi)]))
            if "more" in selected_variants:
                outputs.append(
                    (more_pdf, [*stretch_args, "-odpi",
                                str(args.more_odpi)]))

            for output_pdf, extra_args in outputs:
                label = "baseline" if not extra_args else " ".join(extra_args)
                print(f"  k2pdfopt -> {output_pdf.name} {label}", flush=True)
                page_count, size_mb = run_k2pdfopt(args.k2pdfopt, docling_pdf,
                                                   output_pdf, extra_args)
                print(f"    pages={page_count} size_mb={size_mb:.2f}",
                      flush=True)
        except Exception as exc:
            failures.append(f"{source_pdf.name}: {exc}")
            print(f"  FAILED: {exc}", flush=True)

    print("Batch complete.")
    if failures:
        print("Failures:")
        for failure in failures:
            print(f"  {failure}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
