// TODO(parent): mount <LightGizmos lights={doc.lights} onSelect={...} /> in Renderer.jsx

/**
 * LightGizmos.jsx — Declarative wrapper that mounts per-light Three.js gizmos
 * into a parent-supplied THREE.Group via a ref-callback.
 *
 * Usage:
 *   const gizmoGroupRef = useRef(new THREE.Group());
 *   scene.add(gizmoGroupRef.current);
 *   <LightGizmos
 *     lights={doc.lights}
 *     groupRef={gizmoGroupRef}
 *     onSelect={(id) => setSelectedLight(id)}
 *   />
 *
 * The component renders no DOM; it is purely a side-effect manager that keeps
 * the THREE.Group in sync with the `lights` array.
 */

import { useEffect } from 'react';
import type { RefObject } from 'react';
import * as THREE from 'three';
import { dispatchGizmo } from '../lib/lightGizmoBuilders.js';

/**
 * A light entry from the render-doc `doc.lights` array. Not modeled in `src/types/` yet — the
 * union of fields every `lightGizmoBuilders.ts` builder reads (`direction`/`position`/`size_mm`/
 * `angle` are each only used by their own light `kind`, so all but `id`/`kind` are optional here).
 */
export interface GizmoLight {
  id: string;
  kind: 'sun' | 'area' | 'point' | 'spot';
  direction?: [number, number, number];
  position?: [number, number, number];
  size_mm?: number;
  angle?: number;
}

export interface LightGizmosProps {
  /** Array of light objects from doc.lights. */
  lights?: GizmoLight[];
  /** React ref holding the THREE.Group to populate. */
  groupRef: RefObject<THREE.Group | null>;
  /** Callback fired on click with the selected light id. */
  onSelect: (id: string) => void;
}

// `onSelect` is accepted but never read here (pre-existing; see hitTestGizmoGroup below, which is
// the actual click-dispatch path — this component only manages the THREE.Group side-effect).
export function LightGizmos({ lights = [], groupRef, onSelect: _onSelect }: LightGizmosProps) {
  useEffect(() => {
    const group = groupRef?.current;
    if (!group) return;

    // Remove stale gizmos
    while (group.children.length > 0) {
      const child = group.children[0];
      group.remove(child);
    }

    if (!Array.isArray(lights) || lights.length === 0) return;

    for (const light of lights) {
      let gizmo;
      try {
        gizmo = dispatchGizmo(light);
      } catch {
        // Skip unrecognised light kinds silently
        continue;
      }
      group.add(gizmo);
    }
  }, [lights, groupRef]);

  // Pointer-down on gizmo meshes/lines fires onSelect with the light id.
  // Raycasting is handled by the parent renderer's pointer-event loop.
  // We expose a helper so the parent can forward hits to this component.
  return null;
}

/**
 * hitTestGizmoGroup — utility for the parent renderer's pointer handler.
 *
 * Raycasts against all gizmo objects in `group`, finds the closest hit,
 * and calls `onSelect(lightId)`.
 *
 * The `raycaster` parameter only needs `intersectObjects` — narrowed to that instead of the full
 * `THREE.Raycaster` class so tests can pass a minimal fake without satisfying every unrelated
 * raycaster field.
 * @param raycaster
 * @param group       - The group passed to LightGizmos.
 * @param onSelect    - Callback (id: string) => void.
 * @returns True if a gizmo was hit.
 */
/**
 * The slice of THREE.Raycaster hitTestGizmoGroup needs.
 *
 * The hit type is `{ object }` rather than THREE.Intersection because that is
 * all the function reads — it walks up from the hit object looking for a
 * lightId and never touches point, distance, face or uv. Demanding a full
 * Intersection would oblige every caller and every test to fabricate five
 * fields nothing looks at, which is how a port stops describing its own
 * requirements. A real Raycaster still satisfies this.
 */
export interface GizmoRaycaster {
  intersectObjects(
    objects: THREE.Object3D[],
    recursive?: boolean,
  ): { object: THREE.Object3D }[];
}

// Pre-existing: this file exports a non-component utility alongside the LightGizmos component,
// which breaks Vite Fast Refresh for this module; not a behavior change for this slice.
// eslint-disable-next-line react-refresh/only-export-components
export function hitTestGizmoGroup(
  raycaster: GizmoRaycaster | null | undefined,
  group: THREE.Group | null | undefined,
  onSelect: ((id: string) => void) | null | undefined,
): boolean {
  if (!raycaster || !group) return false;

  const intersects = raycaster.intersectObjects(group.children, /* recursive */ true);
  if (intersects.length === 0) return false;

  // Walk up to find the gizmo root (which holds userData.lightId)
  let obj: THREE.Object3D | null = intersects[0].object;
  while (obj && !obj.userData?.lightId && obj.parent !== group) {
    obj = obj.parent;
  }
  // Also check the parent group level
  if (!obj?.userData?.lightId && obj?.parent?.userData?.lightId) {
    obj = obj.parent;
  }

  const lightId = obj?.userData?.lightId;
  if (lightId && typeof onSelect === 'function') {
    onSelect(lightId);
    return true;
  }
  return false;
}
