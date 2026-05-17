"""dag.py — the FeatureDAG, the orchestration spine of parametric history.

The DAG owns:

  * The set of :class:`Feature` nodes, keyed by ``id``.
  * The directed-acyclic dependency relation derived from each feature's
    ``inputs`` (FeatureRef + PersistentSelector edges).
  * Per-feature evaluation cache + invalidation.
  * Topological sort and cycle detection.
  * Evaluator dispatch (kind -> callable).
  * Round-trip serialisation as a dict.

Edits go through one of:

  * :meth:`FeatureDAG.set_param` — mutate a frozen scalar parameter; invalidate
    the changed feature + every transitive downstream.
  * :meth:`FeatureDAG.link` — change an input wiring (FeatureRef /
    PersistentSelector); same invalidation rule.
  * :meth:`FeatureDAG.regenerate` — re-evaluate every invalidated feature in
    topological order, reusing cached outputs upstream.

The keystone correctness property: after ``set_param``, a downstream Chamfer
or Fillet that referenced an upstream face/edge by :class:`PersistentSelector`
re-resolves through the producing feature's regenerated naming table to the
*same role*, NOT a different topology. This is what makes the kernel
parametric.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

from kerf_cad_core.geom.brep import Body, Edge, Face, Vertex
from kerf_cad_core.geom.history.feature import (
    Feature,
    FeatureRef,
    MissingReferenceError,
    PersistentSelector,
)
from kerf_cad_core.geom.history.persistent_naming import NamingTable


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class DAGCycleError(ValueError):
    """Raised when adding a link would create a cycle in the feature DAG."""

    def __init__(self, cycle_path: List[str]):
        self.cycle_path = list(cycle_path)
        super().__init__(
            "feature DAG would contain a cycle: "
            + " -> ".join(p[:8] for p in cycle_path)
        )


# ---------------------------------------------------------------------------
# EvaluationCache
# ---------------------------------------------------------------------------


@dataclass
class EvaluationCache:
    """Per-feature cached evaluation result.

    Stores enough state to skip re-evaluating an unchanged feature even if a
    downstream sibling is being regenerated.
    """

    body: Optional[Body] = None
    naming_table: Optional[NamingTable] = None
    extra_outputs: Dict[str, Any] = field(default_factory=dict)
    valid: bool = False

    def invalidate(self) -> None:
        self.body = None
        self.naming_table = None
        self.extra_outputs.clear()
        self.valid = False


# ---------------------------------------------------------------------------
# Evaluator signature
# ---------------------------------------------------------------------------
#
# An evaluator is a callable with the signature:
#
#     evaluate(feature: Feature, context: EvaluationContext) -> EvaluationResult
#
# where EvaluationContext gives the evaluator access to resolved upstream
# Body + NamingTable, and EvaluationResult bundles the produced Body, the new
# NamingTable, and an optional dict of extra outputs.


@dataclass
class EvaluationContext:
    """Read-only view of upstream evaluations passed to an evaluator.

    ``upstream_bodies[input_name]``  -> Body produced by the upstream feature
    ``upstream_tables[input_name]``  -> NamingTable from that feature
    ``resolve_selector(selector)``   -> resolves a PersistentSelector to a
                                        live Face/Edge/Vertex; raises
                                        MissingReferenceError if the role is
                                        gone.
    """

    upstream_bodies: Dict[str, Body]
    upstream_tables: Dict[str, NamingTable]
    resolve_selector: Callable[
        [PersistentSelector], Any
    ]


@dataclass
class EvaluationResult:
    """Return value from an evaluator."""

    body: Body
    naming_table: NamingTable
    extra_outputs: Dict[str, Any] = field(default_factory=dict)


Evaluator = Callable[[Feature, EvaluationContext], EvaluationResult]


# ---------------------------------------------------------------------------
# FeatureDAG
# ---------------------------------------------------------------------------


class FeatureDAG:
    """The parametric history DAG.

    Construct with no args; populate with :meth:`add_feature`; query with
    :meth:`evaluate` / :meth:`regenerate`.
    """

    def __init__(self) -> None:
        self._features: Dict[str, Feature] = {}
        # Per-feature evaluation cache. Created lazily.
        self._cache: Dict[str, EvaluationCache] = {}
        # Evaluator registry: kind -> Evaluator.
        self._evaluators: Dict[str, Evaluator] = {}
        # Insertion order (used as a stable secondary sort for topo).
        self._insertion_order: List[str] = []

    # ── feature management ────────────────────────────────────────────────

    def add_feature(self, feature: Feature) -> Feature:
        """Add a feature to the DAG.

        Raises :class:`DAGCycleError` if doing so would create a cycle (based
        on the feature's current ``inputs``).
        """
        if feature.id in self._features:
            raise ValueError(
                f"feature {feature.id[:8]} already in DAG"
            )
        self._features[feature.id] = feature
        self._cache[feature.id] = EvaluationCache()
        self._insertion_order.append(feature.id)
        try:
            self._topological_order()
        except DAGCycleError:
            # roll back
            del self._features[feature.id]
            del self._cache[feature.id]
            self._insertion_order.remove(feature.id)
            raise
        return feature

    def get_feature(self, feature_id: str) -> Feature:
        if feature_id not in self._features:
            raise KeyError(f"feature {feature_id[:8]} not in DAG")
        return self._features[feature_id]

    def has_feature(self, feature_id: str) -> bool:
        return feature_id in self._features

    def __contains__(self, feature_id: str) -> bool:
        return feature_id in self._features

    def __len__(self) -> int:
        return len(self._features)

    def feature_ids(self) -> List[str]:
        """All feature ids in insertion order."""
        return list(self._insertion_order)

    # ── evaluator registration ────────────────────────────────────────────

    def register_evaluator(self, kind: str, evaluator: Evaluator) -> None:
        self._evaluators[kind] = evaluator

    def evaluators(self) -> Dict[str, Evaluator]:
        return dict(self._evaluators)

    # ── editing ───────────────────────────────────────────────────────────

    def set_param(self, feature_id: str, key: str, value: Any) -> None:
        """Mutate a frozen scalar parameter and invalidate downstream.

        The user-facing edit verb. After this call, ``regenerate()`` will
        re-evaluate the changed feature and every transitively downstream
        feature. Upstream and independent-sibling features are NOT
        re-evaluated.
        """
        feature = self.get_feature(feature_id)
        feature.params[key] = value
        self._invalidate_downstream(feature_id)

    def replace_feature_kind(
        self,
        feature_id: str,
        new_kind: str,
        new_params: Dict[str, Any],
        new_inputs: Optional[Dict[str, Any]] = None,
    ) -> None:
        """In-place mutation of a feature's kind/params/inputs.

        The feature's ``id`` is preserved (so downstream
        :class:`PersistentSelector` references still aim at the same node),
        but its evaluator changes. This is the "user replaces a box with a
        cylinder" operation — downstream selectors that aimed at a Box role
        (e.g. ``+Y``) will fail to resolve against the new naming table and
        raise :class:`MissingReferenceError`.
        """
        feature = self.get_feature(feature_id)
        feature.kind = new_kind
        feature.params = dict(new_params)
        if new_inputs is not None:
            feature.inputs = dict(new_inputs)
        self._invalidate_downstream(feature_id)

    def link(
        self,
        downstream_id: str,
        input_name: str,
        upstream_ref: Any,
    ) -> None:
        """Re-wire the input of a downstream feature.

        ``upstream_ref`` is either a :class:`FeatureRef`, a
        :class:`PersistentSelector`, or a literal scalar.
        """
        downstream = self.get_feature(downstream_id)
        old = downstream.inputs.get(input_name)
        downstream.inputs[input_name] = upstream_ref
        try:
            self._topological_order()
        except DAGCycleError:
            if old is None:
                downstream.inputs.pop(input_name, None)
            else:
                downstream.inputs[input_name] = old
            raise
        self._invalidate_downstream(downstream_id)

    # ── topological sort + cycle detection ────────────────────────────────

    def _upstream_ids(self, feature: Feature) -> List[str]:
        out: List[str] = []
        for v in feature.inputs.values():
            if isinstance(v, FeatureRef):
                out.append(v.feature_id)
            elif isinstance(v, PersistentSelector):
                out.append(v.feature_id)
        return out

    def _topological_order(self) -> List[str]:
        """Kahn's algorithm with deterministic tie-breaking by insertion order.

        Raises :class:`DAGCycleError` on cycle.
        """
        # in_degree counts only INTERNAL edges (refs to features in the DAG).
        in_degree: Dict[str, int] = {fid: 0 for fid in self._features}
        adj: Dict[str, List[str]] = {fid: [] for fid in self._features}
        for fid, feature in self._features.items():
            for up in self._upstream_ids(feature):
                if up == fid:
                    raise DAGCycleError([fid])
                if up in self._features:
                    adj[up].append(fid)
                    in_degree[fid] += 1

        order: List[str] = []
        ready: List[str] = [
            fid for fid in self._insertion_order if in_degree.get(fid, 0) == 0
        ]
        ready.sort(key=lambda f: self._insertion_order.index(f))
        while ready:
            cur = ready.pop(0)
            order.append(cur)
            for nxt in adj[cur]:
                in_degree[nxt] -= 1
                if in_degree[nxt] == 0:
                    ready.append(nxt)
            # keep ready sorted by insertion order for determinism
            ready.sort(key=lambda f: self._insertion_order.index(f))

        if len(order) != len(self._features):
            # Cycle: find one.
            remaining = [
                fid for fid in self._features if fid not in order
            ]
            cycle = self._find_cycle(remaining)
            raise DAGCycleError(cycle)
        return order

    def _find_cycle(self, candidates: List[str]) -> List[str]:
        """DFS-based cycle finder over ``candidates``."""
        visited: Set[str] = set()
        stack: List[str] = []
        on_stack: Set[str] = set()

        def dfs(node: str) -> Optional[List[str]]:
            if node in on_stack:
                idx = stack.index(node)
                return stack[idx:] + [node]
            if node in visited:
                return None
            visited.add(node)
            on_stack.add(node)
            stack.append(node)
            feature = self._features[node]
            for up in self._upstream_ids(feature):
                if up in self._features:
                    result = dfs(up)
                    if result is not None:
                        return result
            on_stack.discard(node)
            stack.pop()
            return None

        for c in candidates:
            r = dfs(c)
            if r is not None:
                return r
        return list(candidates[:1])

    def topological_order(self) -> List[str]:
        """Public alias of the internal topological sort."""
        return self._topological_order()

    # ── invalidation ──────────────────────────────────────────────────────

    def _downstream_ids(self, feature_id: str) -> Set[str]:
        """All features transitively downstream of ``feature_id`` (inclusive)."""
        result: Set[str] = {feature_id}
        # Build reverse adjacency on demand.
        rev: Dict[str, List[str]] = {fid: [] for fid in self._features}
        for fid, feature in self._features.items():
            for up in self._upstream_ids(feature):
                if up in rev:
                    rev[up].append(fid)
        # BFS
        frontier = [feature_id]
        while frontier:
            cur = frontier.pop()
            for nxt in rev.get(cur, []):
                if nxt not in result:
                    result.add(nxt)
                    frontier.append(nxt)
        return result

    def _invalidate_downstream(self, feature_id: str) -> None:
        for fid in self._downstream_ids(feature_id):
            self._cache[fid].invalidate()

    # ── evaluation ────────────────────────────────────────────────────────

    def evaluate(self, feature_id: str) -> Body:
        """Evaluate ``feature_id``, reusing cached results where possible.

        Returns the produced ``Body``. The full :class:`EvaluationResult`
        (with naming table) lives on the cache.
        """
        self._evaluate_to_cache(feature_id, _evaluation_counter=None)
        return self._cache[feature_id].body  # type: ignore[return-value]

    def regenerate(self, changed_feature_ids: Optional[Iterable[str]] = None) -> None:
        """Re-evaluate all invalidated features in topological order.

        If ``changed_feature_ids`` is provided, those features (and their
        downstream subtree) are explicitly invalidated first. If omitted, the
        DAG simply walks every feature that is currently invalid.

        After regenerate, every feature in the DAG with a reachable evaluator
        has an up-to-date :attr:`outputs` and :attr:`naming_table`.
        """
        if changed_feature_ids:
            for fid in changed_feature_ids:
                self._invalidate_downstream(fid)

        order = self._topological_order()
        for fid in order:
            cache = self._cache[fid]
            if cache.valid:
                continue
            self._evaluate_to_cache(fid)

    # Internal evaluation: ensures upstream caches are valid, dispatches the
    # evaluator, populates the cache and the feature's outputs/naming_table.
    def _evaluate_to_cache(
        self,
        feature_id: str,
        _evaluation_counter: Optional[Dict[str, int]] = None,
    ) -> None:
        cache = self._cache[feature_id]
        if cache.valid:
            return
        feature = self._features[feature_id]

        # 1. Evaluate upstream features first.
        upstream_bodies: Dict[str, Body] = {}
        upstream_tables: Dict[str, NamingTable] = {}
        for input_name, ref in feature.inputs.items():
            if isinstance(ref, FeatureRef):
                self._evaluate_to_cache(ref.feature_id, _evaluation_counter)
                up_cache = self._cache[ref.feature_id]
                upstream_bodies[input_name] = up_cache.body  # type: ignore[assignment]
                upstream_tables[input_name] = up_cache.naming_table  # type: ignore[assignment]
            elif isinstance(ref, PersistentSelector):
                self._evaluate_to_cache(ref.feature_id, _evaluation_counter)
                up_cache = self._cache[ref.feature_id]
                # The body/table are available through the *producing* feature
                # — we record them under the input name plus a "_selector"
                # discriminator so an evaluator that consumes a selector can
                # still find the producing body if it needs to.
                upstream_bodies.setdefault(
                    f"{input_name}__body", up_cache.body  # type: ignore[arg-type]
                )
                upstream_tables.setdefault(
                    f"{input_name}__table", up_cache.naming_table  # type: ignore[arg-type]
                )

        # 2. Build the resolve_selector callable for this evaluation step.
        def _resolve(selector: PersistentSelector) -> Any:
            return self._resolve_selector(selector)

        ctx = EvaluationContext(
            upstream_bodies=upstream_bodies,
            upstream_tables=upstream_tables,
            resolve_selector=_resolve,
        )

        # 3. Dispatch.
        evaluator = self._evaluators.get(feature.kind)
        if evaluator is None:
            raise KeyError(
                f"no evaluator registered for feature kind {feature.kind!r} "
                f"(feature {feature_id[:8]})"
            )
        result = evaluator(feature, ctx)

        # 4. Track call count (test fixture support).
        if _evaluation_counter is not None:
            _evaluation_counter[feature_id] = (
                _evaluation_counter.get(feature_id, 0) + 1
            )

        # 5. Populate cache + feature.
        cache.body = result.body
        cache.naming_table = result.naming_table
        cache.extra_outputs = dict(result.extra_outputs)
        cache.valid = True
        feature.outputs = {"body": result.body, **result.extra_outputs}
        feature.naming_table = result.naming_table

    # ── selector resolution ───────────────────────────────────────────────

    def _resolve_selector(self, selector: PersistentSelector) -> Any:
        """Resolve a :class:`PersistentSelector` to the live Face/Edge/Vertex
        on the producing feature's current naming table.

        Raises :class:`MissingReferenceError` when the role is no longer
        present (kind-change, parametric edit that eliminated the entity, ...).
        """
        if selector.feature_id not in self._features:
            raise MissingReferenceError(selector, {"face": [], "edge": [], "vertex": []})
        # Ensure the producing feature is evaluated.
        self._evaluate_to_cache(selector.feature_id)
        table = self._cache[selector.feature_id].naming_table
        if table is None:
            raise MissingReferenceError(selector, {"face": [], "edge": [], "vertex": []})
        if selector.entity_kind == "face":
            ent = table.faces.get(selector.role)
        elif selector.entity_kind == "edge":
            ent = table.edges.get(selector.role)
        elif selector.entity_kind == "vertex":
            ent = table.vertices.get(selector.role)
        else:
            raise ValueError(
                f"unknown entity_kind {selector.entity_kind!r} on selector {selector.short}"
            )
        if ent is None:
            raise MissingReferenceError(selector, table.all_roles())
        return ent

    def resolve_selector(self, selector: PersistentSelector) -> Any:
        """Public selector resolution (exposed for callers + tests)."""
        return self._resolve_selector(selector)

    def naming_table(self, feature_id: str) -> NamingTable:
        """Return the live naming table of ``feature_id`` (evaluating if
        necessary)."""
        self._evaluate_to_cache(feature_id)
        table = self._cache[feature_id].naming_table
        assert table is not None
        return table

    # ── instrumentation ───────────────────────────────────────────────────

    def evaluate_with_counter(
        self,
        feature_id: str,
    ) -> Tuple[Body, Dict[str, int]]:
        """Evaluate ``feature_id``; return (body, call_counts).

        The call_counts dict maps feature_id -> number of times its evaluator
        was invoked during this call (i.e. >0 for genuinely re-evaluated
        features, 0 for ones already in cache).
        """
        counts: Dict[str, int] = {}
        self._evaluate_to_cache(feature_id, _evaluation_counter=counts)
        return self._cache[feature_id].body, counts  # type: ignore[return-value]

    # ── serialisation ─────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """Round-trip-safe dict snapshot.

        Note: caches + outputs are NOT serialised — they are pure derived
        state. To restore an evaluated state, call :meth:`regenerate` after
        :meth:`from_dict`.
        """
        return {
            "features": [
                self._features[fid].to_dict() for fid in self._insertion_order
            ]
        }

    @classmethod
    def from_dict(
        cls,
        d: Dict[str, Any],
        evaluators: Optional[Dict[str, Evaluator]] = None,
    ) -> "FeatureDAG":
        dag = cls()
        if evaluators:
            for kind, ev in evaluators.items():
                dag.register_evaluator(kind, ev)
        for fd in d.get("features", []):
            dag.add_feature(Feature.from_dict(fd))
        return dag


__all__ = [
    "FeatureDAG",
    "DAGCycleError",
    "EvaluationCache",
    "EvaluationContext",
    "EvaluationResult",
    "Evaluator",
]
