"""Dual-column detection and page splitting for academic papers.

Detects the white gutter between two text columns by projecting content
density onto the X axis and finding a near-zero valley near the page
centre.  Single-column pages (or pages with full-width figures) are
detected automatically and returned unchanged.
"""

import logging
from typing import Optional, Tuple

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# A column pixel must be darker than this grey level to count as "content"
_DARK_THRESHOLD = 220
# Gutter valley must be below this fraction of the mean column density to be
# accepted as a real gutter (10 % is very conservative; keeps false positives low)
_GUTTER_DENSITY_RATIO = 0.10
# The smoothing window (in pixels) applied to the projection before searching
_SMOOTH_WINDOW = 5


def find_column_gutter(
    image: Image.Image,
    search_band: float = 0.25,
) -> Optional[int]:
    """Return the x-pixel of the gutter between two columns, or None.

    Args:
        image: PIL Image of the *already margin-cropped* page.
        search_band: Half-width of the centre region to search, as a fraction
                     of image width.  0.25 means ±25 % of centre → middle 50 %.

    Returns:
        x-pixel position (relative to the supplied image) of the best gutter
        candidate, or ``None`` if no convincing two-column gutter was found.
    """
    arr = np.array(image.convert("L"), dtype=np.float32)
    is_dark = (arr < _DARK_THRESHOLD).astype(np.float32)

    # Project content onto the X axis: count dark pixels per column
    col_proj = is_dark.sum(axis=0)

    W = len(col_proj)
    if W < 40:
        return None

    # Smooth to suppress isolated ink marks
    kernel = np.ones(_SMOOTH_WINDOW) / _SMOOTH_WINDOW
    col_proj_smooth = np.convolve(col_proj, kernel, mode="same")

    # Search band around the centre
    lo = int(W * (0.5 - search_band))
    hi = int(W * (0.5 + search_band))
    band = col_proj_smooth[lo:hi]

    if band.max() == 0:
        return None  # blank page

    gutter_rel = int(band.argmin())
    gutter_x = lo + gutter_rel
    gutter_val = float(col_proj_smooth[gutter_x])

    # Reference: mean density of the left and right column regions
    left_mean = float(col_proj_smooth[:gutter_x].mean()) if gutter_x > 4 else 0.0
    right_mean = float(col_proj_smooth[gutter_x + 1:].mean()) if gutter_x < W - 4 else 0.0
    content_density = (left_mean + right_mean) / 2.0

    if content_density == 0.0:
        return None

    if gutter_val / content_density > _GUTTER_DENSITY_RATIO:
        logger.debug(
            "Column gutter rejected: valley=%.1f mean=%.1f ratio=%.3f",
            gutter_val,
            content_density,
            gutter_val / content_density,
        )
        return None

    # Both halves must have meaningful content (guards against mostly-blank pages)
    if left_mean < 1.0 or right_mean < 1.0:
        return None

    logger.debug("Column gutter found at x=%d (valley=%.1f mean=%.1f)", gutter_x, gutter_val, content_density)
    return int(gutter_x)


def split_image_columns(
    image: Image.Image,
    gutter_x: int,
) -> Tuple[Image.Image, Image.Image]:
    """Split a page image vertically at *gutter_x*.

    Args:
        image: The (margin-cropped) page image.
        gutter_x: x-pixel where the gutter centre lies (image coordinates).

    Returns:
        ``(left_column_image, right_column_image)``
    """
    W, H = image.size
    left = image.crop((0, 0, gutter_x, H))
    right = image.crop((gutter_x, 0, W, H))
    return left, right


def detect_gutters_for_pages(
    images: list,
    margins_list: list,
) -> list:
    """Run ``find_column_gutter`` on every cropped page image.

    Args:
        images: Raw page images (before cropping) as returned by
                ``convert_pages_to_images()``.
        margins_list: Per-page margin dicts ``{left, top, right, bottom}``.

    Returns:
        List of the same length as *images*: each entry is either ``None``
        (single column / no clear gutter) or an ``int`` (gutter pixel within
        the *cropped* image coordinate space).
    """
    gutter_list = []
    for i, (image, margin) in enumerate(zip(images, margins_list)):
        cropped = image.crop((
            margin["left"], margin["top"],
            margin["right"], margin["bottom"],
        ))
        gutter = find_column_gutter(cropped)
        if gutter is not None:
            logger.debug("Page %d: dual-column gutter at x=%d", i + 1, gutter)
        gutter_list.append(gutter)

    split_count = sum(1 for g in gutter_list if g is not None)
    logger.info("Column detection: %d/%d pages identified as dual-column", split_count, len(gutter_list))
    return gutter_list
