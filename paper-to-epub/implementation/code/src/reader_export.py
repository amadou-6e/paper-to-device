"""Final e-reader export helpers for cropped page images."""

import logging
from io import BytesIO
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image

try:
    from .column_splitter import split_image_columns
    from .epub_generator import crop_image_and_save, images_to_epub
except ImportError:
    # Support direct script execution where src/ is not treated as a package.
    from column_splitter import split_image_columns
    from epub_generator import crop_image_and_save, images_to_epub

logger = logging.getLogger(__name__)

SUPPORTED_READER_FORMATS: Tuple[str, ...] = ("epub", "cbz")


def resolve_reader_formats(
    legacy_format: str,
    skip_epub: bool,
    reader_formats: Sequence[str],
) -> List[str]:
    """Resolve requested reader formats from legacy and explicit CLI options."""
    if reader_formats:
        normalized = [fmt.lower() for fmt in reader_formats]
    elif legacy_format in ("epub", "both") and not skip_epub:
        normalized = ["epub"]
    else:
        normalized = []

    if skip_epub:
        normalized = [fmt for fmt in normalized if fmt != "epub"]

    ordered: List[str] = []
    for fmt in normalized:
        if fmt not in SUPPORTED_READER_FORMATS:
            raise ValueError(
                f"Unsupported reader format: {fmt}. "
                f"Supported: {', '.join(SUPPORTED_READER_FORMATS)}"
            )
        if fmt not in ordered:
            ordered.append(fmt)

    return ordered


def build_cropped_images(
    images: Sequence[Image.Image],
    margins_list: Sequence[dict],
    split_columns: bool,
    gutter_list: Optional[Sequence[Optional[int]]],
) -> List[Image.Image]:
    """Build cropped page images and optionally split dual-column pages."""
    cropped_images: List[Image.Image] = []

    for i, (image, margin) in enumerate(zip(images, margins_list)):
        cropped = crop_image_and_save(image, margin)
        if split_columns and gutter_list and gutter_list[i] is not None:
            left_col, right_col = split_image_columns(cropped, gutter_list[i])
            cropped_images.extend([left_col, right_col])
        else:
            cropped_images.append(cropped)

    return cropped_images


def images_to_cbz(images: Iterable[Image.Image], output_path: str) -> None:
    """Write images to a CBZ archive.

    CBZ is widely supported by e-reader apps and tablet reading software.
    """
    with ZipFile(output_path, "w", compression=ZIP_DEFLATED) as archive:
        for i, image in enumerate(images):
            img_bytes = BytesIO()
            image.save(img_bytes, format="PNG")
            archive.writestr(f"page_{i:04d}.png", img_bytes.getvalue())

    logger.info("Saved CBZ: %s", output_path)


def export_reader_formats(
    images: Sequence[Image.Image],
    source_filename: str,
    output_base_path: Path,
    formats: Sequence[str],
) -> Dict[str, Path]:
    """Export final reader files from cropped page images.

    Args:
        images: Cropped page images.
        source_filename: Original input filename for metadata.
        output_base_path: Output path without extension.
        formats: Sequence of target formats (epub, cbz).

    Returns:
        Map of format name to output file path.
    """
    exported: Dict[str, Path] = {}

    for fmt in formats:
        fmt_lower = fmt.lower()
        if fmt_lower not in SUPPORTED_READER_FORMATS:
            raise ValueError(
                f"Unsupported reader format: {fmt_lower}. "
                f"Supported: {', '.join(SUPPORTED_READER_FORMATS)}"
            )

        output_file = output_base_path.with_suffix(f".{fmt_lower}")

        if fmt_lower == "epub":
            images_to_epub(list(images), source_filename, str(output_file))
        elif fmt_lower == "cbz":
            images_to_cbz(images, str(output_file))

        exported[fmt_lower] = output_file

    return exported
