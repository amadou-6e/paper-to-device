"""Track extraction defect drift across run versions.

Compares two defect monitor reports and classifies findings as:
1) unchanged (same paper + similar snippet + same page),
2) moved (same paper + similar snippet, but page changed),
3) new (only in target run),
4) resolved (only in base run).

Usage examples:
  python tests/track_defect_drift.py --base-run-tag 2026-04-03 --target-run-tag 2026-04-04
  python tests/track_defect_drift.py --base-run-tag 2026-04-03 --target-run-tag 2026-04-03
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNS_ROOT = REPO_ROOT / "tests" / "runs"


@dataclass(frozen=True)
class FlatFinding:
    run_tag: str
    paper: str
    pdf: str
    page: int
    kind: str
    detail: str
    snippet: str
    norm_snippet: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare defect reports across runs and track drift")
    parser.add_argument(
        "--runs-root",
        type=Path,
        default=RUNS_ROOT,
        help="Root path for run folders (default: tests/runs)",
    )
    parser.add_argument(
        "--base-run-tag",
        required=True,
        help="Base run tag (older run)",
    )
    parser.add_argument(
        "--target-run-tag",
        required=True,
        help="Target run tag (newer run)",
    )
    parser.add_argument(
        "--similarity-threshold",
        type=float,
        default=0.78,
        help="Snippet similarity threshold for matching (default: 0.78)",
    )
    parser.add_argument(
        "--ignore-snippet-regex",
        default=r"^#+$",
        help="Regex for snippets to ignore as unstable/noisy (default: '^#+$')",
    )
    parser.add_argument(
        "--output-name",
        default=None,
        help=("Output stem under target run defect_review; default: "
              "defect_drift_<base>_to_<target>"),
    )
    return parser.parse_args()


def normalize_snippet(text: str) -> str:
    s = text.lower()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[^a-z0-9 ]", "", s)
    return s.strip()


def report_path(runs_root: Path, run_tag: str) -> Path:
    return runs_root / run_tag / "defect_review" / "defect_report.json"


def load_report(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(
            f"Missing report: {path}. Run tests/monitor_extraction_defects.py first."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def flatten_report(report: dict,
                   ignore_re: re.Pattern[str]) -> list[FlatFinding]:
    run_tag = str(report.get("run_tag", ""))
    out: list[FlatFinding] = []
    for pdf_item in report.get("pdfs", []):
        pdf = str(pdf_item.get("pdf", ""))
        paper = pdf.split("/", 1)[0] if "/" in pdf else pdf
        for page_item in pdf_item.get("pages", []):
            page = int(page_item.get("page", 0))
            for f in page_item.get("findings", []):
                kind = str(f.get("kind", ""))
                detail = str(f.get("detail", ""))
                snippet = str(f.get("snippet", "")).strip()
                if not snippet:
                    continue
                if ignore_re.search(snippet):
                    continue
                out.append(
                    FlatFinding(
                        run_tag=run_tag,
                        paper=paper,
                        pdf=pdf,
                        page=page,
                        kind=kind,
                        detail=detail,
                        snippet=snippet,
                        norm_snippet=normalize_snippet(snippet),
                    ))
    return out


def similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(a=a, b=b).ratio()


def best_match(
    target: FlatFinding,
    base_candidates: list[tuple[int, FlatFinding]],
    threshold: float,
    used_base_ids: set[int],
) -> tuple[int, FlatFinding, float] | None:
    scored: list[tuple[float, int, FlatFinding]] = []
    for idx, cand in base_candidates:
        if idx in used_base_ids:
            continue
        if cand.paper != target.paper:
            continue
        if cand.kind != target.kind:
            continue
        s = similarity(target.norm_snippet, cand.norm_snippet)
        # Small preference for same detail text.
        if target.detail == cand.detail:
            s += 0.02
        scored.append((s, idx, cand))

    if not scored:
        return None

    scored.sort(key=lambda x: x[0], reverse=True)
    s, idx, cand = scored[0]
    if s < threshold:
        return None
    return idx, cand, min(s, 1.0)


def group_counts(rows: list[dict], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        k = str(r.get(key, ""))
        out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))


def write_outputs(out_dir: Path, stem: str, data: dict) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{stem}.json"
    md_path = out_dir / f"{stem}.md"

    json_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    summary = data["summary"]
    lines = [
        f"# Defect Drift Report ({data['base_run_tag']} -> {data['target_run_tag']})",
        "",
        f"Matched unchanged: {summary['unchanged_count']}",
        f"Matched moved: {summary['moved_count']}",
        f"New defects: {summary['new_count']}",
        f"Resolved defects: {summary['resolved_count']}",
        "",
    ]

    moved = data.get("moved", [])
    if moved:
        lines.append("## Moved Defects")
        for m in moved:
            lines.append(
                f"- {m['paper']} | page {m['base_page']} -> {m['target_page']} | {m['kind']} | sim={m['similarity']:.2f}"
            )
            lines.append(f"  - `{m['target_snippet']}`")
        lines.append("")

    new_rows = data.get("new", [])
    if new_rows:
        lines.append("## New Defects")
        for r in new_rows[:40]:
            lines.append(
                f"- {r['paper']} | page {r['target_page']} | {r['kind']} | `{r['target_snippet']}`"
            )
        if len(new_rows) > 40:
            lines.append(f"- ... ({len(new_rows) - 40} more)")
        lines.append("")

    resolved_rows = data.get("resolved", [])
    if resolved_rows:
        lines.append("## Resolved Defects")
        for r in resolved_rows[:40]:
            lines.append(
                f"- {r['paper']} | page {r['base_page']} | {r['kind']} | `{r['base_snippet']}`"
            )
        if len(resolved_rows) > 40:
            lines.append(f"- ... ({len(resolved_rows) - 40} more)")
        lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def main() -> None:
    args = parse_args()
    ignore_re = re.compile(args.ignore_snippet_regex)

    base_report = load_report(report_path(args.runs_root, args.base_run_tag))
    target_report = load_report(
        report_path(args.runs_root, args.target_run_tag))

    base = flatten_report(base_report, ignore_re)
    target = flatten_report(target_report, ignore_re)

    base_candidates = list(enumerate(base))
    used_base_ids: set[int] = set()

    unchanged: list[dict] = []
    moved: list[dict] = []
    new: list[dict] = []

    for t in target:
        m = best_match(t, base_candidates, args.similarity_threshold,
                       used_base_ids)
        if m is None:
            new.append({
                "paper": t.paper,
                "kind": t.kind,
                "target_page": t.page,
                "target_snippet": t.snippet,
            })
            continue

        base_idx, b, sim = m
        used_base_ids.add(base_idx)

        row = {
            "paper": t.paper,
            "kind": t.kind,
            "similarity": round(sim, 4),
            "base_page": b.page,
            "target_page": t.page,
            "base_snippet": b.snippet,
            "target_snippet": t.snippet,
        }
        if b.page == t.page:
            unchanged.append(row)
        else:
            moved.append(row)

    resolved: list[dict] = []
    for idx, b in base_candidates:
        if idx in used_base_ids:
            continue
        resolved.append({
            "paper": b.paper,
            "kind": b.kind,
            "base_page": b.page,
            "base_snippet": b.snippet,
        })

    moved.sort(key=lambda r: (r["paper"], r["base_page"], r["target_page"]))
    new.sort(key=lambda r: (r["paper"], r["target_page"]))
    resolved.sort(key=lambda r: (r["paper"], r["base_page"]))

    summary = {
        "base_findings": len(base),
        "target_findings": len(target),
        "unchanged_count": len(unchanged),
        "moved_count": len(moved),
        "new_count": len(new),
        "resolved_count": len(resolved),
        "moved_by_paper": group_counts(moved, "paper"),
        "new_by_paper": group_counts(new, "paper"),
        "resolved_by_paper": group_counts(resolved, "paper"),
    }

    report = {
        "base_run_tag": args.base_run_tag,
        "target_run_tag": args.target_run_tag,
        "similarity_threshold": args.similarity_threshold,
        "ignore_snippet_regex": args.ignore_snippet_regex,
        "summary": summary,
        "unchanged": unchanged,
        "moved": moved,
        "new": new,
        "resolved": resolved,
    }

    stem = args.output_name or f"defect_drift_{args.base_run_tag}_to_{args.target_run_tag}"
    out_dir = args.runs_root / args.target_run_tag / "defect_review"
    json_path, md_path = write_outputs(out_dir, stem, report)

    print(f"Base run: {args.base_run_tag}")
    print(f"Target run: {args.target_run_tag}")
    print(f"Base findings: {len(base)}")
    print(f"Target findings: {len(target)}")
    print(f"Moved defects: {len(moved)}")
    print(f"New defects: {len(new)}")
    print(f"Resolved defects: {len(resolved)}")
    print(f"JSON: {json_path.relative_to(REPO_ROOT)}")
    print(f"MD:   {md_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
