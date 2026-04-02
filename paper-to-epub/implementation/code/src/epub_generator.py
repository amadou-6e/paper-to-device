"""EPUB generation from cropped PDF pages."""

import logging
from pathlib import Path
from typing import List, Optional
from PIL import Image
import ebooklib
from ebooklib import epub
from io import BytesIO

logger = logging.getLogger(__name__)


def images_to_epub(images: List[Image.Image], pdf_filename: str, output_path: str) -> None:
    """
    Convert a list of page images to an EPUB file.
    
    Creates an image-based EPUB that preserves the exact formatting,
    equations, and diagrams from the original PDF.
    
    Args:
        images: List of PIL Images (one per page)
        pdf_filename: Name of the original PDF (for metadata)
        output_path: Path to save the EPUB file
    
    Returns:
        None
    """
    logger.info(f"Generating EPUB from {len(images)} pages...")

    if not images:
        raise ValueError("Cannot generate EPUB: no page images were provided.")
    
    # Create EPUB book
    book = epub.EpubBook()
    
    # Set metadata
    book_title = Path(pdf_filename).stem.replace('_', ' ').title()
    book.set_identifier(f'pdf-crop-{Path(pdf_filename).stem}')
    book.set_title(f'{book_title} (Cropped)')
    book.set_language('en')
    
    # Add author/contributor
    book.add_author('PDF Cropper')
    
    chapters = []
    
    # Convert each image to EPUB chapter
    for i, image in enumerate(images):
        # Convert image to PNG bytes
        img_bytes = BytesIO()
        image.save(img_bytes, format='PNG')
        img_bytes.seek(0)
        
        # Create EPUB image item
        img_filename = f'page_{i:04d}.png'
        img_item = epub.EpubImage()
        img_item.file_name = f'images/{img_filename}'
        img_item.content = img_bytes.read()
        book.add_item(img_item)
        
        # Create chapter with centered image.
        # Use body fragment content (not a full XML/HTML document) to keep
        # ebooklib's nav/page parser from seeing an empty document.
        chapter = epub.EpubHtml()
        chapter.file_name = f'page_{i:04d}.xhtml'
        chapter.title = f'Page {i + 1}'
        chapter.content = (
            "<div style=\"margin:0;padding:0;\">"
            f"<img src=\"../images/{img_filename}\" alt=\"Page {i + 1}\" "
            "style=\"max-width:100%;height:auto;display:block;\"/>"
            "</div>"
        )
        
        book.add_item(chapter)
        chapters.append(chapter)
    
    # Create cover using first page
    if images:
        cover_bytes = BytesIO()
        images[0].save(cover_bytes, format='PNG')
        cover_bytes.seek(0)
        
        c = epub.EpubItem()
        c.file_name = 'images/cover.png'
        c.content = cover_bytes.read()
        book.add_item(c)
    
    # Add Table of Contents
    book.toc = chapters
    
    # Add default NCX and Nav files
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    
    # Add all items to spine
    book.spine = ['nav'] + chapters
    
    # Write EPUB
    try:
        epub.write_epub(output_path, book, {})
        logger.info(f"Saved EPUB: {output_path}")
    except Exception as e:
        logger.error(f"Failed to generate EPUB: {e}")
        raise


def crop_image_and_save(image: Image.Image, margin: dict, output_path: Optional[str] = None) -> Image.Image:
    """
    Crop an image based on detected margins.
    
    Args:
        image: PIL Image to crop
        margin: Dictionary with 'left', 'top', 'right', 'bottom' keys
        output_path: Optional path to save cropped image
    
    Returns:
        Cropped PIL Image
    """
    left = margin['left']
    top = margin['top']
    right = margin['right']
    bottom = margin['bottom']
    
    # PIL crop: (left, top, right, bottom)
    cropped = image.crop((left, top, right, bottom))
    
    if output_path:
        cropped.save(output_path)
        logger.debug(f"Saved cropped image: {output_path}")
    
    return cropped
