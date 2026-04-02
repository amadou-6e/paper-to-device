"""Command-line interface for PDF border cropper."""

import logging
import sys
from typing import Callable

import click

from app_service import (
    ProcessingOptions,
    prepare_document,
    process_document,
    resolve_output_selection,
)

logger = logging.getLogger(__name__)


def _emit_status(echo: Callable[[str], None]) -> Callable[[str], None]:
    """Wrap Click's echo function into a status callback."""

    def callback(message: str) -> None:
        echo(f"[*] {message}")

    return callback


@click.group()
def cli():
    """PDF Border Cropper - Automatically crop white margins from academic papers."""
    pass


@cli.command()
@click.argument('input_pdf', type=click.Path(exists=True))
@click.option('--output-dir',
              type=click.Path(),
              default=None,
              help='Directory to save output files (default: same as input)')
@click.option(
    '--sensitivity',
    type=click.IntRange(0, 100),
    default=90,
    help=
    'Margin detection sensitivity (0=conservative, 100=aggressive) [default: 90]'
)
@click.option('--dpi',
              type=int,
              default=150,
              help='DPI for PDF to image conversion [default: 150]')
@click.option('--format',
              type=click.Choice(['pdf', 'epub', 'both']),
              default='both',
              help='Output format(s) [default: both]')
@click.option('--skip-epub',
              is_flag=True,
              help='Skip EPUB generation (faster)')
@click.option(
    '--reader-format',
    'reader_formats',
    multiple=True,
    type=click.Choice(['epub', 'cbz']),
    help=
    'Final e-reader output format. Repeat for multiple (e.g., --reader-format epub --reader-format cbz)'
)
@click.option(
    '--detector-mode',
    type=click.Choice(['network', 'hybrid', 'legacy', 'image']),
    default='network',
    help=
    'Detection strategy: network-only, hybrid fallback, legacy heuristics, or image-only pixel crop [default: network]'
)
@click.option(
    '--allow-fallback',
    is_flag=True,
    help=
    'When in network mode, allow fallback detectors instead of failing hard')
@click.option(
    '--docling-ocr/--no-docling-ocr',
    default=False,
    help=
    'Enable Docling OCR during layout detection (default: disabled for faster runs)'
)
@click.option(
    '--debug-layout-dir',
    type=click.Path(),
    default=None,
    help='Optional directory to save per-page layout overlay debug images')
@click.option(
    '--split-columns',
    is_flag=True,
    help='Detect dual-column pages and split each into two separate pages')
def crop(
    input_pdf: str,
    output_dir: str,
    sensitivity: int,
    dpi: int,
    format: str,
    skip_epub: bool,
    reader_formats: tuple[str, ...],
    detector_mode: str,
    allow_fallback: bool,
    docling_ocr: bool,
    debug_layout_dir: str,
    split_columns: bool,
):
    """
    Crop white borders from PDF pages and export e-reader files.
    
    Automatically detects and removes margins from each page individually,
    preserving formatting for academic papers and technical documents.
    
    Example:
        python cli.py crop paper.pdf --sensitivity 85
        python cli.py crop paper.pdf --output-dir ./output --format both
    """
    try:
        logger.info(f"Processing: {input_pdf}")
        logger.info(f"Sensitivity: {sensitivity}%")
        logger.info(f"DPI: {dpi}")
        logger.info(f"Detector mode: {detector_mode}")
        logger.info(f"Allow fallback: {'yes' if allow_fallback else 'no'}")
        logger.info(f"Docling OCR: {'on' if docling_ocr else 'off'}")
        if debug_layout_dir:
            logger.info(f"Debug layout dir: {debug_layout_dir}")
        if split_columns:
            logger.info("Split columns: on")

        prepared_document = prepare_document(
            input_pdf=input_pdf,
            options=ProcessingOptions(
                sensitivity=sensitivity,
                dpi=dpi,
                detector_mode=detector_mode,
                allow_fallback=allow_fallback,
                docling_ocr=docling_ocr,
                debug_layout_dir=debug_layout_dir,
                split_columns=split_columns,
            ),
            status_callback=_emit_status(click.echo),
        )

        outputs = resolve_output_selection(
            legacy_format=format,
            skip_epub=skip_epub,
            reader_formats=reader_formats,
        )

        result = process_document(
            prepared_document=prepared_document,
            outputs=outputs,
            output_dir=output_dir,
            status_callback=_emit_status(click.echo),
        )

        if result.pdf_path is not None:
            click.echo(f"[OK] Cropped PDF saved: {result.pdf_path}")

        for fmt_name, file_path in result.exported_reader_files.items():
            click.echo(f"[OK] {fmt_name.upper()} saved: {file_path}")

        click.echo("\n[SUCCESS] Done!")

    except FileNotFoundError as e:
        click.echo(f"[ERROR] {e}", err=True)
        sys.exit(1)
    except Exception as e:
        logger.exception("Unexpected error")
        click.echo(f"[ERROR] {e}", err=True)
        sys.exit(1)


if __name__ == '__main__':
    cli()
