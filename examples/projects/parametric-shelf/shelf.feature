{
  "version": 1,
  "name": "Parametric shelving unit",
  "features": [
    {
      "id": "side-left",
      "op": "pad",
      "sketch_path": "/side-panel.sketch",
      "height": "${height}",
      "direction": "up"
    },
    {
      "id": "side-right",
      "op": "pad",
      "sketch_path": "/side-panel.sketch",
      "height": "${height}",
      "direction": "up"
    },
    {
      "id": "shelf-repeated",
      "op": "pattern_repeat",
      "source_feature_id": "shelf-pad",
      "axis": "y",
      "count": "${shelf_count}",
      "spacing": 150
    },
    {
      "id": "shelf-pad",
      "op": "pad",
      "sketch_path": "/shelf.sketch",
      "height": 18,
      "direction": "up"
    },
    {
      "id": "pocket-left",
      "op": "pocket",
      "target_id": "side-left",
      "sketch_path": "/mounting-pockets.sketch",
      "depth": 15,
      "type": "thru"
    },
    {
      "id": "pocket-right",
      "op": "pocket",
      "target_id": "side-right",
      "sketch_path": "/mounting-pockets.sketch",
      "depth": 15,
      "type": "thru"
    },
    {
      "id": "back-panel",
      "op": "pad",
      "sketch_path": "/back-panel.sketch",
      "height": 6,
      "direction": "back"
    }
  ],
  "metadata": {}
}