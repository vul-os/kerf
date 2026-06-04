# optics

*Module: `kerf_cad_core.optics.tools` · Domain: cad*

This module registers **46** LLM tool(s):

- [`optics_lensmaker`](#optics-lensmaker)
- [`optics_thin_lens_imaging`](#optics-thin-lens-imaging)
- [`optics_mirror_imaging`](#optics-mirror-imaging)
- [`optics_two_lens_system`](#optics-two-lens-system)
- [`optics_abcd_system`](#optics-abcd-system)
- [`optics_fnumber`](#optics-fnumber)
- [`optics_numerical_aperture`](#optics-numerical-aperture)
- [`optics_depth_of_field`](#optics-depth-of-field)
- [`optics_airy_spot`](#optics-airy-spot)
- [`optics_snell`](#optics-snell)
- [`optics_critical_angle`](#optics-critical-angle)
- [`optics_brewster_angle`](#optics-brewster-angle)
- [`optics_prism_deviation`](#optics-prism-deviation)
- [`optics_chromatic_aberration`](#optics-chromatic-aberration)
- [`optics_achromat_powers`](#optics-achromat-powers)
- [`optics_ray_trace_lens_stack`](#optics-ray-trace-lens-stack)
- [`optics_mtf_across_field`](#optics-mtf-across-field)
- [`optics_seidel_aberrations`](#optics-seidel-aberrations)
- [`optics_compute_vignetting`](#optics-compute-vignetting)
- [`optics_pupil_diagram`](#optics-pupil-diagram)
- [`optics_defocus_curve`](#optics-defocus-curve)
- [`optics_distortion_map`](#optics-distortion-map)
- [`optics_compute_coma`](#optics-compute-coma)
- [`optics_compute_chromatic_focus`](#optics-compute-chromatic-focus)
- [`optics_compute_abbe_number`](#optics-compute-abbe-number)
- [`optics_compute_relative_illum_map`](#optics-compute-relative-illum-map)
- [`optics_compute_entrance_pupil`](#optics-compute-entrance-pupil)
- [`optics_compute_exit_pupil`](#optics-compute-exit-pupil)
- [`optics_compute_petzval_curvature`](#optics-compute-petzval-curvature)
- [`optics_compute_diffraction_mtf`](#optics-compute-diffraction-mtf)
- [`optics_fit_zernike_wavefront`](#optics-fit-zernike-wavefront)
- [`optics_analyze_wavefront_alignment`](#optics-analyze-wavefront-alignment)
- [`optics_compute_spot_diagram`](#optics-compute-spot-diagram)
- [`optics_compute_sagitta_arrow_chart`](#optics-compute-sagitta-arrow-chart)
- [`optics_compute_seidel_coma`](#optics-compute-seidel-coma)
- [`optics_compute_vignetting_check`](#optics-compute-vignetting-check)
- [`optics_compute_pixel_mtf`](#optics-compute-pixel-mtf)
- [`optics_compute_depth_of_field`](#optics-compute-depth-of-field)
- [`optics_compute_telecentricity`](#optics-compute-telecentricity)
- [`optics_compute_working_fno`](#optics-compute-working-fno)
- [`optics_compute_iris_diameter_map`](#optics-compute-iris-diameter-map)
- [`optics_compute_diffraction_psf`](#optics-compute-diffraction-psf)
- [`optics_compute_lens_volume`](#optics-compute-lens-volume)
- [`optics_trace_chief_ray`](#optics-trace-chief-ray)
- [`optics_design_schmidt_corrector`](#optics-design-schmidt-corrector)
- [`optics_trace_skew_ray`](#optics-trace-skew-ray)

---

## `optics_lensmaker`

Compute the focal length of a lens using the lensmaker's equation.

Thin lens (d=0, default):  1/f = (n-1)*(1/R1 - 1/R2)
Thick lens (d > 0):        1/f = (n-1)*[1/R1 - 1/R2 + (n-1)*d/(n*R1*R2)]

Sign convention (Cartesian): R > 0 if centre of curvature is to the right.
Use R = 1e18 (effectively infinity) for a flat surface.

Returns focal length f_m (m), optical power (dioptres), and lens_type.

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "R1": {
      "type": "number",
      "description": "Radius of curvature of the first surface (m). Non-zero."
    },
    "R2": {
      "type": "number",
      "description": "Radius of curvature of the second surface (m). Non-zero."
    },
    "n": {
      "type": "number",
      "description": "Refractive index of lens material (>= 1.0)."
    },
    "d": {
      "type": "number",
      "description": "Centre thickness (m). 0 for thin-lens approximation (default)."
    }
  },
  "required": [
    "R1",
    "R2",
    "n"
  ]
}
```

---

## `optics_thin_lens_imaging`

Thin-lens Gaussian imaging formula: image distance and magnification.

  1/s_i = 1/f - 1/s_o      m = -s_i / s_o

Returns s_i_m (image distance, m), magnification, image_type ('real' or 'virtual'), and erect (True if upright).

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "f": {
      "type": "number",
      "description": "Focal length (m). Negative for diverging lens."
    },
    "s_o": {
      "type": "number",
      "description": "Object distance (m). Positive for real object."
    }
  },
  "required": [
    "f",
    "s_o"
  ]
}
```

---

## `optics_mirror_imaging`

Spherical mirror imaging formula.

  f = R/2     1/s_i + 1/s_o = 2/R     m = -s_i / s_o

Sign convention: R > 0 = concave (converging), R < 0 = convex (diverging).
Returns s_i_m, magnification, f_m, mirror_type, image_type, erect.

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "R": {
      "type": "number",
      "description": "Radius of curvature (m). Non-zero. Positive = concave."
    },
    "s_o": {
      "type": "number",
      "description": "Object distance (m). Positive = real object."
    }
  },
  "required": [
    "R",
    "s_o"
  ]
}
```

---

## `optics_two_lens_system`

Two thin-lens system: effective focal length and principal-plane positions.

  1/f_eff = 1/f1 + 1/f2 - d/(f1*f2)

Returns f_eff_m, combined power (dioptres), delta_H_m (front principal plane from L1), delta_H_prime_m (rear principal plane from L2).

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "f1": {
      "type": "number",
      "description": "Focal length of first lens (m). Non-zero."
    },
    "f2": {
      "type": "number",
      "description": "Focal length of second lens (m). Non-zero."
    },
    "d": {
      "type": "number",
      "description": "Separation between the two lenses (m). Must be >= 0."
    }
  },
  "required": [
    "f1",
    "f2",
    "d"
  ]
}
```

---

## `optics_abcd_system`

Cascade a list of ABCD ray-transfer matrices into the system matrix.

Supported element types (pass as list of objects in 'elements'):
  {"type": "free_space", "d": <m>}
  {"type": "thin_lens", "f": <m>}
  {"type": "mirror", "R": <m>}
  {"type": "refraction", "n1": <>, "n2": <>, "R": <m>}

Elements are listed in the order the ray encounters them (left to right).
Returns A, B, C, D of the system matrix.

Errors: {ok:false, reason} for unknown element type or invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "elements": {
      "type": "array",
      "description": "List of optical element objects, each with a 'type' field and corresponding parameters.",
      "items": {
        "type": "object"
      }
    }
  },
  "required": [
    "elements"
  ]
}
```

---

## `optics_fnumber`

Compute the F-number (f/#) of a lens.

  N = f / D

Parameters: f (focal length, m), D (entrance-pupil diameter, m).
Returns f_number, f_m, D_m.

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "f": {
      "type": "number",
      "description": "Focal length (m). Must be > 0."
    },
    "D": {
      "type": "number",
      "description": "Entrance-pupil diameter (m). Must be > 0."
    }
  },
  "required": [
    "f",
    "D"
  ]
}
```

---

## `optics_numerical_aperture`

Compute the numerical aperture NA = n * sin(θ).

Parameters: n (refractive index >= 1), half_angle_rad (acceptance half-angle, rad).
Returns NA, n, half_angle_rad.

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "n": {
      "type": "number",
      "description": "Refractive index of medium (>= 1)."
    },
    "half_angle_rad": {
      "type": "number",
      "description": "Half-angle of acceptance cone (rad). [0, \u03c0/2]."
    }
  },
  "required": [
    "n",
    "half_angle_rad"
  ]
}
```

---

## `optics_depth_of_field`

Compute depth of field (DOF) and hyperfocal distance for a camera lens.

  H = f² / (N * c)     (hyperfocal distance)
  DOF_near = s_o*(H-f)/(H+s_o-2f)
  DOF_far  = s_o*(H-f)/(H-s_o)   [∞ if s_o >= H]

Returns DOF_total_m, DOF_near_m, DOF_far_m, hyperfocal_m.

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "f": {
      "type": "number",
      "description": "Focal length (m). Must be > 0."
    },
    "N": {
      "type": "number",
      "description": "F-number. Must be > 0."
    },
    "c": {
      "type": "number",
      "description": "Circle of confusion diameter (m). Must be > 0."
    },
    "s_o": {
      "type": "number",
      "description": "Subject distance from lens (m). Must be > 0."
    }
  },
  "required": [
    "f",
    "N",
    "c",
    "s_o"
  ]
}
```

---

## `optics_airy_spot`

Compute the diffraction-limited Airy disk radius (first dark ring).

  r_Airy = 1.22 * λ * N

Parameters: wavelength (m), N (F-number).
Returns r_airy_m, diameter_m.

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "wavelength": {
      "type": "number",
      "description": "Wavelength of light (m). E.g. 550e-9 for green light."
    },
    "N": {
      "type": "number",
      "description": "F-number. Must be > 0."
    }
  },
  "required": [
    "wavelength",
    "N"
  ]
}
```

---

## `optics_snell`

Apply Snell's law of refraction: n1*sin(θ1) = n2*sin(θ2).

Returns theta2_rad and tir=True when total internal reflection occurs (theta2_rad = NaN on TIR).

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "n1": {
      "type": "number",
      "description": "Refractive index of incident medium (>= 1)."
    },
    "theta1_rad": {
      "type": "number",
      "description": "Angle of incidence (rad). [0, \u03c0/2]."
    },
    "n2": {
      "type": "number",
      "description": "Refractive index of transmitted medium (>= 1)."
    }
  },
  "required": [
    "n1",
    "theta1_rad",
    "n2"
  ]
}
```

---

## `optics_critical_angle`

Compute the critical angle for total internal reflection.

  θ_c = arcsin(n2 / n1)    [requires n1 > n2]

Returns theta_c_rad, theta_c_deg, tir_possible.
Sets tir_possible=False (with a warning) if n1 <= n2.

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "n1": {
      "type": "number",
      "description": "Refractive index of denser medium (>= 1)."
    },
    "n2": {
      "type": "number",
      "description": "Refractive index of less-dense medium (>= 1)."
    }
  },
  "required": [
    "n1",
    "n2"
  ]
}
```

---

## `optics_brewster_angle`

Compute Brewster's angle (polarisation angle).

  θ_B = arctan(n2 / n1)

At this angle, p-polarised (TM) light is not reflected.
Returns theta_B_rad, theta_B_deg.

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "n1": {
      "type": "number",
      "description": "Refractive index of incident medium (>= 1)."
    },
    "n2": {
      "type": "number",
      "description": "Refractive index of transmitted medium (>= 1)."
    }
  },
  "required": [
    "n1",
    "n2"
  ]
}
```

---

## `optics_prism_deviation`

Compute the deviation angle for a ray through a prism.

Uses exact Snell's law at both surfaces. Returns delta_rad, delta_deg.
Sets tir=True and delta=NaN if total internal reflection occurs at either surface.

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "n": {
      "type": "number",
      "description": "Refractive index of prism material (>= 1)."
    },
    "apex_rad": {
      "type": "number",
      "description": "Apex angle of prism (rad). Range: (0, \u03c0/2]."
    },
    "theta_i_rad": {
      "type": "number",
      "description": "Angle of incidence at first surface (rad). [0, \u03c0/2)."
    }
  },
  "required": [
    "n",
    "apex_rad",
    "theta_i_rad"
  ]
}
```

---

## `optics_chromatic_aberration`

Compute longitudinal chromatic aberration (LCA) using the Abbe number.

  LCA = f / V

where V = (n_d - 1) / (n_F - n_C) is the Abbe V-number.
Typical values: crown glass V≈64, flint glass V≈36.

Returns LCA_m (m), f_m, V.

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "f": {
      "type": "number",
      "description": "Focal length (m). Non-zero."
    },
    "V": {
      "type": "number",
      "description": "Abbe V-number. Must be > 0."
    }
  },
  "required": [
    "f",
    "V"
  ]
}
```

---

## `optics_achromat_powers`

Compute crown/flint element powers for an achromatic doublet.

Achromatic condition:
  phi1/V1 + phi2/V2 = 0    with phi1 + phi2 = 1/f_total

  phi1 = phi_total * V1 / (V1 - V2)
  phi2 = -phi_total * V2 / (V1 - V2)

Typical: V1 = crown (~64), V2 = flint (~36).
Returns phi1_m, phi2_m, f1_m, f2_m.

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "f_total": {
      "type": "number",
      "description": "Target combined focal length (m). Non-zero."
    },
    "V1": {
      "type": "number",
      "description": "Abbe number of first (crown) element. Must be > 0."
    },
    "V2": {
      "type": "number",
      "description": "Abbe number of second (flint) element. Must be > 0. Must differ from V1."
    }
  },
  "required": [
    "f_total",
    "V1",
    "V2"
  ]
}
```

---

## `optics_ray_trace_lens_stack`

Sequential paraxial + meridional ray trace through a multi-element lens stack.

Traces a single ray (specified by height and angle at the first surface) through
an ordered list of optical surfaces using:
  * Paraxial refraction (Welford 1986 §3.3, nu-form).
  * Exact meridional Snell's law + Newton-Raphson conic intersect
    (Welford 1986 §5.2-5.3).

Also computes system paraxial properties (EFL, BFL, FFL).

NOTE v1 scope: ray heights + angles at each surface; EFL / BFL / FFL.
OUT OF SCOPE: Seidel aberration coefficients, polychromatic traces,
vignetting, skew rays.

Surface definition (each element of 'surfaces' array):
  c  : curvature 1/R (mm^-1). 0 = flat.
  t  : thickness to NEXT surface vertex (mm). Last surface: 0.
  n  : refractive index of medium AFTER this surface.
  k  : conic constant (default 0 = sphere).

Oracle: biconvex BK7 (n=1.5168, R1=+50 mm, R2=-50 mm, t=5 mm) => EFL ~48.4 mm
(Hecht 'Optics' 5e §6.4 thick-lens formula).

Returns paraxial_surfaces, meridional_surfaces (per-surface Y/L/M),
paraxial_image_distance_mm, meridional_image_Y_mm, EFL_mm, BFL_mm, FFL_mm.

Errors: {ok:false, reason} for invalid inputs. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "surfaces": {
      "type": "array",
      "description": "Ordered list of optical surface dicts. Each must have: c (mm^-1), t (mm), n (>= 1.0). Optional: k (conic, default 0).",
      "items": {
        "type": "object",
        "properties": {
          "c": {
            "type": "number",
            "description": "Curvature 1/R (mm^-1). 0 = flat."
          },
          "t": {
            "type": "number",
            "description": "Thickness to next surface (mm)."
          },
          "n": {
            "type": "number",
            "description": "Refractive index after surface (>= 1.0)."
          },
          "k": {
            "type": "number",
            "description": "Conic constant (default 0 = sphere)."
          }
        },
        "required": [
          "c",
          "t",
          "n"
        ]
      }
    },
    "ray_h": {
      "type": "number",
      "description": "Ray height at first surface (mm)."
    },
    "ray_u": {
      "type": "number",
      "description": "Ray angle in object space (rad). Small for paraxial."
    },
    "n_object": {
      "type": "number",
      "description": "Refractive index of object space (default 1.0 = air)."
    }
  },
  "required": [
    "surfaces",
    "ray_h",
    "ray_u"
  ]
}
```

---

## `optics_mtf_across_field`

Compute the tangential Modulation Transfer Function (MTF) as a function of
field angle (off-axis position) for a multi-element lens stack.

Algorithm (Hecht 'Optics' 5e SS11.2; Welford 1986 SS11.4):
  1. Trace a uniform aperture bundle from a point source at infinity at each
     field angle through the lens stack using exact meridional Snell traces.
  2. Histogram ray-intercept Y positions at the paraxial image plane -> line-PSF.
  3. FFT(PSF) -> MTF;  MTF[0] is normalised to 1.0.

Honest limits:
  * Monochromatic only. Polychromatic MTF requires integrating MTF(lambda)
    weighted by the spectral power density -- out of scope.
  * Tangential plane only; sagittal MTF is not computed.
  * Wavefront-based MTF (Strehl / OTF phase) is out of scope.

Surface definition (same as optics_ray_trace_lens_stack):
  c  : curvature 1/R (mm^-1). 0 = flat.
  t  : thickness to NEXT surface vertex (mm). Last surface: 0.
  n  : refractive index of medium AFTER this surface.
  k  : conic constant (default 0 = sphere).

Pass field_angles_deg as a list (e.g. [0, 5, 10, 14]) to get MTF curves for
all angles in a single call.

Returns for each field angle:
  frequencies_lp_per_mm : spatial frequency axis (lp/mm)
  mtf                   : MTF values in [0, 1]
  psf_bins_mm / psf     : line-PSF histogram
  n_rays_traced / n_rays_vignetted

Errors: {ok:false, reason} for invalid inputs. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "surfaces": {
      "type": "array",
      "description": "Ordered list of optical surface dicts. Each must have: c (mm^-1), t (mm), n (>= 1.0). Optional: k (conic, default 0).",
      "items": {
        "type": "object",
        "properties": {
          "c": {
            "type": "number",
            "description": "Curvature 1/R (mm^-1). 0 = flat."
          },
          "t": {
            "type": "number",
            "description": "Thickness to next surface (mm)."
          },
          "n": {
            "type": "number",
            "description": "Refractive index after surface (>= 1.0)."
          },
          "k": {
            "type": "number",
            "description": "Conic constant (default 0 = sphere)."
          }
        },
        "required": [
          "c",
          "t",
          "n"
        ]
      }
    },
    "field_angles_deg": {
      "type": "array",
      "description": "List of field angles in degrees (e.g. [0, 5, 10, 14]). 0 = on-axis. Ordering is preserved in the output.",
      "items": {
        "type": "number"
      }
    },
    "samples_per_aperture": {
      "type": "integer",
      "description": "Number of rays sampled across the entrance-pupil diameter (default 50). More rays give a smoother PSF and finer MTF sampling."
    },
    "aperture_radius_mm": {
      "type": "number",
      "description": "Half-diameter of the entrance pupil in mm (default 10 mm). Should be <= the physical clear aperture of the first surface."
    },
    "n_object": {
      "type": "number",
      "description": "Refractive index of object space (default 1.0 = air)."
    }
  },
  "required": [
    "surfaces",
    "field_angles_deg"
  ]
}
```

---

## `optics_seidel_aberrations`

Compute the five Seidel third-order aberration coefficients (S_I-S_V)
for a sequential lens stack via dual paraxial-ray trace.

Theory (Welford 1986 §6.2 / Born & Wolf §5.3):
  Traces a *marginal ray* (full aperture, on-axis) and a *chief ray*
  (zero height at stop, full field angle) through all surfaces.
  Per-surface contributions are summed:

    S_I   = -A^2    * h * delta(u/n)   [spherical aberration]
    S_II  = -A*Abar * h * delta(u/n)   [coma]
    S_III = -Abar^2 * h * delta(u/n)   [astigmatism]
    S_IV  = -H^2    * delta(c/n)        [Petzval field curvature]
    S_V   = (S_III + S_IV) * Abar/A    [distortion]

  where A = n*i (marginal refraction invariant), Abar = n*ibar (chief),
  H = Lagrange invariant (n*u*ybar - n*ubar*y), constant across surfaces.

  Positive S_I = under-corrected spherical aberration (converging singlet).

HONEST FLAG: Third-order only. Higher-order aberrations require Hopkins
exact finite-ray OPD. Monochromatic; chromatic aberrations excluded.
Stop assumed at first surface (entrance pupil = front surface).

Surface definition (each element of 'surfaces' array):
  c  : curvature 1/R (mm^-1). 0 = flat.
  t  : thickness to NEXT surface vertex (mm). Last surface: 0.
  n  : refractive index of medium AFTER this surface.
  k  : conic constant (default 0 = sphere, unused for paraxial Seidel).

Returns S_I, S_II, S_III, S_IV, S_V, H_lagrange, per_surface contributions,
and total_wavefront_aberration_waves (RSS / 8*lambda at 550 nm).

Errors: {ok:false, reason} for invalid inputs. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "surfaces": {
      "type": "array",
      "description": "Ordered list of optical surface dicts. Each must have: c (mm^-1), t (mm), n (>= 1.0). Optional: k (conic, unused).",
      "items": {
        "type": "object",
        "properties": {
          "c": {
            "type": "number",
            "description": "Curvature 1/R (mm^-1). 0 = flat."
          },
          "t": {
            "type": "number",
            "description": "Thickness to next surface (mm)."
          },
          "n": {
            "type": "number",
            "description": "Refractive index after surface (>= 1.0)."
          },
          "k": {
            "type": "number",
            "description": "Conic constant (default 0 = sphere)."
          }
        },
        "required": [
          "c",
          "t",
          "n"
        ]
      }
    },
    "aperture": {
      "type": "number",
      "description": "Marginal ray height at first surface (mm). Default 1.0."
    },
    "field_angle_deg": {
      "type": "number",
      "description": "Chief-ray field angle (degrees). Default 5.0."
    },
    "n_object": {
      "type": "number",
      "description": "Refractive index of object space (default 1.0 = air)."
    }
  },
  "required": [
    "surfaces"
  ]
}
```

---

## `optics_compute_vignetting`

Compute vignetting (relative illumination) across field angles for a
sequential lens stack.

Algorithm (Welford 1986 §4.5 / Hecht §6.6):
  1. For each field angle θ, trace N marginal rays uniformly around the
     entrance-pupil perimeter using the exact paraxial height formula.
  2. At each surface, check if the ray height exceeds the surface clear
     aperture (physical lens rim radius).  Rays that exceed any CA are
     blocked.
  3. Relative illumination (RI) = n_surviving / N_M.
  4. Compare RI against the natural cos⁴(θ) photometric baseline.

cos⁴ baseline: for a lens with no physical clipping, illumination falls
off as cos⁴(θ) due to projected-area + obliquity (Hecht §6.6).
Physical clipping causes RI to drop below this baseline.

HONEST FLAG: circular, rotationally-symmetric apertures only.
Anamorphic / off-axis stops, polychromatic pupil walk: NOT modelled.
Sagittal-ray component is projected onto the meridional plane.

Surface definition (each element of 'surfaces' array):
  c  : curvature 1/R (mm^-1). 0 = flat.
  t  : thickness to NEXT surface vertex (mm). Last surface: 0.
  n  : refractive index of medium AFTER this surface.
  k  : conic constant (default 0 = sphere).

Returns per-field:
  relative_illumination   : fraction of marginal rays that survive [0,1]
  cos4_baseline           : natural cos⁴(θ) baseline
  excess_vignetting       : RI / cos⁴ (< 1 means clipping beyond natural)
  per_field_blocked_surfaces : surface indices where clipping occurred

Errors: {ok:false, reason} for invalid inputs. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "surfaces": {
      "type": "array",
      "description": "Ordered list of optical surface dicts. Each must have: c (mm^-1), t (mm), n (>= 1.0). Optional: k (conic, default 0).",
      "items": {
        "type": "object",
        "properties": {
          "c": {
            "type": "number",
            "description": "Curvature 1/R (mm^-1). 0 = flat."
          },
          "t": {
            "type": "number",
            "description": "Thickness to next surface (mm)."
          },
          "n": {
            "type": "number",
            "description": "Refractive index after surface (>= 1.0)."
          },
          "k": {
            "type": "number",
            "description": "Conic constant (default 0 = sphere)."
          }
        },
        "required": [
          "c",
          "t",
          "n"
        ]
      }
    },
    "field_angles_deg": {
      "type": "array",
      "description": "List of field angles in degrees (e.g. [0, 5, 10, 14]). 0 = on-axis.",
      "items": {
        "type": "number"
      }
    },
    "aperture_radius_mm": {
      "type": "number",
      "description": "Entrance-pupil half-diameter (mm). Default 10 mm. Should be <= the physical clear aperture of the first surface."
    },
    "clear_apertures_mm": {
      "type": "array",
      "description": "Per-surface clear aperture radius (mm). Length must equal number of surfaces. Use 1e18 for surfaces with no physical rim (infinite aperture). If omitted, all surfaces are treated as infinite \u2014 produces pure cos\u2074.",
      "items": {
        "type": "number"
      }
    },
    "n_marginal_rays": {
      "type": "integer",
      "description": "Number of marginal rays sampled around the pupil perimeter. Default 8. Minimum 4."
    },
    "n_object": {
      "type": "number",
      "description": "Refractive index of object space (default 1.0 = air)."
    }
  },
  "required": [
    "surfaces",
    "field_angles_deg"
  ]
}
```

---

## `optics_pupil_diagram`

Generate spot diagrams and pupil illumination maps for a sequential lens stack.

Algorithm (Welford 1986 §8.2 / Hecht §5.7):
  1. For each field angle, fill the entrance pupil with a uniform grid of N
     ray positions (px, py) over the unit disk.
  2. Trace each ray through the lens stack using exact meridional Snell traces
     + Newton-Raphson conic intersect (trace_lens_stack).
  3. Collect (x, y) intercepts at the paraxial image plane:
       y_img : exact meridional trace result
       x_img : first-order sagittal estimate = -px * R_ap * BFL/EFL
         (pass use_skew_ray=True for exact 3-D x+y via Born & Wolf §4.6)
  4. Compute RMS spot radius (2-D), meridional y-only RMS, and max ray
     distance from chief ray.
  5. Return surviving pupil coordinates (exit-pupil illumination map).

Depth bar (Welford 1986 §8.2):
  * Stigmatic stack (flat surface, c=0): y-RMS < 1e-6 mm (single-point focus).
  * BK7 biconvex on-axis: y-RMS > 0 (spherical aberration).
  * BK7 biconvex at 14 deg: y-RMS >> y-RMS at 0 deg (coma dominates off-axis).
  * Use rms_spot_y_mm (meridional-only) as the aberration diagnostic;
    rms_spot_radius_mm (2-D) includes the first-order sagittal x contribution
    which is nearly constant across field angles.

HONEST FLAGS:
  * Monochromatic only in default mode. Polychromatic pupil illumination maps
    are not produced by this tool; for polychromatic spot analysis see
    optics_compute_spot_diagram with use_skew_ray=True and spectral weights.
  * Sagittal (x) intercepts are first-order estimates in default mode; pass
    use_skew_ray=True to trace a rigorous hexapolar 3-D skew-ray bundle
    (Born & Wolf §4.6) for exact x+y intercepts and vignetting detection.
  * Exit-pupil position is a paraxial estimate (BFL) in default mode; exact
    exit-pupil position via chief-ray back-trace is available via
    compute_exit_pupil_chief_ray() (Welford 1986 §3.5).
  * Physical aperture clipping not applied; use optics_compute_vignetting.

Surface definition (same as optics_ray_trace_lens_stack):
  c  : curvature 1/R (mm^-1). 0 = flat.
  t  : thickness to NEXT surface vertex (mm). Last surface: 0.
  n  : refractive index of medium AFTER this surface.
  k  : conic constant (default 0 = sphere).

Returns for each field angle:
  intercepts_mm          : list of [x_mm, y_mm] intercepts at image plane
  chief_ray_y_mm         : chief-ray y intercept
  rms_spot_radius_mm     : 2-D RMS spot radius (mm, includes sagittal x)
  rms_spot_y_mm          : meridional y-only RMS (aberration signal)
  max_ray_distance_mm    : max ray distance from chief ray (mm)
  n_rays_traced          : number of rays successfully traced
  pupil_coords_surviving : surviving [px, py] pupil positions
Plus top-level: rms_spot_size_per_field, rms_spot_y_per_field,
exit_pupil_pos_mm, EFL_mm.

Errors: {ok:false, reason} for invalid inputs. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "surfaces": {
      "type": "array",
      "description": "Ordered list of optical surface dicts. Each must have: c (mm^-1), t (mm), n (>= 1.0). Optional: k (conic, default 0).",
      "items": {
        "type": "object",
        "properties": {
          "c": {
            "type": "number",
            "description": "Curvature 1/R (mm^-1). 0 = flat."
          },
          "t": {
            "type": "number",
            "description": "Thickness to next surface (mm)."
          },
          "n": {
            "type": "number",
            "description": "Refractive index after surface (>= 1.0)."
          },
          "k": {
            "type": "number",
            "description": "Conic constant (default 0 = sphere)."
          }
        },
        "required": [
          "c",
          "t",
          "n"
        ]
      }
    },
    "field_angles_deg": {
      "type": "array",
      "description": "List of field angles in degrees (e.g. [0, 5, 10, 14]). 0 = on-axis.",
      "items": {
        "type": "number"
      }
    },
    "n_rays_per_field": {
      "type": "integer",
      "description": "Target number of rays per field angle (default 200). Actual count may be slightly less due to unit-disk clipping."
    },
    "aperture_radius_mm": {
      "type": "number",
      "description": "Entrance-pupil half-diameter (mm). Default 10 mm. Should be <= physical clear aperture of first surface."
    },
    "n_object": {
      "type": "number",
      "description": "Refractive index of object space (default 1.0 = air)."
    }
  },
  "required": [
    "surfaces",
    "field_angles_deg"
  ]
}
```

---

## `optics_defocus_curve`

Compute the through-focus RMS spot-size curve (defocus curve) for a lens stack.

Algorithm (Welford 1986 §11.5 / Hecht §6.5):
  1. Determine paraxial image distance (BFL) via marginal paraxial trace.
  2. For each of `samples` defocus steps Dz in [-defocus_range_mm, +defocus_range_mm],
     trace a uniform aperture bundle at field_angle_deg through the stack.
  3. Propagate each ray to the shifted evaluation plane (BFL + Dz).
  4. Compute meridional RMS = sqrt(mean((y - mean_y)^2)) over surviving rays.
  5. best_focus_shift_mm = Dz at minimum RMS.

Depth bar:
  * Ideal paraxial singlet at 0 deg: parabolic RMS curve; minimum at Dz=0.
  * Full-aperture singlet: spherical aberration shifts RMS minimum to Dz < 0
    (marginal best focus is closer to the lens than paraxial best focus).
  * Off-axis field: field curvature / astigmatism shifts the minimum further.

HONEST FLAGS:
  * MONOCHROMATIC ONLY in default mode. Polychromatic defocus curves are
    supported: pass use_skew_ray=True and spectral_weights=[(λ_nm, w), ...]
    to compute SPD-weighted RMS defocus (Hecht §6.3 / Welford §6.5); chromatic
    focus shift is then quantified as best_focus_shift_mm per wavelength.
  * MERIDIONAL (tangential) RMS only. Astigmatic sagittal/tangential focus
    splitting requires full 3-D skew-ray trace — use optics_trace_skew_ray.
  * Dz=0 is the paraxial BFL. For aberrated systems the RMS minimum may lie
    at Dz != 0; best_focus_shift_mm quantifies this offset.

Surface definition (same as optics_ray_trace_lens_stack):
  c  : curvature 1/R (mm^-1). 0 = flat.
  t  : thickness to NEXT surface vertex (mm). Last surface: 0.
  n  : refractive index of medium AFTER this surface.
  k  : conic constant (default 0 = sphere).

Returns:
  defocus_axis_mm      : list[float] -- Dz values (mm), length = samples
  rms_per_defocus_mm   : list[float] -- RMS spot radius at each Dz (mm)
  best_focus_shift_mm  : float -- Dz at RMS minimum
  min_rms_mm           : float -- RMS value at best focus
  bfl_mm               : float -- nominal paraxial BFL (mm)
  n_rays_valid         : list[int] -- surviving ray counts per step
  honest_flag          : str -- caveats

Errors: {ok:false, reason} for invalid inputs. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "surfaces": {
      "type": "array",
      "description": "Ordered list of optical surface dicts. Each must have: c (mm^-1), t (mm), n (>= 1.0). Optional: k (conic, default 0).",
      "items": {
        "type": "object",
        "properties": {
          "c": {
            "type": "number",
            "description": "Curvature 1/R (mm^-1). 0 = flat."
          },
          "t": {
            "type": "number",
            "description": "Thickness to next surface (mm)."
          },
          "n": {
            "type": "number",
            "description": "Refractive index after surface (>= 1.0)."
          },
          "k": {
            "type": "number",
            "description": "Conic constant (default 0 = sphere)."
          }
        },
        "required": [
          "c",
          "t",
          "n"
        ]
      }
    },
    "field_angle_deg": {
      "type": "number",
      "description": "Field angle from optical axis (degrees, default 0.0 = on-axis)."
    },
    "defocus_range_mm": {
      "type": "number",
      "description": "Half-width of the defocus scan (mm, default 0.5). Scans Dz in [-defocus_range_mm, +defocus_range_mm]."
    },
    "samples": {
      "type": "integer",
      "description": "Number of defocus steps (default 21, minimum 3)."
    },
    "aperture_radius_mm": {
      "type": "number",
      "description": "Entrance-pupil half-diameter (mm, default 10 mm)."
    },
    "n_rays": {
      "type": "integer",
      "description": "Number of rays across the entrance-pupil diameter (default 51)."
    },
    "n_object": {
      "type": "number",
      "description": "Refractive index of object space (default 1.0 = air)."
    }
  },
  "required": [
    "surfaces"
  ]
}
```

---

## `optics_distortion_map`

Compute the geometric (tangential) distortion map for a sequential lens stack.

For each field angle θ, traces the chief ray (height=0 at first surface,
aperture stop = first surface) and computes:
  y_actual    = exact meridional image-plane intercept (chief ray).
  y_paraxial  = f_eff * tan(θ)  (ideal first-order image height).
  distortion  = (y_actual - y_paraxial) / |y_paraxial| × 100  [%]

Sign convention (Hecht §5.6 / ISO 9039):
  barrel distortion     → D < 0  (image compressed at edges)
  pincushion distortion → D > 0  (image stretched at edges)

Also returns the Seidel third-order S_V additive prediction
(Welford §6.3) for comparison: accurate for small θ, diverges at
large field where higher-order terms dominate.

Depth bar:
  Symmetric equiconvex singlet at small field: |D| < 2%
    (S_V ≈ 0 by bending symmetry; Welford §6.4).
  BK7 biconvex singlet at 20 deg field: |D| > 5% typical
    for an uncorrected singlet with high S_V coefficient.

HONEST FLAGS:
  * Monochromatic only for the main distortion_percent output. Spectral
    distortion (lateral chromatic distortion) is available via
    compute_spectral_distortion(): SPD-weighted D̄(θ)=∫D(θ,λ)·SPD(λ)dλ with
    standard CIE photopic, D65, and blackbody SPD helpers.
  * Tangential (meridional) distortion only. For rotationally symmetric
    systems sagittal distortion is identical; astigmatic differences ignored.
  * Aperture stop assumed at first surface (chief ray height = 0 there).

Surface definition (same as optics_ray_trace_lens_stack):
  c  : curvature 1/R (mm^-1). 0 = flat.
  t  : thickness to NEXT surface vertex (mm). Last surface: 0.
  n  : refractive index of medium AFTER this surface.
  k  : conic constant (default 0 = sphere).

Returns:
  field_angles_deg         : input field angles (degrees)
  y_actual_mm              : actual chief-ray image heights (mm)
  y_paraxial_mm            : ideal paraxial image heights (mm)
  distortion_percent       : (y_actual - y_paraxial)/|y_paraxial| × 100
  max_distortion_pct       : max |distortion| across all field angles
  kind                     : 'barrel' | 'pincushion' | 'mixed' | 'none'
  EFL_mm                   : effective focal length used for y_paraxial
  seidel_distortion_percent: Seidel S_V third-order additive prediction (%)
  honest_flag              : caveats

Errors: {ok:false, reason} for invalid inputs. Never raises.

References: Hecht §5.6; Welford 1986 §6.3.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "surfaces": {
      "type": "array",
      "description": "Ordered list of optical surface dicts. Each must have: c (mm^-1), t (mm), n (>= 1.0). Optional: k (conic, default 0).",
      "items": {
        "type": "object",
        "properties": {
          "c": {
            "type": "number",
            "description": "Curvature 1/R (mm^-1). 0 = flat."
          },
          "t": {
            "type": "number",
            "description": "Thickness to next surface (mm)."
          },
          "n": {
            "type": "number",
            "description": "Refractive index after surface (>= 1.0)."
          },
          "k": {
            "type": "number",
            "description": "Conic constant (default 0 = sphere)."
          }
        },
        "required": [
          "c",
          "t",
          "n"
        ]
      }
    },
    "field_angles_deg": {
      "type": "array",
      "description": "List of field angles in degrees (e.g. [0, 5, 10, 15, 20]). 0 = on-axis (distortion = 0 by definition).",
      "items": {
        "type": "number"
      }
    },
    "aperture_mm": {
      "type": "number",
      "description": "Marginal ray height for Seidel cross-check and paraxial EFL computation (mm). Default 1.0 mm."
    },
    "n_object": {
      "type": "number",
      "description": "Refractive index of object space (default 1.0 = air)."
    }
  },
  "required": [
    "surfaces",
    "field_angles_deg"
  ]
}
```

---

## `optics_compute_coma`

Compute coma aberration metrics from a lens stack across multiple field angles.

Algorithm (Welford 1986 §11.4 / Born & Wolf §5.3):
  1. Establish the paraxial focal plane (marginal ray h=aperture, u=0).
  2. For each field angle, trace N rim rays at heights h=ap·cos(φ) with
     angle u=tan(θ_f) using exact meridional Snell traces.
  3. Propagate each ray to the paraxial focal plane.
  4. Tangential coma = |mean(Y_tang) − y₀|, where Y_tang are the tangential-
     fan ray intercepts and y₀ is the paraxial chief-ray image height
     (Welford §11.4 — the comatic flare length).
  5. Sagittal coma = tangential_coma / 3 (Welford §11.4 eq. 11.4.4).
  6. total_coma = sqrt(tangential² + sagittal²).
  7. Seidel prediction = 3 × |S_II| × |y₀|
     where S_II is the Seidel coma coefficient (Born & Wolf §5.3 eq. 5.3.29).

Depth bar:
  * Afocal / flat stacks (c=0): coma = 0 (no focal plane).
  * BK7 biconvex (R=±50 mm, t=5 mm, n=1.5168) at 14° field, 5 mm aperture:
    total_coma > 1 μm (1e-3 mm).
  * Field-angle scaling: total_coma ∝ |tan(θ)| (linear in small-angle limit).
  * Seidel match: < 50% error at ≤ 5° field.

HONEST FLAG: Third-order (Seidel) coma by default. Higher-order coma
(Hopkins 5th-order, oblique spherical aberration) is available via
finite-ray OPD analysis: pass compare_seidel_to_finite_ray=True to add
the W₁₃₁ Zernike-fitted coma term and residual higher-order contribution;
or call compare_seidel_vs_finite_ray_coma() directly. Monochromatic;
chromatic coma excluded.
Stop assumed at first surface.

Surface definition (same as optics_ray_trace_lens_stack):
  c  : curvature 1/R (mm^-1). 0 = flat.
  t  : thickness to NEXT surface vertex (mm). Last surface: 0.
  n  : refractive index of medium AFTER this surface.
  k  : conic constant (default 0 = sphere).

Returns:
  S_II                 : float  Seidel coma coefficient
  aperture_radius_mm   : float  pupil rim radius used
  per_field            : list   one entry per field angle:
    field_angle_deg      : input angle (deg)
    tangential_coma_mm   : comatic flare length in tangential plane (mm)
    sagittal_coma_mm     : coma in sagittal plane = tan_coma/3 (mm)
    total_coma_mm        : sqrt(tan² + sag²) (mm)
    seidel_prediction_mm : 3×|S_II|×|y_chief| (mm)
    seidel_match_fraction: |total − seidel_total|/seidel_total; null when seidel≈0
    chief_ray_y_mm       : paraxial chief-ray image height (mm)
    n_rays_valid         : number of successfully traced rim rays
  honest_flag          : str caveats

Errors: {ok:false, reason} for invalid inputs. Never raises.

References: Welford (1986) §11.4; Born & Wolf (1999) §5.3.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "surfaces": {
      "type": "array",
      "description": "Ordered list of optical surface dicts. Each must have: c (mm^-1), t (mm), n (>= 1.0). Optional: k (conic, default 0).",
      "items": {
        "type": "object",
        "properties": {
          "c": {
            "type": "number",
            "description": "Curvature 1/R (mm^-1). 0 = flat."
          },
          "t": {
            "type": "number",
            "description": "Thickness to next surface (mm)."
          },
          "n": {
            "type": "number",
            "description": "Refractive index after surface (>= 1.0)."
          },
          "k": {
            "type": "number",
            "description": "Conic constant (default 0 = sphere)."
          }
        },
        "required": [
          "c",
          "t",
          "n"
        ]
      }
    },
    "field_angles_deg": {
      "type": "array",
      "description": "List of field angles in degrees (e.g. [0, 5, 10, 14]). 0 = on-axis (coma = 0 by symmetry).",
      "items": {
        "type": "number"
      }
    },
    "n_pupil_rays": {
      "type": "integer",
      "description": "Number of rim rays sampled around the entrance pupil (default 16). Must be >= 4."
    },
    "aperture_radius_mm": {
      "type": "number",
      "description": "Entrance-pupil rim radius (mm). Default 1.0. Should be <= physical clear aperture of the first surface."
    },
    "n_object": {
      "type": "number",
      "description": "Refractive index of object space (default 1.0 = air)."
    }
  },
  "required": [
    "surfaces",
    "field_angles_deg"
  ]
}
```

---

## `optics_compute_chromatic_focus`

Compute longitudinal chromatic aberration (LCA) through a thin-lens stack
using Sellmeier dispersion for each glass element.

For each wavelength λ, refractive indices n(λ) are evaluated from the
Sellmeier equation:
  n²(λ) = 1 + Σ B_i·λ²/(λ² − C_i)   [λ in μm; Schott catalog coefficients]

The paraxial back focal length (BFL) is derived via thin-lens ABCD matrix
reduction at each wavelength. Primary LCA is:
  LCA = BFL(F, 486 nm) − BFL(C, 656 nm)

Depth bar (Hecht §6.3 / Welford §6.5):
  BK7 singlet f=100 mm: V = (n_d−1)/(n_F−n_C) ≈ 64.2; LCA ≈ f/V ≈ 1.56 mm.
  BK7+F2 achromatic doublet: LCA < 0.1 mm (F-line focus ≈ C-line focus).
  SF6 singlet f=100 mm: V ≈ 25.4; LCA ≈ 3.9 mm (high LCA dense flint).

HONEST FLAGS:
  * PARAXIAL THIN-LENS LCA ONLY. Chromatic lateral aberration (transverse
    colour) is NOT computed (requires real chief-ray traces per wavelength).
  * Thick-lens principal-plane shifts with wavelength are not modelled.
  * V_number is reported only for single-element stacks. For two-element
    systems, use design_achromatic_doublet() (Smith MOE §6.4) which performs
    Abbe-number balancing (φ₁/V₁ + φ₂/V₂ = 0) and reports residual LCA.

Supported glasses: BK7, F2, SF6, K5, SF11, BK10 (Schott catalog 2023).

Each element of 'stack' requires:
  glass          — glass name string (e.g. 'BK7')
  R1             — front radius of curvature (mm). Non-zero; use 1e18 for flat.
  R2             — rear radius of curvature (mm). Non-zero; use -1e18 for flat.
  separation_mm  — axial gap to next element (mm). 0 for last element.

Returns:
  per_wavelength_focal_mm — dict mapping e.g. '486nm' -> BFL (mm)
  lca_FC_mm               — BFL(486nm) − BFL(656nm)  (mm; negative = blue shorter)
  lca_percent             — |LCA| / mean_BFL × 100
  V_number                — Abbe V-number (singlet only; null for multi-element)
  mean_BFL_mm             — mean BFL across requested wavelengths
  honest_flag             — scope caveats

Errors: {ok:false, reason} for invalid inputs. Never raises.

References: Hecht §6.3; Welford (1986) §6.5; Schott Optical Glass catalog 2023.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "stack": {
      "type": "array",
      "description": "Ordered list of thin-lens elements, front to back. Each element: glass (str), R1 (mm), R2 (mm), separation_mm (mm, default 0).",
      "items": {
        "type": "object",
        "properties": {
          "glass": {
            "type": "string",
            "description": "Schott glass name. Supported: BK7, F2, SF6, K5, SF11, BK10."
          },
          "R1": {
            "type": "number",
            "description": "Front surface radius of curvature (mm). Non-zero; use 1e18 for flat surface."
          },
          "R2": {
            "type": "number",
            "description": "Rear surface radius of curvature (mm). Non-zero; use -1e18 for flat surface."
          },
          "separation_mm": {
            "type": "number",
            "description": "Axial gap to next element (mm). Use 0 for last element or cemented pair."
          }
        },
        "required": [
          "glass",
          "R1",
          "R2"
        ]
      }
    },
    "wavelengths_nm": {
      "type": "array",
      "description": "Wavelengths to evaluate (nm). Defaults to [486, 587, 656] (F, d, C Fraunhofer lines).",
      "items": {
        "type": "number"
      }
    }
  },
  "required": [
    "stack"
  ]
}
```

---

## `optics_compute_abbe_number`

Compute the Abbe number (V-number) and secondary-spectrum partial
dispersion for a named Schott glass using its Sellmeier coefficients.

Abbe number (ISO 10110 / Hecht §6.3):
  V_d = (n_d − 1) / (n_F − n_C)

where n_d, n_F, n_C are refractive indices at Fraunhofer lines:
  d  — helium  d-line  587.56 nm  (photopic peak)
  F  — hydrogen F-line 486.13 nm  (blue)
  C  — hydrogen C-line 656.27 nm  (red)

High V (> 55) = crown glass (low dispersion); e.g. BK7 V ≈ 64.17.
Low  V (< 40) = flint glass (high dispersion); e.g. SF11 V ≈ 25.76.

Secondary spectrum partial dispersion P_{F,g}:
  P_FC_g = (n_g − n_F) / (n_F − n_C)
where n_g is the refractive index at the mercury g-line (435.84 nm).
Matching P_{F,g} between two glasses suppresses residual secondary
spectrum (apochromat condition, Hecht §6.3 / Conrady criterion).

Supported glasses: BK7, F2, SF6, K5, SF11, BK10 (Schott catalog 2023).

Depth bar (Schott catalog values):
  BK7:  V_d = 64.17  (n_d = 1.5168)
  F2:   V_d = 36.37  (n_d = 1.6200)
  SF11: V_d = 25.76  (n_d = 1.7847)
  SF6:  V_d = 25.43  (n_d = 1.8052)
  K5:   V_d = 59.48  (n_d = 1.5225)
  BK10: V_d = 67.02  (n_d = 1.4978)

Returns glass_name, n_d, n_F, n_C, n_g, V_d, P_FC_g, honest_flag.

HONEST FLAG: Sellmeier coefficients are catalog nominal/melt-mean values;
melt-to-melt V_d variation ±0.3–0.5% (Schott TIE-31). Only six glasses
are available; other glasses require adding their Sellmeier coefficients.

Errors: {ok:false, reason} for unknown glass or invalid input. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "glass_name": {
      "type": "string",
      "description": "Schott glass name (case-sensitive). One of: BK7, F2, SF6, K5, SF11, BK10."
    }
  },
  "required": [
    "glass_name"
  ]
}
```

---

## `optics_compute_relative_illum_map`

Compute a 2-D relative illumination (RI) map across the image plane
for a sequential lens stack.

For each grid point (x, y) on the sensor the field angle
  theta(x, y) = arctan(sqrt(x^2+y^2) / EFL)
is computed and RI(theta) is evaluated by tracing a bundle of marginal
rays through all lens surfaces and counting the surviving fraction.

Theory (Welford 1986 §4.5 / Hecht §6.6 / Slyusarev §3.4):
  cos4_map: natural cos4(theta) photometric baseline — 1.0 at centre,
    falling to cos4(theta_corner) at corners (Hecht §6.6 eq. 6.68).
  ri_map: physical aperture clipping model — 1.0 everywhere without
    clear_apertures_mm; drops below 1.0 when finite CAs block marginal rays.
  Real system with clipping: ri_map shows sharper drop than cos4 baseline.
  Wide-angle lens (theta_max > 50 deg): cos4_corner < 16%.

Returns:
  ri_map      : 2-D list (grid x grid), physical clipping model RI.
  cos4_map    : 2-D list (grid x grid), cos4(theta) natural baseline.
  corner_ri   : RI at sensor corner (physical clipping).
  corner_cos4 : cos4 baseline at corner.
  max_field_angle : degrees at sensor corner.
  efl_mm      : effective focal length used (mm).

HONEST FLAGS:
  * Monochromatic only (polychromatic pupil walk out of scope).
  * Rotationally symmetric stack assumed; map is azimuthally symmetric.
  * Sensor acceptance tilt / field-lens telecentricity not modelled.

Surface definition (same as optics_ray_trace_lens_stack):
  c : curvature 1/R (mm^-1). 0 = flat.
  t : thickness to NEXT surface (mm). Last surface: 0.
  n : refractive index after surface (>= 1.0).
  k : conic constant (default 0 = sphere).

Errors: {ok:false, reason} for invalid inputs. Never raises.

References: Welford 1986 §4.5; Hecht §6.6; Slyusarev §3.4.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "surfaces": {
      "type": "array",
      "description": "Ordered list of optical surface dicts. Each must have: c (mm^-1), t (mm), n (>= 1.0). Optional: k (conic, default 0).",
      "items": {
        "type": "object",
        "properties": {
          "c": {
            "type": "number",
            "description": "Curvature 1/R (mm^-1). 0 = flat."
          },
          "t": {
            "type": "number",
            "description": "Thickness to next surface (mm)."
          },
          "n": {
            "type": "number",
            "description": "Refractive index after surface (>= 1.0)."
          },
          "k": {
            "type": "number",
            "description": "Conic constant (default 0 = sphere)."
          }
        },
        "required": [
          "c",
          "t",
          "n"
        ]
      }
    },
    "image_grid_size": {
      "type": "integer",
      "description": "Number of grid points per side (default 33, minimum 3). Odd values place a sample at the exact image centre."
    },
    "sensor_half_height_mm": {
      "type": "number",
      "description": "Half-side of the square sensor (mm). Default 15 mm (30 mm sensor \u2014 full-frame 35 mm equivalent)."
    },
    "aperture_radius_mm": {
      "type": "number",
      "description": "Entrance-pupil half-diameter (mm). Default 10 mm."
    },
    "clear_apertures_mm": {
      "type": "array",
      "description": "Per-surface clear aperture radius (mm). Length must equal number of surfaces. Use 1e18 for surfaces with no physical rim. If omitted, all surfaces are infinite \u2014 ri_map = all 1.0.",
      "items": {
        "type": "number"
      }
    },
    "n_marginal_rays": {
      "type": "integer",
      "description": "Marginal rays per field angle (default 8, minimum 4)."
    },
    "n_object": {
      "type": "number",
      "description": "Refractive index of object space (default 1.0 = air)."
    }
  },
  "required": [
    "surfaces"
  ]
}
```

---

## `optics_compute_entrance_pupil`

Compute the paraxial entrance pupil position and size for a lens stack.

The entrance pupil is the image of the aperture stop formed by all lens
elements in front of the stop, as seen from object space.
Its position and semi-diameter define the light-gathering cone accepted
by the system (Welford 1986 §4.4; Hecht §6.6).

Algorithm (Welford 1986 §4.4):
  For each surface j = stop_surface_index−1 … 0 (right to left):
    1. Transfer backward by t[j] (gap from surface j to next surface).
    2. Refract at surface j with negated curvature (reverse-trace convention).
  Then:
    position_z_mm = -h_exit / u_exit  (axis crossing from first surface).
    radius_mm = D * stop_radius  where D is the (2,2) paraxial matrix element.
    magnification = radius_mm / (stop_diameter_mm / 2).

Depth bar:
  * Stop at first surface (stop_surface_index=0): pupil at z=0, m=1.
    (Thin-lens identity; Hecht §6.6.)
  * Converging front lens, rear stop (d << f): pupil at positive z,
    slightly demagnified (m < 1). (BK7 biconvex, stop at rear surface.)
  * Diverging front lens, rear stop: pupil at negative z (virtual),
    magnified (m > 1). (Hecht §6.6 virtual-pupil example.)

HONEST FLAGS:
  * PARAXIAL ONLY.  Real chief-ray entrance pupil requires finite-ray
    chief-ray back-tracing from the stop; for rigorous exit-pupil position
    via chief-ray tracing use compute_exit_pupil_chief_ray() (Welford §3.5).
  * EXIT PUPIL is a separate computation (not in this tool).
  * Stop modelled as a thin plane; thick stops not handled.
  * Paraxial approximation degrades for fast (f/# < 2) or wide-field systems.

Surface definition (same as optics_ray_trace_lens_stack):
  c  : curvature 1/R (mm^-1). 0 = flat.
  t  : thickness to NEXT surface vertex (mm). Last surface: 0.
  n  : refractive index of medium AFTER this surface.
  k  : conic constant (default 0; unused for paraxial trace).

Returns:
  position_z_mm  : entrance pupil z-position from first surface (mm).
                   Negative = virtual pupil in front of the first surface.
  radius_mm      : entrance pupil semi-diameter (mm).
  diameter_mm    : full entrance pupil diameter (mm).
  magnification  : D matrix element of front group (radius / stop_radius).
  honest_flag    : scope caveats.

Errors: {ok:false, reason} for invalid inputs. Never raises.

References: Welford (1986) §4.4; Hecht §6.6.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "surfaces": {
      "type": "array",
      "description": "Ordered list of optical surface dicts. Each must have: c (mm^-1), t (mm), n (>= 1.0). Optional: k (conic, default 0).",
      "items": {
        "type": "object",
        "properties": {
          "c": {
            "type": "number",
            "description": "Curvature 1/R (mm^-1). 0 = flat."
          },
          "t": {
            "type": "number",
            "description": "Thickness to next surface (mm)."
          },
          "n": {
            "type": "number",
            "description": "Refractive index after surface (>= 1.0)."
          },
          "k": {
            "type": "number",
            "description": "Conic constant (default 0 = sphere)."
          }
        },
        "required": [
          "c",
          "t",
          "n"
        ]
      }
    },
    "stop_diameter_mm": {
      "type": "number",
      "description": "Full diameter of the aperture stop (mm). Must be > 0."
    },
    "stop_surface_index": {
      "type": "integer",
      "description": "0-based index of the aperture-stop surface (default 0 = first surface). The stop is at the vertex plane of this surface."
    },
    "n_object": {
      "type": "number",
      "description": "Refractive index of object space (default 1.0 = air)."
    }
  },
  "required": [
    "surfaces",
    "stop_diameter_mm"
  ]
}
```

---

## `optics_compute_exit_pupil`

Compute the paraxial exit pupil position and size for a lens stack.

The exit pupil is the image of the aperture stop formed by all lens
elements behind the stop, as seen from image space.
Its position and semi-diameter define the cone of rays converging
toward each image point (Welford 1986 §4.4; Hecht §6.6).

Algorithm (Welford 1986 §4.4, two-ray forward trace):
  Ray 1 (h=stop_r, nu=0) and Ray 2 (h=0, nu=1) are traced forward
  from the stop through the rear sub-stack.
  position_z_mm = -h2_last / u2_last  (image of stop via B-element; Welford eq. 4.4.5)
  radius_mm = |h1_last + z_ep * u1_last|  (stop edge image height at exit pupil plane)
  magnification = radius_mm / (stop_diameter_mm / 2)

Depth bar:
  * Stop at last surface (stop_surface_index=N-1): pupil at z=0, m=1.
    (Thin-lens identity; Hecht §6.6.)
  * Thin lens (t=0), stop at front surface: pupil at z=0, m=1.
  * BK7 biconvex, stop at first surface: virtual pupil (z<0) just
    inside the rear surface; m approx 1.035.
  * Afocal telescope (f_obj=100mm, f_eye=25mm): stop at objective ->
    Ramsden disk at z=31.25mm, radius=1.25mm, m=0.25 = 1/M_telescope.
    (Hecht §6.6 Ramsden disk.)

HONEST FLAGS:
  * PARAXIAL ONLY.  Real chief-ray exit pupil with exact position is
    available via compute_exit_pupil_chief_ray(): traces the chief ray
    (h=0 at aperture stop) through downstream surfaces; solves axis-crossing
    in image space for exact exit-pupil z-position (Welford 1986 §3.5).
  * ENTRANCE PUPIL is a separate computation (optics_compute_entrance_pupil).
  * Stop modelled as a thin plane; thick stops not handled.
  * Paraxial approximation degrades for fast (f/# < 2) or wide-field systems.

Surface definition (same as optics_ray_trace_lens_stack):
  c  : curvature 1/R (mm^-1). 0 = flat.
  t  : thickness to NEXT surface vertex (mm). Last surface: 0.
  n  : refractive index of medium AFTER this surface.
  k  : conic constant (default 0; unused for paraxial trace).

Returns:
  position_z_mm  : exit pupil z-position from last surface (mm).
                   Positive = real pupil behind the last surface.
                   Negative = virtual pupil inside the barrel.
  radius_mm      : exit pupil semi-diameter (mm).
  diameter_mm    : full exit pupil diameter (mm).
  magnification  : radius / stop_radius (rear group transverse mag).
  honest_flag    : scope caveats.

Errors: {ok:false, reason} for invalid inputs. Never raises.

References: Welford (1986) §4.4; Hecht §6.6.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "surfaces": {
      "type": "array",
      "description": "Ordered list of optical surface dicts. Each must have: c (mm^-1), t (mm), n (>= 1.0). Optional: k (conic, default 0).",
      "items": {
        "type": "object",
        "properties": {
          "c": {
            "type": "number",
            "description": "Curvature 1/R (mm^-1). 0 = flat."
          },
          "t": {
            "type": "number",
            "description": "Thickness to next surface (mm)."
          },
          "n": {
            "type": "number",
            "description": "Refractive index after surface (>= 1.0)."
          },
          "k": {
            "type": "number",
            "description": "Conic constant (default 0 = sphere)."
          }
        },
        "required": [
          "c",
          "t",
          "n"
        ]
      }
    },
    "stop_diameter_mm": {
      "type": "number",
      "description": "Full diameter of the aperture stop (mm). Must be > 0."
    },
    "stop_surface_index": {
      "type": "integer",
      "description": "0-based index of the aperture-stop surface (default 0 = first surface). The stop is at the vertex plane of this surface."
    },
    "n_object": {
      "type": "number",
      "description": "Refractive index of object space (default 1.0 = air)."
    }
  },
  "required": [
    "surfaces",
    "stop_diameter_mm"
  ]
}
```

---

## `optics_compute_petzval_curvature`

Compute Petzval field curvature (1/R_P) for a sequential optical system.

Theory (Hecht 'Optics' 5e §6.3.2 / Born & Wolf §4.5):
  The Petzval sum is the curvature of the Petzval sphere — the ideal image
  surface for a system free of astigmatism:

    P = Σ_i (n_after_i − n_before_i) / (n_before_i · n_after_i · R_i)

  Petzval radius R_P = 1/P.
  P = 0 (flat-field condition) requires compensating positive and negative
  contributions from lens elements with appropriate glass choice and bending.

Oracle: single thin BK7 lens (n=1.5168, R1=+50 mm, R2=−50 mm):
  Surface 1: P_1 = (1.5168−1)/(1·1.5168·50) = 0.006813 mm⁻¹
  Surface 2: P_2 = (1−1.5168)/(1.5168·1·(−50)) = 0.006813 mm⁻¹ → wait
  Correct:   P_2 = (1.0 − 1.5168) / (1.5168 · 1.0 · (−50)) = +0.006813
  Total P ≈ 0.013657 mm⁻¹  →  R_P ≈ 73.2 mm.

Input format:
  'surfaces' is a list of dicts, each with:
    radius_mm      : float  Radius of curvature (mm). Use 1e18 for plano.
    n_index_before : float  Refractive index before this surface (>= 1.0).
    n_index_after  : float  Refractive index after this surface (>= 1.0).

  Note: unlike optics_ray_trace_lens_stack (which uses curvature c=1/R),
  THIS tool uses radius_mm directly for clarity.

Returns:
  petzval_sum_mm_inv       : P = 1/R_P (mm⁻¹). 0 = flat field.
  petzval_radius_mm        : R_P = 1/P (mm). null when P=0 (flat).
  field_flatness_score     : 0..1 quality score; 1.0 = flat field.
  per_surface_contributions: per-surface breakdown with radius, n values,
                             contribution, and is_plano flag.
  honest_caveat            : scope caveats (astigmatism, thick-lens effects).

HONEST FLAG:
  Petzval sum is a PARAXIAL quantity. It equals the Seidel S_IV
  field-curvature coefficient but does NOT include astigmatism (S_III).
  Real curved-field appearance includes both S_III and S_IV.
  P=0 guarantees a flat Petzval sphere but NOT zero field curvature in
  the presence of astigmatism (Hecht §6.3.2).
  Thick-lens and pupil-shift corrections to P are ignored.

Errors: {ok:false, reason} for invalid inputs. Never raises.

References: Hecht §6.3.2; Born & Wolf §4.5; Smith 'Modern Optical Engineering' §4.4.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "surfaces": {
      "type": "array",
      "description": "Ordered list of refracting surface dicts. Each must have: radius_mm (float; use 1e18 for plano), n_index_before (float >= 1.0), n_index_after (float >= 1.0).",
      "items": {
        "type": "object",
        "properties": {
          "radius_mm": {
            "type": "number",
            "description": "Radius of curvature (mm). Sign: R > 0 if centre of curvature is to the right. Use 1e18 for a flat (plano) surface."
          },
          "n_index_before": {
            "type": "number",
            "description": "Refractive index of medium before this surface (>= 1.0)."
          },
          "n_index_after": {
            "type": "number",
            "description": "Refractive index of medium after this surface (>= 1.0)."
          }
        },
        "required": [
          "radius_mm",
          "n_index_before",
          "n_index_after"
        ]
      }
    }
  },
  "required": [
    "surfaces"
  ]
}
```

---

## `optics_compute_diffraction_mtf`

Compute the diffraction-limited Modulation Transfer Function MTF(ν) for a
circular aperture as a function of spatial frequency (cyc/mm).

Theory (Goodman 'Introduction to Fourier Optics' §6.4, eq. 6-49;
        Hecht 'Optics' 5e §11.3.3):

  ν_0 = 1 / (λ · F#)               [diffraction cutoff, cyc/mm]

  MTF(ν) = (2/π)·[arccos(ν/ν_0) − (ν/ν_0)·√(1−(ν/ν_0)²)]   ν ≤ ν_0
  MTF(ν) = 0                                                   ν > ν_0

This is the theoretical UPPER BOUND for a perfect, aberration-free lens.
Any real system will have lower MTF due to aberrations, defocus, or sensor
blur.  See honest_caveat in the response.

Parameters
----------
wavelength_nm         : wavelength of light in nm (e.g. 550 for green).
f_number              : F-number of the system (e.g. 4 for f/4).
num_samples           : frequency samples in [0, max_freq] (default 200).
max_freq_cyc_per_mm   : upper frequency limit (default 1.05 × ν_0).

Returns
-------
cutoff_freq_cyc_per_mm : ν_0 = 1/(λ·F#) in cyc/mm.
mtf_curve              : list of [ν, MTF(ν)] pairs.
mtf_at_50_percent      : frequency at which MTF ≈ 0.50.
honest_caveat          : plain-English scope limitations.

Analytic oracle (λ=550 nm, F/4):
  ν_0 = 454.5 cyc/mm; MTF(0)=1.0; MTF(ν_0)=0; MTF(ν_0/2)≈0.391.

HONEST: diffraction-limited only — no aberrations, no defocus, no sensor MTF,
no polychromatic weighting, on-axis only, circular aperture only.

Errors: {ok:false, reason} for invalid inputs. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "wavelength_nm": {
      "type": "number",
      "description": "Wavelength of light in nanometres (nm). E.g. 550 for green, 486 for blue (F-line), 656 for red (C-line). Must be > 0."
    },
    "f_number": {
      "type": "number",
      "description": "System F-number (f/#). E.g. 4 for f/4, 1.4 for f/1.4. Must be > 0."
    },
    "num_samples": {
      "type": "integer",
      "description": "Number of equally-spaced frequency samples from 0 to max_freq_cyc_per_mm. Default 200. Must be >= 2."
    },
    "max_freq_cyc_per_mm": {
      "type": "number",
      "description": "Upper frequency limit for the output curve (cyc/mm). If omitted, defaults to 1.05 \u00d7 \u03bd_0 so the zero-crossing is visible. Must be > 0 if provided."
    }
  },
  "required": [
    "wavelength_nm",
    "f_number"
  ]
}
```

---

## `optics_fit_zernike_wavefront`

Fit the first N Zernike polynomial coefficients (Noll 1976 ordering,
j=1..15) to sampled wavefront data W(ρ,θ) over a unit-disk pupil using
least-squares regression (numpy.linalg.lstsq).

Noll j-index and aberration name mapping (first 15 terms):
  j=1  piston         j=2  tip             j=3  tilt
  j=4  defocus        j=5  astigmatism_45  j=6  astigmatism_0
  j=7  coma_y         j=8  coma_x          j=9  trefoil_y
  j=10 trefoil_x      j=11 spherical       j=12 secondary_astig_0
  j=13 secondary_astig_45  j=14 tetrafoil_x  j=15 tetrafoil_y

Explicit polynomial formulas (Noll 1976 orthonormal on unit disk):
  Z_1  = 1
  Z_2  = 2ρ cos θ
  Z_3  = 2ρ sin θ
  Z_4  = √3 (2ρ²−1)
  Z_5  = √6 ρ² sin 2θ
  Z_6  = √6 ρ² cos 2θ
  Z_7  = √8 (3ρ³−2ρ) sin θ
  Z_8  = √8 (3ρ³−2ρ) cos θ
  Z_9  = √8 ρ³ sin 3θ
  Z_10 = √8 ρ³ cos 3θ
  Z_11 = √5 (6ρ⁴−6ρ²+1)
  Z_12 = √10 (4ρ⁴−3ρ²) cos 2θ
  Z_13 = √10 (4ρ⁴−3ρ²) sin 2θ
  Z_14 = √10 ρ⁴ cos 4θ
  Z_15 = √10 ρ⁴ sin 4θ

Returns:
  coefficients       : list of N floats [c_1..c_N] in Noll order
  rms_residual_waves : RMS of (W_measured − W_fitted) [same units as W]
  dominant_aberration: name of argmax(|c_j|) for j ≥ 2 (piston excluded)
  coefficient_names  : list of N strings
  honest_caveat      : scope limitations

Honest limits:
  * First 15 Noll terms only; higher-order wavefront content aliases into
    residual — report rms_residual to expose unmodelled power.
  * Unit-disk pupil (ρ ∈ [0,1]); no elliptical aperture, no obscuration.
  * Requires ≥ num_terms samples; returns error for under-determined system.

References: Noll (1976) J. Opt. Soc. Am. 66 207; Born & Wolf §9.2;
Wyant & Creath (1992) Applied Optics and Optical Engineering XI ch.1.

Errors: {ok: false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "samples": {
      "type": "array",
      "description": "List of wavefront sample points.  Each element must be a\n3-element array [rho, theta, W] where:\n  rho   : normalised pupil radius in [0, 1]\n  theta : pupil angle (radians)\n  W     : wavefront value at this point (waves)",
      "items": {
        "type": "array",
        "items": {
          "type": "number"
        },
        "minItems": 3,
        "maxItems": 3
      },
      "minItems": 1
    },
    "num_terms": {
      "type": "integer",
      "description": "Number of Noll-ordered Zernike terms to fit (1..15). Default 15.  Must be \u2264 number of samples."
    }
  },
  "required": [
    "samples"
  ]
}
```

---

## `optics_analyze_wavefront_alignment`

Extract piston (Z₁), tip (Z₂), tilt (Z₃), and defocus (Z₄) Zernike
alignment components from a sampled wavefront W(ρ,θ) and report each
in waves at the specified wavelength.

This is the most common alignment-quality metric in optical-shop testing
(Hecht §11.3; Born & Wolf §9.2; Wyant & Creath 1992 §3).

Noll j-index mapping for the four alignment terms:
  Z₁ (j=1)  piston  = 1                    [constant OPD offset]
  Z₂ (j=2)  tip     = 2ρ cosθ              [wavefront tilt about y-axis]
  Z₃ (j=3)  tilt    = 2ρ sinθ              [wavefront tilt about x-axis]
  Z₄ (j=4)  defocus = √3(2ρ²−1)            [longitudinal focus error]

Input wavefront W must be in nanometres (nm). The tool divides each
Zernike coefficient by wavelength_nm to express results in waves.

Returns:
  piston_waves         : Z₁ coefficient in waves
  tip_waves            : Z₂ coefficient in waves
  tilt_waves           : Z₃ coefficient in waves
  defocus_waves        : Z₄ coefficient in waves
  residual_rms_waves   : RMS of (W_measured − W_fitted_4terms) in waves;
                         non-zero → higher-order aberration content present
  dominant_misalignment: 'piston'|'tip'|'tilt'|'defocus'|'none'
  honest_caveat        : scope limitations

Honest limits:
  * Circular unit-disk pupil only (ρ ∈ [0,1]); no obscuration or
    elliptical aperture.
  * Alignment analysis only: corrects rigid-body misalignment (piston,
    tip, tilt, defocus). Does NOT characterise higher-order aberrations
    (coma, astigmatism, spherical, etc.) — use optics_fit_zernike_wavefront
    for full 15-term decomposition.
  * Requires ≥ 4 wavefront samples (minimum for a 4-term fit).

References: Hecht (2017) §11.3; Born & Wolf (1999) §9.2;
Wyant & Creath (1992) Applied Optics and Optical Engineering XI ch.1;
Noll (1976) J. Opt. Soc. Am. 66 207.

Errors: {ok: false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "samples": {
      "type": "array",
      "description": "List of wavefront sample points.  Each element must be a\n3-element array [rho, theta, W_nm] where:\n  rho   : normalised pupil radius in [0, 1]\n  theta : pupil angle (radians)\n  W_nm  : wavefront OPD at this point in nanometres (nm)",
      "items": {
        "type": "array",
        "items": {
          "type": "number"
        },
        "minItems": 3,
        "maxItems": 3
      },
      "minItems": 4
    },
    "wavelength_nm": {
      "type": "number",
      "description": "Reference wavelength in nanometres (nm). E.g. 632.8 for HeNe. All wave values in the report are W_nm / wavelength_nm. Must be > 0."
    }
  },
  "required": [
    "samples",
    "wavelength_nm"
  ]
}
```

---

## `optics_compute_spot_diagram`

Trace a fan of rays through a sequential lens system and compute the
spot diagram at the paraxial image plane.

Algorithm (Hecht 'Optics' 5e §6.3 / Welford 'Aberrations' §6):
  1. Generate a ceil(sqrt(num_rays)) × ceil(sqrt(num_rays)) Cartesian
     pupil grid over the unit disk (Welford §8.2 uniform sampling).
  2. Trace each ray through the lens stack using exact meridional Snell
     + Newton-Raphson conic intersect (Welford §5.2-5.3).
  3. Collect (x, y) intercepts at the paraxial image plane:
       y_img : exact meridional trace result
       x_img : first-order sagittal estimate (Hecht §5.7)
  4. Compute:
       centroid          = (mean_x, mean_y)
       rms_radius_mm     = sqrt(mean((xi-cx)^2 + (yi-cy)^2))  [Welford §8.2]
       encircled_80pct   = radius enclosing 80% of rays from centroid [Hecht §6.3]
  5. Render SVG with RMS ring (red), EE80 ring (green), Airy-disk ring (orange),
     centroid marker, and scale bar.

Surface definition (lens_system_dict.surfaces list):
  c  : curvature 1/R (mm^-1). 0 = flat.
  t  : thickness to NEXT surface vertex (mm). Last surface: 0.
  n  : refractive index of medium AFTER this surface (>= 1.0).
  k  : conic constant (default 0 = sphere).

Optional lens_system_dict keys:
  aperture_radius_mm : entrance-pupil half-diameter (mm, default 10).
  n_object           : object-space refractive index (default 1.0).

Oracle (Hecht §6.3):
  BK7 biconvex (R1=+50, R2=-50, n=1.5168, t=5mm), 0° field, aperture 5mm:
    rms_radius_mm > 0 (spherical aberration).
  Same lens at 10° field: rms_radius > on-axis rms (coma grows off-axis).
  Ideal thin lens (paraxial, no aberrations): rms ≈ 0.

Returns:
  image_points_xy           : list of [x_mm, y_mm] intercepts
  rms_radius_mm             : 2-D RMS spot radius (mm)
  encircled_80pct_radius_mm : radius enclosing 80% of rays (mm)
  centroid_xy               : [x_mean, y_mean] (mm)
  svg_diagram               : SVG string
  honest_caveat             : scope limitations
  n_rays                    : number of rays successfully traced

HONEST FLAGS:
  * Monochromatic only — wavelength_nm used for Airy reference only;
    chromatic aberration NOT modelled.
  * Sagittal (x) intercepts are first-order estimates; rigorous x requires
    full 3-D skew-ray tracing.
  * Physical aperture clipping not applied.
  * encircled_80pct is geometric (ray-counting), not diffraction-based.
  * Stop assumed at first surface.

References: Hecht (2017) §6.3, §10.2; Welford (1986) §5.2-5.3, §6, §8.2.

Errors: {ok:false, reason} for invalid inputs. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "lens_system_dict": {
      "type": "object",
      "description": "Lens system description with key 'surfaces' (list of surface dicts, each with c, t, n; optional k). Optional keys: aperture_radius_mm (default 10), n_object (default 1.0).",
      "properties": {
        "surfaces": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "c": {
                "type": "number",
                "description": "Curvature 1/R (mm^-1). 0 = flat."
              },
              "t": {
                "type": "number",
                "description": "Thickness to next surface (mm)."
              },
              "n": {
                "type": "number",
                "description": "Refractive index after surface (>= 1.0)."
              },
              "k": {
                "type": "number",
                "description": "Conic constant (default 0 = sphere)."
              }
            },
            "required": [
              "c",
              "t",
              "n"
            ]
          }
        },
        "aperture_radius_mm": {
          "type": "number",
          "description": "Entrance-pupil half-diameter (mm). Default 10."
        },
        "n_object": {
          "type": "number",
          "description": "Refractive index of object space. Default 1.0."
        }
      },
      "required": [
        "surfaces"
      ]
    },
    "field_angle_deg": {
      "type": "number",
      "description": "Field angle (degrees). 0 = on-axis."
    },
    "wavelength_nm": {
      "type": "number",
      "description": "Wavelength (nm). Used for Airy-disk reference only; chromatic aberration not modelled. E.g. 550.0 for green."
    },
    "num_rays": {
      "type": "integer",
      "description": "Target number of rays to trace (default 49). A ceil(sqrt(num_rays)) grid is built; actual count may be slightly less."
    }
  },
  "required": [
    "lens_system_dict",
    "field_angle_deg",
    "wavelength_nm"
  ]
}
```

---

## `optics_compute_sagitta_arrow_chart`

Compute the sagitta z(r) of a conic + even-power aspheric optical surface
across the clear aperture radius and produce an SVG chart with sagittal
arrow markers showing local slope dz/dr.

Standard surface formula (ISO 10110-12 §6.2 / Welford §3.3):

  z(r) = c·r² / (1 + √(1−(1+k)·c²·r²))  +  Σ aᵢ·r^(2i+4)

where c = 1/R, k = conic constant, and aᵢ are even-power aspheric
coefficients (a₀ multiplies r⁴, a₁ → r⁶, etc.).

Conic constant guide:
  k =  0   → sphere
  k = -1   → paraboloid
  k < -1   → hyperboloid
  k > -1 (≠0) → oblate / prolate ellipsoid

Returns:
  sagitta_samples         : list of [r, z] pairs (mm)
  max_sagitta_mm          : z at the aperture edge
  conic_only_sagitta_mm   : edge z from conic term only
  aspheric_contribution_mm: max_sagitta − conic_only
  svg_chart               : SVG string (polyline + arrow markers + axes)
  honest_caveat           : scope limitations

HONEST FLAGS:
  * Conic + even-power polynomial asphere only (ISO 10110-12 §6.2).
  * NO Zernike surfaces, freeform/XY polynomial, Q-polynomial, or
    off-axis / tilted / decentred surfaces.
  * Arrow markers show dz/dr (local slope), not the surface normal.
  * Validity requires (1+k)·c²·r² ≤ 1 at the aperture edge.

References: Welford §3.3; ISO 10110-12:2019.

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "radius_mm": {
      "type": "number",
      "description": "Paraxial radius of curvature R (mm). Non-zero and finite. c = 1/R. Use a large value (e.g. 1e12) for a flat surface."
    },
    "conic_k": {
      "type": "number",
      "description": "Conic constant k. 0 = sphere, -1 = paraboloid, < -1 = hyperboloid, > 0 = oblate ellipsoid."
    },
    "aspheric_coeffs": {
      "type": "array",
      "description": "Even-power aspheric coefficients [a\u2080, a\u2081, a\u2082, \u2026] (mm^-3, mm^-5, \u2026). a\u2080 multiplies r\u2074, a\u2081 multiplies r\u2076, etc. Pass [] for a pure conic surface.",
      "items": {
        "type": "number"
      }
    },
    "clear_aperture_radius_mm": {
      "type": "number",
      "description": "Semi-diameter of the clear aperture (mm). Must be > 0."
    },
    "num_samples": {
      "type": "integer",
      "description": "Number of radial sample points (default 50). Samples are at r = i\u00b7R_ap/num_samples for i = 0\u2026num_samples."
    }
  },
  "required": [
    "radius_mm",
    "conic_k",
    "aspheric_coeffs",
    "clear_aperture_radius_mm"
  ]
}
```

---

## `optics_compute_seidel_coma`

Compute the third-order Seidel coma aberration coefficient S_II for a
sequential thin-lens system from the surface paraxial parameters.

Theory (Welford 'Aberrations of Optical Systems' §7 / Born & Wolf §5.3):
  Traces a marginal ray (h=aperture, u=0) and a chief ray (ybar=0 at stop,
  u=tan(field_angle_deg)) through all surfaces.  Per-surface contributions:

    A_j    = n_j * (u_j + h_j * c_j)          [marginal refraction invariant]
    Ā_j    = n_j * (ubar_j + ybar_j * c_j)    [chief refraction invariant]
    S_II_j = -A_j * Ā_j * h_j * Δ(u/n)_j     [Welford §7 eq. 7.42]

  S_II = Σ S_II_j  (total Seidel coma sum).

  Coma in physical units (Born & Wolf §5.3 eq. 5.3.29):
    tangential_coma = 3 * S_II * y_chief   [y_chief = chief-ray image height]
    coma_waves = |tangential_coma| / (8 * lambda)

HONEST FLAGS:
  * Third-order (Seidel) only.  Higher-order coma requires Hopkins finite-ray OPD.
  * Monochromatic.  Chromatic coma / lateral colour NOT computed.
  * Paraxial Seidel; no defocus residual.
  * Stop assumed at first surface.

Surface definition (same as optics_seidel_aberrations):
  c  : curvature 1/R (mm^-1). 0 = flat.
  t  : thickness to NEXT surface vertex (mm). Last surface: 0.
  n  : refractive index of medium AFTER this surface (>= 1.0).

Returns:
  S_II                      : float  Seidel coma coefficient sum (Welford §7)
  coma_waves_at_lambda      : float  |3*S_II*y_chief| / (8*lambda) in waves
  dominant_surface_idx      : int    surface with max |S_II_j| (0-based; -1 if all zero)
  per_surface_contributions : list   per-surface S_II_j + A, Ā, h, ybar
  honest_caveat             : str    scope limitations

Errors: {ok:false, reason} for invalid inputs.  Never raises.

References: Welford (1986) §7, eq. 7.42; Born & Wolf (1999) §5.3, eq. 5.3.29.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "lens_system_dict": {
      "type": "object",
      "description": "Lens system description with key 'surfaces' (list of surface dicts, each with c, t, n). Optional top-level keys: aperture_radius_mm (default 1.0), n_object (default 1.0).",
      "properties": {
        "surfaces": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "c": {
                "type": "number",
                "description": "Curvature 1/R (mm^-1). 0 = flat."
              },
              "t": {
                "type": "number",
                "description": "Thickness to next surface (mm)."
              },
              "n": {
                "type": "number",
                "description": "Refractive index after surface (>= 1.0)."
              }
            },
            "required": [
              "c",
              "t",
              "n"
            ]
          }
        },
        "aperture_radius_mm": {
          "type": "number",
          "description": "Marginal ray height at first surface (mm). Default 1.0."
        },
        "n_object": {
          "type": "number",
          "description": "Refractive index of object space. Default 1.0."
        }
      },
      "required": [
        "surfaces"
      ]
    },
    "wavelength_nm": {
      "type": "number",
      "description": "Reference wavelength (nm). Used for coma_waves_at_lambda. Default 550."
    },
    "field_angle_deg": {
      "type": "number",
      "description": "Chief-ray field angle (degrees). Default 5.0. 0 = on-axis."
    }
  },
  "required": [
    "lens_system_dict"
  ]
}
```

---

## `optics_compute_vignetting_check`

Compute the vignetting fraction (fraction of entrance-pupil area occluded
by clear-aperture limits) at a given field angle for a sequential lens
system.

Theory (Welford 'Aberrations of Optical Systems' §3.7 / Hecht §5.7):
  For a field angle θ, the chief ray is displaced at each surface z_j by:
    Δ_j = z_j · tan(θ)     (paraxial, object at infinity, stop at z=0)

  The effective entrance-pupil area at each surface is the intersection
  of two circles:
    • Entrance-pupil disk: radius R = marginal_ray_at_stop_mm, centred at 0
    • CA disk at surface j: radius r_j, centred at Δ_j

  Using the exact two-circle intersection-area formula (Weisstein).

  vignetting_pct = (1 − A_eff / A_full) × 100
  where A_eff = minimum intersection area over all surfaces.

HONEST FLAG:
  Paraxial chief-ray displacement only (no exact ray trace through glass).
  Circular, rotationally-symmetric CAs only.
  Diffraction-induced vignetting: NOT modelled.
  Chromatic pupil walk: NOT modelled.

Surface specification (each element of 'surfaces'):
  clear_aperture_radius_mm : float  — physical rim half-diameter (mm). > 0.
  axial_position_mm        : float  — vertex Z along optical axis (mm).
                                       Stop assumed at z = 0.

Returns:
  field_angle_deg       : input field angle (degrees)
  vignetting_pct        : % of pupil area blocked [0, 100]
  limiting_surface_idx  : surface index causing max vignetting (null if none)
  effective_pupil_area_pct : surviving pupil area % [0, 100]
  honest_caveat         : scope disclaimer

Errors: {ok:false, reason} for invalid inputs. Never raises.

References: Welford (1986) §3.7; Hecht (2017) §5.7.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "surfaces": {
      "type": "array",
      "description": "Ordered list of surface dicts for the lens system. Each must have: clear_aperture_radius_mm (float, > 0, mm) and axial_position_mm (float, mm). The aperture stop should be at axial_position_mm = 0.",
      "items": {
        "type": "object",
        "properties": {
          "clear_aperture_radius_mm": {
            "type": "number",
            "description": "Physical rim half-diameter (mm). Must be > 0."
          },
          "axial_position_mm": {
            "type": "number",
            "description": "Surface vertex Z position along optical axis (mm)."
          }
        },
        "required": [
          "clear_aperture_radius_mm",
          "axial_position_mm"
        ]
      }
    },
    "field_angle_deg": {
      "type": "number",
      "description": "Field angle in degrees. 0 = on-axis. Range: (-90, +90). Typical: 0\u201330\u00b0 for most lens systems."
    },
    "marginal_ray_at_stop_mm": {
      "type": "number",
      "description": "Entrance-pupil half-diameter (mm). Default 10.0 mm. Must be > 0. Should be <= the clear_aperture_radius_mm of the aperture-stop surface."
    }
  },
  "required": [
    "surfaces",
    "field_angle_deg"
  ]
}
```

---

## `optics_compute_pixel_mtf`

Compute the pixel aperture Modulation Transfer Function (MTF) for an imaging
sensor given pixel pitch and fill factor.

Theory (Boreman §3.4 / Hecht §11.3):
  A finite-sized pixel integrates incident irradiance over its aperture a = pitch × ff.
  This spatial averaging acts as a sinc low-pass filter:

    MTF_pixel(ν) = |sinc(π · a · ν)| = |sin(π·a·ν) / (π·a·ν)|

  where a = pixel_pitch_um × fill_factor × 1e-3 (mm), ν in cyc/mm.

  Nyquist limit: ν_N = 1 / (2 × pixel_pitch_mm).
  Spatial frequencies above ν_N ALIAS and cannot be recovered.

  For fill_factor=1.0 (full fill):
    MTF(0)    = 1.0 exactly
    MTF(ν_N)  = |sinc(π/2)| = 2/π ≈ 0.6366

  For fill_factor < 1.0 (partial fill), the effective aperture is narrower
  → sinc rolls off more slowly → MTF at Nyquist is HIGHER than 2/π.

System MTF (Boreman §2.1 cascade):
  MTF_system(ν) = MTF_optical(ν) × MTF_pixel(ν)
  Combine this result with optics_compute_diffraction_mtf for end-to-end quality.

Oracle (p=1.5μm, ff=1.0):
  ν_N = 1/(2×0.0015) = 333.33 cyc/mm
  MTF(ν_N) = 2/π ≈ 0.6366
  MTF(0)   = 1.0

HONEST: pixel aperture (sinc) ONLY — NOT modelled: silicon carrier-diffusion
MTF (Boreman §3.4); inter-pixel electrical/optical crosstalk; anti-aliasing
filter MTF; Bayer CFA demosaicing; charge-transfer inefficiency; non-square pixels.

Returns:
  nyquist_freq_cyc_per_mm : ν_N = 1/(2p) in cyc/mm
  mtf_curve               : list of [ν, MTF(ν)] sampled from 0 to 2·ν_N
  mtf_at_nyquist          : MTF at ν_N (≈0.6366 for ff=1; higher for ff<1)
  mtf_at_50_percent_nyquist : MTF at 0.5·ν_N
  honest_caveat           : plain-English limitations string

Errors: {ok:false, reason} for invalid inputs. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "pixel_pitch_um": {
      "type": "number",
      "description": "Centre-to-centre pixel pitch in micrometres (\u03bcm). Must be > 0. E.g. 1.5 for a modern smartphone, 5.5 for a scientific sensor."
    },
    "fill_factor": {
      "type": "number",
      "description": "Fraction of pixel area that collects light (0 < ff \u2264 1). Modelled as rect aperture of width = pitch \u00d7 ff. Default 1.0 (100%% fill). BSI CMOS: 0.95\u20131.0; FSI CMOS: 0.3\u20130.7."
    },
    "num_samples": {
      "type": "integer",
      "description": "Number of frequency samples from 0 to 2\u00b7\u03bd_N (default 200). Must be >= 2."
    }
  },
  "required": [
    "pixel_pitch_um"
  ]
}
```

---

## `optics_compute_depth_of_field`

Compute depth-of-field (DoF) and hyperfocal distance for a thin-lens
imaging system.

Formulae (Greenleaf §3 / Hecht §6.4):
  H      = f² / (N · c) + f          (hyperfocal distance)
  D_near = D · (H−f) / (H + D − 2f)  (near limit of sharp focus)
  D_far  = D · (H−f) / (H − D)       (far limit; ∞ when D ≥ H)
  DoF    = D_far − D_near             (∞ when D ≥ H)

All distances in millimetres.

Returns:
  hyperfocal_distance_mm     — H in mm
  near_limit_mm              — nearest acceptable-focus distance
  far_limit_mm               — furthest acceptable-focus distance; null = ∞
  depth_of_field_mm          — total DoF; null = ∞
  behind_focus_fraction      — fraction of DoF behind focus plane; null = ∞
  infinity_focus_at_hyperfocal — true when focus ≥ H
  honest_caveat              — geometric model only; Airy-disk blur NOT added

HONEST: Geometric thin-lens model only.  Does NOT add diffraction-limited
Airy-disk blur to the geometric CoC.  At small apertures (f/# ≳ f/16 for
visible light) the Airy disk 1.22·λ·N approaches the 35mm-FF CoC of 0.03 mm.
For a combined blur circle: c_eff = sqrt(c_geom² + c_airy²).

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "focal_length_mm": {
      "type": "number",
      "description": "Focal length of the lens (mm). Must be > 0. E.g. 50 for a standard 35mm-FF lens."
    },
    "f_number": {
      "type": "number",
      "description": "Aperture f-number (f/#). Must be > 0. E.g. 2.8 for a fast prime; 8 for landscape shooting."
    },
    "focus_distance_mm": {
      "type": "number",
      "description": "Distance from lens to focus plane (mm). Must be > focal_length_mm. E.g. 5000 for a subject 5 m away."
    },
    "circle_of_confusion_mm": {
      "type": "number",
      "description": "Maximum acceptable blur-spot diameter on the image plane (mm). Default 0.03 \u2014 the 35mm full-frame standard. APS-C \u2248 0.019; MFT \u2248 0.015; medium-format 645 \u2248 0.045."
    }
  },
  "required": [
    "focal_length_mm",
    "f_number",
    "focus_distance_mm"
  ]
}
```

---

## `optics_compute_telecentricity`

Compute the telecentricity (chief-ray angle in object/image space) for a
sequential optical system.

A telecentric system has the aperture stop placed at a focal plane so that
chief rays are parallel to the optical axis in one or both conjugate spaces.

Object-space telecentric:
  Stop at rear focal plane of the system. Chief rays in object space
  are parallel to the optical axis. Magnification invariant with object
  defocus. Used in machine vision / metrology (Smith MOE §5.4).

Image-space telecentric:
  Stop at front focal plane. Chief rays in image space are parallel.
  Magnification invariant with image-plane defocus.

Algorithm (paraxial, Welford 1986 §3):
  1. Solve for u_obj (object-space chief-ray angle) via superposition:
     Ray A (H, 0) + alpha * Ray B (0, 1) → h_stop = 0; alpha = u_obj.
  2. Trace chief ray through all surfaces → image-space angle.
  3. |angle| < 0.5 deg → telecentric (conventional threshold).
  4. Magnification variation over ±focus_shift_mm/2 image-plane defocus.

lens_system_dict keys:
  surfaces : list of {c (mm^-1), t (mm), n (>=1.0), k (conic, opt.)}
  stop_surface_index : int (optional, default 0)
  object_distance_mm : float (optional; omit for infinite-conjugate)
  n_object : float (optional, default 1.0)

Returns:
  chief_ray_angle_object_deg    - angle in object space (deg)
  chief_ray_angle_image_deg     - angle in image space (deg)
  object_telecentric            - |obj angle| < 0.5 deg
  image_telecentric             - |img angle| < 0.5 deg
  both_telecentric              - doubly telecentric flag
  max_magnification_variation_pct - % mag change over ±focus_shift_mm/2
  honest_caveat                 - scope disclaimer

HONEST FLAG: Paraxial first-order only. Stop thin plane. Aspheric
higher-order terms do not affect first-order chief-ray angle.
Infinite-conjugate approximated by 10,000 x EFL object distance.

Ref: Welford (1986) §3, §4.4; Smith 'Modern Optical Engineering' §5.4;
Hecht §6.6; Kingslake (1978) §5.1.

Errors: {ok:false, reason} for invalid inputs. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "lens_system_dict": {
      "type": "object",
      "description": "Optical system descriptor. Required: 'surfaces' list. Optional: 'stop_surface_index' (int), 'object_distance_mm' (float), 'n_object' (float).",
      "properties": {
        "surfaces": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "c": {
                "type": "number"
              },
              "t": {
                "type": "number"
              },
              "n": {
                "type": "number"
              },
              "k": {
                "type": "number"
              }
            },
            "required": [
              "c",
              "t",
              "n"
            ]
          }
        },
        "stop_surface_index": {
          "type": "integer"
        },
        "object_distance_mm": {
          "type": "number"
        },
        "n_object": {
          "type": "number"
        }
      },
      "required": [
        "surfaces"
      ]
    },
    "field_height_mm": {
      "type": "number",
      "description": "Off-axis field height (mm). Default 10.0. Must be > 0."
    },
    "focus_shift_mm": {
      "type": "number",
      "description": "Focus shift range (mm). Default 0.5. Must be > 0."
    }
  },
  "required": [
    "lens_system_dict"
  ]
}
```

---

## `optics_compute_working_fno`

Compute the working f-number N_w for a finite-conjugate optical system.

The nominal f-number N = f/D describes a lens focused at infinity.
When focused at a finite object distance, the image-side cone of light
is slower (larger effective f-number), reducing image irradiance.

Formula (Hecht §6.4 / Smith MOE §4.5 — thin-lens approximation):

  N_w = N * (1 + |m|)

where m = image-to-object magnification = -s_i / s_o.
Convention: m is negative for real (inverted) images.
  m = 0.0  → infinity focus; N_w = N (no penalty)
  m = -1.0 → 1:1 macro (life-size); N_w = 2N (+2 stops)
  m = -0.5 → 1:2 (half life-size); N_w = 1.5N (+1.17 stops)
  m = -2.0 → 2:1 photomacrography; N_w = 3N (+3.17 stops)

Image irradiance relative to infinity focus:
  factor = (N / N_w)²  =  1 / (1 + |m|)²

Exposure loss in photographic stops:
  loss = 2 · log₂(N_w / N)  =  2 · log₂(1 + |m|)

Returns:
  nominal_f_number       : input N
  working_f_number       : N_w = N*(1+|m|)
  exposure_loss_stops    : stops lost vs infinity focus (0 = no loss)
  image_irradiance_factor: relative sensor irradiance in [0, 1]
  honest_caveat          : thin-lens caveat; pupil-asymmetry warning

HONEST FLAG: Thin-lens (symmetric-pupil) formula ONLY.  For asymmetric
lenses (retrofocus, telephoto, macro with floating elements) the pupil
magnification p = D_exit/D_entrance differs from 1; exact formula is
N_w = (1/p)*N*(1+|m|/p) (Smith MOE §4.5).  Error can reach 0.5–1 stop.

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "nominal_f_number": {
      "type": "number",
      "description": "Lens nominal (infinity-focus) f-number N = f/D.  Must be > 0.  Examples: 1.4, 2.8, 4.0, 8.0."
    },
    "magnification": {
      "type": "number",
      "description": "Transverse image-to-object magnification m = -s_i/s_o.  Negative for real (inverted) images.  0.0 = infinity focus; -1.0 = 1:1 macro; -0.5 = 1:2 half life-size."
    }
  },
  "required": [
    "nominal_f_number",
    "magnification"
  ]
}
```

---

## `optics_compute_iris_diameter_map`

Compute the required iris (aperture stop) physical diameter for a sequential
lens system given a target f-number and verify that the marginal ray does not
clip any other surface's clear aperture.

Formula (Welford 'Aberrations' §3.4 / Smith 'Modern Optical Engineering' §6):

  D_iris = EFL / f#     (paraxial, infinity-conjugate)

EFL is computed by a canonical paraxial marginal-ray trace (h=1, u=0) unless
target_efl_mm is supplied explicitly.

Marginal-ray clearance check:
  A paraxial marginal ray (h = D_iris/2 at the stop, u = 0) is traced through
  all surfaces.  For each surface with a specified clear aperture CA, the
  clearance_ratio = CA_radius / |h_at_surface|.  If h > 0.95 * CA_radius the
  surface is flagged and clipped=True is set in the report.

lens_system_dict keys:
  surfaces            : list[dict]  — c (mm^-1), t (mm), n (>=1), k (opt)
  stop_surface_index  : int  — aperture-stop surface (default 0)
  clear_apertures_mm  : list[float] — per-surface CA diameter (mm); omit to
                         skip clipping check
  n_object            : float — object-space index (default 1.0)

Returns:
  iris_diameter_mm          — D = EFL/f# (mm)
  effective_f_number        — EFL / D (equals target when EFL not overridden)
  efl_mm                    — effective focal length used
  surface_clearance_check   — per-surface list:
      surface_idx, clear_aperture_mm, marginal_ray_height_mm,
      clearance_ratio (>1 = clears), flagged
  clipped                   — True if any surface marginal ray > 0.95 × CA
  honest_caveat             — paraxial limitations

HONEST FLAG: Paraxial marginal-ray trace only.  D = EFL/f# is the
infinity-conjugate formula; finite-conjugate systems require the working
f-number (N_w = N*(1+|m|), Smith MOE §4.5).  Aspheric higher-order sag
terms are ignored; for production design use exact ray analysis (Zemax /
CODE V / Welford §5).  Clear apertures must be supplied by the caller.

Ref: Welford (1986) §3.4; Smith (2008) §6; Hecht (2017) §6.4.

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "lens_system_dict": {
      "type": "object",
      "description": "Optical system descriptor.  Required: 'surfaces' list.  Optional: 'stop_surface_index' (int), 'clear_apertures_mm' (list[float], per-surface CA diameter in mm), 'n_object' (float, default 1.0).",
      "properties": {
        "surfaces": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "c": {
                "type": "number",
                "description": "Curvature 1/R (mm^-1)."
              },
              "t": {
                "type": "number",
                "description": "Thickness to next surface (mm)."
              },
              "n": {
                "type": "number",
                "description": "Refractive index after surface (>= 1.0)."
              },
              "k": {
                "type": "number",
                "description": "Conic constant (default 0)."
              }
            },
            "required": [
              "c",
              "t",
              "n"
            ]
          }
        },
        "stop_surface_index": {
          "type": "integer",
          "description": "0-based index of the aperture-stop surface (default 0)."
        },
        "clear_apertures_mm": {
          "type": "array",
          "description": "Per-surface clear aperture DIAMETER (mm).  Length must equal the number of surfaces.  Omit to skip clipping check.",
          "items": {
            "type": "number"
          }
        },
        "n_object": {
          "type": "number",
          "description": "Refractive index of object space (default 1.0 = air)."
        }
      },
      "required": [
        "surfaces"
      ]
    },
    "target_f_number": {
      "type": "number",
      "description": "Target f-number N = EFL / D.  Must be > 0.  Examples: 1.4, 2.8, 4.0, 8.0, 22."
    },
    "target_efl_mm": {
      "type": "number",
      "description": "Override effective focal length (mm).  If omitted the EFL is computed from the surface data via the canonical marginal-ray trace.  Must be > 0."
    }
  },
  "required": [
    "lens_system_dict",
    "target_f_number"
  ]
}
```

---

## `optics_compute_diffraction_psf`

Compute the diffraction-limited Airy-disk Point Spread Function (PSF)
for a circular aperture.

Theory (Hecht 'Optics' 5e §10.2; Born & Wolf 'Principles of Optics' 7e §8.5):

  I(r) = [2·J1(x)/x]²          x = π·D·r / (λ·f) = π·r / (λ·F#)

  Airy disk radius  r_Airy = 1.22·λ·F#   [first dark ring, first zero of J1]
  Rayleigh limit    Δr     = 1.22·λ·F#   [Rayleigh resolution criterion]
  FWHM              ≈ 1.03·λ·F#           [Hecht eq. 10.59]

Oracle: λ=550nm, D=10mm, f=50mm → F#=5:
  r_Airy ≈ 3.355 μm, FWHM ≈ 2.833 μm, I(0) = 1.0 exactly.

Returns:
  airy_disk_radius_um    : 1.22·λ·F# (μm)
  rayleigh_resolution_um : equals airy_disk_radius_um
  fwhm_um                : 1.03·λ·F# (μm)
  psf_profile            : list of [r_um, I] pairs, I ∈ [0,1], I(0)=1.0
  honest_caveat          : model limitations

HONEST LIMITATIONS:
  SCALAR DIFFRACTION ONLY — no polarisation / vector diffraction effects
    (Richards-Wolf high-NA integral, Born & Wolf §8.7).
  CIRCULAR APERTURE — non-circular/annular pupils not modelled.
  ABERRATION-FREE — no Seidel/Zernike wavefront error (Strehl < 1).
  MONOCHROMATIC (this tool) — polychromatic PSF I_poly(r) = Σ W(λ_i)·I(r,λ_i)/Σ W(λ_i)
    is available via compute_polychromatic_psf(na, focal_length_mm,
    wavelength_samples_nm, spd_weights) with standard CIE photopic / D65 /
    blackbody SPD helpers.
  ON-AXIS / PARAXIAL — valid for NA = D/(2f) ≪ 1 only.

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "wavelength_nm": {
      "type": "number",
      "description": "Wavelength of light in nanometres (nm). E.g. 550 for green, 632.8 for HeNe laser. Must be > 0."
    },
    "aperture_diameter_mm": {
      "type": "number",
      "description": "Entrance-pupil (aperture) diameter D in millimetres. Must be > 0."
    },
    "focal_length_mm": {
      "type": "number",
      "description": "Lens focal length f in millimetres. Must be > 0."
    },
    "num_samples": {
      "type": "integer",
      "description": "Number of radial samples in [0, max_radius_um]. Default 200. Must be >= 2."
    },
    "max_radius_um": {
      "type": "number",
      "description": "Maximum radial extent of the PSF profile in micrometres. Default 20.0 \u03bcm.  Increase to see multiple Airy rings. Must be > 0."
    }
  },
  "required": [
    "wavelength_nm",
    "aperture_diameter_mm",
    "focal_length_mm"
  ]
}
```

---

## `optics_compute_lens_volume`

Compute the glass volume (mm³) and weight (g) of a spherical-surface singlet
lens from its radii, center thickness, clear aperture, and glass density.

Theory (Smith 'Modern Optical Engineering' §13.3 / Mahajan §1.2):

  Sagitta:    h = |R| − √(|R|² − r²)          r = clear_aperture_radius
  Cap volume: V_cap = π·h²·(3·|R| − h) / 3
  Lens vol:   V = π·r²·t_c  ± V_cap1 ± V_cap2

  Sign convention (Cartesian):
    R1 > 0: front surface convex toward object → subtract V_cap1
    R1 < 0: front surface concave toward object → add V_cap1
    R2 < 0: rear  surface convex toward image   → subtract V_cap2
    R2 > 0: rear  surface concave toward image  → add V_cap2
    R = ±∞ (use 1e18): flat (plano) surface, no cap contribution.

  Weight = V × ρ    where ρ = glass_density_g_cm3 × 1e−3 g/mm³

Depth-bar oracle (BK7 plano-convex):
  R1=+100 mm, R2=∞, t_c=5 mm, CA_r=12.5 mm, ρ=2.51 g/cm³
  → sag1 ≈ 0.7843 mm, V ≈ 2262 mm³, weight ≈ 5.68 g

Returns:
  volume_mm3         : total glass volume (mm³)
  weight_g           : glass weight (g)
  edge_thickness_mm  : lens thickness at clear-aperture edge (mm)
  sag1_mm, sag2_mm   : sagitta of each surface at CA radius (mm)
  lens_form          : 'biconvex'|'biconcave'|'plano_convex'|
                       'plano_concave'|'meniscus'|'plano_plano'
  honest_caveat      : scope limitations

HONEST LIMITATIONS:
  SPHERICAL SURFACES ONLY — aspheric sag h=Rc·r²/(1+√(1−(1+k)c²r²))
    requires numerical integration; out of scope.
  NO AR COATING — anti-reflection layers (100–500 nm) are not modelled.
  HOMOGENEOUS DENSITY — GRIN / melt-inhomogeneous glass may differ ~0.3%.
  CLEAR APERTURE ≠ BLANK — physical blank is larger; weight will be higher.

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "radius_R1_mm": {
      "type": "number",
      "description": "Radius of curvature of the first (object-side) surface (mm). Positive = convex toward object (Cartesian sign convention). Use 1e18 for a flat (plano) surface."
    },
    "radius_R2_mm": {
      "type": "number",
      "description": "Radius of curvature of the second (image-side) surface (mm). Negative = convex toward image. Use 1e18 for a flat (plano) surface."
    },
    "center_thickness_mm": {
      "type": "number",
      "description": "Axial center thickness (mm). Must be > 0."
    },
    "clear_aperture_radius_mm": {
      "type": "number",
      "description": "Semi-diameter of the optically-used zone (mm). Must be > 0 and < |R1|, |R2|. For weight budgets, use the physical blank semi-diameter."
    },
    "glass_density_g_cm3": {
      "type": "number",
      "description": "Glass density in g/cm\u00b3. Default = 2.51 (Schott BK7). Other common values: SF11 \u2248 4.74, CaF2 \u2248 3.18, fused silica \u2248 2.20, N-LAK22 \u2248 3.67."
    }
  },
  "required": [
    "radius_R1_mm",
    "radius_R2_mm",
    "center_thickness_mm",
    "clear_aperture_radius_mm"
  ]
}
```

---

## `optics_trace_chief_ray`

Trace the paraxial chief ray through a sequential optical system and
report the chief-ray height at each surface.

The chief ray (principal ray) is the ray from an off-axis object point
that passes through the *centre* of the aperture stop (h_stop = 0).
Chief-ray heights are the fundamental input to vignetting analysis,
field-of-view design, and Seidel distortion/coma computation.

Theory (Welford 'Aberrations of Optical Systems' §3 / Mahajan §2):

  Paraxial nu-form trace (per surface j):
    n u = n u - h c (n - n)       [refraction]
    h_{j+1} = h_j + t_j u_j       [transfer]

  Chief-ray initial conditions solved by superposition:
    h_stop = 0  <->  u_obj = -h_A_stop / h_B_stop

Oracle (single thin lens, f=50mm, stop at lens surface, field=5 deg):
  image_height = f * tan(5 deg) ~= 4.37 mm.
  Chief ray height at stop surface ~= 0 (passes through centre).

Surface definition (same as optics_ray_trace_lens_stack):
  c  : curvature 1/R (mm^-1). 0 = flat.
  t  : thickness to NEXT surface vertex (mm). Last surface: 0.
  n  : refractive index of medium AFTER this surface.
  k  : conic constant (default 0 = sphere, unused for paraxial).

Returns:
  per_surface_heights : list of {surface_idx, ray_height_mm,
                        ray_angle_deg} - chief-ray data at each surface
  image_height_mm     : chief-ray height at paraxial image plane (mm)
  magnification       : paraxial lateral magnification (NaN for inf conj.)
  stop_surface_idx    : aperture stop surface index (as supplied)
  chief_ray_at_stop_mm: chief-ray height at stop (should be ~= 0)
  object_angle_deg    : chief-ray angle in object space (degrees)
  image_angle_deg     : chief-ray angle in image space (degrees)
  honest_caveat       : scope limitations

HONEST LIMITATIONS:
  PARAXIAL ONLY - first-order heights. Exact chief ray requires Newton-
    Raphson conic intersect (use optics_ray_trace_lens_stack for that).
  STOP POSITION MUST BE SUPPLIED - no automatic stop detection.
  ROTATIONALLY SYMMETRIC - meridional plane only.
  IMAGE HEIGHT = f*tan(theta) - no distortion correction.

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "lens_system_dict": {
      "type": "object",
      "description": "Optical system specification.  Required: surfaces (list of {c, t, n, optional k}). Optional: n_object (default 1.0), object_distance_mm (default 1e9 = infinity), object_height_mm (default 1.0, finite conjugate only).",
      "properties": {
        "surfaces": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "c": {
                "type": "number",
                "description": "Curvature 1/R (mm^-1). 0 = flat."
              },
              "t": {
                "type": "number",
                "description": "Thickness to next surface (mm)."
              },
              "n": {
                "type": "number",
                "description": "Refractive index after surface (>= 1.0)."
              },
              "k": {
                "type": "number",
                "description": "Conic constant (default 0 = sphere)."
              }
            },
            "required": [
              "c",
              "t",
              "n"
            ]
          }
        },
        "n_object": {
          "type": "number",
          "description": "Refractive index of object space (default 1.0 = air)."
        },
        "object_distance_mm": {
          "type": "number",
          "description": "Object distance from first surface (mm). Default 1e9 (infinity conjugate)."
        },
        "object_height_mm": {
          "type": "number",
          "description": "Off-axis object height (mm) for magnification. Default 1.0."
        }
      },
      "required": [
        "surfaces"
      ]
    },
    "field_angle_deg": {
      "type": "number",
      "description": "Half-field angle in object space (degrees). Range [0, 90). 0 = on-axis."
    },
    "stop_surface_idx": {
      "type": "integer",
      "description": "Index (0-based) of the aperture stop surface. Chief ray is constrained to h=0 at this surface."
    }
  },
  "required": [
    "lens_system_dict",
    "field_angle_deg",
    "stop_surface_idx"
  ]
}
```

---

## `optics_design_schmidt_corrector`

Compute the Schmidt corrector plate aspheric profile z(r) that cancels
the spherical aberration of a spherical primary mirror in a Schmidt
telescope.

Theory (Schmidt 1932 / Born & Wolf §6.3):
  A Schmidt corrector plate placed at the centre of curvature (distance R
  from mirror vertex) introduces the conjugate wavefront error to cancel
  the W∝r^4 spherical aberration of the spherical mirror.

  Corrector sag:  z(r) = r²·(r² − 2·κ·ρ_n²) / [8·(n−1)·R³]

  where:
    R   = primary mirror radius of curvature (mm)
    n   = corrector glass refractive index (default 1.5168 = BK7)
    κ   = neutral-zone factor (default 1.5, minimises peak-to-valley sag)
    ρ_n = (D/2) / sqrt(κ)  neutral zone radius

  The neutral zone (dz/dr = 0) is at r = ρ_n. With κ = 1.5, this is
  at r ≈ 0.8165·(D/2) — the classic Schmidt (1932) optimum.

Oracle / cross-check:
  200 mm aperture, f/2 mirror (R=400 mm), BK7 (n=1.5168), κ=1.5:
    neutral zone at r ≈ 81.65 mm
    max sag ≈ 0.0207 mm  (computed by formula)

HONEST LIMITATIONS:
  * Classical Schmidt (1932) only. Modern Schmidt-Cassegrain and
    Schmidt-Newtonian designs include a secondary mirror, field-flattener,
    and refined aspherics — these are NOT modelled here.
  * Monochromatic. Chromatic residual (second-order, Wilkins 1950) is
    not computed.
  * On-axis only. Off-axis coma appears if corrector is not at the exact
    centre-of-curvature plane.
  * Field curvature (Petzval radius ≈ −R/2) is not corrected.
  * Thin-plate approximation: sag ≪ plate thickness assumed.

Returns:
  aspheric_profile     : [[r_mm, z_mm], ...] sampled profile
  max_sag_mm           : peak-to-valley sag amplitude
  neutral_zone_radius_mm: radius where plate slope = 0
  schwarzschild_constant_k: equivalent mirror conic (always -1 = paraboloid)
  honest_caveat        : plain-text limitations

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "primary_radius_R_mm": {
      "type": "number",
      "description": "Radius of curvature of the spherical primary mirror (mm). Must be > 0. Focal length = R/2. Example: f/2 200mm aperture => R=400 mm."
    },
    "aperture_diameter_D_mm": {
      "type": "number",
      "description": "Clear aperture diameter of the corrector plate (mm). Must be > 0. Typically equals telescope entrance diameter."
    },
    "glass_index_n": {
      "type": "number",
      "description": "Refractive index of the corrector glass at design wavelength. Default 1.5168 (BK7 at 587.6 nm d-line). Must be > 1.0."
    },
    "neutral_zone_factor_kappa": {
      "type": "number",
      "description": "Neutral-zone placement factor kappa. Default 1.5 (minimises peak-to-valley sag, classic Schmidt optimum). kappa=1.0 places the neutral zone at the aperture edge. Must be > 0."
    },
    "num_radii": {
      "type": "integer",
      "description": "Number of radial sample points from 0 to D/2. Default 50. Must be >= 2."
    }
  },
  "required": [
    "primary_radius_R_mm",
    "aperture_diameter_D_mm"
  ]
}
```

---

## `optics_trace_skew_ray`

Trace a 3-D skew ray through a sequential conicoid lens stack (Born & Wolf §4.6 / Welford 1986 §5).

A skew ray is any ray that does not lie in the meridional (Y-Z) plane.
Skew rays are essential for off-axis aberrations (sagittal coma,
astigmatism, field curvature) that are invisible to 2-D meridional
tracing.  This tool implements full 6-DOF 3-D ray tracing.

Algorithm (Born & Wolf §4.6; Welford §5):
  1. Each surface is a conicoid of revolution about z with vertex at
     vertex_z_mm. Implicit form:
       F(x,y,z') = c(x²+y²) + c(1+k)z'² - 2z' = 0,  z'=z−vertex_z
  2. Ray-surface intersection: parametric quadratic P(t)=origin+t·d;
     smallest positive t taken.
  3. Surface normal at intersection: grad F, normalised and oriented
     to oppose the incoming ray.
  4. 3-D vector Snell's law (Born & Wolf §1.5.3 eq. 1.5.23):
       d' = (n1/n2)·d + (n1/n2·cos_i − cos_t)·N̂
     where cos_i = −d·N̂ (angle of incidence), N̂ points into medium 1.
  5. TIR detected when sin²(θ_t) > 1.

Input ray:
  origin_xyz    : [x, y, z] starting position (mm)
  direction_xyz : [dx, dy, dz] direction vector (auto-normalised)
  wavelength_nm : float, default 587.6 (Fraunhofer d-line)

Surface definition (list, in order):
  vertex_z_mm            : z-position of surface vertex (mm)
  radius_mm              : signed radius of curvature (mm); 0 = flat
  refractive_index_after : n of medium AFTER this surface (>= 1.0)
  conic_k                : conic constant (default 0 = sphere;
                           -1 = paraboloid, <-1 = hyperboloid)

n_before_first : refractive index of object-space medium (default 1.0)

Returns:
  ray_history    : list of {origin_xyz, direction_xyz, wavelength_nm}
                   — one entry per surface + initial ray
  final_position_xyz  : [x,y,z] at last intersection (mm)
  final_direction_xyz : [dx,dy,dz] after last refraction
  tir_occurred   : bool — true if TIR stopped the trace
  honest_caveat  : str — scope/limitation notes

HONEST FLAGS:
  * Monochromatic only; polychromatic requires one ray per wavelength.
  * Conic surfaces only — no higher-order aspheric terms (A4, A6, ...).
  * Sequential only — no non-sequential paths or ghost-ray detection.
  * No aperture-stop clipping; caller must test ray height vs CA.

Errors: {ok:false, reason} for invalid inputs. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "ray": {
      "type": "object",
      "description": "Incident ray specification.",
      "properties": {
        "origin_xyz": {
          "type": "array",
          "items": {
            "type": "number"
          },
          "minItems": 3,
          "maxItems": 3,
          "description": "Starting position [x, y, z] in mm."
        },
        "direction_xyz": {
          "type": "array",
          "items": {
            "type": "number"
          },
          "minItems": 3,
          "maxItems": 3,
          "description": "Direction vector [dx, dy, dz]. Need not be unit-length; auto-normalised."
        },
        "wavelength_nm": {
          "type": "number",
          "description": "Vacuum wavelength in nm. Default 587.6 (d-line)."
        }
      },
      "required": [
        "origin_xyz",
        "direction_xyz"
      ]
    },
    "surfaces": {
      "type": "array",
      "description": "Ordered list of optical surfaces. Each must have vertex_z_mm, radius_mm, refractive_index_after. Optional: conic_k (default 0 = sphere).",
      "items": {
        "type": "object",
        "properties": {
          "vertex_z_mm": {
            "type": "number",
            "description": "z-position of surface vertex (mm)."
          },
          "radius_mm": {
            "type": "number",
            "description": "Signed radius of curvature (mm). 0 = flat plane. R>0: centre to right."
          },
          "refractive_index_after": {
            "type": "number",
            "description": "Refractive index of medium after surface (>= 1.0)."
          },
          "conic_k": {
            "type": "number",
            "description": "Conic constant. 0=sphere, -1=paraboloid, <-1=hyperboloid, >0=oblate ellipsoid. Default 0."
          }
        },
        "required": [
          "vertex_z_mm",
          "radius_mm",
          "refractive_index_after"
        ]
      }
    },
    "n_before_first": {
      "type": "number",
      "description": "Refractive index of object-space medium (before first surface). Default 1.0 (air/vacuum)."
    }
  },
  "required": [
    "ray",
    "surfaces"
  ]
}
```

---

## See also

- Package: `kerf_cad_core`
