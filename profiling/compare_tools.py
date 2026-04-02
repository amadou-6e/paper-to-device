from __future__ import annotations

import csv
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = [
    ROOT / "example-papers" / "ashish_vaswani_attention_is_all_you.pdf",
    ROOT / "example-papers" / "jason_wei_chain_of_thought_pro.pdf",
]
OUT_ROOT = ROOT / "profiling" / "competitors"
OUT_PDFCROP = OUT_ROOT / "pdfcropmargins"
OUT_OURS = OUT_ROOT / "ours_network"


def run_cmd(cmd: list[str]) -> tuple[int, float, str, str]:
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    t1 = time.perf_counter()
    return proc.returncode, (t1 - t0), proc.stdout or "", proc.stderr or ""


def main() -> int:
    OUT_PDFCROP.mkdir(parents=True, exist_ok=True)
    OUT_OURS.mkdir(parents=True, exist_ok=True)

    python = ROOT / "venv" / "Scripts" / "python.exe"
    pdfcrop = ROOT / "venv" / "Scripts" / "pdfcropmargins.exe"

    rows: list[dict[str, object]] = []

    for pdf in EXAMPLES:
        out_pcm = OUT_PDFCROP / f"{pdf.stem}_pcm.pdf"
        rc, wall, _out, err = run_cmd([str(pdfcrop), str(pdf), "-o", str(out_pcm)])
        rows.append(
            {
                "tool": "pdfcropmargins",
                "input": pdf.name,
                "exit_code": rc,
                "wall_sec": round(wall, 3),
                "output": str(out_pcm),
                "output_exists": out_pcm.exists(),
                "output_bytes": out_pcm.stat().st_size if out_pcm.exists() else 0,
                "stderr_tail": err.splitlines()[-1] if err else "",
            }
        )

        out_ours = OUT_OURS / f"{pdf.stem}_cropped.pdf"
        rc, wall, _out, err = run_cmd(
            [
                str(python),
                "src/cli.py",
                "crop",
                str(pdf),
                "--detector-mode",
                "network",
                "--allow-fallback",
                "--format",
                "pdf",
                "--output-dir",
                str(OUT_OURS),
            ]
        )
        rows.append(
            {
                "tool": "ours_network",
                "input": pdf.name,
                "exit_code": rc,
                "wall_sec": round(wall, 3),
                "output": str(out_ours),
                "output_exists": out_ours.exists(),
                "output_bytes": out_ours.stat().st_size if out_ours.exists() else 0,
                "stderr_tail": err.splitlines()[-1] if err else "",
            }
        )

    csv_path = OUT_ROOT / "comparison.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"wrote {csv_path}")
    for row in rows:
        print(row)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
