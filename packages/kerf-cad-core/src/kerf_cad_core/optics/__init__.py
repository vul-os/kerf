"""
kerf_cad_core.optics — geometric optics & lens design.

Public API (re-exported for convenience):

    from kerf_cad_core.optics import (
        lensmaker,
        thin_lens_imaging,
        mirror_imaging,
        two_lens_system,
        abcd_system,
        fnumber,
        numerical_aperture,
        depth_of_field,
        hyperfocal_distance,
        airy_spot_radius,
        snell,
        critical_angle,
        brewster_angle,
        prism_deviation,
        chromatic_aberration,
        achromat_powers,
    )

References
----------
Hecht, E. — "Optics", 5th ed. (2017)
Smith, W.J. — "Modern Optical Engineering", 4th ed. (2008)
Born & Wolf — "Principles of Optics", 7th ed. (1999)

Author: imranparuk
"""

from kerf_cad_core.optics.lens import (
    lensmaker,
    thin_lens_imaging,
    mirror_imaging,
    two_lens_system,
    abcd_free_space,
    abcd_refraction,
    abcd_thin_lens,
    abcd_thick_lens,
    abcd_mirror,
    abcd_system,
    fnumber,
    numerical_aperture,
    depth_of_field,
    hyperfocal_distance,
    airy_spot_radius,
    snell,
    critical_angle,
    brewster_angle,
    prism_deviation,
    chromatic_aberration,
    achromat_powers,
)
from kerf_cad_core.optics.petzval_curvature import (
    PetzvalReport,
    compute_petzval_curvature,
)
from kerf_cad_core.optics.mtf_diffraction import (
    MTFReport,
    compute_diffraction_mtf,
)
from kerf_cad_core.optics.zernike_fit import (
    ZernikeFitReport,
    fit_zernike_wavefront,
)
from kerf_cad_core.optics.spot_diagram import (
    SpotDiagramResult,
    compute_spot_diagram,
)
from kerf_cad_core.optics.sagitta_arrow_chart import (
    AsphericSurfaceSpec,
    SagittaArrowChartResult,
    compute_sagitta_arrow_chart,
)
from kerf_cad_core.optics.piston_tip_tilt import (
    PistonTipTiltReport,
    analyze_wavefront_alignment,
)
from kerf_cad_core.optics.seidel_coma import (
    SeidelComaReport,
    compute_seidel_coma,
)
from kerf_cad_core.optics.vignetting_check import (
    LensClearApertureSpec,
    VignettingReport as VignettingCheckReport,
    compute_vignetting as compute_vignetting_check,
)
from kerf_cad_core.optics.pixel_mtf import (
    PixelSensorSpec,
    PixelMtfReport,
    compute_pixel_mtf,
    combine_mtf_curves,
)
from kerf_cad_core.optics.focal_depth_field import (
    LensFocusSpec,
    DepthOfFieldReport,
    compute_depth_of_field,
)
from kerf_cad_core.optics.telecentricity_check import (
    TelecentricityReport,
    compute_telecentricity,
)
from kerf_cad_core.optics.fno_working import (
    FnoWorkingSpec,
    FnoWorkingReport,
    compute_working_fno,
)
from kerf_cad_core.optics.iris_diameter_map import (
    IrisMapSpec,
    IrisDiameterReport,
    compute_iris_diameter,
)
from kerf_cad_core.optics.diffraction_psf import (
    DiffractionPSFSpec,
    DiffractionPSFReport,
    compute_diffraction_psf,
)
from kerf_cad_core.optics.lens_volume import (
    SingletLensSpec,
    LensVolumeReport,
    compute_lens_volume,
)
from kerf_cad_core.optics.chief_ray_height import (
    ChiefRayHeightReport,
    trace_chief_ray,
)

__all__ = [
    "lensmaker",
    "thin_lens_imaging",
    "mirror_imaging",
    "two_lens_system",
    "abcd_free_space",
    "abcd_refraction",
    "abcd_thin_lens",
    "abcd_thick_lens",
    "abcd_mirror",
    "abcd_system",
    "fnumber",
    "numerical_aperture",
    "depth_of_field",
    "hyperfocal_distance",
    "airy_spot_radius",
    "snell",
    "critical_angle",
    "brewster_angle",
    "prism_deviation",
    "chromatic_aberration",
    "achromat_powers",
    "PetzvalReport",
    "compute_petzval_curvature",
    "MTFReport",
    "compute_diffraction_mtf",
    "ZernikeFitReport",
    "fit_zernike_wavefront",
    "SpotDiagramResult",
    "compute_spot_diagram",
    "AsphericSurfaceSpec",
    "SagittaArrowChartResult",
    "compute_sagitta_arrow_chart",
    "PistonTipTiltReport",
    "analyze_wavefront_alignment",
    "SeidelComaReport",
    "compute_seidel_coma",
    "LensClearApertureSpec",
    "VignettingCheckReport",
    "compute_vignetting_check",
    "PixelSensorSpec",
    "PixelMtfReport",
    "compute_pixel_mtf",
    "combine_mtf_curves",
    "LensFocusSpec",
    "DepthOfFieldReport",
    "compute_depth_of_field",
    "TelecentricityReport",
    "compute_telecentricity",
    "FnoWorkingSpec",
    "FnoWorkingReport",
    "compute_working_fno",
    "IrisMapSpec",
    "IrisDiameterReport",
    "compute_iris_diameter",
    "DiffractionPSFSpec",
    "DiffractionPSFReport",
    "compute_diffraction_psf",
    "SingletLensSpec",
    "LensVolumeReport",
    "compute_lens_volume",
    "ChiefRayHeightReport",
    "trace_chief_ray",
]
