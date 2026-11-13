"""
tools/make_card.py
Generates a printable PDF of the TantSaakshi marker card.

Usage:
    python tools/make_card.py                   # writes tools/marker_card.pdf
    python tools/make_card.py --out my_card.pdf

Card geometry (all values from config.yaml, never hard-coded here):
    card_size_mm = window_mm + 2*(marker_gap_mm + marker_size_mm) + 2*margin_mm
                 = 20 + 2*(3+8) + 2*4 = 50 mm square

The PDF is at true scale (A4). Print at 100% and verify the 10 mm scale bar = 10 mm.
Tiles 4 cards per page with a gap between them.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Make sure the repo root is importable when running as a script
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import cv2
import numpy as np
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.pdfgen import canvas as rl_canvas

from engine.config import get_config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _generate_aruco_marker(dictionary_id: int, marker_id: int, size_px: int) -> np.ndarray:
    """Return a grayscale ArUco marker image (uint8, size_px × size_px)."""
    aruco_dict = cv2.aruco.getPredefinedDictionary(dictionary_id)
    img = cv2.aruco.generateImageMarker(aruco_dict, marker_id, size_px)
    return img


def _aruco_dict_id(name: str) -> int:
    """Convert config string like 'DICT_4X4_50' to the cv2.aruco integer ID."""
    attr = getattr(cv2.aruco, name, None)
    if attr is None:
        raise ValueError(
            f"Unknown ArUco dictionary '{name}'. "
            "Check config.yaml card.aruco_dict."
        )
    return int(attr)


def _np_to_pdf_image(img_gray: np.ndarray, canvas: rl_canvas.Canvas,
                     x_pt: float, y_pt: float, size_pt: float) -> None:
    """Draw a grayscale numpy array as a PDF image at (x_pt, y_pt) with given size_pt."""
    # ReportLab expects an image file or PIL image; use a temporary PNG in memory.
    import io
    from PIL import Image as PILImage
    pil = PILImage.fromarray(img_gray)
    buf = io.BytesIO()
    pil.save(buf, format="PNG")
    buf.seek(0)
    canvas.drawImage(
        canvas._doc.filename if False else buf,  # type: ignore[arg-type]
        x_pt, y_pt, width=size_pt, height=size_pt,
        mask="auto",
    )


# ---------------------------------------------------------------------------
# Card drawing — one card at a time, in PDF user-space points
# ---------------------------------------------------------------------------

def draw_card(
    c: rl_canvas.Canvas,
    origin_x_pt: float,
    origin_y_pt: float,
    cfg: dict,
) -> None:
    """
    Draw a single marker card with origin at (origin_x_pt, origin_y_pt).

    Card coordinate convention (PDF y-axis points up):
        origin is at the BOTTOM-LEFT of the card's outer margin.

    Layout (all in mm, converted to points = mm × 72/25.4):
        margin_mm         outer margin
        marker_size_mm    ArUco marker squares
        marker_gap_mm     gap between marker inner edge and window edge
        window_mm         cut-out window (the measurement area)

    Marker positions (corners, clockwise from TL):
        TL (id=0): top-left    TR (id=1): top-right
        BR (id=2): bottom-right BL (id=3): bottom-left
    """
    card_cfg = cfg["card"]
    window_mm_val: float  = card_cfg["window_mm"]
    marker_size: float    = card_cfg["marker_size_mm"]
    gap: float            = card_cfg["marker_gap_mm"]
    margin: float         = card_cfg["margin_mm"]
    marker_ids: list[int] = card_cfg["marker_ids"]
    dict_name: str        = card_cfg["aruco_dict"]

    card_size = window_mm_val + 2 * (gap + marker_size) + 2 * margin
    # In PDF points (1 pt = 1/72 inch = 25.4/72 mm)
    PT = mm  # reportlab's mm constant converts mm → points

    card_pt   = card_size    * PT
    window_pt = window_mm_val * PT
    marker_pt = marker_size  * PT
    gap_pt    = gap          * PT
    margin_pt = margin       * PT

    # Derived positions from bottom-left of card
    # Window left edge = margin + marker_size + gap
    win_left   = margin_pt + marker_pt + gap_pt
    win_bottom = margin_pt + marker_pt + gap_pt
    # (symmetric: window is centred)

    # ---- Outer card border ------------------------------------------------
    c.setStrokeColor(colors.black)
    c.setLineWidth(0.5)
    c.rect(origin_x_pt, origin_y_pt, card_pt, card_pt, stroke=1, fill=0)

    # ---- Cut-line window (dashed red) -------------------------------------
    c.setStrokeColor(colors.red)
    c.setLineWidth(0.8)
    c.setDash([3, 3])
    c.rect(
        origin_x_pt + win_left,
        origin_y_pt + win_bottom,
        window_pt,
        window_pt,
        stroke=1, fill=0,
    )
    c.setDash([])  # reset dash

    # ---- ArUco markers ----------------------------------------------------
    # Marker centres (clockwise from TL):
    #   TL: left = margin,  top = card_size - margin - marker_size  (PDF: bottom = card_size - margin - marker_size)
    #   TR: left = card_size - margin - marker_size,  same top
    #   BR: same left as TR,  bottom = margin
    #   BL: same left as TL,  bottom = margin
    marker_px = 200  # resolution for ArUco image generation (doesn't affect PDF scale)
    dict_id = _aruco_dict_id(dict_name)

    # (corner_x_mm, corner_y_mm) in card coordinate (0,0 = bottom-left)
    marker_corners_mm = [
        # TL (id=0)
        (margin, card_size - margin - marker_size),
        # TR (id=1)
        (card_size - margin - marker_size, card_size - margin - marker_size),
        # BR (id=2)
        (card_size - margin - marker_size, margin),
        # BL (id=3)
        (margin, margin),
    ]

    for idx, mid in enumerate(marker_ids):
        mx_mm, my_mm = marker_corners_mm[idx]
        mx_pt = origin_x_pt + mx_mm * PT
        my_pt = origin_y_pt + my_mm * PT

        img = _generate_aruco_marker(dict_id, mid, marker_px)

        # ReportLab drawImage with ImageReader accepts PIL images directly
        from PIL import Image as PILImage
        from reportlab.lib.utils import ImageReader
        pil_img = PILImage.fromarray(img)
        c.drawImage(ImageReader(pil_img), mx_pt, my_pt, width=marker_pt, height=marker_pt, mask="auto")

        # Marker ID label (small, below each marker)
        c.setFont("Helvetica", 5)
        c.setFillColor(colors.black)
        label_y = my_pt - 6 if my_mm < card_size / 2 else my_pt + marker_pt + 1
        c.drawCentredString(mx_pt + marker_pt / 2, label_y, f"ID {mid}")

    # ---- "CUT HERE" label for the window ----------------------------------
    c.setFont("Helvetica", 5)
    c.setFillColor(colors.red)
    c.drawCentredString(
        origin_x_pt + win_left + window_pt / 2,
        origin_y_pt + win_bottom + window_pt + 2,
        "CUT OUT (measurement window)",
    )

    # ---- Notch on the LEFT edge (where QR tag butts) ----------------------
    # Draw a small filled triangle at the left edge, vertically centred
    notch_size = 3 * PT  # 3 mm notch
    notch_x = origin_x_pt
    notch_y = origin_y_pt + card_pt / 2
    p = c.beginPath()
    p.moveTo(notch_x, notch_y)
    p.lineTo(notch_x + notch_size, notch_y + notch_size / 2)
    p.lineTo(notch_x + notch_size, notch_y - notch_size / 2)
    p.close()
    c.setFillColor(colors.black)
    c.drawPath(p, fill=1, stroke=0)

    # ---- Arrow "↑ along saree length" (warp direction) -------------------
    # Drawn in the right margin, vertically centred
    arrow_x = origin_x_pt + card_pt - margin_pt / 2
    arrow_cy = origin_y_pt + card_pt / 2
    arrow_len = 12 * PT
    c.setStrokeColor(colors.black)
    c.setLineWidth(1)
    c.line(arrow_x, arrow_cy - arrow_len / 2, arrow_x, arrow_cy + arrow_len / 2)
    # Arrowhead (up)
    ah = 2 * PT
    c.line(arrow_x, arrow_cy + arrow_len / 2, arrow_x - ah, arrow_cy + arrow_len / 2 - ah)
    c.line(arrow_x, arrow_cy + arrow_len / 2, arrow_x + ah, arrow_cy + arrow_len / 2 - ah)
    c.setFont("Helvetica", 5)
    c.setFillColor(colors.black)
    c.saveState()
    c.translate(arrow_x + 3 * PT, arrow_cy)
    c.rotate(90)
    c.drawCentredString(0, 0, "↑ along saree length (warp)")
    c.restoreState()

    # ---- 10 mm scale bar --------------------------------------------------
    # Place below the window, centred horizontally
    bar_len = 10 * PT  # exactly 10 mm
    bar_x = origin_x_pt + win_left + (window_pt - bar_len) / 2
    bar_y = origin_y_pt + win_bottom - 7 * PT
    c.setStrokeColor(colors.black)
    c.setLineWidth(1)
    c.line(bar_x, bar_y, bar_x + bar_len, bar_y)
    # Tick marks at each end
    tick = 1.5 * PT
    c.line(bar_x, bar_y - tick, bar_x, bar_y + tick)
    c.line(bar_x + bar_len, bar_y - tick, bar_x + bar_len, bar_y + tick)
    c.setFont("Helvetica", 5)
    c.setFillColor(colors.black)
    c.drawCentredString(bar_x + bar_len / 2, bar_y - 5, "10 mm")

    # ---- Main text --------------------------------------------------------
    c.setFont("Helvetica-Bold", 6)
    c.setFillColor(colors.black)
    c.drawCentredString(
        origin_x_pt + card_pt / 2,
        origin_y_pt + 1.5 * PT,
        "TantSaakshi marker card  |  Print at 100% — check scale bar = 10 mm",
    )


# ---------------------------------------------------------------------------
# PDF generation
# ---------------------------------------------------------------------------

def make_card_pdf(out_path: Path, cfg: dict) -> None:
    """Generate a PDF with 4 marker cards per A4 page."""
    card_cfg = cfg["card"]
    window_mm_val: float = card_cfg["window_mm"]
    marker_size: float   = card_cfg["marker_size_mm"]
    gap: float           = card_cfg["marker_gap_mm"]
    margin: float        = card_cfg["margin_mm"]

    card_size_mm = window_mm_val + 2 * (gap + marker_size) + 2 * margin
    card_pt = card_size_mm * mm

    page_w, page_h = A4  # points
    gap_between_cards = 5 * mm  # 5 mm gap between cards on the page

    c = rl_canvas.Canvas(str(out_path), pagesize=A4)

    # Title
    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(colors.black)
    c.drawCentredString(page_w / 2, page_h - 15 * mm, "TantSaakshi Marker Card — Print at 100%")

    # 2×2 grid of cards on a single A4 page
    start_x = (page_w - 2 * card_pt - gap_between_cards) / 2
    start_y = (page_h - 2 * card_pt - gap_between_cards) / 2 - 10 * mm  # offset for title

    positions = [
        (start_x,                       start_y + card_pt + gap_between_cards),
        (start_x + card_pt + gap_between_cards, start_y + card_pt + gap_between_cards),
        (start_x,                       start_y),
        (start_x + card_pt + gap_between_cards, start_y),
    ]

    for ox, oy in positions:
        draw_card(c, ox, oy, cfg)

    # Footer instruction
    c.setFont("Helvetica", 8)
    c.setFillColor(colors.darkgrey)
    c.drawCentredString(
        page_w / 2,
        10 * mm,
        "Print at 100% scale (no 'fit to page'). Verify: scale bar on card = exactly 10 mm.",
    )

    c.save()
    print(f"Saved: {out_path}")
    print(f"Card geometry: {card_size_mm:.1f} mm × {card_size_mm:.1f} mm")
    print(f"Window: {window_mm_val:.1f} mm × {window_mm_val:.1f} mm (cut-out)")
    print(f"Scale bar: 10 mm (verify after printing)")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate TantSaakshi marker card PDF.")
    parser.add_argument(
        "--out",
        default=str(_REPO_ROOT / "tools" / "marker_card.pdf"),
        help="Output PDF path (default: tools/marker_card.pdf)",
    )
    args = parser.parse_args()

    cfg = get_config()
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    make_card_pdf(out_path, cfg)


if __name__ == "__main__":
    main()
