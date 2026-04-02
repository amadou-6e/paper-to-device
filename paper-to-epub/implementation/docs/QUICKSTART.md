# Quick Start Guide

## Setup (One-time)

```bash
# Create and activate virtual environment
python -m venv venv
source venv/Scripts/activate  # On Windows

# Install dependencies
pip install -r requirements.txt
```

## Usage

### Basic Usage
```bash
python src/cli.py crop your_paper.pdf
```

This will create `your_paper_cropped.pdf` in the same directory.

### With Options

```bash
# Adjust margin detection sensitivity (0-100, default 90)
python src/cli.py crop paper.pdf --sensitivity 85

# Save to specific directory
python src/cli.py crop paper.pdf --output-dir ./output

# Only generate PDF (faster, skip EPUB)
python src/cli.py crop paper.pdf --format pdf --skip-epub

# Generate final e-reader files
python src/cli.py crop paper.pdf --reader-format epub
python src/cli.py crop paper.pdf --reader-format cbz
python src/cli.py crop paper.pdf --reader-format epub --reader-format cbz

# Adjust resolution (higher = slower but more accurate)
python src/cli.py crop paper.pdf --dpi 120

# Disable layout-network first-page handling (legacy mode)
python src/cli.py crop paper.pdf --no-first-page-layout-net
```

## Example: Processing Your Papers

```bash
# Process a single paper
python src/cli.py crop ~/Documents/my_research_paper.pdf --output-dir ./cropped

# The output will be ready to transfer to Kindle via USB or email-to-Kindle service
```

## Sensitivity Guide

- **0-30**: Very conservative, keeps most margins
- **50-70**: Balanced approach, good for most papers
- **85-95**: Aggressive, optimized for Kindle (default: 90)
- **95-100**: Very aggressive, maximum margin removal

## Troubleshooting

**Command not found?** Make sure venv is activated:
```bash
source venv/Scripts/activate  # Windows: venv\Scripts\activate
```

**Margins not cropped enough?** Increase sensitivity:
```bash
python src/cli.py crop paper.pdf --sensitivity 95
```

**Margins cropped too much?** Decrease sensitivity:
```bash
python src/cli.py crop paper.pdf --sensitivity 75
```

## Next Steps

1. Test on one of your papers
2. Transfer cropped PDF to Kindle via USB or email
3. Verify readability on Kindle
4. Adjust sensitivity if needed based on results

Happy reading on Kindle!
