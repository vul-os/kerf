"""kerf-render: GPU-SKU dispatch policy for Cycles render jobs.

Maps estimated scene complexity to a Koyeb GPU SKU so each render job is
routed to hardware that can finish in a reasonable time without
over-provisioning.

The SKU keys here MUST match the ``GPU_RATES_USD_PER_SECOND`` rate table in
:mod:`kerf_render.pricing_meter` (``rtx_a4000``, ``l4``, ``a6000``,
``l40s``, ``a100``, ``a100_sxm``, ``rtx_pro_6000``, ``h100``, ``h200``).

Complexity signal priority
--------------------------
1. **Preset** (``draft`` / ``standard`` / ``hero`` / ``cinema``) — always
   available; coarsest but very reliable.
2. **Sample count** — overrides the preset band when specified explicitly.
3. **Resolution** — pixel count moves the tier up when it signals
   a high-fidelity render.
4. **Poly + light counts** — fine-grained upward nudge.
5. **Fallback** → ``l4`` (the documented Koyeb default).

Policy (complexity → SKU)
--------------------------
+----------------------------+----------------------------------+
| Complexity tier            | Selected SKU                     |
+============================+==================================+
| tiny (browser preview)     | rtx_a4000                        |
| small (draft / low-sample) | l4                               |
| medium                     | a6000 or l40s (by resolution)    |
| large / photoreal          | a100 (hero) or h100 (cinema)     |
| uncertain / unknown        | l4  (fallback)                   |
+----------------------------+----------------------------------+

Usage
-----
::

    from kerf_render.dispatch import select_gpu_sku

    sku = select_gpu_sku({"preset": "hero", "resolution": [3840, 2160]})
    # → "a100"

    sku = select_gpu_sku({"preset": "cinema"})
    # → "h100"

    sku = select_gpu_sku({})   # no signal at all → fallback
    # → "l4"
"""
from __future__ import annotations

from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# SKU constants — must stay in sync with pricing_meter.GPU_RATES_USD_PER_SECOND
# ---------------------------------------------------------------------------

_SKU_RTX_A4000    = "rtx_a4000"   # 20 GB  entry/tiny
_SKU_L4           = "l4"           # 24 GB  small / fallback default
_SKU_A6000        = "a6000"        # 48 GB  medium
_SKU_L40S         = "l40s"         # 48 GB  medium-high
_SKU_A100         = "a100"         # 80 GB  large / hero
_SKU_H100         = "h100"         # 80 GB  cinema / very large
_SKU_FALLBACK     = _SKU_L4        # documented default

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

# Sample counts
_SAMPLES_TINY   = 64
_SAMPLES_SMALL  = 512
_SAMPLES_MEDIUM = 2048
_SAMPLES_LARGE  = 8192   # ≥ this → large/cinema

# Polygon counts
_POLYS_MEDIUM   = 100_000
_POLYS_LARGE    = 500_000

# Light counts
_LIGHTS_LARGE   = 8

# Resolution thresholds (total pixel count)
_RES_MEDIUM     = 1920 * 1080      # FullHD
_RES_LARGE      = 3840 * 2160      # 4K UHD


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def select_gpu_sku(scene_metrics: Dict[str, Any]) -> str:
    """Return the Koyeb GPU SKU best suited for *scene_metrics*.

    Parameters
    ----------
    scene_metrics:
        Dict carrying any subset of the fields listed below.  Unknown or
        missing fields are ignored.

        ``preset``        str   — ``"draft"`` / ``"standard"`` / ``"hero"`` /
                                  ``"cinema"``; also accepts ``"preview"``,
                                  ``"thumbnail"``.
        ``samples``       int   — explicit sample count (overrides preset
                                  default when present).
        ``resolution``    list  — ``[width, height]`` in pixels.
        ``poly_count``    int   — total polygon / triangle count of the scene.
        ``light_count``   int   — number of light sources.

    Returns
    -------
    str
        One of the rate-table keys from
        :data:`kerf_render.pricing_meter.GPU_RATES_USD_PER_SECOND`.
        Guaranteed to be a valid key; falls back to ``"l4"`` when the
        heuristic cannot determine a tier.

    Notes
    -----
    This function is deliberately **pure** (no I/O, no side-effects) so it
    is easy to unit-test and to swap the policy without touching the worker.
    """
    if not isinstance(scene_metrics, dict):
        return _SKU_FALLBACK

    preset = str(scene_metrics.get("preset", "")).strip().lower()

    # ── Resolve sample count ─────────────────────────────────────────────────
    raw_samples = scene_metrics.get("samples")
    if raw_samples is not None:
        try:
            samples: Optional[int] = int(raw_samples)
        except (TypeError, ValueError):
            samples = None
    else:
        # Derive from preset name when explicit count is absent.
        samples = _samples_from_preset(preset)

    # ── Resolve resolution (pixel count) ─────────────────────────────────────
    raw_res = scene_metrics.get("resolution")
    pixel_count: Optional[int] = None
    if raw_res is not None:
        try:
            w, h = int(raw_res[0]), int(raw_res[1])
            pixel_count = w * h
        except (TypeError, ValueError, IndexError, KeyError):
            pass

    # ── Resolve poly / light counts ──────────────────────────────────────────
    poly_count: Optional[int] = _safe_int(scene_metrics.get("poly_count"))
    light_count: Optional[int] = _safe_int(scene_metrics.get("light_count"))

    # ── Tier selection ────────────────────────────────────────────────────────
    #
    # The preset is the primary signal (always available).  Explicit metrics
    # can only upgrade the tier — never downgrade — so a "draft" preset with
    # 1 M polygons still gets a larger GPU.

    # 1. Start from the preset-derived baseline tier.
    tier = _preset_tier(preset)

    # 2. Upgrade from sample count.
    if samples is not None:
        tier = max(tier, _samples_tier(samples))

    # 3. Upgrade from resolution.
    if pixel_count is not None:
        tier = max(tier, _resolution_tier(pixel_count))

    # 4. Upgrade from geometry / lighting complexity.
    if poly_count is not None:
        tier = max(tier, _poly_tier(poly_count))
    if light_count is not None:
        tier = max(tier, _light_tier(light_count))

    return _tier_to_sku(tier)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Tier integers: 0=tiny, 1=small, 2=medium, 3=medium-high, 4=large, 5=cinema
_TIER_TINY        = 0
_TIER_SMALL       = 1
_TIER_MEDIUM      = 2
_TIER_MEDIUM_HIGH = 3
_TIER_LARGE       = 4
_TIER_CINEMA      = 5
_TIER_UNKNOWN     = -1   # no signal; maps to fallback


def _preset_tier(preset: str) -> int:
    """Return a tier integer from a preset name.

    An absent or empty preset means the caller didn't supply one; in that
    case we return ``_TIER_UNKNOWN`` so the fallback path kicks in and the
    sample-count / resolution signals drive the decision.
    """
    if preset in ("preview", "thumbnail", "browser"):
        return _TIER_TINY
    if preset in ("draft",):
        return _TIER_SMALL
    if preset in ("standard",):
        return _TIER_MEDIUM
    if preset in ("hero",):
        return _TIER_LARGE
    if preset in ("cinema",):
        return _TIER_CINEMA
    # Empty string or unknown preset name → no signal.
    return _TIER_UNKNOWN


def _samples_from_preset(preset: str) -> Optional[int]:
    """Return the canonical sample count implied by *preset*."""
    _TABLE = {
        "preview":   32,
        "thumbnail": 32,
        "browser":   32,
        "draft":     256,
        "standard":  1024,
        "hero":      4096,
        "cinema":    16384,
    }
    return _TABLE.get(preset)


def _samples_tier(samples: int) -> int:
    if samples <= _SAMPLES_TINY:
        return _TIER_TINY
    if samples <= _SAMPLES_SMALL:
        return _TIER_SMALL
    if samples <= _SAMPLES_MEDIUM:
        return _TIER_MEDIUM
    if samples <= _SAMPLES_LARGE:
        return _TIER_LARGE
    return _TIER_CINEMA


def _resolution_tier(pixel_count: int) -> int:
    if pixel_count <= 0:
        return _TIER_TINY
    if pixel_count < _RES_MEDIUM:
        # Small resolution (below FullHD) — treat as tiny; don't upgrade.
        return _TIER_TINY
    if pixel_count < _RES_LARGE:
        return _TIER_MEDIUM
    return _TIER_LARGE


def _poly_tier(poly_count: int) -> int:
    if poly_count < _POLYS_MEDIUM:
        return _TIER_SMALL
    if poly_count < _POLYS_LARGE:
        return _TIER_MEDIUM
    return _TIER_LARGE


def _light_tier(light_count: int) -> int:
    if light_count >= _LIGHTS_LARGE:
        return _TIER_LARGE
    return _TIER_SMALL


def _tier_to_sku(tier: int) -> str:
    """Map a resolved tier integer to a Koyeb GPU SKU key."""
    if tier < _TIER_TINY:
        # UNKNOWN / no signal → documented l4 fallback.
        return _SKU_FALLBACK
    if tier == _TIER_TINY:
        return _SKU_RTX_A4000
    if tier == _TIER_SMALL:
        return _SKU_L4
    if tier == _TIER_MEDIUM:
        return _SKU_A6000
    if tier == _TIER_MEDIUM_HIGH:
        return _SKU_L40S
    if tier == _TIER_LARGE:
        return _SKU_A100
    # CINEMA or higher
    return _SKU_H100


def _safe_int(value: Any) -> Optional[int]:
    """Return int(value) or None on any error."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = ["select_gpu_sku"]
