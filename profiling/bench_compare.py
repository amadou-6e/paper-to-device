import csv
import os
import re
import subprocess
import time

PYTHON = r"c:/Users/acisse/Documents/CodeWorkspace/epub-papers/venv/Scripts/python.exe"
BASE_CMD = [
    PYTHON,
    "src/cli.py",
    "crop",
    "example-papers/ashish_vaswani_attention_is_all_you.pdf",
    "--allow-fallback",
    "--format",
    "pdf",
    "--output-dir",
    "profiling/out",
]

CASES = [
    ("legacy", {"detector_mode": "legacy"}, {}),
    ("onnx_cpu_forced", {"detector_mode": "hybrid"}, {"DOCLING_DEVICE": "cpu"}),
    ("onnx_auto_cuda", {"detector_mode": "hybrid"}, {"DOCLING_DEVICE": "auto"}),
]

CONVERT_PATTERN = re.compile(r"Finished converting document .* in ([0-9]+\.[0-9]+) sec")
PROVIDER_PATTERN = re.compile(r"ONNX Runtime engine ready \(providers=\[(.*?)\]\)")


def run_case(name, opts, extra_env):
    cmd = BASE_CMD.copy()
    cmd.extend(["--detector-mode", opts["detector_mode"]])

    env = os.environ.copy()
    env.update(extra_env)

    t0 = time.perf_counter()
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    t1 = time.perf_counter()

    output = (proc.stdout or "") + "\n" + (proc.stderr or "")
    convert_match = CONVERT_PATTERN.search(output)
    provider_match = PROVIDER_PATTERN.search(output)

    convert_sec = float(convert_match.group(1)) if convert_match else None
    provider = provider_match.group(1) if provider_match else "n/a"

    return {
        "case": name,
        "exit": proc.returncode,
        "wall_sec": round(t1 - t0, 3),
        "docling_convert_sec": convert_sec if convert_sec is not None else "",
        "providers": provider,
    }


def main():
    print("Benchmark starting... this can take several minutes.")
    results = [run_case(*case) for case in CASES]

    out_csv = "profiling/benchmark_results.csv"
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["case", "exit", "wall_sec", "docling_convert_sec", "providers"],
        )
        writer.writeheader()
        writer.writerows(results)

    print("\nRESULTS")
    print("case,exit,wall_sec,docling_convert_sec,providers")
    for row in results:
        print(
            f"{row['case']},{row['exit']},{row['wall_sec']},"
            f"{row['docling_convert_sec']},{row['providers']}"
        )

    lookup = {r["case"]: r for r in results}
    if "onnx_cpu_forced" in lookup and "onnx_auto_cuda" in lookup:
        a = float(lookup["onnx_cpu_forced"]["wall_sec"])
        b = float(lookup["onnx_auto_cuda"]["wall_sec"])
        if b > 0:
            print(f"\nonnx_auto_cuda_speedup_vs_onnx_cpu_forced={a / b:.3f}x")

    print(f"\nSaved benchmark CSV: {out_csv}")


if __name__ == "__main__":
    main()
