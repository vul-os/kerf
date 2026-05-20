{
  "version": 1,
  "name": "two-box union fixture",
  "features": [
    {
      "id": "box-a",
      "op": "box",
      "corner": [0, 0, 0],
      "dx": 5.0,
      "dy": 5.0,
      "dz": 5.0
    },
    {
      "id": "box-b",
      "op": "box",
      "corner": [10, 0, 0],
      "dx": 5.0,
      "dy": 5.0,
      "dz": 5.0
    },
    {
      "id": "bool-1",
      "op": "boolean",
      "kind": "union",
      "target_a_id": "box-a",
      "target_b_id": "box-b"
    }
  ]
}
