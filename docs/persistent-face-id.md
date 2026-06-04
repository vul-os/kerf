# Persistent Face IDs

*Domain: Geometry kernel · Module: `packages/kerf-cad-core/src/kerf_cad_core/afr/persistent_face_id.py` · Shipped: Wave 9*

## Overview

Assigns stable, geometry-derived identifiers to BRep faces so that downstream features (fillets, threads, mate constraints) can survive upstream edits. Each face receives a `FacePersistentId` derived from its centroid relative to the body centroid, area, and normal direction. After an edit, `reattach_face_ids_after_edit` maps old IDs to the new face set and reports any breaks.

## When to use

- Building parametric features that reference specific faces (fillets on a particular edge loop, thread on a cylinder face).
- Detecting which faces changed identity after a Boolean operation or edit.
- Round-tripping feature trees that must survive geometry regen.

## API

```python
from kerf_cad_core.afr.persistent_face_id import (
    FacePersistentId,
    assign_persistent_ids,
    reattach_face_ids_after_edit,
    detect_id_breaks,
)

# Assign IDs to all faces in a body topology dict
body_with_ids = assign_persistent_ids(body_topology)

# After an upstream edit, remap IDs
remapped = reattach_face_ids_after_edit(old_body, new_body, tolerance=0.1)

# List faces whose IDs could not be remapped
breaks = detect_id_breaks(old_body, new_body)
```

## LLM tools

`feature_assign_face_ids`, `feature_detect_id_breaks`

## References

- Kripac, "A mechanism for persistently naming topological entities in history-based parametric solid models", *SMA 1997*.

## Honest caveats

ID stability depends on face centroid and normal hashing. Symmetric parts with many similar faces (e.g. a gear with 40 identical teeth) may have hash collisions; the `feature_role` field (inferred from geometry type) is used as a secondary disambiguator but may not be sufficient. Coloured BRep faces (colour-based identification) are not currently used.
