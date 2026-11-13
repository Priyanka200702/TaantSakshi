# TantSaakshi Fingerprint Matching & Calibration Report

> [!WARNING]
> **synthetic validation only — not real-world accuracy**

- **Evaluation Date:** 2026-11-13
- **Total Genuine Pairs:** 165
- **Total Impostor Pairs:** 538
- **Genuine NCC Range:** `[0.6978, 0.8500]` (Mean: `0.7796`)
- **Impostor NCC Range:** `[-0.0023, 0.2780]` (Mean: `0.0619`)
- **Equal Error Rate (EER):** `0.00%` (at threshold `0.279`)

## Recommended Decision Threshold

> [!IMPORTANT]
> **Recommended NCC Threshold:** `match_threshold_residual: 0.28`
> - **At this threshold:** False Accept Rate (FAR) = `0.00%`, False Reject Rate (FRR) = `0.00%`.
> - **NOTE:** As per protocol, do NOT write this into `config.yaml` until real field photos are verified.

## Condition Breakdown

| Condition | N Pairs | Mean NCC | Min NCC | Max NCC | FRR @ Rec Thresh |
| :--- | :---: | :---: | :---: | :---: | :---: |
| `light` | 27 | 0.7966 | 0.7368 | 0.8500 | 0.0% |
| `offset1mm` | 18 | 0.7862 | 0.7486 | 0.8127 | 0.0% |
| `offset2mm` | 15 | 0.7827 | 0.7641 | 0.8048 | 0.0% |
| `offset2mm_diag` | 12 | 0.7625 | 0.7424 | 0.7958 | 0.0% |
| `offset3mm` | 9 | 0.7799 | 0.7629 | 0.7940 | 0.0% |
| `phone2` | 24 | 0.7386 | 0.6978 | 0.7810 | 0.0% |
| `phone3` | 21 | 0.8176 | 0.7726 | 0.8472 | 0.0% |
| `refold` | 30 | 0.7668 | 0.7107 | 0.8276 | 0.0% |
| `rot10deg` | 3 | 0.7943 | 0.7882 | 0.8046 | 0.0% |
| `rot5deg` | 6 | 0.7954 | 0.7936 | 0.7971 | 0.0% |

## Evaluation Plots

### Score Distribution Histogram
![Score Distribution Histogram](fp_histogram.png)

### ROC Curve
![ROC Curve](fp_roc.png)

### FAR & FRR vs. Threshold
![FAR/FRR vs Threshold](fp_far_frr.png)

### Breakdown by Condition
![Condition Breakdown](fp_conditions.png)
