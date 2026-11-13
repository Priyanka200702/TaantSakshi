"""
eval/eval_quality.py
Evaluation script for image quality rejection gates (§9.4 of TANTSAAKSHI_ENGINE_SPEC.md).

Validates the 9 priority rejection gates:
  1. NO_CARD (markers obscured, truncated, or absent)
  2. TOO_TILTED (perspective tilt > 25°)
  3. LOW_RES (native resolution < 20 px/mm)
  4. TOO_DARK (> 30% underexposed pixels)
  5. GLARE (> 2% saturated glare pixels)
  6. BLURRY (variance of Laplacian on window < 60)
  7. ALIASING (spatial resolution < 4.0 px/thread)
  8. NO_WEAVE (no periodic peaks found or peak SNR < 8.0)
  9. DESIGN_AREA (low-frequency pattern energy > 50% thread energy)
 10. OK (clean, sharp, well-lit valid registration photo)

Outputs:
  eval/reports/<date>/quality_report.md
  eval/reports/<date>/quality_confusion.png
"""
from __future__ import annotations

import argparse
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

import cv2
from engine._analyze import analyze, quality_check
from engine.config import get_config
from tools.synth_fabric import FabricSpec, make_card_scene, to_uint8


def create_synthetic_quality_samples(target_dir: Path) -> list[dict]:
    """Generate representative test scenes for each quality failure mode."""
    target_dir.mkdir(parents=True, exist_ok=True)
    cfg = get_config()
    samples = []

    spec_base = FabricSpec(ends_per_inch=60, picks_per_inch=60, noise_sigma=0.01)

    # 1. OK (Clean valid photo)
    sc, _ = make_card_scene(spec_base, cfg, tilt_deg=0.0, camera_px_per_mm=30.0, seed=1)
    p = target_dir / "case_01_OK.png"
    cv2.imwrite(str(p), to_uint8(sc))
    samples.append({"path": str(p), "expected_code": "OK"})

    # 2. NO_CARD (plain background, no markers)
    noise_img = np.full((1200, 1200, 3), 128, dtype=np.uint8)
    p = target_dir / "case_02_NO_CARD.png"
    cv2.imwrite(str(p), noise_img)
    samples.append({"path": str(p), "expected_code": "NO_CARD"})

    # 3. TOO_TILTED (32 deg tilt exceeds max 25 deg)
    sc, _ = make_card_scene(spec_base, cfg, tilt_deg=32.0, camera_px_per_mm=30.0, seed=2)
    p = target_dir / "case_03_TOO_TILTED.png"
    cv2.imwrite(str(p), to_uint8(sc))
    samples.append({"path": str(p), "expected_code": "TOO_TILTED"})

    # 4. LOW_RES (camera_px_per_mm = 14 is below min 20 px/mm)
    sc, _ = make_card_scene(spec_base, cfg, tilt_deg=0.0, camera_px_per_mm=14.0, seed=3)
    p = target_dir / "case_04_LOW_RES.png"
    cv2.imwrite(str(p), to_uint8(sc))
    samples.append({"path": str(p), "expected_code": "LOW_RES"})

    # 5. TOO_DARK (underexposed window)
    sc, _ = make_card_scene(spec_base, cfg, tilt_deg=0.0, camera_px_per_mm=30.0, seed=4)
    dark_img = to_uint8(sc)
    H, W = dark_img.shape[:2]
    win_half = int(9.5 * 30.0)
    dark_img[H // 2 - win_half : H // 2 + win_half, W // 2 - win_half : W // 2 + win_half] = 15
    p = target_dir / "case_05_TOO_DARK.png"
    cv2.imwrite(str(p), dark_img)
    samples.append({"path": str(p), "expected_code": "TOO_DARK"})

    # 6. GLARE (large saturated spot inside window)
    sc, _ = make_card_scene(spec_base, cfg, tilt_deg=0.0, camera_px_per_mm=30.0, seed=5)
    u8 = to_uint8(sc)
    H, W = u8.shape[:2]
    cv2.circle(u8, (W // 2, H // 2), radius=80, color=(255, 255, 255), thickness=-1)
    p = target_dir / "case_06_GLARE.png"
    cv2.imwrite(str(p), u8)
    samples.append({"path": str(p), "expected_code": "GLARE"})

    # 7. BLURRY (defocused fabric window)
    sc, _ = make_card_scene(spec_base, cfg, tilt_deg=0.0, camera_px_per_mm=30.0, seed=6)
    u8 = to_uint8(sc)
    H, W = u8.shape[:2]
    win_half = int(9.5 * 30.0)
    patch = u8[H // 2 - win_half : H // 2 + win_half, W // 2 - win_half : W // 2 + win_half]
    u8[H // 2 - win_half : H // 2 + win_half, W // 2 - win_half : W // 2 + win_half] = cv2.GaussianBlur(patch, (0, 0), sigmaX=8.0)
    p = target_dir / "case_07_BLURRY.png"
    cv2.imwrite(str(p), u8)
    samples.append({"path": str(p), "expected_code": "BLURRY"})

    # 8. ALIASING (high density 180 ends/inch @ 22 px/mm -> px/thread < 4)
    spec_dense = FabricSpec(ends_per_inch=180.0, picks_per_inch=180.0)
    sc, _ = make_card_scene(spec_dense, cfg, tilt_deg=0.0, camera_px_per_mm=22.0, seed=7)
    p = target_dir / "case_08_ALIASING.png"
    cv2.imwrite(str(p), to_uint8(sc))
    samples.append({"path": str(p), "expected_code": "ALIASING"})

    # 9. NO_WEAVE (noise patch replacing window)
    sc, _ = make_card_scene(spec_base, cfg, tilt_deg=0.0, camera_px_per_mm=30.0, seed=8)
    u8 = to_uint8(sc)
    H, W = u8.shape[:2]
    win_half = int(9.5 * 30.0)
    rng = np.random.default_rng(123)
    noise_patch = rng.integers(110, 140, (2 * win_half, 2 * win_half), dtype=np.uint8)
    u8[H // 2 - win_half : H // 2 + win_half, W // 2 - win_half : W // 2 + win_half] = noise_patch
    p = target_dir / "case_09_NO_WEAVE.png"
    cv2.imwrite(str(p), u8)
    samples.append({"path": str(p), "expected_code": "NO_WEAVE"})

    # 10. DESIGN_AREA (large low-frequency stripes across window)
    sc, _ = make_card_scene(spec_base, cfg, tilt_deg=0.0, camera_px_per_mm=30.0, seed=9)
    u8 = to_uint8(sc)
    H, W = u8.shape[:2]
    win_half = int(9.5 * 30.0)
    yy, xx = np.ogrid[: 2 * win_half, : 2 * win_half]
    stripe = (np.sin(2 * np.pi * xx / 150.0) * 80).astype(np.int16)
    patch = u8[H // 2 - win_half : H // 2 + win_half, W // 2 - win_half : W // 2 + win_half].astype(np.int16)
    u8[H // 2 - win_half : H // 2 + win_half, W // 2 - win_half : W // 2 + win_half] = np.clip(patch + stripe, 10, 240).astype(np.uint8)
    p = target_dir / "case_10_DESIGN_AREA.png"
    cv2.imwrite(str(p), u8)
    samples.append({"path": str(p), "expected_code": "DESIGN_AREA"})

    return samples


def run_quality_evaluation(
    data_dir: Path,
    out_dir: Path,
    is_synthetic: bool = False,
) -> dict[str, Any]:
    """Execute quality evaluation across all rejection gates."""
    out_dir.mkdir(parents=True, exist_ok=True)
    all_codes = ["OK", "NO_CARD", "TOO_TILTED", "LOW_RES", "TOO_DARK", "GLARE", "BLURRY", "ALIASING", "NO_WEAVE", "DESIGN_AREA"]

    image_files = list(data_dir.glob("*.jpg")) + list(data_dir.glob("*.png"))
    if is_synthetic or len(image_files) == 0:
        samples = create_synthetic_quality_samples(data_dir)
        is_synthetic = True
    else:
        samples = []
        for p in image_files:
            # Infer expected code from filename if present
            exp = "OK"
            for code in all_codes:
                if code.lower() in p.stem.lower():
                    exp = code
                    break
            samples.append({"path": str(p), "expected_code": exp})

    results = []
    tmp_out = out_dir / "tmp_an"
    tmp_out.mkdir(exist_ok=True)

    print(f"[eval_quality] Evaluating quality gates across {len(samples)} test cases...")
    for s in samples:
        res = analyze([s["path"]], out_dir=str(tmp_out))
        pred_code = res.get("code", "UNKNOWN")
        passed = (pred_code == s["expected_code"])
        results.append({
            "path": s["path"],
            "expected_code": s["expected_code"],
            "predicted_code": pred_code,
            "reason": res.get("reason", ""),
            "passed": passed,
        })

    # Confusion Matrix
    conf_matrix = np.zeros((len(all_codes), len(all_codes)), dtype=int)
    code_to_idx = {c: i for i, c in enumerate(all_codes)}

    for r in results:
        exp_i = code_to_idx.get(r["expected_code"], 0)
        pred_i = code_to_idx.get(r["predicted_code"], 0)
        conf_matrix[exp_i, pred_i] += 1

    total_correct = sum(1 for r in results if r["passed"])
    overall_accuracy = (total_correct / len(results)) * 100.0

    # Confusion Matrix Plot
    plt.figure(figsize=(9, 8))
    tag = " (Synthetic Validation Only — Not Real-World Accuracy)" if is_synthetic else ""
    plt.imshow(conf_matrix, interpolation="nearest", cmap=plt.cm.Blues)
    plt.title(f"Quality Rejection Gate Confusion Matrix\nOverall Accuracy: {overall_accuracy:.1f}%{tag}")
    plt.colorbar()

    tick_marks = np.arange(len(all_codes))
    plt.xticks(tick_marks, all_codes, rotation=45, ha="right")
    plt.yticks(tick_marks, all_codes)
    plt.xlabel("Predicted Gate Code")
    plt.ylabel("Expected Gate Code")

    thresh = conf_matrix.max() / 2.0
    for i in range(len(all_codes)):
        for j in range(len(all_codes)):
            val = conf_matrix[i, j]
            plt.text(j, i, str(val), horizontalalignment="center", color="white" if val > thresh else "black")

    conf_png = out_dir / "quality_confusion.png"
    plt.tight_layout()
    plt.savefig(conf_png, dpi=200)
    plt.close()

    # Markdown Report
    report_md = out_dir / "quality_report.md"
    with open(report_md, "w", encoding="utf-8") as f:
        f.write("# TantSaakshi Image Quality Rejection Gate Evaluation\n\n")
        if is_synthetic:
            f.write("> [!WARNING]\n")
            f.write("> **synthetic validation only — not real-world accuracy**\n\n")

        f.write(f"- **Evaluation Date:** {datetime.date.today().isoformat()}\n")
        f.write(f"- **Total Test Cases:** {len(results)}\n")
        f.write(f"- **Overall Gate Accuracy:** `{overall_accuracy:.1f}%` ({total_correct}/{len(results)})\n\n")

        f.write("## Test Case Breakdown\n\n")
        f.write("| Test Case | Expected Code | Predicted Code | Status | Reason / Guidance |\n")
        f.write("| :--- | :---: | :---: | :---: | :--- |\n")
        for r in results:
            fname = Path(r["path"]).name
            status = "✅ PASS" if r["passed"] else "❌ FAIL"
            f.write(f"| `{fname}` | `{r['expected_code']}` | `{r['predicted_code']}` | {status} | {r['reason']} |\n")

        f.write("\n## Confusion Matrix\n\n")
        f.write("![Quality Gate Confusion Matrix](quality_confusion.png)\n")

    print(f"[eval_quality] Report generated successfully: {report_md}")
    return {
        "overall_accuracy": overall_accuracy,
        "n_samples": len(results),
        "report_path": str(report_md),
    }


def main():
    parser = argparse.ArgumentParser(description="Evaluate quality rejection gates")
    parser.add_argument("--data-dir", type=str, default="data/quality", help="Path to data/quality")
    parser.add_argument("--out-dir", type=str, default=None, help="Output directory for reports")
    parser.add_argument("--synthetic", action="store_true", help="Force synthetic evaluation mode")
    args = parser.parse_args()

    date_str = datetime.date.today().strftime("%Y%m%d")
    out_dir = Path(args.out_dir) if args.out_dir else REPO_ROOT / "eval" / "reports" / date_str
    data_dir = Path(args.data_dir)
    if not data_dir.is_absolute():
        data_dir = REPO_ROOT / data_dir

    run_quality_evaluation(data_dir=data_dir, out_dir=out_dir, is_synthetic=args.synthetic)


if __name__ == "__main__":
    main()
