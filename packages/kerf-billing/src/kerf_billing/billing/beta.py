# >>> CLOUD-BETA (remove post-launch): entire module — delete this file and
# all callers that import payments_disabled().  Search: CLOUD-BETA.
"""Cloud-beta payments gate.

Single source of truth for the "are payments disabled?" question during the
cloud-beta period.  Route ALL Paystack-skip decisions through this helper so
that removing cloud-beta mode is a mechanical, grepping exercise.

    from kerf_billing.billing.beta import payments_disabled

Usage
-----
In any place that would otherwise check ``settings.cloud_beta`` directly,
call ``payments_disabled(settings)`` instead.  The helper is intentionally
trivial — it just reads the flag — so that post-launch cleanup is a single
delete rather than a logic refactor.

Post-launch removal
-------------------
See packages/kerf-billing/CLOUD_BETA.md for the full checklist.
"""
from __future__ import annotations


def payments_disabled(settings) -> bool:
    """Return True when Paystack payments must be suppressed (cloud-beta mode).

    ``settings`` is any object with a ``cloud_beta`` boolean attribute
    (i.e. an instance of ``kerf_core.config.Settings`` or the lightweight
    stub objects used in tests).

    When this returns True:
    - PaystackClient must NOT be constructed.
    - Charge / webhook routes must return 503 (billing disabled in beta).
    - No outbound calls to Paystack are made.

    When this returns False the caller proceeds with normal Paystack logic.
    """
    # >>> CLOUD-BETA (remove post-launch): delete the body and this function.
    return bool(getattr(settings, "cloud_beta", False))
    # <<< CLOUD-BETA
# <<< CLOUD-BETA
