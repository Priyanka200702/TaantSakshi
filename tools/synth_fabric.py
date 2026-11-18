"""
tools/synth_fabric.py
Generates synthetic woven-fabric images with KNOWN ground truth for unit tests and eval.

Supports:
  - Exact thread density (ends/inch, picks/inch) at any scale (px_per_mm)
  - Grid tilt (angle_deg)
  - Realistic yarn properties:
      * non-sinusoidal thread profile (harmonic overtones)
      * random thickness variations (slubs)
      * hairiness micro-texture
      * Gaussian optical blur (sigma 1-2 px)
      * uneven lighting gradients
      * spacing jitter (irregularity)
  - Defects (knots, broken threads, missing picks)
  - Multi-frame bursts with sub-pixel motion (make_burst)
  - Full card scene simulation with ArUco markers & perspective tilt (make_card_scene)

NOTE: Any evaluations generated with this module are:
"synthetic validation only — not real-world accuracy".
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np


@dataclass
class FabricSpec:
    """Parameters for a synthetic fabric image."""
    ends_per_inch: float = 60.0       # warp threads per inch
    picks_per_inch: float = 60.0      # weft threads per inch
    px_per_mm: float = 40.0           # scale of the output image

    # Physical size of the measurement window
    window_mm: float = 20.0           # square window; image will be window_mm × window_mm

    # Warp runs vertically in the image (angle=0° → peak on horizontal axis).
    grid_angle_deg: float = 0.0       # tilt of the warp direction (degrees, +ve = CW)

    # Thread amplitude (0–1 range after normalisation)
    amplitude: float = 0.22

    # Realistic yarn effects
    harmonic_amplitude: float = 0.0   # non-sinusoidal profile: 2nd harmonic amplitude
    slub_amplitude: float = 0.0       # random thickness variation (slubs) along thread
    hairiness_sigma: float = 0.0      # fine micro-fibril texture
    gaussian_blur_sigma: float = 0.0  # optical blur sigma (1-2 px)
    uneven_lighting: float = 0.0      # illumination gradient (0.0 to 1.0)
    irregularity_jitter: float = 0.0  # thread spacing jitter (for testing irregularity)

    # Defects
    defect_type: str | None = None    # None | "knot" | "broken_thread" | "blob"
    defect_location: tuple[float, float] | None = None  # (norm_x, norm_y) in [0, 1]

    # Noise
    noise_sigma: float = 0.0          # Gaussian noise std (image in 0–1 range)

    # Motion blur (0 = none)
    blur_kernel: int = 0              # odd integer or 0

    # Design stripes: low-frequency (should be outside the thread band)
    design_stripe_amplitude: float = 0.0
    design_stripe_period_mm: float = 5.0   # period in mm (> band_max → ignored by FFT)

    # Glare: saturated circular patches
    glare_spots: int = 0              # number of glare spots
    glare_radius_px: int = 10

    # Seed for reproducibility (None = random)
    seed: int | None = 42


@dataclass
class FabricGroundTruth:
    ends_per_inch: float
    picks_per_inch: float
    px_per_mm: float
    window_mm: float
    grid_angle_deg: float
    # Derived
    warp_px_per_thread: float = field(init=False)
    weft_px_per_thread: float = field(init=False)
    warp_threads_per_mm: float = field(init=False)
    weft_threads_per_mm: float = field(init=False)
    # FFT peak positions (in cycles per window, i.e. the k values)
    warp_k: float = field(init=False)      # = threads_per_mm × window_mm
    weft_k: float = field(init=False)
    # Angles of FFT peaks (degrees; warp threads vertical → peak near 0°)
    warp_peak_angle_deg: float = field(init=False)
    weft_peak_angle_deg: float = field(init=False)

    def __post_init__(self):
        self.warp_threads_per_mm = self.ends_per_inch / 25.4
        self.weft_threads_per_mm = self.picks_per_inch / 25.4
        self.warp_px_per_thread = 1.0 / self.warp_threads_per_mm * self.px_per_mm
        self.weft_px_per_thread = 1.0 / self.weft_threads_per_mm * self.px_per_mm
        self.warp_k = self.warp_threads_per_mm * self.window_mm
        self.weft_k = self.weft_threads_per_mm * self.window_mm
        self.warp_peak_angle_deg = self.grid_angle_deg          # near 0°
        self.weft_peak_angle_deg = self.grid_angle_deg + 90.0   # near 90°


def make_fabric(spec: FabricSpec) -> tuple[np.ndarray, FabricGroundTruth]:
    """
    Generate a synthetic fabric image with realistic yarn physics and known ground truth.

    Returns
    -------
    img : np.ndarray  float32, shape (H, W), values in [0, 1]
    gt  : FabricGroundTruth
    """
    rng = np.random.default_rng(spec.seed)

    N = int(round(spec.window_mm * spec.px_per_mm))
    if N < 2:
        raise ValueError("window_mm × px_per_mm must be ≥ 2 px")

    # Pixel coordinate grids
    xs = np.arange(N, dtype=np.float64)
    ys = np.arange(N, dtype=np.float64)
    XX, YY = np.meshgrid(xs, ys)  # shape (N, N)

    # Rotate coordinate grid by grid_angle_deg
    angle_rad = math.radians(spec.grid_angle_deg)
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)
    XX_r = cos_a * XX + sin_a * YY
    YY_r = -sin_a * XX + cos_a * YY

    # Thread periods in pixels
    warp_threads_per_mm = spec.ends_per_inch / 25.4
    weft_threads_per_mm = spec.picks_per_inch / 25.4
    warp_period_px = spec.px_per_mm / warp_threads_per_mm
    weft_period_px = spec.px_per_mm / weft_threads_per_mm

    # Spacing jitter (irregularity simulation)
    if spec.irregularity_jitter > 0:
        # Smooth low-frequency phase perturbation along threads
        raw_jx = rng.normal(0, 1.0, (N, N))
        raw_jy = rng.normal(0, 1.0, (N, N))
        bl_jx = cv2.GaussianBlur(raw_jx, (0, 0), sigmaX=warp_period_px * 2, sigmaY=warp_period_px * 4)
        bl_jy = cv2.GaussianBlur(raw_jy, (0, 0), sigmaX=weft_period_px * 4, sigmaY=weft_period_px * 2)
        std_x = np.std(bl_jx) + 1e-9
        std_y = np.std(bl_jy) + 1e-9
        XX_r = XX_r + (bl_jx / std_x) * (spec.irregularity_jitter * warp_period_px)
        YY_r = YY_r + (bl_jy / std_y) * (spec.irregularity_jitter * weft_period_px)

    # Slub modulation (random thickness variation along thread length)
    warp_amp = spec.amplitude
    weft_amp = spec.amplitude
    if spec.slub_amplitude > 0:
        slub_warp = 1.0 + spec.slub_amplitude * cv2.GaussianBlur(
            rng.normal(0, 1.0, (N, N)), (0, 0), sigmaX=warp_period_px * 0.5, sigmaY=warp_period_px * 5
        )
        slub_weft = 1.0 + spec.slub_amplitude * cv2.GaussianBlur(
            rng.normal(0, 1.0, (N, N)), (0, 0), sigmaX=weft_period_px * 5, sigmaY=weft_period_px * 0.5
        )
        warp_amp = warp_amp * slub_warp
        weft_amp = weft_amp * slub_weft

    # Thread profiles (including non-sinusoidal harmonic overtones)
    phase_warp = 2 * np.pi * XX_r / warp_period_px
    phase_weft = 2 * np.pi * YY_r / weft_period_px

    warp_profile = np.cos(phase_warp)
    weft_profile = np.cos(phase_weft)

    if spec.harmonic_amplitude > 0:
        # Add 2nd and 3rd harmonics to produce rounded/flattened yarn cross-sections
        h_amp = spec.harmonic_amplitude
        warp_profile += h_amp * 0.5 * np.cos(2 * phase_warp) + h_amp * 0.25 * np.cos(3 * phase_warp)
        weft_profile += h_amp * 0.5 * np.cos(2 * phase_weft) + h_amp * 0.25 * np.cos(3 * phase_weft)

    warp = warp_amp * warp_profile
    weft = weft_amp * weft_profile

    # Weave interaction (plain weave over-under shadow effect)
    img = 0.5 + warp + weft - 0.2 * (warp * weft)

    # Hairiness / micro-fibril noise
    if spec.hairiness_sigma > 0:
        h_noise = rng.normal(0, spec.hairiness_sigma, (N, N))
        # Anisotropic blur to simulate micro-fibres oriented along weave
        h_noise = cv2.GaussianBlur(h_noise, (3, 3), 0.8)
        img += h_noise

    # Low-frequency design stripes
    if spec.design_stripe_amplitude > 0:
        design_period_px = spec.design_stripe_period_mm * spec.px_per_mm
        design = spec.design_stripe_amplitude * np.cos(2 * np.pi * XX / design_period_px)
        img = img + design

    # Uneven lighting (spatial illumination gradient / vignetting)
    if spec.uneven_lighting > 0:
        cx, cy = N / 2, N / 2
        # Center-weighted hotspot plus linear gradient
        r_sq = ((XX - cx) ** 2 + (YY - cy) ** 2) / (cx ** 2 + cy ** 2)
        grad = 1.0 - spec.uneven_lighting * 0.4 * r_sq + spec.uneven_lighting * 0.2 * ((XX - cx) / cx)
        img = img * grad

    # Defects insertion
    if spec.defect_type:
        loc = spec.defect_location or (0.5, 0.5)
        dx_c = int(round(loc[0] * N))
        dy_c = int(round(loc[1] * N))
        if spec.defect_type == "knot":
            # Compact dark/dense circular knot with halo
            r_k = max(int(round(warp_period_px * 0.8)), 3)
            y_d, x_d = np.ogrid[:N, :N]
            dist_sq = (x_d - dx_c) ** 2 + (y_d - dy_c) ** 2
            knot_mask = dist_sq <= r_k ** 2
            img[knot_mask] = img[knot_mask] * 0.2 + 0.8  # bright/dense knot
        elif spec.defect_type == "broken_thread":
            # Missing segment in warp thread
            len_b = int(round(warp_period_px * 6))
            wid_b = max(int(round(warp_period_px * 0.7)), 2)
            y1 = max(0, dy_c - len_b // 2)
            y2 = min(N, dy_c + len_b // 2)
            x1 = max(0, dx_c - wid_b // 2)
            x2 = min(N, dx_c + wid_b // 2)
            img[y1:y2, x1:x2] = 0.2  # dark thread gap
        elif spec.defect_type == "blob":
            # Stain or dye spot
            r_b = max(int(round(warp_period_px * 1.5)), 4)
            y_d, x_d = np.ogrid[:N, :N]
            blob_mask = (x_d - dx_c) ** 2 + (y_d - dy_c) ** 2 <= r_b ** 2
            img[blob_mask] = 0.15

    # Gaussian optical blur (sigma 1-2 px)
    if spec.gaussian_blur_sigma > 0:
        img = cv2.GaussianBlur(img.astype(np.float32), (0, 0), spec.gaussian_blur_sigma)

    # General sensor noise
    if spec.noise_sigma > 0:
        img = img + rng.normal(0, spec.noise_sigma, img.shape)

    # Motion blur
    if spec.blur_kernel > 1:
        k = spec.blur_kernel | 1
        kernel = np.zeros((k, k), dtype=np.float32)
        kernel[k // 2, :] = 1.0 / k
        img = cv2.filter2D(img, -1, kernel)

    # Glare spots
    if spec.glare_spots > 0:
        for _ in range(spec.glare_spots):
            cgx = int(rng.integers(spec.glare_radius_px, N - spec.glare_radius_px))
            cgy = int(rng.integers(spec.glare_radius_px, N - spec.glare_radius_px))
            rr = spec.glare_radius_px
            yy, xx = np.ogrid[:N, :N]
            g_mask = (xx - cgx) ** 2 + (yy - cgy) ** 2 <= rr ** 2
            img[g_mask] = 1.0

    img = np.clip(img, 0.0, 1.0).astype(np.float32)

    gt = FabricGroundTruth(
        ends_per_inch=spec.ends_per_inch,
        picks_per_inch=spec.picks_per_inch,
        px_per_mm=spec.px_per_mm,
        window_mm=spec.window_mm,
        grid_angle_deg=spec.grid_angle_deg,
    )
    return img, gt


def make_burst(
    spec: FabricSpec,
    n_frames: int = 5,
    max_shift_px: float = 2.0,
    noise_per_frame_sigma: float = 0.02,
) -> tuple[list[np.ndarray], FabricGroundTruth]:
    """Generate a burst of N fabric frames with sub-pixel shifts and sensor noise."""
    base_img, gt = make_fabric(spec)
    rng = np.random.default_rng(spec.seed if spec.seed is not None else 0)
    H, W = base_img.shape
    frames: list[np.ndarray] = []

    for _ in range(n_frames):
        dx = rng.uniform(-max_shift_px, max_shift_px)
        dy = rng.uniform(-max_shift_px, max_shift_px)
        M = np.array([[1.0, 0.0, dx], [0.0, 1.0, dy]], dtype=np.float64)
        shifted = cv2.warpAffine(
            base_img, M, (W, H),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REFLECT_101,
        )
        noise = rng.normal(0, noise_per_frame_sigma, shifted.shape).astype(np.float32)
        frame = np.clip(shifted + noise, 0.0, 1.0).astype(np.float32)
        frames.append(frame)

    return frames, gt


def make_card_scene(
    spec: FabricSpec,
    cfg: dict[str, Any],
    tilt_deg: float = 0.0,
    camera_px_per_mm: float = 30.0,
    image_size: tuple[int, int] = (1600, 1600),
    seed: int = 42,
    fabric_patch: np.ndarray | None = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    """
    Simulate a full phone photograph showing the marker card lying on fabric.

    Parameters
    ----------
    spec : FabricSpec for the fabric in the window
    cfg : engine config dict (card section geometry)
    tilt_deg : perspective tilt angle of the camera
    camera_px_per_mm : native sensor resolution scale
    image_size : output image (height, width)
    """
    card_cfg = cfg["card"]
    window_mm = float(card_cfg["window_mm"])
    marker_size_mm = float(card_cfg["marker_size_mm"])
    marker_gap_mm = float(card_cfg["marker_gap_mm"])
    margin_mm = float(card_cfg["margin_mm"])
    marker_ids = list(card_cfg["marker_ids"])
    dict_name = str(card_cfg["aruco_dict"])

    card_size_mm = window_mm + 2 * (marker_gap_mm + marker_size_mm) + 2 * margin_mm

    # Build unwarped card plane in high-res pixels
    scale = camera_px_per_mm
    card_px = int(round(card_size_mm * scale))
    plane = np.full((card_px, card_px), 0.95, dtype=np.float32)  # white laminated card

    # Window geometry in card coordinates
    win_offset_mm = margin_mm + marker_size_mm + marker_gap_mm
    win_left = int(round(win_offset_mm * scale))
    win_top = int(round(win_offset_mm * scale))
    win_sz = int(round(window_mm * scale))

    if fabric_patch is not None:
        fabric_res = cv2.resize(fabric_patch, (win_sz, win_sz), interpolation=cv2.INTER_AREA)
        gt = {}
    else:
        # Generate synthetic fabric scaled to fit the window
        fab_spec = FabricSpec(
            ends_per_inch=spec.ends_per_inch,
            picks_per_inch=spec.picks_per_inch,
            px_per_mm=scale,
            window_mm=window_mm,
            amplitude=spec.amplitude,
            grid_angle_deg=spec.grid_angle_deg,
            noise_sigma=spec.noise_sigma,
            hairiness_sigma=spec.hairiness_sigma,
            harmonic_amplitude=spec.harmonic_amplitude,
            slub_amplitude=spec.slub_amplitude,
            irregularity_jitter=spec.irregularity_jitter,
            uneven_lighting=spec.uneven_lighting,
            gaussian_blur_sigma=spec.gaussian_blur_sigma,
            defect_type=spec.defect_type,
            defect_location=spec.defect_location,
            design_stripe_amplitude=spec.design_stripe_amplitude,
            design_stripe_period_mm=spec.design_stripe_period_mm,
            seed=seed,
        )
        fabric_img, gt = make_fabric(fab_spec)
        fabric_res = cv2.resize(fabric_img, (win_sz, win_sz))
    plane[win_top:win_top + win_sz, win_left:win_left + win_sz] = fabric_res

    # Draw 4 ArUco markers at exact corner positions
    dict_id = getattr(cv2.aruco, dict_name)
    aruco_dict = cv2.aruco.getPredefinedDictionary(dict_id)
    marker_px = int(round(marker_size_mm * scale))

    corner_offsets_mm = [
        (margin_mm, margin_mm),                                              # TL (0)
        (card_size_mm - margin_mm - marker_size_mm, margin_mm),              # TR (1)
        (card_size_mm - margin_mm - marker_size_mm, card_size_mm - margin_mm - marker_size_mm),  # BR (2)
        (margin_mm, card_size_mm - margin_mm - marker_size_mm),              # BL (3)
    ]

    for mid, (mx_mm, my_mm) in zip(marker_ids, corner_offsets_mm):
        mx = int(round(mx_mm * scale))
        my = int(round(my_mm * scale))
        marker_img = cv2.aruco.generateImageMarker(aruco_dict, mid, marker_px)
        marker_float = (marker_img.astype(np.float32) / 255.0)
        plane[my:my + marker_px, mx:mx + marker_px] = marker_float

    # Ensure background scene is larger than card
    if image_size is None or (image_size[0] <= card_px or image_size[1] <= card_px):
        dim = int(round(card_px * 1.4))
        H_out, W_out = dim, dim
    else:
        H_out, W_out = image_size

    scene = np.full((H_out, W_out), 0.3, dtype=np.float32)  # surrounding fabric / tabletop
    start_y = (H_out - card_px) // 2
    start_x = (W_out - card_px) // 2
    scene[start_y:start_y + card_px, start_x:start_x + card_px] = plane

    # Apply 3D perspective warp to simulate camera tilt
    if abs(tilt_deg) > 0.01:
        rad = math.radians(tilt_deg)
        pts_src = np.float32([
            [start_x, start_y],
            [start_x + card_px, start_y],
            [start_x + card_px, start_y + card_px],
            [start_x, start_y + card_px]
        ])
        cx_c = start_x + card_px / 2.0
        cy_c = start_y + card_px / 2.0
        D = 4.0 * card_px  # camera distance relative to card size
        pts_dst = []
        for px, py in pts_src:
            X = px - cx_c
            Y = py - cy_c
            Y_rot = Y * math.cos(rad)
            Z_rot = Y * math.sin(rad)
            scale_p = D / (D + Z_rot)
            pts_dst.append([cx_c + X * scale_p, cy_c + Y_rot * scale_p])
        pts_dst = np.float32(pts_dst)
        M_warp = cv2.getPerspectiveTransform(pts_src, pts_dst)
        scene = cv2.warpPerspective(scene, M_warp, (W_out, H_out), borderValue=0.25)

    # Per-photo sensor noise
    rng = np.random.default_rng(seed if seed is not None else 0)
    scene = scene + rng.normal(0, 0.01, scene.shape).astype(np.float32)

    info = {
        "ground_truth": gt,
        "tilt_deg": tilt_deg,
        "camera_px_per_mm": camera_px_per_mm,
        "window_mm": window_mm,
    }
    return np.clip(scene, 0.0, 1.0).astype(np.float32), info


def to_uint8(img: np.ndarray) -> np.ndarray:
    """Convert float32 [0,1] image to uint8 [0,255]."""
    return (np.clip(img, 0.0, 1.0) * 255).astype(np.uint8)


# ---------------------------------------------------------------------------
# True interlacement rendering (plain / matt / rib / twill)
# ---------------------------------------------------------------------------

# Weave matrices: rows = picks (j), cols = ends (i); 1 = weft on top at (j, i).
WEAVES: dict[str, np.ndarray] = {
    "plain":      np.array([[1, 0], [0, 1]]),
    # 2/2 matt (basket): ends AND picks work in pairs
    "matt22":     np.array([[1, 1, 0, 0], [1, 1, 0, 0], [0, 0, 1, 1], [0, 0, 1, 1]]),
    # 2/2 weft rib: ends work in pairs, picks single
    "weft_rib22": np.array([[1, 1, 0, 0], [0, 0, 1, 1]]),
    # 1/2 twill: weft over 1, under 2, shifting one end per pick
    "twill12":    np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1]]),
}


@dataclass
class WovenSpec:
    """Synthetic fabric drawn from a real interlacement matrix."""
    weave: str = "plain"
    ends_per_inch: float = 60.0
    picks_per_inch: float = 60.0
    px_per_mm: float = 40.0
    window_mm: float = 19.0
    grid_angle_deg: float = 0.0
    weft_brightness: float = 0.80     # weft floats (bright in the red saree)
    warp_brightness: float = 0.50
    gap_brightness: float = 0.15
    yarn_fill: float = 0.85           # yarn diameter / pitch
    merge_paired_picks: bool = False  # picks sharing a shed pack into one band (no seam)
    gaussian_blur_sigma: float = 1.0
    noise_sigma: float = 0.02
    seed: int | None = 7


def _yarn_profile(frac: np.ndarray, fill: float) -> np.ndarray:
    """Raised-cosine cross-section of a yarn centred in its cell (frac in [0,1))."""
    d = np.abs(frac - 0.5) / (0.5 * fill)
    return np.where(d < 1.0, 0.5 * (1.0 + np.cos(np.pi * np.clip(d, 0, 1))), 0.0)


def make_woven(spec: WovenSpec) -> tuple[np.ndarray, FabricGroundTruth]:
    """Render a woven structure: each (pick, end) cell shows whichever yarn is on top."""
    if spec.weave not in WEAVES:
        raise ValueError(f"unknown weave {spec.weave!r}; choose from {sorted(WEAVES)}")
    W = WEAVES[spec.weave]
    rng = np.random.default_rng(spec.seed)
    N = int(round(spec.window_mm * spec.px_per_mm))
    ys, xs = np.mgrid[0:N, 0:N].astype(np.float64)
    a = math.radians(spec.grid_angle_deg)
    xr = math.cos(a) * xs + math.sin(a) * ys
    yr = -math.sin(a) * xs + math.cos(a) * ys

    p_end = spec.px_per_mm * 25.4 / spec.ends_per_inch
    p_pick = spec.px_per_mm * 25.4 / spec.picks_per_inch
    gi, fx = np.divmod(xr / p_end, 1.0)
    gj, fy = np.divmod(yr / p_pick, 1.0)
    gi = gi.astype(np.int64)
    gj = gj.astype(np.int64)
    weft_up = W[gj % W.shape[0], gi % W.shape[1]].astype(bool)

    if spec.merge_paired_picks and spec.weave == "matt22":
        # Two picks in one shed lie together: one band two picks tall.
        fy_band = ((gj % 2) + fy) / 2.0
        weft_prof = _yarn_profile(fy_band, spec.yarn_fill)
    else:
        weft_prof = _yarn_profile(fy, spec.yarn_fill)
    warp_prof = _yarn_profile(fx, spec.yarn_fill)

    g = spec.gap_brightness
    img_weft = g + (spec.weft_brightness - g) * weft_prof
    img_warp = g + (spec.warp_brightness - g) * warp_prof
    img = np.where(weft_up, img_weft, img_warp)

    if spec.gaussian_blur_sigma > 0:
        img = cv2.GaussianBlur(img.astype(np.float32), (0, 0), spec.gaussian_blur_sigma)
    if spec.noise_sigma > 0:
        img = img + rng.normal(0, spec.noise_sigma, img.shape)
    img = np.clip(img, 0.0, 1.0).astype(np.float32)

    gt = FabricGroundTruth(
        ends_per_inch=spec.ends_per_inch,
        picks_per_inch=spec.picks_per_inch,
        px_per_mm=spec.px_per_mm,
        window_mm=spec.window_mm,
        grid_angle_deg=spec.grid_angle_deg,
    )
    return img, gt
