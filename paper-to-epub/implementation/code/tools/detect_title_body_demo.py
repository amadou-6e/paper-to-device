#!/usr/bin/env python3
"""
DEMO: Detect title region + find body text width on ReAct paper.
Shows the 2-part algorithm (~30 min + ~20 min) in action.
"""
import fitz
import sys
from pathlib import Path
from PIL import Image
import numpy as np

sys.path.insert(0, 'src')

pdf_path = Path('extract/2210.03629_ReAct_raw_k2opt_demo.pdf')
doc = fitz.open(str(pdf_path))
dpi = 200
scale = dpi / 72.0

print("=" * 75)
print("DEMO: 2-PART TITLE-WIDTH DETECTION ON ReAct PAPER")
print("=" * 75)
print()

# === PART 1: DETECT TITLE REGION ON PAGE 1 (Target: ~30 min) ===
print("PART 1: DETECT TITLE REGION (PAGE 1)")
print("      ├─ Use Docling layout or text-based detector")
print("      ├─ Identify full-width blocks at top")
print("      └─ Find text bounding box spanning page width")
print("-" * 75)

page1 = doc[0]
pix1 = page1.get_pixmap(matrix=fitz.Matrix(scale, scale))
img1 = Image.frombytes("RGB", [pix1.width, pix1.height], pix1.samples)
arr1 = np.array(img1)

print(f"  Render page 1 @ {dpi}dpi: {img1.size[0]}x{img1.size[1]} pixels")

# Find text columns
gray = np.mean(arr1, axis=2)
text_mask = gray < 200
text_columns = np.any(text_mask, axis=0)

text_cols = np.where(text_columns)[0]
content_width_p1 = None
if len(text_cols) > 0:
    left_bound = text_cols[0]
    right_bound = text_cols[-1]
    content_width_p1 = right_bound - left_bound
    print(f"  Text bounds found: {left_bound}px–{right_bound}px")
    print(f"  ✓ Full-width content: {content_width_p1}px")

# Detect title region
top_height = int(img1.size[1] * 0.4)
top_region = arr1[:top_height, :]
top_gray = np.mean(top_region, axis=2)
top_text_mask = top_gray < 200
top_text_rows = np.any(top_text_mask, axis=1)
top_text_row_indices = np.where(top_text_rows)[0]

title_height = 0
if len(top_text_row_indices) > 0:
    title_top = top_text_row_indices[0]
    title_bottom = top_text_row_indices[-1]
    title_height = title_bottom - title_top
    print(f"  Title region detected: rows {title_top}–{title_bottom}px")
    print(
        f"  ✓ Title height: {title_height}px ({100*title_height/img1.size[1]:.0f}% of page)"
    )

print()

# === PART 2: FIND BODY TEXT WIDTH (Target: ~20 min) ===
print("PART 2: FIND BODY TEXT WIDTH")
print("      ├─ Analyze remaining pages")
print("      ├─ Find most common text width")
print("      └─ This becomes the TARGET WIDTH")
print("-" * 75)

widths = []
page_sample_range = min(10, len(doc) - 1)

for pg_idx in range(1, 1 + page_sample_range):
    page = doc[pg_idx]
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    arr = np.array(img)

    gray = np.mean(arr, axis=2)
    text_mask = gray < 200
    text_columns = np.any(text_mask, axis=0)

    text_cols_pg = np.where(text_columns)[0]
    if len(text_cols_pg) > 0:
        width = text_cols_pg[-1] - text_cols_pg[0]
        widths.append(width)
        print(f"  Page {pg_idx+1:2d}: {width:4d}px")

if widths:
    median_width = np.median(widths)
    print(f"\n  Median width across all body pages: {median_width:.0f}px")
    print(f"  ✓ TARGET WIDTH: {median_width:.0f}px")

print()
print("=" * 75)
print("ANALYSIS RESULT")
print("=" * 75)

if content_width_p1 and widths:
    delta = content_width_p1 - median_width
    pct = 100 * delta / median_width

    print(f"  Page 1 (title):    {content_width_p1:5.0f}px")
    print(f"  Body target:       {median_width:5.0f}px")
    print(f"  Difference:        {delta:+6.0f}px ({pct:+5.1f}%)")

    if abs(delta) > 50:
        print(
            f"\n  ✓ MISMATCH DETECTED: Title is {abs(delta):.0f}px wider than body"
        )
        print(f"\n  Recommended action:")
        print(f"    1. Extract page 1 as image")
        print(f"    2. Locate title block ({title_height}px tall)")
        print(
            f"    3. Narrow from {content_width_p1}px → {median_width:.0f}px (center it)"
        )
        print(f"    4. Apply uniform crop to entire PDF")
    else:
        print(f"\n  ✓ No mismatch: title and body widths are consistent")

doc.close()
print()
