"""
engine/debug.py
Debug visualization outputs for the TantSaakshi vision engine (§7.10).

Saves visual artifacts for competition presentations and engineering analysis:
  - Detected markers on raw image
  - Rectified window (color & grayscale)
  - Log spectrum with band boundaries and peak crosshairs
  - Defect detection overlay
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import cv2
import numpy as np


def save_debug_images(
    debug_dir: str | Path,
    raw_img: np.ndarray,
    card_result: dict[str, Any],
    window_color: np.ndarray | None,
    fft_result: dict[str, Any] | None,
    base_name: str = "debug",
) -> dict[str, str]:
    """
    Save all relevant debug images into debug_dir.
    Returns mapping of artifact name -> saved file path.
    """
    out_dir = Path(debug_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    saved: dict[str, str] = {}

    # 1. Detected markers overlay
    if raw_img is not None:
        vis_markers = raw_img.copy()
        if vis_markers.dtype != np.uint8:
            vis_markers = (np.clip(vis_markers, 0.0, 1.0) * 255).astype(np.uint8)
        if len(vis_markers.shape) == 2:
            vis_markers = cv2.cvtColor(vis_markers, cv2.COLOR_GRAY2BGR)

        corners_dict = card_result.get("corners_dict", {})
        for mid, pts in corners_dict.items():
            pts_i = pts.astype(int)
            cv2.polylines(vis_markers, [pts_i], isClosed=True, color=(0, 255, 0), thickness=2)
            c = np.mean(pts, axis=0).astype(int)
            cv2.putText(
                vis_markers, f"ID:{mid}", (c[0] - 15, c[1] + 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2
            )

        p_mark = str(out_dir / f"{base_name}_detected_markers.jpg")
        cv2.imwrite(p_mark, vis_markers)
        saved["detected_markers"] = p_mark

    # 2. Rectified window
    if window_color is not None:
        p_win = str(out_dir / f"{base_name}_rectified_window.png")
        cv2.imwrite(p_win, window_color)
        saved["rectified_window"] = p_win

    # 3. Defect overlay
    if fft_result and fft_result.get("ok"):
        # If defect mask or residual is available
        defects = fft_result.get("defects", {})
        if window_color is not None:
            vis_defects = window_color.copy()
            # Annotate defect summary on image
            cv2.putText(
                vis_defects,
                f"Defects: {defects.get('count', 0)} ({defects.get('area_fraction', 0.0)*100:.2f}%)",
                (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1
            )
            p_def = str(out_dir / f"{base_name}_defects_overlay.png")
            cv2.imwrite(p_def, vis_defects)
            saved["defects_overlay"] = p_def

    return saved
