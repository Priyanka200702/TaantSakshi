"""
tools/run_engine.py
CLI tool to run the TantSaakshi vision engine on a folder of images or bursts.

Usage:
    python tools/run_engine.py <folder> --out out/ --debug out/debug/
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

# Add repo root to sys.path
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from engine import analyze


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run TantSaakshi engine on a directory of saree photos.")
    parser.add_argument("input_folder", help="Directory containing saree photos or bursts")
    parser.add_argument("--out", default="out", help="Directory to save output CSV and metadata")
    parser.add_argument("--debug", default=None, help="Directory to save debug spectrum and overlay images")
    args = parser.parse_args()

    in_dir = Path(args.input_folder)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    debug_dir = Path(args.debug) if args.debug else None
    if debug_dir:
        debug_dir.mkdir(parents=True, exist_ok=True)

    if not in_dir.exists():
        print(f"Error: input folder does not exist: {in_dir}", file=sys.stderr)
        sys.exit(1)

    image_files = sorted([
        f for f in in_dir.iterdir()
        if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS
    ])

    if not image_files:
        print(f"No image files found in {in_dir}")
        sys.exit(0)

    print(f"Found {len(image_files)} image(s) to process...")

    csv_path = out_dir / "results.csv"
    fieldnames = [
        "filename", "ok", "code", "reason",
        "ends_per_inch", "picks_per_inch",
        "warp_angle_deg", "weft_angle_deg",
        "grade", "irregularity_warp", "irregularity_weft",
        "defects_count", "defects_area_fraction",
        "native_px_per_mm", "time_total_ms"
    ]

    results_summary = []

    with open(csv_path, "w", newline="", encoding="utf-8") as csv_fh:
        writer = csv.DictWriter(csv_fh, fieldnames=fieldnames)
        writer.writeheader()

        for idx, img_path in enumerate(image_files, 1):
            print(f"[{idx}/{len(image_files)}] Processing {img_path.name}...")
            img_debug = (debug_dir / img_path.stem) if debug_dir else None

            res = analyze([str(img_path)], out_dir=str(out_dir), debug_dir=str(img_debug) if img_debug else None)

            timings = res.get("timings_ms", {})
            irr = res.get("irregularity", {})
            defects = res.get("defects", {})

            row = {
                "filename": img_path.name,
                "ok": res.get("ok", False),
                "code": res.get("code", "UNKNOWN"),
                "reason": res.get("reason", ""),
                "ends_per_inch": round(res.get("ends_per_inch", 0.0), 2) if res.get("ends_per_inch") else None,
                "picks_per_inch": round(res.get("picks_per_inch", 0.0), 2) if res.get("picks_per_inch") else None,
                "warp_angle_deg": round(res.get("warp_angle_deg", 0.0), 2) if res.get("warp_angle_deg") else None,
                "weft_angle_deg": round(res.get("weft_angle_deg", 0.0), 2) if res.get("weft_angle_deg") else None,
                "grade": res.get("grade"),
                "irregularity_warp": round(irr.get("warp", 0.0), 4) if irr.get("warp") else None,
                "irregularity_weft": round(irr.get("weft", 0.0), 4) if irr.get("weft") else None,
                "defects_count": defects.get("count"),
                "defects_area_fraction": round(defects.get("area_fraction", 0.0), 6) if defects.get("area_fraction") is not None else None,
                "native_px_per_mm": round(res.get("native_px_per_mm", 0.0), 2) if res.get("native_px_per_mm") else None,
                "time_total_ms": round(timings.get("total", 0.0), 2),
            }

            writer.writerow(row)
            results_summary.append(row)

            status = "✓ OK" if row["ok"] else f"✗ FAIL ({row['code']})"
            epi_ppi = f"{row['ends_per_inch']}×{row['picks_per_inch']} tpi" if row["ok"] else row["reason"]
            print(f"    -> {status} | {epi_ppi} | {row['time_total_ms']}ms")

    print(f"\nProcessing complete! Results saved to {csv_path}")


if __name__ == "__main__":
    main()
