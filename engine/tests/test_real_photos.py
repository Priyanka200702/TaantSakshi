"""
engine/tests/test_real_photos.py
Real-photo regression tests (Task 8).

Run only if the JPEG files exist in data/samples/real/.
Skip otherwise with a clear message.

Expected files:
  data/samples/real/20261116_125626.jpeg  → DESIGN_AREA
  data/samples/real/20261116_125914.jpeg  → DESIGN_AREA
  data/samples/real/20261116_130240.jpeg  → ok, red handloom:
      both peaks within ±20° of card axes (0° and 90°),
      ends AND picks in 35–60 tpi range (temporary until hand count provided).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_REAL_DIR = _REPO_ROOT / "data" / "samples" / "real"
_P_DESIGN1 = _REAL_DIR / "20261116_125626.jpeg"
_P_DESIGN2 = _REAL_DIR / "20261116_125914.jpeg"
_P_RED     = _REAL_DIR / "20261116_130240.jpeg"

_ANY_REAL = any(p.exists() for p in [_P_DESIGN1, _P_DESIGN2, _P_RED])

skip_if_no_real = pytest.mark.skipif(
    not _ANY_REAL,
    reason="Real photo samples not found in data/samples/real/ — skipping",
)


def _run_photo(path: Path, debug_dir: Path | None = None) -> dict:
    """Run the full engine pipeline on a single real JPEG photo."""
    from engine._analyze import analyze
    import tempfile

    out_dir = str(debug_dir / "out") if debug_dir else tempfile.mkdtemp()
    dd = str(debug_dir) if debug_dir else None
    return analyze([str(path)], out_dir=out_dir, debug_dir=dd)


# ---------------------------------------------------------------------------
# TC-R1: 125626 → DESIGN_AREA
# ---------------------------------------------------------------------------

@skip_if_no_real
@pytest.mark.skipif(not _P_DESIGN1.exists(), reason=f"File not found: {_P_DESIGN1.name}")
def test_real_design_area_125626(tmp_path):
    """
    Photo 125626: window is on a black printed motif.
    Engine must return DESIGN_AREA (or a gate that fires before it such as NO_CARD,
    BLURRY etc.  — only ok=True with wrong counts is a failure).
    """
    res = _run_photo(_P_DESIGN1)
    assert not res["ok"], (
        f"Expected rejection for 125626 (design area), got ok=True: "
        f"ends={res.get('ends_per_inch')}, picks={res.get('picks_per_inch')}"
    )
    assert res["code"] == "DESIGN_AREA", (
        f"Expected DESIGN_AREA for 125626, got code={res['code']} reason={res.get('reason')}"
    )


# ---------------------------------------------------------------------------
# TC-R2: 125914 → DESIGN_AREA
# ---------------------------------------------------------------------------

@skip_if_no_real
@pytest.mark.skipif(not _P_DESIGN2.exists(), reason=f"File not found: {_P_DESIGN2.name}")
def test_real_design_area_125914(tmp_path):
    """
    Photo 125914: window is on a black printed motif.
    Engine must return DESIGN_AREA.
    """
    res = _run_photo(_P_DESIGN2)
    assert not res["ok"], (
        f"Expected rejection for 125914 (design area), got ok=True: "
        f"ends={res.get('ends_per_inch')}, picks={res.get('picks_per_inch')}"
    )
    assert res["code"] == "DESIGN_AREA", (
        f"Expected DESIGN_AREA for 125914, got code={res['code']} reason={res.get('reason')}"
    )


# ---------------------------------------------------------------------------
# TC-R3: 130240 (red handloom) → ok, correct axis angles, 35–60 tpi
# ---------------------------------------------------------------------------

@skip_if_no_real
@pytest.mark.skipif(not _P_RED.exists(), reason=f"File not found: {_P_RED.name}")
def test_real_red_handloom_130240(tmp_path):
    """
    Photo 130240: plain red handloom fabric with heavy slubs.

    Assertions (temporary until hand count provided):
      - ok=True
      - warp peak angle within ±20° of 0° (card axis)
      - weft peak angle within ±20° of 90° (card axis)
      - ends_per_inch in [35, 60]
      - picks_per_inch in [35, 60]
    """
    debug_dir = tmp_path / "debug_130240"
    debug_dir.mkdir(parents=True, exist_ok=True)

    res = _run_photo(_P_RED, debug_dir=debug_dir)

    assert res["ok"], (
        f"Expected ok=True for 130240 (red handloom), got code={res.get('code')} "
        f"reason={res.get('reason')}"
    )

    epi = res["ends_per_inch"]
    ppi = res["picks_per_inch"]
    warp_ang = res["warp_angle_deg"]
    weft_ang = res["weft_angle_deg"]

    # Angle check: within ±20° of card axes
    # warp: near 0° (or 180° — allow both)
    warp_err = min(abs(warp_ang), abs(abs(warp_ang) - 180))
    assert warp_err <= 20.0, (
        f"warp angle {warp_ang:.1f}° not within ±20° of card axis (0°/180°)"
    )

    # weft: near 90°
    weft_err = abs(abs(weft_ang) - 90)
    assert weft_err <= 20.0, (
        f"weft angle {weft_ang:.1f}° not within ±20° of card axis (90°)"
    )

    # TPI range check (temporary, until hand count provided)
    TPI_LO, TPI_HI = 35, 60
    assert TPI_LO <= epi <= TPI_HI, (
        f"ends_per_inch {epi:.1f} not in [{TPI_LO}, {TPI_HI}] (temporary range)"
    )
    assert TPI_LO <= ppi <= TPI_HI, (
        f"picks_per_inch {ppi:.1f} not in [{TPI_LO}, {TPI_HI}] (temporary range)"
    )

    # Debug images should be present
    assert (debug_dir / "spectrum_peaks.png").exists(), "spectrum_peaks.png not saved"

    # Also check channel used is reported
    quality = res.get("quality", {})
    assert "channel_used" in quality, "channel_used not in quality metrics"

    print(
        f"\n[130240] ok={res['ok']} code={res['code']}\n"
        f"  ends={epi:.1f} picks={ppi:.1f} tpi\n"
        f"  warp_angle={warp_ang:.1f}°  weft_angle={weft_ang:.1f}°\n"
        f"  channel_used={quality.get('channel_used')}\n"
        f"  design_ratio={quality.get('design_energy_ratio', 'n/a')}\n"
        f"  snr_warp={quality.get('peak_snr_warp', 'n/a'):.1f}  "
        f"snr_weft={quality.get('peak_snr_weft', 'n/a'):.1f}"
    )

