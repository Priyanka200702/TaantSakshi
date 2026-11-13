"""
engine/enhance.py
Multi-frame burst enhancement and honest clarity improvements.

Permitted techniques (§8):
  - Best-frame selection by sharpness (variance of Laplacian)
  - Multi-frame stacking (sub-pixel alignment via cv2.findTransformECC with MOTION_EUCLIDEAN)
  - Flat-field correction (divide by heavy Gaussian blur to remove uneven lighting/torch hotspot)
  - Glare masking (masking saturated pixels >= 250)
  - Contrast normalisation (zero-mean, unit-variance)

FORBIDDEN:
  - No AI super-resolution, AI deblurring, or generative filters.
"""
from __future__ import annotations

import cv2
import numpy as np


def measure_sharpness(img_gray: np.ndarray) -> float:
    """
    Compute sharpness as variance of Laplacian on grayscale image.
    Input float32 [0, 1] or uint8 [0, 255].
    Returns float variance (scaled to [0, 255] equivalent scale).
    """
    if img_gray.dtype != np.uint8:
        u8 = (np.clip(img_gray, 0.0, 1.0) * 255).astype(np.uint8)
    else:
        u8 = img_gray

    lap = cv2.Laplacian(u8, cv2.CV_64F)
    return float(lap.var())


def select_best_frames(frames: list[np.ndarray], top_k: int = 3) -> list[tuple[int, float, np.ndarray]]:
    """
    Rank rectified frames by sharpness and return the top_k best frames.
    Returns list of (index, sharpness, frame).
    """
    scored = []
    for idx, f in enumerate(frames):
        s = measure_sharpness(f)
        scored.append((idx, s, f))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


def stack_burst_frames(
    frames: list[np.ndarray],
    top_k: int = 3,
    max_ecc_iterations: int = 50,
    ecc_eps: float = 1e-4,
) -> tuple[np.ndarray, int]:
    """
    Align and average the top_k sharpest frames using sub-pixel ECC Euclidean motion.

    Parameters
    ----------
    frames : list[np.ndarray]
        List of rectified grayscale float32 [0, 1] frames.
    top_k : int
        Maximum number of frames to stack.

    Returns
    -------
    stacked : np.ndarray  float32 [0, 1]
    n_stacked : int       number of frames successfully aligned and averaged
    """
    if not frames:
        raise ValueError("Cannot stack an empty list of frames")

    if len(frames) == 1:
        return frames[0].copy(), 1

    ranked = select_best_frames(frames, top_k=top_k)
    ref_idx, ref_score, ref_img = ranked[0]

    H, W = ref_img.shape[:2]
    accum = ref_img.copy().astype(np.float64)
    count = 1

    criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, max_ecc_iterations, ecc_eps)

    for idx, score, frame in ranked[1:]:
        warp_matrix = np.eye(2, 3, dtype=np.float32)
        try:
            # findTransformECC expects uint8 or float32 single-channel
            cv2.findTransformECC(
                templateImage=ref_img.astype(np.float32),
                inputImage=frame.astype(np.float32),
                warpMatrix=warp_matrix,
                motionType=cv2.MOTION_EUCLIDEAN,
                criteria=criteria,
            )
            aligned = cv2.warpAffine(
                frame.astype(np.float32),
                warp_matrix,
                (W, H),
                flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP,
                borderMode=cv2.BORDER_REFLECT_101,
            )
            accum += aligned
            count += 1
        except cv2.error:
            # ECC alignment can fail on severely shaken frames; skip gracefully
            continue

    stacked = (accum / count).astype(np.float32)
    return np.clip(stacked, 0.0, 1.0), count


def flatfield_correct(img: np.ndarray, sigma_px: float = 25.0) -> np.ndarray:
    """
    Flat-field correction: divide by heavy Gaussian blur to eliminate torch hotspots.
    Returns float32 array with zero mean.
    """
    img_f = img.astype(np.float32)
    blur = cv2.GaussianBlur(img_f, (0, 0), sigmaX=sigma_px, sigmaY=sigma_px)
    blur = np.where(blur < 1e-6, 1e-6, blur)
    corrected = img_f / blur
    return (corrected - corrected.mean()).astype(np.float32)


def mask_glare(
    img: np.ndarray,
    saturation_level: int = 250,
) -> tuple[np.ndarray, np.ndarray, float]:
    """
    Detect saturated pixels (glare) and produce a smooth in-painted version (cv2.inpaint TELEA)
    for FFT analysis, along with the boolean glare_mask.

    NOTE: The inpainted image is ONLY for the FFT (to prevent artificial spectral spikes).
    The fingerprint module must use the glare_mask to exclude glare pixels from matching,
    never filled pixels.

    Returns
    -------
    clean_img : np.ndarray (float32, [0, 1], with glare smoothly inpainted)
    glare_mask : np.ndarray (bool mask, True where saturated)
    glare_fraction : float
    """
    is_float = (img.dtype != np.uint8)
    if is_float:
        u8 = (np.clip(img, 0.0, 1.0) * 255).astype(np.uint8)
    else:
        u8 = img.copy()

    if len(u8.shape) == 3:
        glare_mask = np.any(u8 >= saturation_level, axis=2)
    else:
        glare_mask = u8 >= saturation_level

    glare_fraction = float(np.mean(glare_mask))

    if glare_fraction > 0:
        inpaint_mask = (glare_mask.astype(np.uint8) * 255)
        # Smooth inpaint with Telea algorithm
        inpainted_u8 = cv2.inpaint(u8, inpaint_mask, inpaintRadius=3, flags=cv2.INPAINT_TELEA)
        clean_img = (inpainted_u8.astype(np.float32) / 255.0) if is_float else inpainted_u8
    else:
        clean_img = img.copy().astype(np.float32) if is_float else u8

    return clean_img, glare_mask, glare_fraction


def normalize_contrast(img: np.ndarray) -> np.ndarray:
    """Zero-mean, unit-variance contrast normalisation for comparability."""
    img_f = img.astype(np.float32)
    mean = float(np.mean(img_f))
    std = float(np.std(img_f))
    if std < 1e-8:
        return np.zeros_like(img_f)
    return ((img_f - mean) / std).astype(np.float32)
