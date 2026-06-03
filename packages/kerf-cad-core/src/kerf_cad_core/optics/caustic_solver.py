"""
kerf_cad_core.optics.caustic_solver — Caustic pattern rendering via photon-map
gather on an image plane (Jensen 1996, Pass 2).

A caustic is the locus of concentrated illumination produced by specular/refractive
focusing — e.g. the bright pattern cast by a glass of water.  This module
implements the gather pass of Jensen's photon-mapping algorithm, projecting the
photon map onto a user-defined image plane and accumulating RGB irradiance.

Algorithm (Jensen 2001, §7.5)
------------------------------
For each pixel (i, j) of the image plane:
  1. Compute the world-space sample point P = origin + u_frac * u + v_frac * v.
  2. Call PhotonMap.gather(P, image_plane_normal, gather_radius) to obtain RGB
     irradiance.
  3. Accumulate into the output (H × W × 3) array.

Pure Python + NumPy.  No SciPy.

References
----------
Jensen, H.W. (1996).  "Global Illumination Using Photon Maps."
    Proc. Eurographics Workshop on Rendering (EGWR), pp. 21–30.
Jensen, H.W. (2001).  "Realistic Image Synthesis Using Photon Mapping."
    A K Peters. Ch. 7 (caustics), §9.4 (kd-tree gather).
Schott AG — "Optical Glass Data Sheets", 2023 (Sellmeier coefficients).

Author: imranparuk
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

import numpy as np

from kerf_cad_core.optics.photon_map import PhotonMap


# ---------------------------------------------------------------------------
# Image-plane caustic descriptor
# ---------------------------------------------------------------------------

@dataclass
class CausticPattern:
    """
    Caustic irradiance pattern projected onto an image plane.

    Attributes
    ----------
    image_plane_origin : np.ndarray, shape (3,)
        World-space origin (corner) of the image plane.
    image_plane_u : np.ndarray, shape (3,) unit vector
        Horizontal axis of the image plane.
    image_plane_v : np.ndarray, shape (3,) unit vector
        Vertical axis of the image plane.
    width : float
        Physical extent of the image plane along u (scene units).
    height : float
        Physical extent of the image plane along v (scene units).
    resolution : tuple[int, int]
        (W, H) pixel dimensions of the output grid.
    rgb : np.ndarray, shape (H, W, 3)
        Per-pixel RGB irradiance [W / unit_area² per channel].
    """
    image_plane_origin: np.ndarray
    image_plane_u: np.ndarray
    image_plane_v: np.ndarray
    width: float
    height: float
    resolution: Tuple[int, int]
    rgb: np.ndarray  # (H, W, 3)


# ---------------------------------------------------------------------------
# Render function
# ---------------------------------------------------------------------------

def render_caustic(
    photon_map: PhotonMap,
    image_plane_origin: np.ndarray,
    image_plane_u: np.ndarray,
    image_plane_v: np.ndarray,
    image_plane_normal: np.ndarray,
    width: float,
    height: float,
    resolution: Tuple[int, int],
    gather_radius: float = 0.01,
) -> CausticPattern:
    """
    Render a caustic pattern onto the image plane via photon-map gather.

    For each pixel of the image plane the sample point is computed and
    PhotonMap.gather() is called to accumulate the nearby photon power.
    The gather uses the image-plane normal as the surface normal.

    Parameters
    ----------
    photon_map : PhotonMap
        Photon map from trace_photons() (pass 1).
    image_plane_origin : np.ndarray, shape (3,)
        Bottom-left origin of the image plane in world space.
    image_plane_u : np.ndarray, shape (3,) unit vector
        Horizontal (u) axis direction.
    image_plane_v : np.ndarray, shape (3,) unit vector
        Vertical (v) axis direction.
    image_plane_normal : np.ndarray, shape (3,)
        Outward normal of the image plane (used for hemisphere filtering in
        PhotonMap.gather).
    width : float
        Total physical width (u extent) of the image plane.
    height : float
        Total physical height (v extent) of the image plane.
    resolution : tuple[int, int]
        (W, H) — number of pixels in u and v directions.
    gather_radius : float
        Irradiance-gather radius around each pixel sample point.
        Should be chosen relative to the scene scale and photon density.

    Returns
    -------
    CausticPattern
        Contains the (H × W × 3) RGB irradiance image.

    Notes
    -----
    * Pixel centres are placed on a regular grid:
        u_frac = (i + 0.5) / W  →  u_offset = u_frac * width
        v_frac = (j + 0.5) / H  →  v_offset = v_frac * height
    * Photons are not re-normalised; the scale of rgb depends on the photon
      power units used in emit_photons().
    * For high photon counts, replace the brute-force gather in PhotonMap with
      a balanced kd-tree (Jensen 2001 §9.4).

    References
    ----------
    Jensen (1996), §4 (caustic computation).
    Jensen (2001), §7.5 (caustic photon map rendering).
    """
    W, H = resolution
    origin = np.asarray(image_plane_origin, dtype=float)
    u_axis = np.asarray(image_plane_u, dtype=float)
    v_axis = np.asarray(image_plane_v, dtype=float)
    normal = np.asarray(image_plane_normal, dtype=float)
    norm_len = float(np.linalg.norm(normal))
    if norm_len > 0.0:
        normal = normal / norm_len

    rgb_image = np.zeros((H, W, 3), dtype=float)

    pixel_w = width / W
    pixel_h = height / H

    for j in range(H):
        v_offset = (j + 0.5) * pixel_h
        for i in range(W):
            u_offset = (i + 0.5) * pixel_w
            sample_point = origin + u_offset * u_axis + v_offset * v_axis
            irradiance = photon_map.gather(
                sample_point, normal, gather_radius
            )
            rgb_image[j, i, :] = irradiance

    return CausticPattern(
        image_plane_origin=origin,
        image_plane_u=u_axis,
        image_plane_v=v_axis,
        width=width,
        height=height,
        resolution=resolution,
        rgb=rgb_image,
    )
