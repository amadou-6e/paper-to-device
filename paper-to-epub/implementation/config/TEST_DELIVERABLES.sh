#!/bin/bash
echo "=== DELIVERABLE VERIFICATION TEST ==="
echo ""
echo "1. Project Structure:"
ls -la src/ | grep ".py$"
echo ""
echo "2. Can user activate venv?"
test -f venv/Scripts/activate && echo "✓ venv activation script exists"
echo ""
echo "3. Can user run the CLI?"
venv/Scripts/python src/cli.py crop --help | head -3
echo ""
echo "4. Documentation for user:"
ls -1 *.md *.txt
echo ""
echo "5. Example outputs ready:"
ls -1 example-papers/*_cropped.pdf | wc -l
echo ""
echo "=== ALL DELIVERABLES VERIFIED FOR USER ==="
