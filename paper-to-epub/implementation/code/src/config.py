"""Configuration and constants for the PDF border cropper."""

import logging
import sys

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)

# Margin detection constants
DEFAULT_DPI = 150  # DPI for PDF to image conversion
DEFAULT_SENSITIVITY = 90  # Whitespace detection threshold (0-100)
MIN_MARGIN_PIXELS = 10  # Minimum margin size to be considered valid (in pixels)
EDGE_SCAN_SIZE = 50  # How far from edges to scan initially (in pixels)

# File naming
CROPPED_PDF_SUFFIX = "_cropped"
EPUB_SUFFIX = ""

# Image processing
GRAYSCALE_THRESHOLD = 240  # Threshold for detecting white pixels (0-255)
