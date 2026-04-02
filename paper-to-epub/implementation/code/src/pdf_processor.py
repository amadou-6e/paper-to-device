"""PDF processing and manipulation utilities."""

import logging
from pathlib import Path
from typing import Callable, List, Optional, Tuple
from pypdf import PdfReader, PdfWriter
import fitz  # PyMuPDF
from PIL import Image
from io import BytesIO
import numpy as np
from config import DEFAULT_DPI
from margin_detector import detect_page_margins
from layout_detector import run_docling_layout
from column_splitter import split_image_columns

logger = logging.getLogger(__name__)


class PDFProcessor:
    """Handles PDF reading, page extraction, and writing."""

    def __init__(self, pdf_path: str):
        """
        Initialize PDF processor.
        
        Args:
            pdf_path: Path to the PDF file
        """
        self.pdf_path = Path(pdf_path)
        if not self.pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        self.reader = PdfReader(self.pdf_path)
        self.num_pages = len(self.reader.pages)
        logger.info(
            f"Loaded PDF: {self.pdf_path.name} ({self.num_pages} pages)")

    def convert_pages_to_images(self,
                                dpi: int = DEFAULT_DPI) -> List[Image.Image]:
        """
        Convert all PDF pages to PIL Images using PyMuPDF.
        
        Args:
            dpi: Resolution for conversion (higher = better quality, slower)
        
        Returns:
            List of PIL Images
        """
        logger.info(f"Converting PDF to images at {dpi} DPI...")
        images = []

        # PyMuPDF uses zoom factor to control resolution
        # Default is 72 DPI, so zoom = dpi / 72
        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)

        doc = fitz.open(str(self.pdf_path))
        for page_num in range(len(doc)):
            page = doc[page_num]
            pix = page.get_pixmap(matrix=mat)

            # Convert RGBA to RGB if needed
            if pix.n - pix.alpha < 3:  # GRAY or GA
                rgb_pix = fitz.Pixmap(fitz.csRGB, pix)
                image = Image.frombytes("RGB", [rgb_pix.width, rgb_pix.height],
                                        rgb_pix.samples)
            else:
                image = Image.frombytes("RGB", [pix.width, pix.height],
                                        pix.samples)

            images.append(image)

        doc.close()
        logger.info(f"Converted {len(images)} pages")
        return images

    def get_page_dimensions(self, page_index: int) -> Tuple[float, float]:
        """
        Get original page dimensions in points.
        
        Args:
            page_index: Index of the page
        
        Returns:
            Tuple of (width, height) in points
        """
        page = self.reader.pages[page_index]
        mediabox = page.mediabox
        width = float(mediabox.width)
        height = float(mediabox.height)
        return (width, height)

    def _detect_margins_text_based(self, fitz_page, img_width: int,
                                   img_height: int,
                                   dpi: int) -> Optional[dict]:
        """
        Detect margins using the PDF text layer — more accurate than pixel analysis.

        Extracts all text block positions and finds the bounding box of the main
        content, intelligently skipping narrow margin annotations (arXiv watermarks,
        running headers, page number sidebars) by detecting large spatial gaps
        between the annotation and the main content column.

        Returns None if text extraction yields no usable data (e.g. scanned PDFs),
        signalling that the caller should fall back to image-based detection.
        """
        blocks = fitz_page.get_text(
            "blocks")  # (x0,y0,x1,y1,text,block_no,block_type)
        text_blocks = [(x0, y0, x1, y1)
                       for x0, y0, x1, y1, text, _, btype in blocks
                       if btype == 0 and text.strip()]

        if not text_blocks:
            return None

        page_width_pts = fitz_page.rect.width
        page_height_pts = fitz_page.rect.height
        scale = dpi / 72.0

        # --- Left boundary: gap-based outlier detection ---
        # Sort all block left-edges. If the smallest x0 is far from the rest
        # (the gap is the arXiv watermark / sidebar), skip past the gap.
        x0s = sorted(b[0] for b in text_blocks)
        GAP_THRESHOLD_PT = max(20.0, page_width_pts * 0.05)  # 5% of page width
        left_pts = x0s[0]
        for i in range(1, len(x0s)):
            if x0s[i] - x0s[i - 1] >= GAP_THRESHOLD_PT:
                # Everything before this gap is a margin annotation
                left_pts = x0s[i]
                break

        # --- Right boundary: widest reachable text, excluding margin gaps ---
        x1s = sorted((b[2] for b in text_blocks), reverse=True)
        right_pts = x1s[0]
        for i in range(1, len(x1s)):
            if x1s[i - 1] - x1s[i] >= GAP_THRESHOLD_PT:
                right_pts = x1s[i - 1]
                break

        # --- Top / Bottom: simple bounding box (headers/footers are readable content) ---
        top_pts = min(b[1] for b in text_blocks)
        bottom_pts = max(b[3] for b in text_blocks)

        # Convert points → pixels, add small padding
        PADDING_PX = 5
        left_px = max(0, int(left_pts * scale) - PADDING_PX)
        top_px = max(0, int(top_pts * scale) - PADDING_PX)
        right_px = min(img_width, int(right_pts * scale) + PADDING_PX)
        bottom_px = min(img_height, int(bottom_pts * scale) + PADDING_PX)

        if right_px - left_px < 10 or bottom_px - top_px < 10:
            return None  # Something went wrong, fall back

        logger.debug(
            f"Text-based margins (pts): L={left_pts:.1f} T={top_pts:.1f} "
            f"R={right_pts:.1f} B={bottom_pts:.1f}")
        return {
            "left": left_px,
            "top": top_px,
            "right": right_px,
            "bottom": bottom_px
        }

    def detect_margins_for_all_pages(
        self,
        sensitivity: int = 90,
        dpi: int = DEFAULT_DPI,
        detector_mode: str = "network",
        allow_fallback: bool = False,
        docling_ocr: bool = False,
        debug_layout_dir: Optional[str] = None,
        status_callback: Optional[Callable[[str], None]] = None,
    ) -> Tuple[List[dict], List[Image.Image]]:
        """
        Detect margins for all pages.

        In 'network' mode (default): runs Docling's layout analysis network on
        the entire PDF first, then converts per-page cluster bounding boxes to
        pixel crop margins.  Falls back to text/image detectors only when
        allow_fallback=True or detector_mode != 'network'.

        Args:
            sensitivity: Detection sensitivity (0-100) used for image fallback only
            dpi: DPI for image conversion
            detector_mode: 'network' (default), 'hybrid', or 'legacy'
            allow_fallback: When in network mode, fall back instead of raising
            docling_ocr: Enable Docling OCR (off by default for faster layout-only runs)
            debug_layout_dir: Optional directory to export Docling cluster overlays

        Returns:
            Tuple of (margins list, images list)
        """
        images = self.convert_pages_to_images(dpi=dpi)

        # --- Docling layout pass (once for the whole PDF) ---
        docling_margins: list = [None] * len(images)
        if detector_mode in ("network", "hybrid"):
            logger.info("Running Docling layout network on full PDF...")
            result = run_docling_layout(
                str(self.pdf_path),
                dpi=dpi,
                debug_output_dir=debug_layout_dir,
                disable_ocr=not docling_ocr,
                disable_table_structure=True,
            )
            if result is not None:
                # result is indexed 0..N-1 matching page order
                for i, m in enumerate(result):
                    if i < len(docling_margins):
                        docling_margins[i] = m
            else:
                logger.warning("Docling returned no results for this PDF.")

        margins = []
        doc = fitz.open(str(self.pdf_path))

        logger.info(f"Finalising per-page margins (mode={detector_mode})...")
        total_pages = len(images)
        for i, image in enumerate(images):
            if status_callback:
                status_callback(
                    f"Detecting margins: page {i + 1}/{total_pages}")
            fitz_page = doc[i]
            img_w, img_h = image.size
            margin = docling_margins[i] if i < len(docling_margins) else None
            detection_source = "docling-network" if margin else ""

            if margin is None and detector_mode in ("hybrid", "legacy"):
                margin = self._detect_margins_text_based(
                    fitz_page, img_w, img_h, dpi)
                if margin:
                    detection_source = "text-based"

            if margin is None and detector_mode == "image":
                pass  # handled below unconditionally

            if margin:
                logger.info(f"Page {i + 1}/{len(images)}: {detection_source}")
            else:
                if detector_mode == "network" and not allow_fallback:
                    raise RuntimeError(
                        f"Docling network detection returned nothing for page {i + 1}. "
                        "Re-run with --detector-mode hybrid or --allow-fallback."
                    )
                logger.info(f"Page {i + 1}/{len(images)}: image-based")
                margin = detect_page_margins(image, sensitivity)

            margins.append(margin)

        doc.close()
        return margins, images

    def crop_pdf(
        self,
        margins_list: List[dict],
        output_path: str,
        dpi: int = DEFAULT_DPI,
        status_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        """
        Create a cropped version of the PDF based on detected margins.
        
        Args:
            margins_list: List of margin dictionaries (one per page)
            output_path: Path to save cropped PDF
            dpi: DPI used for margin detection (needed for coordinate conversion)
        
        Returns:
            None
        """
        writer = PdfWriter()

        # Points per pixel at given DPI
        # 72 points = 1 inch, DPI pixels = 1 inch
        points_per_pixel = 72.0 / dpi

        logger.info("Cropping PDF pages...")
        total_pages = len(self.reader.pages)
        for page_index, page in enumerate(self.reader.pages):
            if status_callback:
                status_callback(
                    f"Writing PDF: page {page_index + 1}/{total_pages}")
            if page_index < len(margins_list):
                margin = margins_list[page_index]

                # Convert pixel margins to PDF points
                left = margin['left'] * points_per_pixel
                top = margin['top'] * points_per_pixel
                right = margin['right'] * points_per_pixel
                bottom = margin['bottom'] * points_per_pixel

                # Get original page height
                original_height = float(page.mediabox.height)

                # PDF coordinates: bottom-left is origin, top is higher Y
                # Image coordinates: top-left is origin, bottom is higher Y
                # Convert: PDF top = original_height - image_top
                pdf_bottom = original_height - bottom
                pdf_top = original_height - top

                # Create crop box (left, bottom, right, top in PDF coordinates)
                page.cropbox.lower_left = (left, pdf_bottom)
                page.cropbox.upper_right = (right, pdf_top)

                logger.debug(
                    f"Page {page_index + 1}: crop box = ({left:.1f}, {pdf_bottom:.1f}, {right:.1f}, {pdf_top:.1f})"
                )

            writer.add_page(page)

        # Write output
        with open(output_path, 'wb') as f:
            writer.write(f)

        logger.info(f"Saved cropped PDF: {output_path}")

    def crop_and_split_pdf(
        self,
        margins_list: List[dict],
        gutter_list: List[Optional[int]],
        output_path: str,
        dpi: int = DEFAULT_DPI,
        status_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        """Write a PDF where dual-column pages are each split into two pages.

        For pages with a detected column gutter, two output pages are written
        (left column, then right column).  Other pages are written normally.

        Args:
            margins_list: Per-page margin dicts from detect_margins_for_all_pages.
            gutter_list:  Per-page gutter x positions (image-space) or None.
            output_path:  Destination path for the output PDF.
            dpi:          DPI used during image conversion (for pts↔px conversion).
        """
        from copy import deepcopy

        writer = PdfWriter()
        points_per_pixel = 72.0 / dpi

        logger.info("Writing column-split PDF...")
        total_pages = len(self.reader.pages)
        for page_index, page in enumerate(self.reader.pages):
            if status_callback:
                status_callback(
                    f"Writing PDF: page {page_index + 1}/{total_pages}")
            if page_index >= len(margins_list):
                writer.add_page(page)
                continue

            margin = margins_list[page_index]
            gutter_x = gutter_list[page_index] if page_index < len(
                gutter_list) else None

            # Full-page crop box boundaries in PDF points
            left_pts = margin["left"] * points_per_pixel
            top_pts = margin["top"] * points_per_pixel
            right_pts = margin["right"] * points_per_pixel
            bottom_pts = margin["bottom"] * points_per_pixel

            orig_h = float(page.mediabox.height)
            pdf_bottom = orig_h - bottom_pts
            pdf_top = orig_h - top_pts

            if gutter_x is not None:
                # gutter_x is relative to the cropped image;
                # convert to absolute pixel position, then to PDF points.
                gutter_abs_px = margin["left"] + gutter_x
                gutter_pts = gutter_abs_px * points_per_pixel

                # Left column
                left_page = deepcopy(page)
                left_page.cropbox.lower_left = (left_pts, pdf_bottom)
                left_page.cropbox.upper_right = (gutter_pts, pdf_top)
                writer.add_page(left_page)

                # Right column
                right_page = deepcopy(page)
                right_page.cropbox.lower_left = (gutter_pts, pdf_bottom)
                right_page.cropbox.upper_right = (right_pts, pdf_top)
                writer.add_page(right_page)

                logger.debug(
                    "Page %d: split at %.1f pts (gutter px=%d)",
                    page_index + 1,
                    gutter_pts,
                    gutter_x,
                )
            else:
                page.cropbox.lower_left = (left_pts, pdf_bottom)
                page.cropbox.upper_right = (right_pts, pdf_top)
                writer.add_page(page)

        with open(output_path, "wb") as f:
            writer.write(f)
        logger.info("Saved column-split PDF: %s", output_path)

    @staticmethod
    def get_pdf_info(pdf_path: str) -> dict:
        """Get basic information about a PDF."""
        reader = PdfReader(pdf_path)
        return {
            'num_pages': len(reader.pages),
            'has_metadata': bool(reader.metadata),
            'is_encrypted': reader.is_encrypted,
        }
