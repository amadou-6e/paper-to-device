#!/usr/bin/env python3
"""
Detect title region on page 1 and find target body text width.
Demonstrates the two-step analysis for title-width mismatch correction.
"""
import fitz
import sys
from pathlib import Path
from PIL import Image
import numpy as np

sys.path.insert(0, 'src')

pdf_path = Path(
    'extract/2406.01637_Teams_of_LLM_Agents_firstpage_docling_only_k2opt_smaller_extreme_170.pdf'
)
doc = fitz.open(str(pdf_path))
dpi = 150
scale = dpi / 72.0

# === PART 1: DETECT TITLE REGION ON PAGE 1 ===
print("=" * 70)
print("PART 1: TITLE REGION DETECTION (PAGE 1)")
print("=" * 70)

page1 = doc[0]
pix1 = page1.get_pixmap(matrix=fitz.Matrix(scale, scale))
img1 = Image.frombytes("RGB", [pix1.width, pix1.height], pix1.samples)
arr1 = np.array(img1)

print(f"Page 1 size: {img1.size[0]}x{img1.size[1]} pixels")

# Find text regions using simple thresholding (dark pixels = text)
gray = np.mean(arr1, axis=2)
text_mask = gray < 200  # Dark pixels
text_columns = np.any(text_mask, axis=0)  # Find columns with text

# Find leftmost and rightmost text columns
text_cols = np.where(text_columns)[0]
if len(text_cols) > 0:
    left_bound = text_cols[0]
    right_bound = text_cols[-1]
    content_width = right_bound - left_bound
    print(f"Text boundaries: left={left_bound}px, right={right_bound}px")
    print(
        f"Full-width content: {content_width}px ({100*content_width/img1.size[0]:.1f}% of page)"
    )

# Find top text region (title) by analyzing top 30% of page
top_height = int(img1.size[1] * 0.3)
top_region = arr1[:top_height, :]
top_gray = np.mean(top_region, axis=2)
top_text_mask = top_gray < 200
top_text_rows = np.any(top_text_mask, axis=1)
top_text_row_indices = np.where(top_text_rows)[0]

if len(top_text_row_indices) > 0:
    title_top = top_text_row_indices[0]
    title_bottom = top_text_row_indices[-1]
    title_height = title_bottom - title_top
    print(
        f"Title region: rows {title_top}–{title_bottom}px (height={title_height}px)"
    )
    print(f"Title spans {100*title_height/img1.size[1]:.1f}% of page height")

print()
print("=" * 70)
print("PART 2: BODY TEXT WIDTH ANALYSIS (PAGES 2–N)")
print("=" * 70)

# === PART 2: FIND COMMON BODY TEXT WIDTH ===
widths = []
for page_num in range(1, min(6, len(doc))):
    page = doc[page_num]
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    arr = np.array(img)

    gray = np.mean(arr, axis=2)
    text_mask = gray < 200
    text_columns = np.any(text_mask, axis=0)

    text_cols = np.where(text_columns)[0]
    if len(text_cols) > 0:
        left = text_cols[0]
        right = text_cols[-1]
        width = right - left
        widths.append(width)
        print(f"  Page {page_num+1}: {width:4d}px wide")

if widths:
    avg_width = np.mean(widths)
    median_width = np.median(widths)
    std_width = np.std(widths)
    print(f"\nBody width statistics:")
    print(f"  Average: {avg_width:.0f}px")
    print(f"  Median:  {median_width:.0f}px  ← TARGET WIDTH FOR TITLE REFLOW")
    print(f"  Std dev: {std_width:.0f}px")

print()
print("=" * 70)
print("MISMATCH ANALYSIS")
print("=" * 70)
if len(text_cols) > 0 and widths:
    page1_width = content_width
    target_width = median_width
    mismatch_pct = 100 * (page1_width - target_width) / target_width

    print(f"Page 1 full-width content:  {page1_width}px")
    print(f"Body pages target width:    {target_width:.0f}px")
    print(f"Mismatch:                   +{mismatch_pct:.1f}%")

    if mismatch_pct > 10:
        print(f"\n✓ TITLE REFLOW DETECTED")
        print(
            f"  Action: Shrink page 1 from {page1_width}px → {target_width:.0f}px"
        )
        print(f"  Method: Detect title region, center, apply uniform crop")
    else:
        print(f"\n✓ Widths are consistent (no significant reflow)")

doc.close()
print()
