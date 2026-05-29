{
  "version": 1,
  "name": "networkSrf 4-curve network scenario",
  "description": "Phase 4a jewelry: network surface from 2 U-direction curves and 2 V-direction curves. Demonstrates opNetworkSrf (Gordon/Coons-Gordon) for freeform surface panels.",
  "features": [
    {
      "id": "network_srf-1",
      "op": "network_srf",
      "u_curves": [
        "/project/sketches/u_curve_bottom.sketch",
        "/project/sketches/u_curve_top.sketch"
      ],
      "v_curves": [
        "/project/sketches/v_curve_left.sketch",
        "/project/sketches/v_curve_right.sketch"
      ],
      "continuity": "C1"
    }
  ]
}
