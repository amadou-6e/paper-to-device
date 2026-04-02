"""Docling neural-network layout detection for PDF page cropping.

Runs Docling's page layout analysis network (Heron/PubLayNet) on all pages
of a PDF and returns per-page crop boxes derived from the union of detected
content clusters. No heuristics are used.
"""

import logging
import importlib.util
import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import fitz  # PyMuPDF
from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)

_PADDING_PX = 8
_EXCLUDED_LAYOUT_LABELS = {"PAGE_HEADER", "PAGE_FOOTER"}
_EDGE_ANNOTATION_MAX_WIDTH_RATIO = 0.08
_EDGE_ANNOTATION_MIN_HEIGHT_RATIO = 0.25
_EDGE_ANNOTATION_MAX_EDGE_RATIO = 0.08
_EDGE_ANNOTATION_MIN_GAP_RATIO = 0.03


def _ensure_windows_cuda_runtime_on_path() -> None:
    """Add pip-installed NVIDIA runtime DLL directories to PATH on Windows."""
    if os.name != "nt":
        return

    site_packages = Path(sys.prefix) / "Lib" / "site-packages"
    nvidia_root = site_packages / "nvidia"
    if not nvidia_root.exists():
        return

    added_dirs: list[str] = []
    for bin_dir in nvidia_root.glob("*/bin"):
        if not bin_dir.is_dir():
            continue
        bin_dir_str = str(bin_dir)
        added_dirs.append(bin_dir_str)
        try:
            os.add_dll_directory(bin_dir_str)
        except (AttributeError, FileNotFoundError, OSError):
            # PATH update below is the cross-version fallback.
            pass

    if not added_dirs:
        return

    current_path = os.environ.get("PATH", "")
    path_parts = current_path.split(os.pathsep) if current_path else []
    for entry in reversed(added_dirs):
        if entry not in path_parts:
            path_parts.insert(0, entry)
    os.environ["PATH"] = os.pathsep.join(path_parts)


def _label_name(label: Any) -> str:
    """Return a stable label name for enums/strings/objects."""
    return str(getattr(label, "name", label))


def _is_bottom_left_origin(origin: Any) -> bool:
    """Detect whether bbox coordinates use bottom-left origin."""
    name = str(getattr(origin, "name", origin)).upper()
    return name == "BOTTOMLEFT" or name.endswith(".BOTTOMLEFT")


def _normalize_bbox_top_left(bbox: Any, page_height_pts: float) -> Any:
    """Convert bbox to top-left origin if needed."""
    origin = getattr(bbox, "coord_origin", None)
    if _is_bottom_left_origin(origin) and page_height_pts and hasattr(bbox, "to_top_left_origin"):
        return bbox.to_top_left_origin(page_height_pts)
    return bbox


def _is_excluded_edge_annotation(
    *,
    bbox: Any,
    other_boxes: list[Any],
    page_width_pts: float,
    page_height_pts: float,
) -> bool:
    """Return True for tall, narrow edge text strips like arXiv side metadata."""
    if not other_boxes:
        return False

    width = float(getattr(bbox, "r")) - float(getattr(bbox, "l"))
    height = float(getattr(bbox, "b")) - float(getattr(bbox, "t"))
    if width <= 0 or height <= 0:
        return False

    inferred_page_width = page_width_pts if page_width_pts > 0 else max(float(getattr(box, "r")) for box in other_boxes + [bbox])
    if inferred_page_width <= 0 or page_height_pts <= 0:
        return False

    max_width = inferred_page_width * _EDGE_ANNOTATION_MAX_WIDTH_RATIO
    min_height = page_height_pts * _EDGE_ANNOTATION_MIN_HEIGHT_RATIO
    edge_band = inferred_page_width * _EDGE_ANNOTATION_MAX_EDGE_RATIO
    min_gap = inferred_page_width * _EDGE_ANNOTATION_MIN_GAP_RATIO

    is_tall_narrow = width <= max_width and height >= min_height
    if not is_tall_narrow:
        return False

    left_edge_gap = min(
        (float(getattr(other, "l")) - float(getattr(bbox, "r")) for other in other_boxes),
        default=-1.0,
    )
    right_edge_gap = min(
        (float(getattr(bbox, "l")) - float(getattr(other, "r")) for other in other_boxes),
        default=-1.0,
    )

    near_left_edge = float(getattr(bbox, "l")) <= edge_band and left_edge_gap >= min_gap
    near_right_edge = (inferred_page_width - float(getattr(bbox, "r"))) <= edge_band and right_edge_gap >= min_gap
    return near_left_edge or near_right_edge


def compute_margin_from_layout_clusters(
    clusters: Iterable[Any],
    page_height_pts: float,
    dpi: int,
    page_width_pts: float = 0.0,
    excluded_labels: Optional[set[str]] = None,
) -> Optional[Dict[str, int]]:
    """Compute one page margin box from Docling-style layout clusters."""
    labels_to_exclude = excluded_labels if excluded_labels is not None else _EXCLUDED_LAYOUT_LABELS
    scale = dpi / 72.0

    candidate_boxes: list[Any] = []
    for cluster in clusters:
        if _label_name(getattr(cluster, "label", None)) in labels_to_exclude:
            continue

        bbox = _normalize_bbox_top_left(getattr(cluster, "bbox"), page_height_pts)
        candidate_boxes.append(bbox)

    if not candidate_boxes:
        return None

    filtered_boxes: list[Any] = []
    for bbox in candidate_boxes:
        other_boxes = [other for other in candidate_boxes if other is not bbox]
        if _is_excluded_edge_annotation(
            bbox=bbox,
            other_boxes=other_boxes,
            page_width_pts=page_width_pts,
            page_height_pts=page_height_pts,
        ):
            continue
        filtered_boxes.append(bbox)

    boxes_to_use = filtered_boxes or candidate_boxes

    left = max(0, int(min(float(getattr(box, "l")) for box in boxes_to_use) * scale) - _PADDING_PX)
    top = max(0, int(min(float(getattr(box, "t")) for box in boxes_to_use) * scale) - _PADDING_PX)
    right = int(max(float(getattr(box, "r")) for box in boxes_to_use) * scale) + _PADDING_PX
    bottom = int(max(float(getattr(box, "b")) for box in boxes_to_use) * scale) + _PADDING_PX
    return {"left": left, "top": top, "right": right, "bottom": bottom}


def _render_layout_debug_images(
    pdf_path: str,
    pages: list[Any],
    dpi: int,
    output_dir: str,
) -> None:
    """Write page overlay images showing included/excluded layout clusters."""
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    scale = dpi / 72.0
    doc = fitz.open(pdf_path)
    mat = fitz.Matrix(scale, scale)

    try:
        for i, page in enumerate(pages):
            if i >= len(doc):
                break

            pix = doc[i].get_pixmap(matrix=mat)
            if pix.n - pix.alpha < 3:
                rgb_pix = fitz.Pixmap(fitz.csRGB, pix)
                image = Image.frombytes("RGB", [rgb_pix.width, rgb_pix.height], rgb_pix.samples)
            else:
                image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

            draw = ImageDraw.Draw(image)
            layout_pred = page.predictions.layout if page.predictions else None
            clusters = layout_pred.clusters if layout_pred else []
            page_height_pts = page.size.height if page.size else 0.0

            for cluster in clusters:
                label_name = _label_name(getattr(cluster, "label", None))
                excluded = label_name in _EXCLUDED_LAYOUT_LABELS
                bbox = _normalize_bbox_top_left(cluster.bbox, page_height_pts)
                l = int(float(bbox.l) * scale)
                t = int(float(bbox.t) * scale)
                r = int(float(bbox.r) * scale)
                b = int(float(bbox.b) * scale)
                color = "red" if excluded else "lime"
                draw.rectangle((l, t, r, b), outline=color, width=2)
                draw.text((l + 2, max(0, t - 12)), label_name, fill=color)

            image.save(out_path / f"layout_page_{i + 1:04d}.png")
    finally:
        doc.close()


def run_docling_layout(
    pdf_path: str,
    dpi: int,
    debug_output_dir: Optional[str] = None,
    disable_ocr: bool = True,
    disable_table_structure: bool = True,
) -> Optional[List[Optional[Dict[str, int]]]]:
    """Run Docling layout analysis on all pages of a PDF.

    Returns a list with one entry per page: either a margin dict
    {left, top, right, bottom} in pixel coordinates at the given DPI,
    or None if no clusters were detected for that page.

    Returns None (outer) if Docling fails to load / convert.
    """
    _ensure_windows_cuda_runtime_on_path()

    try:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.object_detection_engine_options import (
            OnnxRuntimeObjectDetectionEngineOptions,
        )
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.datamodel.pipeline_options import LayoutObjectDetectionOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption
    except ImportError as exc:
        logger.error("Docling import failed: %s", exc)
        return None

    def _build_pdf_options(use_onnx_layout: bool) -> PdfPipelineOptions:
        """Create Docling pipeline options, preferring ONNX layout when available."""
        if use_onnx_layout:
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
            layout_options = LayoutObjectDetectionOptions.from_preset(
                "layout_heron_default",
                engine_options=OnnxRuntimeObjectDetectionEngineOptions(providers=providers),
            )
            logger.info("Docling layout engine: ONNX Runtime (providers=%s)", providers)
            return PdfPipelineOptions(
                do_ocr=not disable_ocr,
                do_table_structure=not disable_table_structure,
                layout_options=layout_options,
            )

        logger.info("Docling layout engine: transformers fallback")
        return PdfPipelineOptions(
            do_ocr=not disable_ocr,
            do_table_structure=not disable_table_structure,
        )

    try:
        onnx_available = importlib.util.find_spec("onnxruntime") is not None
        if not onnx_available:
            logger.warning(
                "onnxruntime is not installed; using transformers layout engine. "
                "Install onnxruntime or onnxruntime-gpu to use ONNX layout inference."
            )

        pdf_options = _build_pdf_options(use_onnx_layout=onnx_available)
        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_options),
            }
        )
        result = converter.convert(pdf_path)
    except Exception as exc:
        # Prefer resilience: if ONNX path fails for any reason, retry once
        # on the legacy transformers engine.
        if importlib.util.find_spec("onnxruntime") is not None:
            logger.warning("Docling ONNX conversion failed, retrying with transformers: %s", exc)
            try:
                fallback_options = _build_pdf_options(use_onnx_layout=False)
                converter = DocumentConverter(
                    format_options={
                        InputFormat.PDF: PdfFormatOption(pipeline_options=fallback_options),
                    }
                )
                result = converter.convert(pdf_path)
            except Exception as fallback_exc:
                logger.error("Docling conversion failed: %s", fallback_exc)
                return None
        else:
            logger.error("Docling conversion failed: %s", exc)
            return None

    pages = result.pages
    if not pages:
        logger.warning("Docling returned no pages for %s", pdf_path)
        return None

    page_margins: List[Optional[Dict[str, int]]] = []

    for page in pages:
        layout_pred = page.predictions.layout if page.predictions else None
        clusters = layout_pred.clusters if layout_pred else []
        page_height_pts = page.size.height if page.size else 0.0
        page_width_pts = page.size.width if page.size else 0.0
        margin = compute_margin_from_layout_clusters(
            clusters,
            page_height_pts,
            dpi,
            page_width_pts=page_width_pts,
        )
        if margin is None:
            logger.debug("Page %d: no layout clusters detected", page.page_no)
            page_margins.append(None)
            continue

        logger.debug(
            "Page %d: layout bbox L=%d T=%d R=%d B=%d",
            page.page_no,
            margin["left"],
            margin["top"],
            margin["right"],
            margin["bottom"],
        )
        page_margins.append(margin)

    if debug_output_dir:
        try:
            _render_layout_debug_images(pdf_path, pages, dpi, debug_output_dir)
            logger.info("Saved layout debug overlays to %s", debug_output_dir)
        except Exception as exc:
            logger.warning("Failed to export layout debug overlays: %s", exc)

    return page_margins
