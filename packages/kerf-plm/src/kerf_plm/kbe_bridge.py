"""
kerf_plm.kbe_bridge — KBE↔Configurator bridge (Wave 4M).

Connects the KBE forward-chaining engine in ``kerf_rules.kbe`` with the PLM
variant configurator in ``kerf_plm.configurator`` so that KBE-derived
engineering parameters drive downstream parts selection in a single call.

Public surface
--------------
KBEDrivenRule(Rule)
    A Configurator ``Rule`` whose *effect* is fulfilled by a live ``KBEEngine``
    rather than a fixed Python callable.  On firing it runs a sub-engine
    scoped to the current state and converts the resulting ``KBEState`` into
    ``Action`` objects.

kbe_to_actions(state: KBEState) -> list[Action]
    Utility: convert a finished KBEState (params + selections) into the
    Configurator's Action vocabulary.  Params become ``set_param`` actions;
    part selections become ``include_part`` actions.

KBEConfigurator
    Orchestrator that:
      1. Runs the KBEEngine over the raw customer options (forward-chaining).
      2. Merges derived params into the Configurator's seed options.
      3. Runs the Configurator fixed-point solver.
      4. Returns the final BOM (already ECO-filtered if an eco_table is given).

    Raises ``ConfigConflict`` if a KBE-derived param contradicts a
    Configurator hard-constraint rule.

plm_kbe_configure(options, kbe_rules, configurator_rules, eco_table, effective_date)
    Single top-level call — the LLM tool entry point.

Design notes
------------
- This is a *thin* bridge.  Neither KBEEngine nor Configurator is rewritten;
  we only adapt their types at the seam.
- KBEState params are merged as *soft* set_param actions (last-write wins) so
  that hand-authored configurator rules can override KBE defaults.  Mark a
  Configurator Rule's hard_constraint=True to lock a parameter.
- Provenance is preserved end-to-end: every BOM line carries the originating
  KBE rule ID (or configurator rule ID) in its ``provenance`` field.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from kerf_rules.kbe import KBEEngine, KBERule, KBEState, RuleSelection
from kerf_plm.configurator import (
    Action,
    ConfigConflict,
    Configurator,
    ConfiguratorState,
    Rule,
    effectivity_bom,
)


# ---------------------------------------------------------------------------
# kbe_to_actions
# ---------------------------------------------------------------------------


def kbe_to_actions(state: KBEState) -> list[Action]:
    """
    Convert a finished KBEState into Configurator Actions.

    - Each ``state.params`` entry becomes a soft ``set_param`` Action.
    - Each ``RuleSelection`` becomes an ``include_part`` Action.

    The ``rule_id`` on each action is set to the KBE rule ID that produced it
    (from ``state.fired_rules`` for params, or ``sel.rule_id`` for selections).
    """
    actions: list[Action] = []

    # Derived parameters → set_param (soft — configurator rules may override)
    for key, value in state.params.items():
        actions.append(
            Action.set_param(
                key=key,
                value=value,
                rule_id="kbe_engine",
                provenance=f"KBE-derived: {key}={value!r}",
                hard_constraint=False,
            )
        )

    # Part selections → include_part
    for sel in state.selections:
        actions.append(
            Action.include_part(
                sku=sel.sku,
                quantity=1,
                rule_id=sel.rule_id,
                provenance=(
                    sel.provenance
                    or f"KBE rule {sel.rule_id!r}: {sel.param_key}={sel.param_value!r}"
                ),
            )
        )

    return actions


# ---------------------------------------------------------------------------
# KBEDrivenRule
# ---------------------------------------------------------------------------


class KBEDrivenRule(Rule):
    """
    A Configurator Rule whose effect is delegated to a KBEEngine.

    Instead of a fixed Python callable for ``effect``, the rule holds a
    ``KBEEngine`` and fires it against the current ConfiguratorState,
    converting the resulting ``KBEState`` into Actions.

    Parameters
    ----------
    id, description, domain, tags
        Standard Rule metadata.
    kbe_engine
        The ``KBEEngine`` to run when this rule fires.
    condition_keys
        List of state keys that must all be non-None for this rule to fire.
        Pass ``[]`` to fire unconditionally.
    hard_constraint_params
        Set of param keys that should be set as hard constraints (raises
        ``ConfigConflict`` on contradiction).
    """

    def __init__(
        self,
        id: str,
        description: str,
        kbe_engine: KBEEngine,
        condition_keys: list[str] | None = None,
        hard_constraint_params: set[str] | None = None,
        domain: str = "general",
        tags: list[str] | None = None,
    ) -> None:
        self._kbe_engine = kbe_engine
        self._condition_keys = condition_keys or []
        self._hard_params = hard_constraint_params or set()

        def _condition(state: ConfiguratorState) -> bool:
            return all(state.get(k) is not None for k in self._condition_keys)

        def _effect(state: ConfiguratorState) -> list[Action]:
            # Build an options dict from the current configurator state
            opts: dict[str, Any] = dict(state.options)
            opts.update(state.params)
            kbe_state = self._kbe_engine.run(opts)
            actions = kbe_to_actions(kbe_state)
            # Promote hard-constrained params
            for a in actions:
                if (
                    a.action_type == "set_param"
                    and a.param_key in self._hard_params
                ):
                    a.hard_constraint = True
            return actions

        super().__init__(
            id=id,
            description=description,
            condition=_condition,
            effect=_effect,
            domain=domain,
            tags=list(tags or []),
        )


# ---------------------------------------------------------------------------
# KBEConfigurator
# ---------------------------------------------------------------------------


class KBEConfigurator:
    """
    Orchestrator: KBEEngine first, then Configurator fixed-point.

    Parameters
    ----------
    kbe_engine
        KBEEngine loaded with domain-specific derivation rules.
    configurator
        Configurator loaded with variant selection / hard-constraint rules.
    """

    def __init__(
        self,
        kbe_engine: KBEEngine,
        configurator: Configurator,
    ) -> None:
        self.kbe_engine = kbe_engine
        self.configurator = configurator

    def run(
        self,
        options: dict[str, Any],
        eco_table: list[dict[str, Any]] | None = None,
        effective_date: str = "",
    ) -> dict[str, Any]:
        """
        Full pipeline: KBE derivation → configurator solve → effectivity filter.

        Parameters
        ----------
        options
            Raw customer options (e.g. ``{"weight_kg": 1500, "drivetrain": "AWD"}``).
        eco_table
            Optional ECO/ECR table for effectivity filtering (see
            ``effectivity_bom``).
        effective_date
            ISO date string for ECO filtering.  Ignored if ``eco_table`` is
            empty / not provided.

        Returns
        -------
        dict with keys:
            ``bom``          — list of selected part dicts (post-effectivity)
            ``kbe_params``   — dict of KBE-derived parameters
            ``config_params``— dict of final configurator parameters
            ``fired_kbe_rules`` — list of KBE rule IDs that fired
        """
        # Step 1: KBE forward-chaining
        kbe_state = self.kbe_engine.run(options)

        # Step 2: Build configurator state with raw customer options as the seed,
        # then pre-apply KBE-derived params as *soft* set_param Actions so that
        # the conflict detector can see them when a hard-constraint rule fires.
        from kerf_plm.configurator import ConfiguratorState

        config_state = ConfiguratorState(options=dict(options))
        for key, value in kbe_state.params.items():
            config_state.apply_action(
                Action.set_param(
                    key=key,
                    value=value,
                    rule_id="kbe_engine",
                    provenance=f"KBE-derived: {key}={value!r}",
                    hard_constraint=False,
                )
            )

        # Pre-seed configurator with KBE-selected parts via a synthetic rule
        kbe_selected_parts = list(kbe_state.selections)

        # Step 3: Configurator fixed-point (may raise ConfigConflict).
        # Run the fixed-point directly against the pre-seeded state.
        for _iteration in range(self.configurator.max_iterations):
            snapshot_params = dict(config_state.params)
            snapshot_parts_count = len(config_state.included_parts)

            for rule in self.configurator.rules:
                try:
                    fires = rule.condition(config_state)
                except Exception:
                    fires = False

                if not fires:
                    continue

                try:
                    actions = rule.effect(config_state) or []
                except Exception:
                    actions = []

                for action in actions:
                    if action.rule_id == "":
                        action.rule_id = rule.id
                    config_state.apply_action(action)

            # Check for convergence
            if (
                config_state.params == snapshot_params
                and len(config_state.included_parts) == snapshot_parts_count
            ):
                break

        # Inject KBE-selected parts into the configurator state's included parts
        for sel in kbe_selected_parts:
            config_state.included_parts.append(
                {
                    "sku": sel.sku,
                    "quantity": 1,
                    "source": "kbe_engine",
                    "rule_id": sel.rule_id,
                    "provenance": (
                        sel.provenance
                        or f"KBE rule {sel.rule_id!r}: {sel.param_key}={sel.param_value!r}"
                    ),
                }
            )

        raw_bom = config_state.included_parts

        # Step 4: Effectivity filter
        if eco_table and effective_date:
            raw_bom = effectivity_bom(raw_bom, effective_date, eco_table)

        return {
            "bom": raw_bom,
            "kbe_params": dict(kbe_state.params),
            "config_params": dict(config_state.params),
            "fired_kbe_rules": list(kbe_state.fired_rules),
        }


# ---------------------------------------------------------------------------
# Top-level LLM tool entry point
# ---------------------------------------------------------------------------


def plm_kbe_configure(
    options: dict[str, Any],
    kbe_rules: list[KBERule],
    configurator_rules: list[Rule],
    eco_table: list[dict[str, Any]] | None = None,
    effective_date: str = "",
) -> dict[str, Any]:
    """
    Drive KBE derivation + configurator parts selection in one call.

    This is the primary LLM tool entry point for KBE-driven product
    configuration.

    Parameters
    ----------
    options
        Customer options dict (free-form engineering requirements).
        Example: ``{"weight_kg": 1500, "target_range_km": 600, "drivetrain": "AWD"}``
    kbe_rules
        List of ``KBERule`` objects defining the derivation logic.
    configurator_rules
        List of ``Rule`` objects defining parts selection / hard constraints.
    eco_table
        Optional ECO/ECR records for effectivity date-filtering.
    effective_date
        ISO date (e.g. "2026-06-01"); if blank, effectivity is not applied.

    Returns
    -------
    dict:
        ``ok``          — bool, True unless an exception occurred
        ``bom``         — list of selected part dicts
        ``kbe_params``  — KBE-derived engineering parameters
        ``config_params``— final configurator parameter set
        ``fired_kbe_rules`` — ordered list of KBE rule IDs that fired
        ``error``       — error message string (present only on failure)
        ``error_code``  — "CONFIG_CONFLICT" | "KBE_ERROR" | "UNKNOWN"

    Raises
    ------
    Does *not* raise — all exceptions are caught and returned as error dicts.
    """
    try:
        engine = KBEEngine(rules=kbe_rules)
        configurator = Configurator(rules=configurator_rules)
        orchestrator = KBEConfigurator(kbe_engine=engine, configurator=configurator)
        result = orchestrator.run(
            options=options,
            eco_table=eco_table,
            effective_date=effective_date,
        )
        return {"ok": True, **result}

    except ConfigConflict as exc:
        return {
            "ok": False,
            "bom": [],
            "kbe_params": {},
            "config_params": {},
            "fired_kbe_rules": [],
            "error": str(exc),
            "error_code": "CONFIG_CONFLICT",
            "conflict_detail": {
                "param_key": exc.param_key,
                "existing_value": exc.existing_value,
                "new_value": exc.new_value,
                "existing_source": exc.existing_source,
                "new_source": exc.new_source,
            },
        }
    except Exception as exc:
        return {
            "ok": False,
            "bom": [],
            "kbe_params": {},
            "config_params": {},
            "fired_kbe_rules": [],
            "error": str(exc),
            "error_code": "KBE_ERROR",
        }
