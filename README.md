# TantSaakshi — Vision Engine

The vision engine for TantSaakshi turns saree photos into thread density counts (ends & picks per inch), irregularity metrics, defect analysis, quality grading, and unique micro-texture fabric fingerprints for digital handloom provenance verification.

## Python Runtime
- **Required Python version:** Python 3.11+ (tested on Python 3.14.4)
- **Installation:**
  ```bash
  pip install -r requirements-engine.txt
  ```

## Repository Structure
```
├── config.yaml               # Central engine configuration (geometry, thresholds, bands)
├── requirements-engine.txt   # Pinned dependencies
├── engine/                   # Vision engine package
│   ├── config.py             # Config loader
│   ├── card.py               # Marker detection & rectification
│   ├── quality.py            # Quality gates
│   ├── enhance.py            # Multi-frame stacking & flat-field
│   ├── fft_grade.py          # 2D FFT thread density, irregularity, defects, grading
│   ├── fingerprint.py        # Micro-texture extraction (residual & SIFT)
│   ├── match.py              # Fingerprint matcher
│   ├── compat.py             # Backend stub compatibility wrappers
│   ├── debug.py              # Visualization helpers
│   └── tests/                # Unit test suite
├── tools/
│   ├── make_card.py          # Marker card PDF generator
│   ├── synth_fabric.py       # Synthetic woven fabric generator with known ground truth
│   └── run_engine.py         # Batch CLI evaluation tool
└── eval/
    └── reports/              # Reports and generated plots
```

> **Note on evaluation results:** Any evaluations generated using `synth_fabric.py` are **synthetic validation only — not real-world accuracy**. Real-world accuracy is measured exclusively using physical pick-glass ground truth on real saree photographs (under `data/`).

