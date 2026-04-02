#!/usr/bin/env python3
"""
Analyze title-width mismatch on raw k2pdfopt output (before Docling).
Shows the 2-part detection strategy.
"""
import fitz
import sys
from pathlib import Path
from PIL import Image
import numpy as np

sys.path.insert(0, 'src')

# Use RAW k2pdfopt output (no Docling applied)
pdf_path = Path('extract/2406.01637_Teams_of_LLM_Agents_k2opt_demo.pdf')
doc = fitz.open(str(pdf_path))
dpi = 200
scale = dpi / 72.0

print("=" * 70)
print("ANALYSIS: RAW k2pdfopt OUTPUT (BEFORE DOCLING)")
print(f"File: {pdf_path.name}")
print(f"Total pages: {len(doc)}")
print("=" * 70)
print()

# === PART 1: DETECT TITLE REGION ON PAGE 1 ===
print("PART 1: TITLE REGION DETECTION (PAGE 1)")
print("-" * 70)

page1 = doc[0]
pix1 = page1.get_pixmap(matrix=fitz.Matrix(scale, scale))
img1 = Image.frombytes("RGB", [pix1.width, pix1.height], pix1.samples)
arr1 = np.array(img1)

print(f"Page 1 rendered size: {img1.size[0]}x{img1.size[1]} pixels @ {dpi}dpi")

# Find text regions using simple thresholding (dark pixels = text)
gray = np.mean(arr1, axis=2)
text_mask = gray < 200  # Dark pixels
text_columns = np.any(text_mask, axis=0)  # Find columns with text

# Find leftmost and rightmost text columns
text_cols = np.where(text_columns)[0]
if len(text_cols) > 0:
    left_bound = text_cols[0]
    right_bound = text_cols[-1]
    content_width_p1 = right_bound - left_bound
    print(f"  ✓ Full-width text bounds: {left_bound}px—{right_bound}px")
    print(f"  ✓ Content width: {content_width_p1}px")

# Identify title region in top portion
top_height = int(img1.size[1] * 0.35)  # Top 35%
top_region = arr1[:top_height, :]
top_gray = np.mean(top_region, axis=2)
top_text_mask = top_gray < 200
top_text_rows = np.any(top_text_mask, axis=1)
top_text_row_indices = np.where(top_text_rows)[0]

if len(top_text_row_indices) > 0:
    title_top = top_text_row_indices[0]
    title_bottom = top_text_row_indices[-1]
    title_height = title_bottom - title_top
    print(f"  ✓ Title region detected: rows {title_top}–{title_bottom}px")
    print(
        f"  ✓ Title height: {title_height}px ({100*title_height/img1.size[1]:.1f}% of page)"
    )

print()

# === PART 2: FIND COMMON BODY TEXT WIDTH ===
print("PART 2: BODY TEXT WIDTH (PAGES 2–N)")
print("-" * 70)

widths = []
for page_num in range(1, min(10, len(doc))):
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
        marker = " ← column split detected" if page_num < 4 else ""
        print(f"  Page {page_num+1:2d}: {width:5d}px wide{marker}")

if widths:
    avg_width = np.mean(widths)
    median_width = np.median(widths)
    std_width = np.std(widths)
    print(f"\n  Statistics:")
    print(f"    Average: {avg_width:.0f}px")
    print(f"    Median:  {median_width:.0f}px  ← TARGET WIDTH")
    print(f"    Std dev: {std_width:.1f}px")

print()
print("=" * 70)
print("DIAGNOSIS: TITLE-WIDTH MISMATCH")
print("=" * 70)

if len(text_cols) > 0 and widths:
    page1_width = content_width_p1
    body_width = median_width
    delta = page1_width - body_width
    pct_delta = 100 * delta / body_width if body_width > 0 else 0

    print(f"\nPage 1 (title):  {page1_width}px")
    print(f"Body pages:      {body_width:.0f}px")
    print(f"Difference:      +{delta}px ({pct_delta:+.1f}%)")

    if abs(delta) > 50:
        print(f"\n⚠️  MISMATCH DETECTED")
        print(f"Title spans full width while body is reflowed narrower.")
        print(f"\nRecommended action:")
        print(f"  1. Detect title region on page 1 ({title_height}px tall)")
        print(
            f"  2. Narrow title from {page1_width}px → {body_width:.0f}px (center it)"
        )
        print(f"  3. Apply uniform crop to entire document")
        print(f"  4. Result: Consistent width with no truncation")
    else:
        print(f"\nNo significant mismatch.")

doc.close()
print()
