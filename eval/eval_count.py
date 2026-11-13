"""
eval/eval_count.py
Evaluation script for thread-count accuracy (§9.4 of TANTSAAKSHI_ENGINE_SPEC.md).

Evaluates ends_per_inch (warp) and picks_per_inch (weft) against ground truth
manual pick-glass counts.

Data layout:
    data/count/<sareeID>_<phone>_<shot>.jpg
    data/count/ground_truth.csv
    Columns: saree_id, ends_per_inch_manual, picks_per_inch_manual, counted_by, method

Outputs:
    eval/reports/<date>/count_report.md
    eval/reports/<date>/count_scatter.png
"""
from __future__ import annotations

import argparse
import csv
import datetime
import os
import sys
import tempfile
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

from engine._analyze import analyze
from engine.config import get_config
from tools.synth_fabric import FabricSpec, make_card_scene, to_uint8
import cv2


def load_ground_truth(csv_path: Path) -> dict[str, dict[str, Any]]:
    """Load ground_truth.csv into a dictionary keyed by saree_id."""
    gt = {}
    if not csv_path.exists():
        return gt

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sid = row.get("saree_id", "").strip()
            if not sid:
                continue
            gt[sid] = {
                "ends_per_inch_manual": float(row["ends_per_inch_manual"]),
                "picks_per_inch_manual": float(row["picks_per_inch_manual"]),
                "counted_by": row.get("counted_by", "manual"),
                "method": row.get("method", "pick-glass"),
            }
    return gt


def generate_synthetic_count_dataset(target_dir: Path) -> Path:
    """
    Generate synthetic test sarees with known ground truth when real photos
    are not yet available.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    csv_path = target_dir / "ground_truth.csv"
    cfg = get_config()

    sarees = [
        ("saree_01", 60.0, 60.0, 32.0, 0.0),
        ("saree_02", 68.0, 72.0, 30.0, 4.0),
        ("saree_03", 80.0, 80.0, 35.0, -3.0),
        ("saree_04", 55.0, 58.0, 28.0, 8.0),
        ("saree_05", 90.0, 85.0, 36.0, 2.0),
        ("saree_06", 64.0, 64.0, 30.0, -6.0),
        ("saree_07", 75.0, 70.0, 34.0, 5.0),
        ("saree_08", 100.0, 95.0, 38.0, 0.0),
        ("saree_09", 58.0, 62.0, 26.0, -4.0),
        ("saree_10", 82.0, 88.0, 33.0, 7.0),
    ]

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["saree_id", "ends_per_inch_manual", "picks_per_inch_manual", "counted_by", "method"])
        for sid, epi, ppi, scale, tilt in sarees:
            writer.writerow([sid, epi, ppi, "synthetic_ground_truth", "synthesizer"])
            spec = FabricSpec(
                ends_per_inch=epi,
                picks_per_inch=ppi,
                px_per_mm=scale,
                slub_amplitude=0.20,
                irregularity_jitter=0.06,
                hairiness_sigma=0.05,
                noise_sigma=0.015,
                seed=hash(sid) % 100000,
            )
            scene_f32, _ = make_card_scene(spec, cfg, tilt_deg=tilt, camera_px_per_mm=scale)
            img_u8 = to_uint8(scene_f32)
            cv2.imwrite(str(target_dir / f"{sid}_phone1_01.jpg"), img_u8)

    return csv_path


def run_count_evaluation(
    data_dir: Path,
    out_dir: Path,
    is_synthetic: bool = False,
) -> dict[str, Any]:
    """Execute the full thread count evaluation against ground truth."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = get_config()
    gt_csv = data_dir / "ground_truth.csv"

    if not gt_csv.exists() or len(list(data_dir.glob("*.jpg"))) == 0:
        print(f"[eval_count] No data found in {data_dir}. Generating synthetic benchmark dataset...")
        gt_csv = generate_synthetic_count_dataset(data_dir)
        is_synthetic = True

    gt_data = load_ground_truth(gt_csv)
    image_files = sorted(list(data_dir.glob("*.jpg")) + list(data_dir.glob("*.png")))

    # Group image files by saree_id (prefix before first underscore)
    saree_groups: dict[str, list[Path]] = {}
    for p in image_files:
        sid = p.stem.split("_")[0] + "_" + p.stem.split("_")[1] if "_" in p.stem else p.stem
        # Match against gt_data keys
        matched_sid = None
        for k in gt_data:
            if p.stem.startswith(k):
                matched_sid = k
                break
        if matched_sid:
            saree_groups.setdefault(matched_sid, []).append(p)

    results = []
    tmp_out = out_dir / "tmp_an"
    tmp_out.mkdir(exist_ok=True)

    for sid, paths in saree_groups.items():
        gt = gt_data[sid]
        str_paths = [str(p) for p in paths]
        res = analyze(str_paths, out_dir=str(tmp_out))

        if not res["ok"]:
            print(f"[eval_count] Saree {sid} rejected by engine: {res.get('code')} — {res.get('reason')}")
            continue

        epi_engine = float(res["ends_per_inch"])
        ppi_engine = float(res["picks_per_inch"])
        epi_gt = float(gt["ends_per_inch_manual"])
        ppi_gt = float(gt["picks_per_inch_manual"])

        err_epi = abs(epi_engine - epi_gt)
        err_ppi = abs(ppi_engine - ppi_gt)
        pct_epi = (err_epi / epi_gt) * 100.0
        pct_ppi = (err_ppi / ppi_gt) * 100.0

        results.append({
            "saree_id": sid,
            "epi_gt": epi_gt,
            "epi_engine": epi_engine,
            "err_epi": err_epi,
            "pct_epi": pct_epi,
            "ppi_gt": ppi_gt,
            "ppi_engine": ppi_engine,
            "err_ppi": err_ppi,
            "pct_ppi": pct_ppi,
            "native_px_per_mm": res.get("native_px_per_mm", 0.0),
            "n_stacked": res.get("n_stacked", 1),
        })

    if not results:
        print("[eval_count] No valid saree results obtained!")
        return {}

    # Aggregates
    mae_epi = float(np.mean([r["err_epi"] for r in results]))
    mape_epi = float(np.mean([r["pct_epi"] for r in results]))
    max_pct_epi = float(np.max([r["pct_epi"] for r in results]))

    mae_ppi = float(np.mean([r["err_ppi"] for r in results]))
    mape_ppi = float(np.mean([r["pct_ppi"] for r in results]))
    max_pct_ppi = float(np.max([r["pct_ppi"] for r in results]))

    # Plot scatter chart
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    tag = " (Synthetic Validation Only — Not Real-World Accuracy)" if is_synthetic else ""

    # Warp (EPI)
    epis_gt = [r["epi_gt"] for r in results]
    epis_eng = [r["epi_engine"] for r in results]
    min_val = min(epis_gt + epis_eng) - 5
    max_val = max(epis_gt + epis_eng) + 5

    ax1.plot([min_val, max_val], [min_val, max_val], "k--", label="Ideal 1:1")
    ax1.fill_between([min_val, max_val], [min_val * 0.98, max_val * 0.98], [min_val * 1.02, max_val * 1.02], color="green", alpha=0.15, label="±2% Tolerance")
    ax1.scatter(epis_gt, epis_eng, c="royalblue", edgecolors="k", s=60, zorder=5)
    ax1.set_xlabel("Manual Ground Truth (Ends/Inch)")
    ax1.set_ylabel("Vision Engine (Ends/Inch)")
    ax1.set_title(f"Warp Thread Count (EPI)\nMAPE: {mape_epi:.2f}% | MAE: {mae_epi:.2f}")
    ax1.legend(loc="upper left")
    ax1.grid(True, linestyle=":", alpha=0.6)
    ax1.set_xlim(min_val, max_val)
    ax1.set_ylim(min_val, max_val)

    # Weft (PPI)
    ppis_gt = [r["ppi_gt"] for r in results]
    ppis_eng = [r["ppi_engine"] for r in results]
    min_val2 = min(ppis_gt + ppis_eng) - 5
    max_val2 = max(ppis_gt + ppis_eng) + 5

    ax2.plot([min_val2, max_val2], [min_val2, max_val2], "k--", label="Ideal 1:1")
    ax2.fill_between([min_val2, max_val2], [min_val2 * 0.98, max_val2 * 0.98], [min_val2 * 1.02, max_val2 * 1.02], color="green", alpha=0.15, label="±2% Tolerance")
    ax2.scatter(ppis_gt, ppis_eng, c="darkorange", edgecolors="k", s=60, zorder=5)
    ax2.set_xlabel("Manual Ground Truth (Picks/Inch)")
    ax2.set_ylabel("Vision Engine (Picks/Inch)")
    ax2.set_title(f"Weft Thread Count (PPI)\nMAPE: {mape_ppi:.2f}% | MAE: {mae_ppi:.2f}")
    ax2.legend(loc="upper left")
    ax2.grid(True, linestyle=":", alpha=0.6)
    ax2.set_xlim(min_val2, max_val2)
    ax2.set_ylim(min_val2, max_val2)

    fig.suptitle(f"TantSaakshi Thread Count Accuracy{tag}", fontsize=13, weight="bold")
    plt.tight_layout()
    scatter_png = out_dir / "count_scatter.png"
    plt.savefig(scatter_png, dpi=200)
    plt.close()

    # Markdown Report
    report_md = out_dir / "count_report.md"
    with open(report_md, "w", encoding="utf-8") as f:
        f.write("# TantSaakshi Thread Density Evaluation Report\n\n")
        if is_synthetic:
            f.write("> [!WARNING]\n")
            f.write("> **synthetic validation only — not real-world accuracy**\n\n")
        f.write(f"- **Date:** {datetime.date.today().isoformat()}\n")
        f.write(f"- **Evaluated Sarees:** {len(results)}\n")
        f.write(f"- **Warp MAPE:** `{mape_epi:.2f}%` (MAE: `{mae_epi:.2f}` threads/inch, Max: `{max_pct_epi:.2f}%`)\n")
        f.write(f"- **Weft MAPE:** `{mape_ppi:.2f}%` (MAE: `{mae_ppi:.2f}` threads/inch, Max: `{max_pct_ppi:.2f}%`)\n\n")

        f.write("## Per-Saree Breakdown\n\n")
        f.write("| Saree ID | GT Warp | Engine Warp | Warp Err (%) | GT Weft | Engine Weft | Weft Err (%) | Native px/mm |\n")
        f.write("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n")
        for r in results:
            f.write(
                f"| `{r['saree_id']}` | {r['epi_gt']:.1f} | {r['epi_engine']:.1f} | {r['pct_epi']:.2f}% | "
                f"{r['ppi_gt']:.1f} | {r['ppi_engine']:.1f} | {r['pct_ppi']:.2f}% | {r['native_px_per_mm']:.1f} |\n"
            )

        f.write("\n## Scatter Plot\n\n")
        f.write(f"![Thread Count Scatter](count_scatter.png)\n")

    print(f"[eval_count] Successfully generated report: {report_md}")
    return {
        "n_sarees": len(results),
        "mape_epi": mape_epi,
        "mape_ppi": mape_ppi,
        "report_path": str(report_md),
        "scatter_path": str(scatter_png),
    }


def main():
    parser = argparse.ArgumentParser(description="Evaluate thread count against ground truth")
    parser.add_argument("--data-dir", type=str, default="data/count", help="Path to data/count")
    parser.add_argument("--out-dir", type=str, default=None, help="Output directory for reports")
    parser.add_argument("--synthetic", action="store_true", help="Force synthetic evaluation mode")
    args = parser.parse_args()

    date_str = datetime.date.today().strftime("%Y%m%d")
    out_dir = Path(args.out_dir) if args.out_dir else REPO_ROOT / "eval" / "reports" / date_str
    data_dir = Path(args.data_dir)
    if not data_dir.is_absolute():
        data_dir = REPO_ROOT / data_dir

    run_count_evaluation(data_dir=data_dir, out_dir=out_dir, is_synthetic=args.synthetic)


if __name__ == "__main__":
    main()
