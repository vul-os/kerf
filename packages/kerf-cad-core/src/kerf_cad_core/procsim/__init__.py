"""
kerf_cad_core.procsim — manufacturing process simulation sub-package.

Modules
-------
solidification  Transient heat-conduction solidification (enthalpy method).
                1-D and 2-D finite-difference solvers; latent-heat, hot-spot,
                thermal modulus, and cooling-curve extraction.
am_residual     AM residual stress and distortion (inherent-strain method).
                LPBF/DED layer-by-layer thermal contraction → accumulated
                stress field, Stoney-curvature warpage, recoater-collision
                risk, support-load estimate, orientation scan, stress-relief.
"""
