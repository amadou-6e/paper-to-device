"""Automatic margin detection algorithm for PDF pages."""

import logging
import numpy as np
from PIL import Image
from typing import Tuple
from config import (
    GRAYSCALE_THRESHOLD,
    MIN_MARGIN_PIXELS,
    EDGE_SCAN_SIZE,
)

logger = logging.getLogger(__name__)


def calculate_auto_threshold(image: Image.Image, sensitivity: int = 90) -> int:
    """
    Calculate automatic whitespace threshold based on image histogram.
    
    Args:
        image: PIL Image (grayscale)
        sensitivity: User sensitivity (0-100), where 100 = more aggressive margin removal
    
    Returns:
        Threshold value (0-255) for detecting white pixels
    """
    # Convert to numpy array
    img_array = np.array(image)
    
    # Calculate histogram
    hist = np.histogram(img_array, bins=256, range=(0, 256))[0]
    
    # Find the peak (most common pixel value) - typically background/white
    # Start from the bright end (255)
    cumsum = np.cumsum(hist[::-1])  # Reverse cumulative sum from bright end
    total_pixels = img_array.size
    
    # Sensitivity mapping: 100 = aggressive, 0 = conservative
    # Find where the cumsum reaches a percentage of total pixels
    percentage_threshold = 1.0 - (sensitivity / 100.0) * 0.3  # 70% to 100% of pixels
    threshold_idx = np.searchsorted(cumsum, total_pixels * percentage_threshold)
    
    # Convert back to normal grayscale range
    threshold = 255 - threshold_idx
    
    # Clamp between reasonable values
    threshold = max(200, min(250, threshold))
    
    logger.debug(f"Auto-calculated threshold: {threshold} (sensitivity: {sensitivity}%)")
    return threshold


def _find_content_density(is_content: np.ndarray, axis: int, min_width: int = 10) -> int:
    """
    Find the first position with significant content density (not just artifacts).
    
    Args:
        is_content: Binary array marking content pixels
        axis: 0 for horizontal (columns), 1 for vertical (rows)
        min_width: Minimum width needed to consider as real content
    
    Returns:
        Position of first significant content block
    """
    if axis == 0:  # Horizontal: find dense columns
        for x in range(is_content.shape[1]):
            density = np.sum(is_content[:, x:x+min_width]) if x + min_width <= is_content.shape[1] else 0
            if density > (min_width * is_content.shape[0] * 0.1):  # At least 10% filled in next min_width columns
                return max(0, x - MIN_MARGIN_PIXELS)
        return 0
    else:  # Vertical: find dense rows
        for y in range(is_content.shape[0]):
            density = np.sum(is_content[y:y+min_width, :]) if y + min_width <= is_content.shape[0] else 0
            if density > (min_width * is_content.shape[1] * 0.1):  # At least 10% filled in next min_width rows
                return max(0, y - MIN_MARGIN_PIXELS)
        return 0


def detect_margins(image: Image.Image, sensitivity: int = 90) -> Tuple[int, int, int, int]:
    """
    Detect white margins on a page image.
    
    Scans from all four edges inward to find the content bounding box.
    Uses automatic threshold detection and content density analysis to avoid
    margin artifacts like watermarks and logos.
    
    Args:
        image: PIL Image of the page (RGB or grayscale)
        sensitivity: Margin detection sensitivity (0-100)
                    - 0 = conservative (only remove clearly blank space)
                    - 100 = aggressive (optimize heavily for Kindle)
    
    Returns:
        Tuple of (left, top, right, bottom) crop coordinates
    """
    # Convert to grayscale if needed
    if image.mode != 'L':
        image = image.convert('L')
    
    img_array = np.array(image)
    height, width = img_array.shape
    
    # Calculate threshold
    threshold = calculate_auto_threshold(image, sensitivity)
    
    # Detect non-white regions
    is_content = img_array < threshold
    
    # Minimum width/height for content detection (ignore thin artifacts)
    min_content_width = max(10, width // 30)  # At least 1/30 of page width
    min_content_height = max(10, height // 30)  # At least 1/30 of page height
    
    # Find margins by looking for substantial content blocks (not just artifacts)
    # Use moderate density threshold to filter out thin margin text (like arXiv metadata)
    # while preserving legitimate content like authors and titles
    CONTENT_DENSITY_THRESHOLD = 0.08  # 8% density needed to count as real content
    
    left = 0
    right = width
    top = 0
    bottom = height
    
    # Scan from left for dense content block
    for x in range(width - min_content_width):
        density = np.sum(is_content[:, x:x+min_content_width])
        if density > (min_content_width * height * CONTENT_DENSITY_THRESHOLD):
            left = max(0, x - MIN_MARGIN_PIXELS)
            break
    
    # Scan from right for dense content block
    for x in range(width - 1, min_content_width - 1, -1):
        start_x = max(0, x - min_content_width)
        density = np.sum(is_content[:, start_x:x])
        if density > (min_content_width * height * CONTENT_DENSITY_THRESHOLD):
            right = min(width, x + MIN_MARGIN_PIXELS)
            break
    
    # Scan from top for dense content block
    for y in range(height - min_content_height):
        density = np.sum(is_content[y:y+min_content_height, :])
        if density > (min_content_height * width * CONTENT_DENSITY_THRESHOLD):
            top = max(0, y - MIN_MARGIN_PIXELS)
            break
    
    # Scan from bottom for dense content block
    for y in range(height - 1, min_content_height - 1, -1):
        start_y = max(0, y - min_content_height)
        density = np.sum(is_content[start_y:y, :])
        if density > (min_content_height * width * CONTENT_DENSITY_THRESHOLD):
            bottom = min(height, y + MIN_MARGIN_PIXELS)
            break
    
    # Validate results
    if left >= right - 10 or top >= bottom - 10:
        # No valid content detected, return full page
        logger.warning("Could not detect valid content margins; using full page")
        return (0, 0, width, height)
    
    logger.debug(f"Detected margins - L:{left}, T:{top}, R:{right}, B:{bottom} (size: {width}x{height})")
    
    return (left, top, right, bottom)


def detect_page_margins(image: Image.Image, sensitivity: int = 90) -> dict:
    """
    Detect margins and return as a dictionary for PDF cropping.
    
    Args:
        image: PIL Image of the page
        sensitivity: Detection sensitivity (0-100)
    
    Returns:
        Dictionary with 'left', 'top', 'right', 'bottom' keys
    """
    left, top, right, bottom = detect_margins(image, sensitivity)
    return {
        'left': left,
        'top': top,
        'right': right,
        'bottom': bottom
    }
