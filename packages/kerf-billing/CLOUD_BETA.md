# Removing CLOUD BETA mode

This document lists every cloud-beta seam and the exact removal steps.
All seams are marked with:

```
# >>> CLOUD-BETA (remove post-launch): ...
...
# <<< CLOUD-BETA
```

Find them all with:

```
grep -rn "CLOUD-BETA" packages/kerf-billing/
```

---

## Seam inventory

| File | What it does |
|------|-------------|
| `src/kerf_billing/billing/beta.py` | Entire module — the `payments_disabled()` helper |
| `src/kerf_billing/billing/handlers.py` | Import of `payments_disabled` + `if payments_disabled(self.cfg)` guard block in `topup()` |
| `src/kerf_billing/routes.py` | Import of `payments_disabled` + guard in the FastAPI `topup` route + `router_beta_inert` router (4 inert endpoints) |
| `src/kerf_billing/plugin.py` | Import of `payments_disabled` + `if payments_disabled(settings)` block in `register()` that mounts inert routes instead of the real router |

---

## Removal steps (post-launch)

Run these steps in order.  Each step is a mechanical delete or restore, no
logic changes required.

### 1. Delete `beta.py`

```
rm packages/kerf-billing/src/kerf_billing/billing/beta.py
```

### 2. `handlers.py` — remove import + guard block

Delete:
```python
# >>> CLOUD-BETA (remove post-launch): drop this import when beta.py is deleted.
from kerf_billing.billing.beta import payments_disabled
# <<< CLOUD-BETA
```

Delete:
```python
        # >>> CLOUD-BETA (remove post-launch): delete this block.
        # Defense-in-depth: reject payment attempts when cloud beta is active.
        if payments_disabled(self.cfg):
            return JSONResponse(
                status_code=403,
                content={"error": "billing disabled in beta — everyone is on Free"},
            )
        # <<< CLOUD-BETA
```

### 3. `routes.py` — remove import, guard, and inert router

Delete the import block:
```python
# >>> CLOUD-BETA (remove post-launch): drop this import when beta.py is deleted.
from kerf_billing.billing.beta import payments_disabled
# <<< CLOUD-BETA
```

Delete the guard in `topup()`:
```python
    # >>> CLOUD-BETA (remove post-launch): delete this block.
    # Defense-in-depth: reject payment attempts when cloud beta is active.
    if payments_disabled(settings):
        raise HTTPException(
            status_code=403,
            detail="billing disabled in beta — everyone is on Free",
        )
    # <<< CLOUD-BETA
```

Delete the entire `router_beta_inert` block at the bottom of the file
(everything between `# >>> CLOUD-BETA` and `# <<< CLOUD-BETA` at the end).

### 4. `plugin.py` — remove import + inert-router branch

Delete the import block:
```python
# >>> CLOUD-BETA (remove post-launch): drop this import when beta.py is deleted.
from kerf_billing.billing.beta import payments_disabled
# <<< CLOUD-BETA
```

Delete the inert-router branch (the `if payments_disabled(settings):` block
that returns early with `router_beta_inert`).

Restore `provides` in the returned `PluginManifest` to include
`"billing.paystack"`:
```python
    return PluginManifest(
        name="kerf-billing",
        version="0.1.0",
        provides=["billing.paystack", "billing.buckets"],
        depends=["kerf-auth"],
    )
```

### 5. Delete `tests/test_cloud_beta.py` cloud-beta-specific classes

Remove the test classes that only exercise the cloud-beta gate:
- `TestPaymentsDisabledHelper`
- `TestPluginRegisterBeta`
- `TestFxReachableInBothModes` (FX tests can be kept or moved)

The `TestHandlersBetaGuard`, `TestConfigEndpoint`, `TestCloudBetaLogic`, and
`TestSettingsCloudBeta` classes should also be reviewed — keep any assertions
that remain meaningful post-launch.

### 6. Delete this file

```
rm packages/kerf-billing/CLOUD_BETA.md
```

### 7. Verify

```
python -m pytest packages/kerf-billing/tests/ -q
```

All tests must pass.  The app must boot with `cloud_beta=False` (or the env
var absent) and Paystack initialises unconditionally when the keys are set.
