{
  "version": 1,
  "name": "blendSrf G1/G2 continuity scenario",
  "description": "Phase 4a jewelry: blend surface bridging two adjacent surface bodies with G1 (tangent) or G2 (curvature) continuity. Demonstrates opBlendSrf for ring shoulder-to-bezel transitions.",
  "features": [
    {
      "id": "blend_srf-1",
      "op": "blend_srf",
      "target_id": "sweep2-1",
      "edge1_id": 3,
      "edge2_id": 7,
      "blend_dist": 1.5,
      "continuity": "G1",
      "options": {
        "continuity": "G1",
        "blend_dist": 1.5
      }
    }
  ]
}
