"""Shared application service for CLI and desktop UI workflows."""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Sequence

from PIL import Image

from column_splitter import detect_gutters_for_pages
from config import CROPPED_PDF_SUFFIX, DEFAULT_DPI, DEFAULT_SENSITIVITY, EPUB_SUFFIX
from pdf_processor import PDFProcessor
from reader_export import build_cropped_images, export_reader_formats


StatusCallback = Optional[Callable[[str], None]]


@dataclass(frozen=True)
class ProcessingOptions:
    """Runtime options for preparing previews and exporting files."""

    sensitivity: int = DEFAULT_SENSITIVITY
    dpi: int = DEFAULT_DPI
    detector_mode: str = "network"
    allow_fallback: bool = False
    docling_ocr: bool = False
    debug_layout_dir: Optional[str] = None
    split_columns: bool = False


@dataclass(frozen=True)
class OutputSelection:
    """Output types requested by the caller."""

    write_pdf: bool = True
    reader_formats: tuple[str, ...] = ()


@dataclass(frozen=True)
class OutputPaths:
    """Resolved output locations for a processed document."""

    output_dir: Path
    pdf_path: Path
    reader_base_path: Path


@dataclass
class PreparedDocument:
    """In-memory processing state used for preview and export."""

    input_path: Path
    processor: PDFProcessor
    options: ProcessingOptions
    margins_list: List[dict]
    original_images: List[Image.Image]
    preview_images: List[Image.Image]
    gutter_list: Optional[List[Optional[int]]]

    @property
    def page_count(self) -> int:
        """Return the number of preview pages available."""
        return len(self.preview_images)


@dataclass(frozen=True)
class ProcessingResult:
    """Paths created by a completed processing run."""

    pdf_path: Optional[Path]
    exported_reader_files: dict[str, Path]


def build_output_paths(input_path: Path, output_dir: Optional[str]) -> OutputPaths:
    """Resolve output paths from the input file and optional directory."""
    if output_dir:
        base_dir = Path(output_dir)
        base_dir.mkdir(parents=True, exist_ok=True)
    else:
        base_dir = input_path.parent

    stem = input_path.stem
    return OutputPaths(
        output_dir=base_dir,
        pdf_path=base_dir / f"{stem}{CROPPED_PDF_SUFFIX}.pdf",
        reader_base_path=base_dir / f"{stem}{EPUB_SUFFIX}",
    )


def resolve_output_selection(
    legacy_format: str,
    skip_epub: bool,
    reader_formats: Sequence[str],
) -> OutputSelection:
    """Normalize output requests from legacy CLI flags and explicit formats."""
    normalized_reader_formats = tuple(dict.fromkeys(fmt.lower() for fmt in reader_formats))
    if normalized_reader_formats:
        return OutputSelection(write_pdf=legacy_format in ("pdf", "both"), reader_formats=normalized_reader_formats)

    if skip_epub:
        return OutputSelection(write_pdf=legacy_format in ("pdf", "both"), reader_formats=())

    if legacy_format == "epub":
        return OutputSelection(write_pdf=False, reader_formats=("epub",))
    if legacy_format == "both":
        return OutputSelection(write_pdf=True, reader_formats=("epub",))
    return OutputSelection(write_pdf=True, reader_formats=())


def prepare_document(
    input_pdf: str,
    options: ProcessingOptions,
    status_callback: StatusCallback = None,
) -> PreparedDocument:
    """Load a PDF, detect margins, and build preview-ready images."""
    input_path = Path(input_pdf)
    processor = PDFProcessor(str(input_path))

    if status_callback:
        status_callback("Detecting margins on all pages...")

    margins_list, images = processor.detect_margins_for_all_pages(
        sensitivity=options.sensitivity,
        dpi=options.dpi,
        detector_mode=options.detector_mode,
        allow_fallback=options.allow_fallback,
        docling_ocr=options.docling_ocr,
        debug_layout_dir=options.debug_layout_dir,
        status_callback=status_callback,
    )

    gutter_list: Optional[List[Optional[int]]] = None
    if options.split_columns:
        if status_callback:
            status_callback("Detecting dual-column pages...")
        gutter_list = detect_gutters_for_pages(images, margins_list)

    preview_images = build_cropped_images(
        images=images,
        margins_list=margins_list,
        split_columns=options.split_columns,
        gutter_list=gutter_list,
    )

    return PreparedDocument(
        input_path=input_path,
        processor=processor,
        options=options,
        margins_list=margins_list,
        original_images=images,
        preview_images=preview_images,
        gutter_list=gutter_list,
    )


def process_document(
    prepared_document: PreparedDocument,
    outputs: OutputSelection,
    output_dir: Optional[str],
    status_callback: StatusCallback = None,
) -> ProcessingResult:
    """Write requested outputs using a prepared document state."""
    paths = build_output_paths(prepared_document.input_path, output_dir)

    pdf_path: Optional[Path] = None
    if outputs.write_pdf:
        if status_callback:
            status_callback("Writing cropped PDF...")
        if prepared_document.options.split_columns and prepared_document.gutter_list:
            prepared_document.processor.crop_and_split_pdf(
                prepared_document.margins_list,
                prepared_document.gutter_list,
                str(paths.pdf_path),
                dpi=prepared_document.options.dpi,
                status_callback=status_callback,
            )
        else:
            prepared_document.processor.crop_pdf(
                prepared_document.margins_list,
                str(paths.pdf_path),
                dpi=prepared_document.options.dpi,
                status_callback=status_callback,
            )
        pdf_path = paths.pdf_path

    exported_reader_files: dict[str, Path] = {}
    if outputs.reader_formats:
        if status_callback:
            status_callback(f"Generating reader output(s): {', '.join(outputs.reader_formats)}...")
        exported_reader_files = export_reader_formats(
            images=prepared_document.preview_images,
            source_filename=prepared_document.input_path.name,
            output_base_path=paths.reader_base_path,
            formats=outputs.reader_formats,
        )

    return ProcessingResult(pdf_path=pdf_path, exported_reader_files=exported_reader_files)
