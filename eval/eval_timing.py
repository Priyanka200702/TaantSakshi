"""
eval/eval_timing.py
Benchmarking and profiling script for execution latency (§9.4, §11 of TANTSAAKSHI_ENGINE_SPEC.md).

Profiles:
  - Single frame (1080p and 12MP 4000x3000)
  - 3-frame burst
  - 5-frame burst (production burst)
  - Stage-by-stage latency (card detection, stacking, glare masking, FFT grade, fingerprint, match)
  - Calculates Median, 90th percentile (P90), Min, Max over repetitions.

Outputs:
  eval/reports/<date>/timing_report.md
  eval/reports/<date>/timing_breakdown.png
"""
from __future__ import annotations

import argparse
import datetime
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

# Ensure matplotlib writes cache to a writable temp directory
os.environ["MPLCONFIGDIR"] = tempfile.gettempdir()
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import cv2
from engine._analyze import analyze, match
from engine.config import get_config
from tools.synth_fabric import FabricSpec, make_card_scene, to_uint8


def run_timing_evaluation(
    out_dir: Path,
    n_runs: int = 3,
) -> dict[str, Any]:
    """Execute latency benchmarking across image sizes and burst configurations."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = get_config()

    configurations = [
        ("1-frame (1080p)", (1080, 1920), 1),
        ("3-frame burst (1080p)", (1080, 1920), 3),
        ("5-frame burst (1080p)", (1080, 1920), 5),
        ("1-frame (12MP 4K)", (3000, 4000), 1),
        ("3-frame burst (12MP 4K)", (3000, 4000), 3),
        ("5-frame burst (12MP 4K)", (3000, 4000), 5),
    ]

    spec = FabricSpec(ends_per_inch=65, picks_per_inch=65, noise_sigma=0.01)
    results_by_config = []

    with tempfile.TemporaryDirectory() as tmp_bench:
        tmp_p = Path(tmp_bench)

        for cfg_name, (H, W), n_frames in configurations:
            print(f"[eval_timing] Profiling {cfg_name} over {n_runs} repetitions...")
            # Pre-generate burst frames
            frame_paths = []
            for f_idx in range(n_frames):
                sc, _ = make_card_scene(
                    spec,
                    cfg,
                    tilt_deg=1.0 * (f_idx - n_frames // 2),
                    camera_px_per_mm=32.0,
                    image_size=(H, W),
                    seed=200 + f_idx,
                )
                p = tmp_p / f"bench_{cfg_name.replace(' ', '_')}_{f_idx}.jpg"
                cv2.imwrite(str(p), to_uint8(sc), [int(cv2.IMWRITE_JPEG_QUALITY), 95])
                frame_paths.append(str(p))

            totals = []
            stage_timings: dict[str, list[float]] = {
                "card_detection": [],
                "stacking": [],
                "glare_masking": [],
                "fft_grade": [],
                "fingerprint": [],
            }
            fp_results = []

            for run_i in range(n_runs):
                t0 = time.perf_counter()
                res = analyze(frame_paths, out_dir=str(tmp_p / f"out_{run_i}"))
                elapsed_ms = (time.perf_counter() - t0) * 1000
                totals.append(elapsed_ms)

                if res.get("ok"):
                    t_dict = res.get("timings_ms", {})
                    for k in stage_timings:
                        stage_timings[k].append(t_dict.get(k, 0.0))
                    if res.get("fingerprint"):
                        fp_results.append(res["fingerprint"])

            # Measure matching time
            match_times = []
            if len(fp_results) >= 2:
                for _ in range(5):
                    t0 = time.perf_counter()
                    match(fp_results[0], fp_results[1])
                    match_times.append((time.perf_counter() - t0) * 1000)
            elif len(fp_results) == 1:
                for _ in range(5):
                    t0 = time.perf_counter()
                    match(fp_results[0], fp_results[0])
                    match_times.append((time.perf_counter() - t0) * 1000)

            median_tot = float(np.median(totals))
            p90_tot = float(np.percentile(totals, 90))
            mean_stages = {k: float(np.mean(vals)) if vals else 0.0 for k, vals in stage_timings.items()}
            median_match = float(np.median(match_times)) if match_times else 0.0

            results_by_config.append({
                "config_name": cfg_name,
                "n_frames": n_frames,
                "resolution": f"{W}x{H}",
                "median_total_ms": median_tot,
                "p90_total_ms": p90_tot,
                "min_total_ms": float(np.min(totals)),
                "max_total_ms": float(np.max(totals)),
                "stages": mean_stages,
                "median_match_ms": median_match,
            })

    # Plot Latency Breakdown
    fig, ax = plt.subplots(figsize=(10, 6))
    names = [r["config_name"] for r in results_by_config]
    y_pos = np.arange(len(names))

    stage_keys = ["card_detection", "stacking", "glare_masking", "fft_grade", "fingerprint"]
    stage_colors = ["#2b5c8f", "#4b9cd3", "#d9822b", "#388e3c", "#7b1fa2"]
    stage_labels = ["Card Detection", "Burst Stacking", "Glare Masking", "FFT Grade", "Fingerprint"]

    left = np.zeros(len(names))
    for sk, color, label in zip(stage_keys, stage_colors, stage_labels):
        vals = np.array([r["stages"].get(sk, 0.0) for r in results_by_config])
        ax.barh(y_pos, vals, left=left, color=color, label=label, alpha=0.85, edgecolor="black")
        left += vals

    ax.axvline(5000.0, color="crimson", linestyle="--", linewidth=2, label="5.0s Budget Limit (§11)")
    ax.set_yticks(y_pos)
    ax.set_yticklabels(names)
    ax.invert_yaxis()
    ax.set_xlabel("Latency (milliseconds)")
    ax.set_title("TantSaakshi Vision Engine Execution Latency by Pipeline Stage")
    ax.legend(loc="lower right")
    ax.grid(True, linestyle=":", alpha=0.6)
    plt.tight_layout()
    timing_png = out_dir / "timing_breakdown.png"
    plt.savefig(timing_png, dpi=200)
    plt.close()

    # Markdown Report
    report_md = out_dir / "timing_report.md"
    with open(report_md, "w", encoding="utf-8") as f:
        f.write("# TantSaakshi Vision Engine Timing Benchmark Report\n\n")
        f.write(f"- **Benchmark Date:** {datetime.date.today().isoformat()}\n")
        f.write(f"- **Repetitions per test:** {n_runs}\n\n")

        f.write("## Latency Summary Table\n\n")
        f.write("| Configuration | Frames | Resolution | Median Total | P90 Total | Match Time | Budget Check (<5s) |\n")
        f.write("| :--- | :---: | :---: | :---: | :---: | :---: | :---: |\n")
        for r in results_by_config:
            budget_ok = "✅ PASS" if r["median_total_ms"] <= 5000.0 else "❌ FAIL"
            f.write(
                f"| `{r['config_name']}` | {r['n_frames']} | {r['resolution']} | "
                f"`{r['median_total_ms']:.1f} ms` | `{r['p90_total_ms']:.1f} ms` | `{r['median_match_ms']:.1f} ms` | {budget_ok} |\n"
            )

        f.write("\n## Per-Stage Breakdown (Milliseconds, Mean)\n\n")
        f.write("| Configuration | Card Detection | Burst Stacking | Glare Mask | FFT Grade | Fingerprint |\n")
        f.write("| :--- | :---: | :---: | :---: | :---: | :---: |\n")
        for r in results_by_config:
            st = r["stages"]
            f.write(
                f"| `{r['config_name']}` | {st.get('card_detection', 0.0):.1f} | {st.get('stacking', 0.0):.1f} | "
                f"{st.get('glare_masking', 0.0):.1f} | {st.get('fft_grade', 0.0):.1f} | {st.get('fingerprint', 0.0):.1f} |\n"
            )

        f.write("\n## Breakdown Visualization\n\n")
        f.write("![Execution Latency Breakdown](timing_breakdown.png)\n")

    print(f"[eval_timing] Report generated successfully: {report_md}")
    return {
        "results": results_by_config,
        "report_path": str(report_md),
    }


def main():
    parser = argparse.ArgumentParser(description="Profile engine execution timing")
    parser.add_argument("--out-dir", type=str, default=None, help="Output directory for reports")
    parser.add_argument("--runs", type=int, default=3, help="Repetitions per configuration")
    args = parser.parse_args()

    date_str = datetime.date.today().strftime("%Y%m%d")
    out_dir = Path(args.out_dir) if args.out_dir else REPO_ROOT / "eval" / "reports" / date_str

    run_timing_evaluation(out_dir=out_dir, n_runs=args.runs)


if __name__ == "__main__":
    main()
