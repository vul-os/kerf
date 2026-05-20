{
  "version": 1,
  "name": "box with chamfer fixture",
  "features": [
    {
      "id": "box-1",
      "op": "box",
      "corner": [0, 0, 0],
      "dx": 4.0,
      "dy": 4.0,
      "dz": 4.0
    },
    {
      "id": "chamfer-1",
      "op": "chamfer_edge",
      "target_id": "box-1",
      "edge_role": "+Z/-Y",
      "width": 0.5
    }
  ]
}
