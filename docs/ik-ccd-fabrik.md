# Inverse Kinematics — CCD and FABRIK Solvers

> Solve joint angles for a bone chain to reach a target position using CCD or FABRIK.

**Module**: `packages/kerf-cad-core/src/kerf_cad_core/animation/ik_solver.py`
**Shipped**: Wave 9B2
**LLM tools**: `animation_solve_ik`

---

## What it is

The IK solver module provides two algorithms for solving the joint angles of a bone chain so that the end-effector reaches a target position: Cyclic Coordinate Descent (CCD) and FABRIK (Forward And Backward Reaching Inverse Kinematics). Both support optional pole targets (elbow/knee direction vectors) and per-joint angle limits.

## How to use it

### From chat

> "Solve IK for a 3-joint arm chain reaching target (0.8, 0.4, 0.2) using FABRIK, pole target upward."

### From Python

```python
from kerf_cad_core.animation.ik_solver import IKChain, solve_ik_ccd, solve_ik_fabrik

chain = IKChain(
    joint_positions=[
        [0.0, 0.0, 0.0],  # shoulder
        [0.3, 0.0, 0.0],  # elbow
        [0.6, 0.0, 0.0],  # wrist
        [0.9, 0.0, 0.0],  # end-effector
    ],
    bone_lengths=[0.3, 0.3, 0.3],
)
result_fabrik = solve_ik_fabrik(
    chain=chain,
    target=[0.8, 0.4, 0.2],
    pole_target=[0.0, 0.0, 1.0],
    max_iter=50,
    tolerance=1e-4,
)
print(result_fabrik.solved_positions)
print(result_fabrik.residual)
```

### From an LLM tool spec

```json
{"tool": "animation_solve_ik", "input": {"chain": {"joint_positions": [[0,0,0],[0.3,0,0],[0.6,0,0],[0.9,0,0]]}, "target": [0.8, 0.4, 0.2], "method": "fabrik"}}
```

## How it works

**CCD**: Starting from the end-effector, each joint is rotated to bring the end-effector closer to the target. This is repeated from end to root, cycling until the residual is below `tolerance`.

**FABRIK**: In the forward pass, the end-effector is snapped to the target and each parent joint is repositioned along its bone vector toward the child. The backward pass snaps the root back to its original position and propagates forward. Both passes are repeated until convergence.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `solve_ik_ccd(chain, target, max_iter, tolerance)` | `IKResult` | CCD IK solution |
| `solve_ik_fabrik(chain, target, pole_target, max_iter, tolerance)` | `IKResult` | FABRIK IK solution |
| `IKChain(joint_positions, bone_lengths)` | instance | Chain specification |

## Example

```python
res = solve_ik_fabrik(chain, target=[0.8, 0.4, 0.2], pole_target=None, max_iter=20)
# IKResult(solved=True, residual=0.0012, solved_positions=[[...], ...])
```

## Honest caveats

FABRIK is faster and produces more natural results than CCD for most cases, but neither method enforces joint angle limits unless `limits` are explicitly passed. Chains where the target is outside the maximum reach simply extend to the maximum reach without error. CCD may oscillate near the solution for highly constrained chains.

## References

- Aristidou & Lasenby, "FABRIK: A fast, iterative solver for the inverse kinematics problem," *Graphical Models* 73(5), 2011.
- Wang & Chen, "A direct approach for the solution of the inverse kinematics problem," *IJRR* 10(4), 1991.
