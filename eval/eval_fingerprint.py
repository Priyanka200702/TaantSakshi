"""
eval/eval_fingerprint.py
Evaluation script for fabric micro-texture fingerprinting (§9.4 of TANTSAAKSHI_ENGINE_SPEC.md).

Evaluates:
  - All genuine pairs (same saree, different shots / conditions)
  - All impostor pairs (different sarees)
  - Score distributions (masked NCC), histograms, ROC, FAR/FRR curves, EER
  - Breakdown by capture condition (base, refold, light, phone2, phone3, offset2mm, offset2mm_diag, etc.)
  - Determines recommended decision threshold (reported, NOT written to config)
  - Supports --synthetic mode using the physically consistent master-fabric renderer.

Outputs:
  eval/reports/<date>/fingerprint_report.md
  eval/reports/<date>/fp_histogram.png
  eval/reports/<date>/fp_roc.png
  eval/reports/<date>/fp_far_frr.png
  eval/reports/<date>/fp_conditions.png
"""
from __future__ import annotations

import argparse
import datetime
import itertools
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
from engine.config import get_config
from engine.fingerprint import extract_fingerprint
from engine.match import match_fingerprints
from engine.tests.test_fingerprint import _render_phone_photo
from tools.synth_fabric import FabricSpec, make_fabric


def generate_synthetic_fingerprint_dataset(target_dir: Path, n_sarees: int = 5) -> dict[str, list[dict]]:
    """
    Generate synthetic photo dataset from independent master fabrics
    covering all capture conditions.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    dir_gen = target_dir / "genuine"
    dir_imp = target_dir / "impostor"
    dir_gen.mkdir(exist_ok=True)
    dir_imp.mkdir(exist_ok=True)

    master_scale = 60.0
    cfg = get_config()

    conditions = [
        ("base", (0.0, 0.0), 0.0, 30.0, 0.8, 1),
        ("refold", (0.5, 0.3), 1.0, 30.0, 0.8, 2),
        ("light", (0.0, 0.0), 0.0, 30.0, 0.9, 3),
        ("phone2", (0.0, 0.0), 0.0, 22.0, 1.0, 4),
        ("phone3", (0.0, 0.0), 0.0, 38.0, 0.6, 5),
        ("offset1mm", (1.0, 0.0), 0.0, 30.0, 0.8, 6),
        ("offset2mm", (2.0, 0.0), 0.0, 30.0, 0.8, 7),
        ("offset2mm_diag", (2.0, 2.0), 0.0, 30.0, 0.8, 8),
        ("offset3mm", (3.0, 0.0), 0.0, 30.0, 0.8, 9),
        ("rot5deg", (0.0, 0.0), 5.0, 30.0, 0.8, 10),
        ("rot10deg", (0.0, 0.0), 10.0, 30.0, 0.8, 11),
    ]

    items = []
    print(f"[eval_fingerprint] Generating synthetic fabric dataset for {n_sarees} sarees...")

    for s_idx in range(n_sarees):
        sid = f"saree{s_idx + 1:02d}"
        seed_m = 1000 + s_idx * 137
        spec_m = FabricSpec(
            ends_per_inch=68,
            picks_per_inch=68,
            px_per_mm=master_scale,
            window_mm=28.0,
            slub_amplitude=0.25,
            irregularity_jitter=0.07,
            hairiness_sigma=0.06,
            seed=seed_m,
        )
        master_img, _ = make_fabric(spec_m)

        for cond, shift, rot, scale, blur, shot in conditions:
            seed_p = seed_m + shot * 10
            photo = _render_phone_photo(
                master_img,
                master_px_per_mm=master_scale,
                phone_px_per_mm=scale,
                shift_mm=shift,
                rotation_deg=rot,
                blur_sigma_px=blur,
                seed=seed_p,
            )
            phone_tag = f"phone{int(scale)}"
            fname = f"{sid}_{phone_tag}_{cond}_shot{shot}.jpg"
            out_p = dir_gen / fname
            cv2.imwrite(str(out_p), (photo * 255).astype(np.uint8))
            items.append({
                "path": str(out_p),
                "saree_id": sid,
                "phone": phone_tag,
                "condition": cond,
                "shot": shot,
                "scale": scale,
            })

    # Also populate impostor directory with 1 sample per extra impostor saree
    for imp_idx in range(n_sarees, n_sarees + 5):
        sid = f"impostor{imp_idx + 1:02d}"
        seed_m = 9000 + imp_idx * 137
        spec_m = FabricSpec(
            ends_per_inch=68,
            picks_per_inch=68,
            px_per_mm=master_scale,
            window_mm=28.0,
            slub_amplitude=0.25,
            irregularity_jitter=0.07,
            hairiness_sigma=0.06,
            seed=seed_m,
        )
        master_img, _ = make_fabric(spec_m)
        photo = _render_phone_photo(master_img, master_scale, phone_px_per_mm=30.0, seed=seed_m)
        fname = f"{sid}_phone30_shot1.jpg"
        out_p = dir_imp / fname
        cv2.imwrite(str(out_p), (photo * 255).astype(np.uint8))
        items.append({
            "path": str(out_p),
            "saree_id": sid,
            "phone": "phone30",
            "condition": "base",
            "shot": 1,
            "scale": 30.0,
        })

    return items


def collect_images_from_disk(data_dir: Path) -> list[dict]:
    """Scan genuine and impostor directories and parse filenames."""
    items = []
    dir_gen = data_dir / "genuine"
    dir_imp = data_dir / "impostor"

    for p in sorted(list(dir_gen.glob("*.jpg")) + list(dir_gen.glob("*.png"))):
        parts = p.stem.split("_")
        sid = parts[0]
        phone = parts[1] if len(parts) > 1 else "phone1"
        cond = parts[2] if len(parts) > 2 else "base"
        shot = parts[3] if len(parts) > 3 else "1"
        items.append({
            "path": str(p),
            "saree_id": sid,
            "phone": phone,
            "condition": cond,
            "shot": shot,
            "scale": 30.0,
        })

    for p in sorted(list(dir_imp.glob("*.jpg")) + list(dir_imp.glob("*.png"))):
        parts = p.stem.split("_")
        sid = parts[0]
        phone = parts[1] if len(parts) > 1 else "phone1"
        cond = "impostor"
        shot = parts[2] if len(parts) > 2 else "1"
        items.append({
            "path": str(p),
            "saree_id": sid,
            "phone": phone,
            "condition": cond,
            "shot": shot,
            "scale": 30.0,
        })

    return items


def run_fingerprint_evaluation(
    data_dir: Path,
    out_dir: Path,
    is_synthetic: bool = False,
    n_sarees: int = 5,
) -> dict[str, Any]:
    """Execute full genuine vs impostor fingerprint evaluation."""
    out_dir.mkdir(parents=True, exist_ok=True)
    fp_cache_dir = out_dir / "fp_cache"
    fp_cache_dir.mkdir(exist_ok=True)
    cfg = get_config()

    dir_gen = data_dir / "genuine"
    if is_synthetic or not dir_gen.exists() or len(list(dir_gen.glob("*.jpg"))) == 0:
        items = generate_synthetic_fingerprint_dataset(data_dir, n_sarees=n_sarees)
        is_synthetic = True
    else:
        items = collect_images_from_disk(data_dir)

    print(f"[eval_fingerprint] Extracting fingerprints for {len(items)} samples...")
    fingerprints = []
    for idx, item in enumerate(items):
        prefix = f"item_{idx:03d}_{item['saree_id']}_{item['condition']}"
        try:
            fp = extract_fingerprint(
                item["path"],
                out_dir=str(fp_cache_dir),
                cfg=cfg,
                prefix=prefix,
                px_per_mm=item.get("scale"),
            )
            fingerprints.append({**item, "fp": fp})
        except Exception as e:
            print(f"[eval_fingerprint] Skipping {item['path']}: {e}")

    # Build genuine and impostor pairs
    genuine_pairs = []
    impostor_pairs = []

    for i in range(len(fingerprints)):
        for j in range(i + 1, len(fingerprints)):
            f1 = fingerprints[i]
            f2 = fingerprints[j]
            if f1["saree_id"] == f2["saree_id"]:
                # Condition label
                cond = f2["condition"] if f1["condition"] == "base" else f1["condition"]
                genuine_pairs.append((f1, f2, cond))
            else:
                impostor_pairs.append((f1, f2, "impostor"))

    print(f"[eval_fingerprint] Matching {len(genuine_pairs)} genuine pairs and {len(impostor_pairs)} impostor pairs...")

    # Evaluate genuine scores
    gen_results = []
    for f1, f2, cond in genuine_pairs:
        m = match_fingerprints(f1["fp"], f2["fp"], cfg=cfg)
        score = float(m["score_residual"]) if m["score_residual"] is not None else 0.0
        inliers = int(m["inliers"]) if m["inliers"] is not None else 0
        gen_results.append({
            "score": score,
            "inliers": inliers,
            "condition": cond,
            "saree_id": f1["saree_id"],
        })

    # Evaluate impostor scores
    imp_results = []
    # If impostor pairs are very large, sample up to 1000 pairs to avoid excess time
    if len(impostor_pairs) > 1000:
        rng = np.random.default_rng(42)
        sample_indices = rng.choice(len(impostor_pairs), size=1000, replace=False)
        sub_imp = [impostor_pairs[idx] for idx in sample_indices]
    else:
        sub_imp = impostor_pairs

    for f1, f2, cond in sub_imp:
        m = match_fingerprints(f1["fp"], f2["fp"], cfg=cfg)
        score = float(m["score_residual"]) if m["score_residual"] is not None else 0.0
        inliers = int(m["inliers"]) if m["inliers"] is not None else 0
        imp_results.append({
            "score": score,
            "inliers": inliers,
            "condition": cond,
        })

    gen_scores = np.array([r["score"] for r in gen_results])
    imp_scores = np.array([r["score"] for r in imp_results])

    # Threshold sweep: [-0.2, 1.0]
    thresholds = np.linspace(-0.2, 1.0, 600)
    far_list = []
    frr_list = []
    tpr_list = []

    for th in thresholds:
        far = np.mean(imp_scores >= th)
        frr = np.mean(gen_scores < th)
        tpr = 1.0 - frr
        far_list.append(far)
        frr_list.append(frr)
        tpr_list.append(tpr)

    far_arr = np.array(far_list)
    frr_arr = np.array(frr_list)
    tpr_arr = np.array(tpr_list)

    # Compute EER
    diffs = np.abs(far_arr - frr_arr)
    eer_idx = int(np.argmin(diffs))
    eer_thresh = float(thresholds[eer_idx])
    eer_val = float((far_arr[eer_idx] + frr_arr[eer_idx]) / 2.0)

    # Recommended decision threshold:
    # Selected where FAR = 0.0% (zero impostor false acceptance) with high genuine acceptance
    zero_far_indices = np.where(far_arr == 0.0)[0]
    if len(zero_far_indices) > 0:
        rec_idx = zero_far_indices[0]  # lowest threshold that gives FAR = 0
        rec_thresh = float(thresholds[rec_idx])
    else:
        rec_thresh = eer_thresh

    rec_far = float(np.mean(imp_scores >= rec_thresh)) * 100.0
    rec_frr = float(np.mean(gen_scores < rec_thresh)) * 100.0

    # Condition Breakdown Table
    cond_stats = {}
    for r in gen_results:
        c = r["condition"]
        cond_stats.setdefault(c, []).append(r["score"])

    # 1. Histogram plot
    plt.figure(figsize=(9, 5))
    tag = " (Synthetic Validation Only — Not Real-World Accuracy)" if is_synthetic else ""
    bins = np.linspace(-0.2, 1.0, 60)
    plt.hist(imp_scores, bins=bins, alpha=0.6, color="crimson", label=f"Impostor (N={len(imp_scores)})", density=True)
    plt.hist(gen_scores, bins=bins, alpha=0.6, color="forestgreen", label=f"Genuine (N={len(gen_scores)})", density=True)
    plt.axvline(rec_thresh, color="blue", linestyle="--", linewidth=2, label=f"Recommended Threshold ({rec_thresh:.2f})")
    plt.axvline(eer_thresh, color="black", linestyle=":", linewidth=2, label=f"EER Threshold ({eer_thresh:.2f})")
    plt.xlabel("Masked Normalized Cross-Correlation (NCC)")
    plt.ylabel("Density")
    plt.title(f"TantSaakshi Fingerprint Score Distribution{tag}")
    plt.legend(loc="upper right")
    plt.grid(True, linestyle=":", alpha=0.6)
    hist_png = out_dir / "fp_histogram.png"
    plt.tight_layout()
    plt.savefig(hist_png, dpi=200)
    plt.close()

    # 2. ROC Curve
    plt.figure(figsize=(6, 6))
    plt.plot(far_arr, tpr_arr, color="darkorange", lw=2, label="ROC Curve")
    plt.plot([0, 1], [0, 1], color="navy", lw=1.5, linestyle="--")
    plt.scatter([far_arr[eer_idx]], [tpr_arr[eer_idx]], color="red", zorder=5, label=f"EER = {eer_val*100:.2f}%")
    plt.xlim([-0.02, 1.02])
    plt.ylim([-0.02, 1.02])
    plt.xlabel("False Accept Rate (FAR)")
    plt.ylabel("True Accept Rate (TAR = 1 - FRR)")
    plt.title(f"Fingerprint ROC Curve{tag}")
    plt.legend(loc="lower right")
    plt.grid(True, linestyle=":", alpha=0.6)
    roc_png = out_dir / "fp_roc.png"
    plt.tight_layout()
    plt.savefig(roc_png, dpi=200)
    plt.close()

    # 3. FAR / FRR vs Threshold Curve
    plt.figure(figsize=(8, 5))
    plt.plot(thresholds, far_arr * 100.0, color="crimson", lw=2, label="FAR (%)")
    plt.plot(thresholds, frr_arr * 100.0, color="forestgreen", lw=2, label="FRR (%)")
    plt.axvline(eer_thresh, color="black", linestyle=":", label=f"EER Thresh = {eer_thresh:.2f}")
    plt.axvline(rec_thresh, color="blue", linestyle="--", label=f"Rec Thresh = {rec_thresh:.2f}")
    plt.xlabel("Decision Threshold (NCC)")
    plt.ylabel("Error Rate (%)")
    plt.title(f"FAR & FRR vs. Decision Threshold{tag}")
    plt.legend(loc="center right")
    plt.grid(True, linestyle=":", alpha=0.6)
    plt.ylim([-2, 102])
    far_frr_png = out_dir / "fp_far_frr.png"
    plt.tight_layout()
    plt.savefig(far_frr_png, dpi=200)
    plt.close()

    # 4. Conditions breakdown plot
    cond_labels = sorted(list(cond_stats.keys()))
    means = [float(np.mean(cond_stats[c])) for c in cond_labels]
    mins = [float(np.min(cond_stats[c])) for c in cond_labels]
    maxs = [float(np.max(cond_stats[c])) for c in cond_labels]

    plt.figure(figsize=(10, 5))
    y_pos = np.arange(len(cond_labels))
    plt.barh(y_pos, means, xerr=[np.array(means) - np.array(mins), np.array(maxs) - np.array(means)], align="center", alpha=0.7, color="teal", ecolor="black", capsize=4)
    plt.axvline(rec_thresh, color="blue", linestyle="--", label=f"Rec Threshold ({rec_thresh:.2f})")
    plt.yticks(y_pos, cond_labels)
    plt.xlabel("Masked NCC")
    plt.title(f"Genuine Fingerprint Score by Condition (Mean & Range){tag}")
    plt.legend(loc="lower right")
    plt.grid(True, linestyle=":", alpha=0.6)
    plt.xlim([0.0, 1.0])
    cond_png = out_dir / "fp_conditions.png"
    plt.tight_layout()
    plt.savefig(cond_png, dpi=200)
    plt.close()

    # Markdown Report
    report_md = out_dir / "fingerprint_report.md"
    with open(report_md, "w", encoding="utf-8") as f:
        f.write("# TantSaakshi Fingerprint Matching & Calibration Report\n\n")
        if is_synthetic:
            f.write("> [!WARNING]\n")
            f.write("> **synthetic validation only — not real-world accuracy**\n\n")

        f.write(f"- **Evaluation Date:** {datetime.date.today().isoformat()}\n")
        f.write(f"- **Total Genuine Pairs:** {len(gen_scores)}\n")
        f.write(f"- **Total Impostor Pairs:** {len(imp_scores)}\n")
        f.write(f"- **Genuine NCC Range:** `[{float(np.min(gen_scores)):.4f}, {float(np.max(gen_scores)):.4f}]` (Mean: `{float(np.mean(gen_scores)):.4f}`)\n")
        f.write(f"- **Impostor NCC Range:** `[{float(np.min(imp_scores)):.4f}, {float(np.max(imp_scores)):.4f}]` (Mean: `{float(np.mean(imp_scores)):.4f}`)\n")
        f.write(f"- **Equal Error Rate (EER):** `{eer_val * 100.0:.2f}%` (at threshold `{eer_thresh:.3f}`)\n\n")

        f.write("## Recommended Decision Threshold\n\n")
        f.write(f"> [!IMPORTANT]\n")
        f.write(f"> **Recommended NCC Threshold:** `match_threshold_residual: {rec_thresh:.2f}`\n")
        f.write(f"> - **At this threshold:** False Accept Rate (FAR) = `{rec_far:.2f}%`, False Reject Rate (FRR) = `{rec_frr:.2f}%`.\n")
        f.write(f"> - **NOTE:** As per protocol, do NOT write this into `config.yaml` until real field photos are verified.\n\n")

        f.write("## Condition Breakdown\n\n")
        f.write("| Condition | N Pairs | Mean NCC | Min NCC | Max NCC | FRR @ Rec Thresh |\n")
        f.write("| :--- | :---: | :---: | :---: | :---: | :---: |\n")
        for c in cond_labels:
            scores_c = np.array(cond_stats[c])
            frr_c = np.mean(scores_c < rec_thresh) * 100.0
            f.write(f"| `{c}` | {len(scores_c)} | {float(np.mean(scores_c)):.4f} | {float(np.min(scores_c)):.4f} | {float(np.max(scores_c)):.4f} | {frr_c:.1f}% |\n")

        f.write("\n## Evaluation Plots\n\n")
        f.write("### Score Distribution Histogram\n")
        f.write("![Score Distribution Histogram](fp_histogram.png)\n\n")
        f.write("### ROC Curve\n")
        f.write("![ROC Curve](fp_roc.png)\n\n")
        f.write("### FAR & FRR vs. Threshold\n")
        f.write("![FAR/FRR vs Threshold](fp_far_frr.png)\n\n")
        f.write("### Breakdown by Condition\n")
        f.write("![Condition Breakdown](fp_conditions.png)\n")

    print(f"[eval_fingerprint] Report generated successfully: {report_md}")
    return {
        "n_genuine": len(gen_scores),
        "n_impostor": len(imp_scores),
        "recommended_threshold": rec_thresh,
        "eer": eer_val,
        "report_path": str(report_md),
    }


def main():
    parser = argparse.ArgumentParser(description="Evaluate fabric fingerprint matching")
    parser.add_argument("--data-dir", type=str, default="data/fingerprint", help="Path to data/fingerprint")
    parser.add_argument("--out-dir", type=str, default=None, help="Output directory for reports")
    parser.add_argument("--synthetic", action="store_true", help="Force synthetic evaluation mode")
    parser.add_argument("--n-sarees", type=int, default=5, help="Number of synthetic sarees to generate")
    args = parser.parse_args()

    date_str = datetime.date.today().strftime("%Y%m%d")
    out_dir = Path(args.out_dir) if args.out_dir else REPO_ROOT / "eval" / "reports" / date_str
    data_dir = Path(args.data_dir)
    if not data_dir.is_absolute():
        data_dir = REPO_ROOT / data_dir

    run_fingerprint_evaluation(
        data_dir=data_dir,
        out_dir=out_dir,
        is_synthetic=args.synthetic,
        n_sarees=args.n_sarees,
    )


if __name__ == "__main__":
    main()
