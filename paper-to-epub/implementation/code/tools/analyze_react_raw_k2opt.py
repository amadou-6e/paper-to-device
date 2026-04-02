#!/usr/bin/env python3
"""
Analyze ReAct raw k2pdfopt output for title-width mismatch.
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

print("=" * 70)
print("ANALYSIS: ReAct RAW k2pdfopt OUTPUT")
print(f"File: {pdf_path.name}")
print(f"Total pages: {len(doc)}")
print("=" * 70)
print()

# === PART 1: DETECT TITLE REGION ON PAGE 1 ===
print("PART 1: TITLE REGION DETECTION (PAGE 1) [Target: ~30 min]")
print("-" * 70)

page1 = doc[0]
pix1 = page1.get_pixmap(matrix=fitz.Matrix(scale, scale))
img1 = Image.frombytes("RGB", [pix1.width, pix1.height], pix1.samples)
arr1 = np.array(img1)

print(f"Page 1 rendered size: {img1.size[0]}x{img1.size[1]} pixels @ {dpi}dpi")

# Find text regions
gray = np.mean(arr1, axis=2)
text_mask = gray < 200
text_columns = np.any(text_mask, axis=0)

text_cols = np.where(text_columns)[0]
if len(text_cols) > 0:
    left_bound = text_cols[0]
    right_bound = text_cols[-1]
    content_width_p1 = right_bound - left_bound
    print(f"\n  ✓ Identify full-width blocks at top:")
    print(f"    - Text bounds: {left_bound}px–{right_bound}px")
    print(f"    - Content width: {content_width_p1}px")

# Identify title region in top portion
top_height = int(img1.size[1] * 0.4)  # Top 40%
top_region = arr1[:top_height, :]
top_gray = np.mean(top_region, axis=2)
top_text_mask = top_gray < 200
top_text_rows = np.any(top_text_mask, axis=1)
top_text_row_indices = np.where(top_text_rows)[0]

if len(top_text_row_indices) > 0:
    title_top = top_text_row_indices[0]
    title_bottom = top_text_row_indices[-1]
    title_height = title_bottom - title_top
    print(f"\n  ✓ Find text bounding box spanning page width:")
    print(f"    - Title region: rows {title_top}–{title_bottom}px")
    print(f"    - Title height: {title_height}px")
    print(f"    - Spans {100*title_height/img1.size[1]:.1f}% of page (≈ title block)")

print()
print("PART 2: FIND BODY TEXT WIDTH (PAGES 2–N) [Target: ~20 min]")
print("-" * 70)

widths = []
body_start = 1
body_end = min(15, len(doc))

for page_num in range(body_start, body_end):
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
        print(f"  Page {page_num+1:2d}: {width:5d}px wide")
    else:
        print(f"  Page {page_num+1:2d}: (no text found)")

if widths:
    avg_width = np.mean(widths)
    median_width = np.median(widths)
    std_width = np.std(widths)
    print(f"\n  ✓ Analyze remaining pages, find most common text width:")
    print(f"    - Average: {avg_width:.0f}px")
    print(f"    - Median:  {median_width:.0f}px")
    print(f"    - Std dev: {std_width:.1f}px")
    print(f"    - This becomes the TARGET WIDTH ← {median_width:.0f}px")

print()
print("=" * 70)
print("DECISION: APPLY TITLE NARROWING?")
print("=" * 70)

if len(text_cols) > 0 and widths:
    page1_width = content_width_p1
    body_width = median_width
    delta = page1_width - body_width
    pct_delta = 100 * delta / body_width if body_width > 0 else 0
    
    print(f"\nPage 1 content (title):  {page1_width}px")
    print(f"Body pages target width: {body_width:.0f}px")
        print(f"Mismatch: {delta:+.0f}px ({pct_delta:+.1f}%)")
        print(f"Mismatch: {delta:+.0f}px ({pct_delta:+.1f}%)")
    
    if abs(delta) > 50:
        print(f"\n⚠️  MISMATCH DETECTED – Title is wider than body")
        print(f"\nNext steps:")
        print(f"  1. Extract page 1 as separate image")
        print(f"  2. Detect title region (top {100*title_height/img1.size[1]:.0f}% of page)")
        print(f"  3. Calculate padding to center title:")
        padding_per_side = delta / 2
        print(f"     Pad = ({delta}px / 2) = {padding_per_side:.0f}px per side")
        print(f"  4. Narrow title block from {page1_width}px → {body_width:.0f}px (centered)")
        print(f"  5. Apply uniform margin crop to entire document")
    else:
        print(f"\n✓ No significant mismatch – title and body widths are consistent")

doc.close()
print()
