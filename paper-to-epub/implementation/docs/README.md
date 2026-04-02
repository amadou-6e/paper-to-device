
# PDF Border Cropper for Kindle

Automatically detect and crop white margins from PDF pages to optimize reading on Kindle and other e-readers. This tool uses intelligent margin detection algorithms to preserve document content while maximizing usable screen space.

## Features

- ✅ **Automatic margin detection** - Analyzes each page independently using histogram-based threshold calculation
- ✅ **Per-page optimization** - Different margins on each page are detected and cropped individually
- ✅ **Preserves content** - Smart detection avoids clipping diagrams, equations, or important content near edges
- ✅ **Configurable sensitivity** - Adjust margin detection aggressiveness (0=conservative, 100=aggressive)
- ✅ **Batch support ready** - CLI can be easily extended for batch processing
- ✅ **No dependencies on system tools** - Uses pure Python libraries (PyMuPDF, Pillow)

## Installation

```bash
# Install as a package
python -m venv venv
source venv/Scripts/activate  # Windows
# or: source venv/bin/activate  # Linux/Mac
pip install -e .
```

## Usage

```bash
# Basic usage - crop PDF with default settings
epub-papers crop paper.pdf

# Customize sensitivity (0-100, default: 90)
epub-papers crop paper.pdf --sensitivity 85

# Specify output directory
epub-papers crop paper.pdf --output-dir ./cropped

# Adjust DPI for margin detection (higher = slower but more accurate)
epub-papers crop paper.pdf --dpi 150

# Disable first-page layout network (if you want legacy behavior)
epub-papers crop paper.pdf --no-first-page-layout-net

# Output formats
epub-papers crop paper.pdf --format pdf      # PDF only
epub-papers crop paper.pdf --format epub     # EPUB only (experimental)
epub-papers crop paper.pdf --format both     # Both (default)

# Final e-reader outputs (new export step)
epub-papers crop paper.pdf --reader-format epub
epub-papers crop paper.pdf --reader-format cbz
epub-papers crop paper.pdf --reader-format epub --reader-format cbz

# Skip EPUB generation (faster, if only PDF needed)
epub-papers crop paper.pdf --skip-epub
```

## Desktop UI

Launch the desktop app:

```bash
epub-papers-ui
```

The UI provides:
- input PDF and output folder pickers on the left
- processing and output controls on the left
- original/cropped reader preview on the right
- background export so the window stays responsive

## How It Works

### Margin Detection Algorithm

1. **Convert PDF pages to images** at specified DPI using PyMuPDF
2. **Convert to grayscale** for pixel analysis
3. **Calculate automatic threshold** using histogram analysis:
   - Analyzes pixel intensity distribution
   - Determines adaptive threshold based on sensitivity setting
   - Higher sensitivity = more aggressive margin removal
4. **Scan from edges inward** to find first non-white pixels:
   - Check left edge: scan right until content found
   - Check right edge: scan left until content found  
   - Check top edge: scan down until content found
   - Check bottom edge: scan up until content found
5. **Apply bounding box crop** to each page
6. **Reconstruct PDF** with new page dimensions

### Sensitivity Levels

- **0 (Conservative)**: Only removes clearly blank space, preserves all possibly-useful margins
- **50 (Balanced)**: Good for most academic papers, removes most white space
- **90 (Default)**: Optimized for Kindle reading, removes nearly all margins
- **100 (Aggressive)**: Maximum margin removal, risk of clipping edge content

## Output Files

For an input file `paper.pdf`:
- **Cropped PDF**: `paper_cropped.pdf` (recommended for reading on Kindle via USB/email)
- **EPUB**: `paper.epub` (image-based export for e-readers)
- **CBZ**: `paper.cbz` (zip-comic format supported by many reader apps)

## Performance

- **15-page paper**: ~3 seconds
- **27-page paper**: ~5 seconds
- **43-page paper**: ~8 seconds

Performance scales roughly linearly with page count.

## Example Results from Test Dataset

Successfully processed 6 academic papers:
- Attention Is All You Need (15 pages) → 2.1 MB
- LLaMA (27 pages) → 670 KB  
- Chain of Thought (43 pages) → 806 KB
- ReAct (22 pages) → 577 KB
- GPT-3 (72 pages) → 6.4 MB
- Voyager (45 pages) → 18 MB

Output files are ready for transfer to Kindle via USB or Amazon's email-to-Kindle service.

## Limitations

- **EPUB generation**: Currently has compatibility issues with ebooklib. PDF output is recommended.
- **Protected PDFs**: Won't work with password-protected or encrypted PDFs
- **Scanned images**: Works best with born-digital PDFs; scanned image-based PDFs may have uneven margins
- **Special layouts**: Complex multi-column layouts or graphs at page edges may be affected

## First-Page Layout Network

By default, page 1 is processed with a document layout network first, then falls
back to text/image detectors if needed. This uses a lightweight density-based
heuristic (no ML model needed) and is designed to handle arXiv side identifiers
or noisy first-page headers that might otherwise distort crop bounds.

- Enable/disable with: `--first-page-layout-net` / `--no-first-page-layout-net`
- Lightweight heuristic uses no external ML models
- Falls back automatically to text-based and image-based detection if needed

## Project Structure

```
src/
├── cli.py              # Command-line interface
├── config.py           # Configuration and constants
├── pdf_processor.py    # PDF reading and writing  
├── margin_detector.py  # Margin detection algorithm
└── epub_generator.py   # EPUB generation (experimental)
```

## Dependencies

- **pypdf** (6.9.2) - PDF manipulation
- **PyMuPDF** (1.27.2.2) - PDF to image conversion
- **Pillow** (12.1.1) - Image processing
- **numpy** (2.4.3) - Numerical computation for threshold detection
- **click** (8.3.1) - CLI framework
- **ebooklib** (0.20) - EPUB generation
- **lxml** (6.0.2) - XML processing

## Future Improvements

1. **Batch processing**: Add support for processing multiple PDFs at once
2. **GUI interface**: Create a simple graphical interface
3. **Kindle-specific optimization**: Further optimize for Kindle display
4. **EPUB fixes**: Resolve ebooklib compatibility issues or use alternative library
5. **Configuration files**: Support .yaml/.json config files for repeated settings
6. **Progress bar**: Add visual progress indicators for large PDFs
7. **Dry-run mode**: Preview what margins will be cropped without modifying PDF

## Troubleshooting

### "ModuleNotFoundError" when running CLI
Ensure you're using the venv Python interpreter:
```bash
venv/Scripts/python src/cli.py crop paper.pdf  # Explicit venv
```

### Large file sizes after cropping
This can happen if the original PDF has high internal resolution. Try using lower DPI:
```bash
python src/cli.py crop paper.pdf --dpi 100
```

### Margins not being detected
Try adjusting sensitivity:
```bash
python src/cli.py crop paper.pdf --sensitivity 80  # More conservative
python src/cli.py crop paper.pdf --sensitivity 95  # More aggressive
```

## License

MIT License - Use freely!

## Next Steps

To use on your papers:
1. Place PDF files in a folder
2. Run the CLI on each file
3. Transfer cropped PDFs to your Kindle via USB or Amazon's email service
4. Enjoy better reading experience with optimized margins!

**Note**: The tool preserves original PDFs - all output files have the `_cropped` suffix.
