"""Generate run-tagged extraction outputs from example-papers.

Output layout:
tests/runs/<run_tag>/<paper_stem>/
    - <paper_stem>_baseline_source.pdf
    - <paper_stem>_baseline_extracted.pdf
    - <paper_stem>_<config>_extracted.pdf

Examples:
    python tests/samples/run_stretch_samples.py
    python tests/samples/run_stretch_samples.py --run-tag 2026-04-03 --papers 2305.11499_RCOT.pdf
    python tests/samples/run_stretch_samples.py --configs baseline stretch_135
"""

import argparse
import datetime as dt
import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
K2 = REPO_ROOT / "k2pdfopt" / "build-msys" / "k2pdfopt.exe"
PAPERS_DIR = REPO_ROOT / "example-papers"
SAMPLES_DIR = Path(__file__).parent
RUNS_DIR = REPO_ROOT / "tests" / "runs"


def discover_papers() -> list[str]:
    return sorted(p.name for p in PAPERS_DIR.glob("*.pdf"))


# (subfolder name, extra k2pdfopt args)
CONFIGS = [
    ("baseline", []),
    ("stretch_115", ["-stretch", "-stretchr", "1.15", "-stretchmax", "1.35"]),
    ("stretch_125", ["-stretch", "-stretchr", "1.25", "-stretchmax", "1.35"]),
    ("stretch_135", ["-stretch", "-stretchr", "1.35", "-stretchmax", "1.35"]),
]

COMMON_ARGS = ["-fc-", "-x", "-ui-", "-y", "-ow"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate run-tagged extraction samples")
    parser.add_argument(
        "--run-tag",
        default=dt.date.today().isoformat(),
        help="Date/run tag folder under tests/runs (default: YYYY-MM-DD)",
    )
    parser.add_argument(
        "--papers",
        nargs="*",
        default=None,
        help=
        "Optional list of paper filenames from example-papers (e.g. 2305.11499_RCOT.pdf)",
    )
    parser.add_argument(
        "--configs",
        nargs="*",
        default=[name for name, _ in CONFIGS],
        help="Subset of configs to run (default: all)",
    )
    parser.add_argument(
        "--use-existing-samples",
        action="store_true",
        help=("Do not run k2pdfopt. Copy already-generated PDFs from "
              "tests/samples/<paper>/<config>/ into the run-tag layout."),
    )
    return parser.parse_args()


def build_subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    runtime_bin = Path("C:/msys64/mingw64/bin")
    if runtime_bin.exists():
        sep = ";" if os.name == "nt" else ":"
        runtime = str(runtime_bin)
        current = env.get("PATH", "")
        if runtime not in current:
            env["PATH"] = f"{runtime}{sep}{current}"
    return env


def selected_configs(config_names: list[str]) -> list[tuple[str, list[str]]]:
    config_map = {name: extra for name, extra in CONFIGS}
    missing = [name for name in config_names if name not in config_map]
    if missing:
        raise ValueError(f"Unknown configs: {', '.join(missing)}")
    return [(name, config_map[name]) for name in config_names]


def find_existing_sample_pdf(stem: str, config: str) -> Path | None:
    legacy_dir = SAMPLES_DIR / stem / config
    if not legacy_dir.exists():
        return None
    exact = legacy_dir / f"{stem}_{config}.pdf"
    if exact.exists():
        return exact
    candidates = sorted(legacy_dir.glob("*.pdf"),
                        key=lambda p: p.stat().st_mtime,
                        reverse=True)
    return candidates[0] if candidates else None


def run(paper_name: str, config: str, extra_args: list[str],
        paper_run_dir: Path, env: dict[str, str],
        use_existing_samples: bool) -> None:
    input_pdf = PAPERS_DIR / paper_name
    stem = Path(paper_name).stem
    requested_output_pdf = paper_run_dir / f"{stem}_{config}_extracted.pdf"
    baseline_source_pdf = paper_run_dir / f"{stem}_baseline_source.pdf"

    # Keep only this config's canonical file in the run directory.
    if requested_output_pdf.exists():
        requested_output_pdf.unlink()

    if use_existing_samples:
        source_pdf = find_existing_sample_pdf(stem, config)
        if source_pdf is None:
            raise FileNotFoundError(
                f"No existing sample found for {stem}/{config} in tests/samples/{stem}/{config}/"
            )
        shutil.copy2(source_pdf, requested_output_pdf)
        size_kb = requested_output_pdf.stat().st_size // 1024
        print(f"  [{config}] -> {requested_output_pdf.relative_to(REPO_ROOT)}",
              flush=True)
        print(f"           {size_kb} KB (copied)", flush=True)
        return

    cmd = [
        str(K2),
        str(input_pdf),
        *COMMON_ARGS,
        *extra_args,
        "-o",
        str(requested_output_pdf),
    ]
    print(f"  [{config}] -> {requested_output_pdf.relative_to(REPO_ROOT)}",
          flush=True)
    subprocess.run(cmd,
                   check=True,
                   env=env,
                   stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)

    generated = sorted(
        [p for p in paper_run_dir.glob("*.pdf") if p != baseline_source_pdf],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not generated:
        raise FileNotFoundError(
            f"k2pdfopt did not produce output in {paper_run_dir}")

    output_pdf = generated[0]
    canonical_output_pdf = requested_output_pdf
    if output_pdf != canonical_output_pdf:
        if canonical_output_pdf.exists():
            canonical_output_pdf.unlink()
        output_pdf.rename(canonical_output_pdf)
        output_pdf = canonical_output_pdf

    size_kb = output_pdf.stat().st_size // 1024
    print(f"           {size_kb} KB", flush=True)


def main() -> None:
    args = parse_args()

    if not K2.exists():
        raise FileNotFoundError(f"k2pdfopt.exe not found at {K2}")

    papers = args.papers if args.papers else discover_papers()
    if not papers:
        raise FileNotFoundError(f"No PDFs found in {PAPERS_DIR}")

    env = build_subprocess_env()
    run_dir = RUNS_DIR / args.run_tag
    run_dir.mkdir(parents=True, exist_ok=True)
    configs = selected_configs(args.configs)

    print(f"Run tag: {args.run_tag}")
    print(f"Run dir: {run_dir.relative_to(REPO_ROOT)}")
    print(f"Found {len(papers)} papers")
    for paper in papers:
        print(f"\n=== {paper} ===")
        stem = Path(paper).stem
        input_pdf = PAPERS_DIR / paper
        paper_run_dir = run_dir / stem
        paper_run_dir.mkdir(parents=True, exist_ok=True)

        baseline_source = paper_run_dir / f"{stem}_baseline_source.pdf"
        shutil.copy2(input_pdf, baseline_source)
        print(f"  [source]   -> {baseline_source.relative_to(REPO_ROOT)}",
              flush=True)

        for config, extra in configs:
            run(paper, config, extra, paper_run_dir, env,
                args.use_existing_samples)

    print("\nDone.")


if __name__ == "__main__":
    main()
