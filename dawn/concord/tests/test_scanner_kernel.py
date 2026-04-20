"""Tests for CONCORD Phase 9 — scanner_kernel.py."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from dawn.concord.scanner_kernel import (
    ActionCatalog,
    CompoundDangerFinding,
    DangerMap,
    DependencyEdge,
    DependencyNode,
    DimensionScore,
    DraftActionEntry,
    DraftFieldValue,
    PatchItem,
    PatchPlan,
    ReadinessReport,
    ResourceDependencyGraph,
    SinglePointDangerFinding,
    build_danger_map,
    build_dependency_graph,
    compute_maturity_level,
    generate_action_catalog,
    plan_patches,
    score_readiness,
)
from dawn.concord.types.enums import (
    ConfidenceLevel,
    DangerType,
    DependencyEdgeType,
    EvidenceSource,
    MaturityLevel,
    PatchPriority,
    SinglePointDangerCategory,
    SilentFailureLikelihood,
)

NOW = datetime(2026, 3, 5, 12, 0, 0, tzinfo=timezone.utc)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _dim(dimension: str, score: int, source: EvidenceSource = EvidenceSource.DISCOVERED) -> DimensionScore:
    return DimensionScore(dimension=dimension, score=score, evidence_source=source)


def _sp(
    danger_id: str = "d1",
    severity: str = "high",
    resource: str = "POST_/orders",
    category: SinglePointDangerCategory = SinglePointDangerCategory.DESTRUCTIVE_WITHOUT_IDEMPOTENCY,
    confidence: ConfidenceLevel = ConfidenceLevel.CONFIRMED,
) -> SinglePointDangerFinding:
    return SinglePointDangerFinding(
        danger_id=danger_id,
        resource_or_endpoint=resource,
        category=category,
        severity=severity,
        trigger_condition="Agent retries after timeout.",
        likely_failure_mode="Duplicate order created.",
        agent_risk="Agents retry automatically on timeout.",
        recommended_patch="Add idempotency_key parameter.",
        confidence_level=confidence,
    )


def _compound(
    compound_id: str = "c1",
    contributing: list[str] | None = None,
    severity: str = "critical",
    confidence: ConfidenceLevel = ConfidenceLevel.INFERRED,
) -> CompoundDangerFinding:
    if contributing is None:
        contributing = ["d1"]
    return CompoundDangerFinding(
        compound_danger_id=compound_id,
        contributing_risk_ids=contributing,
        interaction_path="read -> write on same resource",
        compound_severity=severity,
        silent_failure_likelihood=SilentFailureLikelihood.HIGH,
        confidence_level=confidence,
        recommended_patch="Add authoritative recheck before mutation.",
    )


def _node(
    node_id: str,
    profile: str | None = None,
    has_compensation: bool = False,
) -> DependencyNode:
    return DependencyNode(
        node_id=node_id,
        label=node_id,
        consistency_profile=profile,
        has_compensation=has_compensation,
    )


def _edge(src: str, tgt: str, edge_type: DependencyEdgeType, label: str | None = None) -> DependencyEdge:
    return DependencyEdge(source_id=src, target_id=tgt, edge_type=edge_type, label=label)


# ── compute_maturity_level ────────────────────────────────────────────────────


class TestComputeMaturityLevel:
    def test_level_0(self):
        assert compute_maturity_level(0) == MaturityLevel.LEVEL_0

    def test_level_6(self):
        assert compute_maturity_level(6) == MaturityLevel.LEVEL_6

    def test_all_levels(self):
        for i in range(7):
            assert compute_maturity_level(i) == MaturityLevel(f"level_{i}")

    def test_clamp_negative(self):
        assert compute_maturity_level(-1) == MaturityLevel.LEVEL_0

    def test_clamp_above_6(self):
        assert compute_maturity_level(99) == MaturityLevel.LEVEL_6


# ── score_readiness ───────────────────────────────────────────────────────────


class TestScoreReadiness:
    def _full_scores(self, scores: dict[str, int]) -> list[DimensionScore]:
        dims = [
            "action_contracts", "state_explicitness", "consistency", "idempotency",
            "trust_and_budget", "coordination", "recovery", "observability",
        ]
        return [_dim(d, scores.get(d, 6)) for d in dims]

    def test_returns_readiness_report(self):
        dims = [_dim("action_contracts", 3)]
        report = score_readiness("scan-1", "my-app", dims, generated_at=NOW)
        assert isinstance(report, ReadinessReport)

    def test_scan_id_and_target(self):
        report = score_readiness("scan-99", "app-x", [], generated_at=NOW)
        assert report.scan_id == "scan-99"
        assert report.target_name == "app-x"

    def test_generated_at_forwarded(self):
        report = score_readiness("s", "t", [], generated_at=NOW)
        assert report.generated_at == NOW

    def test_missing_dimensions_default_to_0(self):
        report = score_readiness("s", "t", [], generated_at=NOW)
        assert report.overall_maturity_level == MaturityLevel.LEVEL_0

    def test_all_8_dimensions_in_map(self):
        report = score_readiness("s", "t", [], generated_at=NOW)
        assert len(report.dimension_scores) == 8

    def test_weakest_link_rule(self):
        dims = self._full_scores({"action_contracts": 2, "recovery": 5})
        report = score_readiness("s", "t", dims, generated_at=NOW)
        # action_contracts=2, all others default to 6 → min=2
        assert report.overall_maturity_level == MaturityLevel.LEVEL_2

    def test_all_6_gives_level_6(self):
        dims = self._full_scores({})   # all default to 6
        report = score_readiness("s", "t", dims, generated_at=NOW)
        assert report.overall_maturity_level == MaturityLevel.LEVEL_6

    def test_top_gaps_are_dimensions_below_3(self):
        dims = self._full_scores({"action_contracts": 1, "recovery": 2, "coordination": 4})
        report = score_readiness("s", "t", dims, generated_at=NOW)
        assert "action_contracts" in report.top_gaps
        assert "recovery" in report.top_gaps
        assert "coordination" not in report.top_gaps

    def test_top_gaps_sorted_ascending_by_score(self):
        dims = self._full_scores({"recovery": 2, "action_contracts": 0, "idempotency": 1})
        report = score_readiness("s", "t", dims, generated_at=NOW)
        scores = [report.dimension_scores[d].score for d in report.top_gaps]
        assert scores == sorted(scores)

    def test_no_gaps_when_all_scores_3_or_above(self):
        dims = self._full_scores({"action_contracts": 3, "recovery": 3})
        report = score_readiness("s", "t", dims, generated_at=NOW)
        assert report.top_gaps == []

    def test_recommended_entry_sequence_starts_with_gaps(self):
        dims = self._full_scores({"action_contracts": 1, "recovery": 2})
        report = score_readiness("s", "t", dims, generated_at=NOW)
        seq = report.recommended_entry_sequence
        for gap in report.top_gaps:
            assert gap in seq
        # gaps come first
        gap_positions = [seq.index(g) for g in report.top_gaps]
        non_gap_positions = [seq.index(d) for d in seq if d not in report.top_gaps]
        assert max(gap_positions) < min(non_gap_positions)

    def test_duplicate_dimension_last_wins(self):
        dims = [_dim("action_contracts", 1), _dim("action_contracts", 5)]
        report = score_readiness("s", "t", dims, generated_at=NOW)
        assert report.dimension_scores["action_contracts"].score == 5

    def test_evidence_source_preserved(self):
        dims = [_dim("action_contracts", 4, EvidenceSource.INFERRED)]
        report = score_readiness("s", "t", dims, generated_at=NOW)
        assert report.dimension_scores["action_contracts"].evidence_source == EvidenceSource.INFERRED

    def test_missing_dims_have_heuristic_source(self):
        report = score_readiness("s", "t", [], generated_at=NOW)
        for ds in report.dimension_scores.values():
            assert ds.evidence_source == EvidenceSource.HEURISTIC


# ── build_danger_map ──────────────────────────────────────────────────────────


class TestBuildDangerMap:
    def test_returns_danger_map(self):
        dm = build_danger_map("s1", [_sp()], [])
        assert isinstance(dm, DangerMap)

    def test_scan_id_preserved(self):
        dm = build_danger_map("scan-abc", [], [])
        assert dm.scan_id == "scan-abc"

    def test_single_point_preserved(self):
        sp = _sp("d1", "high")
        dm = build_danger_map("s", [sp], [])
        assert len(dm.single_point) == 1
        assert dm.single_point[0].danger_id == "d1"

    def test_compound_with_higher_severity_accepted(self):
        sp = _sp("d1", "high")
        cd = _compound("c1", ["d1"], severity="critical")
        dm = build_danger_map("s", [sp], [cd])
        assert dm.compound[0].compound_severity == "critical"

    def test_compound_same_severity_is_escalated(self):
        # Individual is 'high', compound also 'high' → should be escalated to 'critical'
        sp = _sp("d1", "high")
        cd = _compound("c1", ["d1"], severity="high")
        dm = build_danger_map("s", [sp], [cd])
        assert dm.compound[0].compound_severity == "critical"

    def test_compound_lower_severity_is_escalated(self):
        # Individual is 'moderate', compound is 'low' → escalated to 'high'
        sp = _sp("d1", "moderate")
        cd = _compound("c1", ["d1"], severity="low")
        dm = build_danger_map("s", [sp], [cd])
        assert dm.compound[0].compound_severity == "high"

    def test_compound_escalation_uses_highest_contributor(self):
        sp1 = _sp("d1", "moderate")
        sp2 = _sp("d2", "high", resource="DELETE_/orders/{id}")
        cd = _compound("c1", ["d1", "d2"], severity="low")
        dm = build_danger_map("s", [sp1, sp2], [cd])
        # Highest individual is 'high' → compound must be above 'high' → 'critical'
        assert dm.compound[0].compound_severity == "critical"

    def test_no_single_points_empty_map(self):
        dm = build_danger_map("s", [], [])
        assert dm.single_point == []
        assert dm.compound == []

    def test_multiple_compounds(self):
        sp1 = _sp("d1", "low")
        sp2 = _sp("d2", "moderate", resource="r2", category=SinglePointDangerCategory.MUTABLE_WITHOUT_VERSIONING)
        cd1 = _compound("c1", ["d1"], severity="critical")
        cd2 = _compound("c2", ["d2"], severity="critical")
        dm = build_danger_map("s", [sp1, sp2], [cd1, cd2])
        assert len(dm.compound) == 2

    def test_confidence_level_on_single_point(self):
        sp = _sp("d1", confidence=ConfidenceLevel.HEURISTIC)
        dm = build_danger_map("s", [sp], [])
        assert dm.single_point[0].confidence_level == ConfidenceLevel.HEURISTIC

    def test_confidence_level_on_compound(self):
        sp = _sp("d1", "critical")
        cd = _compound("c1", ["d1"], severity="critical", confidence=ConfidenceLevel.HIGH_CONFIDENCE)
        dm = build_danger_map("s", [sp], [cd])
        assert dm.compound[0].confidence_level == ConfidenceLevel.HIGH_CONFIDENCE


# ── build_dependency_graph ────────────────────────────────────────────────────


class TestBuildDependencyGraph:
    def test_returns_graph(self):
        g = build_dependency_graph("g1", [], [])
        assert isinstance(g, ResourceDependencyGraph)

    def test_graph_id_preserved(self):
        g = build_dependency_graph("g-99", [], [])
        assert g.graph_id == "g-99"

    def test_nodes_and_edges_preserved(self):
        nodes = [_node("a"), _node("b")]
        edges = [_edge("a", "b", DependencyEdgeType.MUTATES)]
        g = build_dependency_graph("g1", nodes, edges)
        assert len(g.nodes) == 2
        assert len(g.edges) == 1

    def test_no_hotspots_low_degree(self):
        # 3 edges → degree 3 (source has out-degree 3) — NOT a hotspot (threshold > 3)
        nodes = [_node("a"), _node("b"), _node("c"), _node("d")]
        edges = [
            _edge("a", "b", DependencyEdgeType.MUTATES),
            _edge("a", "c", DependencyEdgeType.READS_BEFORE_MUTATION),
            _edge("a", "d", DependencyEdgeType.TRIGGERS),
        ]
        g = build_dependency_graph("g1", nodes, edges)
        assert "a" not in g.hotspots

    def test_hotspot_detected_above_3(self):
        # 4 edges from/to 'a' → fan degree 4 > 3 → hotspot
        nodes = [_node("a"), _node("b"), _node("c"), _node("d"), _node("e")]
        edges = [
            _edge("a", "b", DependencyEdgeType.MUTATES),
            _edge("a", "c", DependencyEdgeType.TRIGGERS),
            _edge("a", "d", DependencyEdgeType.PROJECTS_TO),
            _edge("e", "a", DependencyEdgeType.BACKGROUND_UPDATES),
        ]
        g = build_dependency_graph("g1", nodes, edges)
        assert "a" in g.hotspots

    def test_consistency_mismatch_on_mutates_edge(self):
        nodes = [_node("a", profile="STRONG"), _node("b", profile="EVENTUAL")]
        edges = [_edge("a", "b", DependencyEdgeType.MUTATES)]
        g = build_dependency_graph("g1", nodes, edges)
        assert ("a", "b") in g.consistency_mismatches

    def test_no_mismatch_when_profiles_same(self):
        nodes = [_node("a", profile="STRONG"), _node("b", profile="STRONG")]
        edges = [_edge("a", "b", DependencyEdgeType.MUTATES)]
        g = build_dependency_graph("g1", nodes, edges)
        assert g.consistency_mismatches == []

    def test_no_mismatch_when_profile_is_none(self):
        nodes = [_node("a", profile=None), _node("b", profile="STRONG")]
        edges = [_edge("a", "b", DependencyEdgeType.MUTATES)]
        g = build_dependency_graph("g1", nodes, edges)
        assert g.consistency_mismatches == []

    def test_saga_gap_on_mutates_without_compensation(self):
        nodes = [_node("a", has_compensation=False), _node("b", has_compensation=False)]
        edges = [_edge("a", "b", DependencyEdgeType.MUTATES)]
        g = build_dependency_graph("g1", nodes, edges)
        assert ("a", "b") in g.saga_gaps

    def test_no_saga_gap_when_source_has_compensation(self):
        nodes = [_node("a", has_compensation=True), _node("b", has_compensation=False)]
        edges = [_edge("a", "b", DependencyEdgeType.MUTATES)]
        g = build_dependency_graph("g1", nodes, edges)
        assert ("a", "b") not in g.saga_gaps

    def test_no_saga_gap_when_target_has_compensation(self):
        nodes = [_node("a", has_compensation=False), _node("b", has_compensation=True)]
        edges = [_edge("a", "b", DependencyEdgeType.MUTATES)]
        g = build_dependency_graph("g1", nodes, edges)
        assert ("a", "b") not in g.saga_gaps

    def test_triggers_edge_not_in_saga_gaps(self):
        nodes = [_node("a"), _node("b")]
        edges = [_edge("a", "b", DependencyEdgeType.TRIGGERS)]
        g = build_dependency_graph("g1", nodes, edges)
        assert g.saga_gaps == []

    def test_reads_before_mutation_mismatch_detected(self):
        nodes = [_node("src", profile="SESSION_MONOTONIC"), _node("tgt", profile="STRONG")]
        edges = [_edge("src", "tgt", DependencyEdgeType.READS_BEFORE_MUTATION)]
        g = build_dependency_graph("g1", nodes, edges)
        assert ("src", "tgt") in g.consistency_mismatches

    def test_empty_graph(self):
        g = build_dependency_graph("g1", [], [])
        assert g.nodes == []
        assert g.edges == []
        assert g.hotspots == []
        assert g.consistency_mismatches == []
        assert g.saga_gaps == []


# ── plan_patches ──────────────────────────────────────────────────────────────


class TestPlanPatches:
    def _make_readiness(self, gaps: list[str] | None = None) -> ReadinessReport:
        gaps = gaps or []
        # Build a full ReadinessReport with top_gaps manually set
        dims = {
            "action_contracts": DimensionScore("action_contracts", 6, EvidenceSource.DISCOVERED),
            "state_explicitness": DimensionScore("state_explicitness", 6, EvidenceSource.DISCOVERED),
            "consistency": DimensionScore("consistency", 6, EvidenceSource.DISCOVERED),
            "idempotency": DimensionScore("idempotency", 6, EvidenceSource.DISCOVERED),
            "trust_and_budget": DimensionScore("trust_and_budget", 6, EvidenceSource.DISCOVERED),
            "coordination": DimensionScore("coordination", 6, EvidenceSource.DISCOVERED),
            "recovery": DimensionScore("recovery", 6, EvidenceSource.DISCOVERED),
            "observability": DimensionScore("observability", 6, EvidenceSource.DISCOVERED),
        }
        for gap in gaps:
            dims[gap] = DimensionScore(gap, 1, EvidenceSource.HEURISTIC)
        return ReadinessReport(
            scan_id="s1",
            target_name="app",
            generated_at=NOW,
            overall_maturity_level=MaturityLevel.LEVEL_1 if gaps else MaturityLevel.LEVEL_6,
            dimension_scores=dims,
            top_gaps=gaps,
            recommended_entry_sequence=gaps,
        )

    def test_returns_patch_plan(self):
        dm = build_danger_map("s1", [], [])
        rr = self._make_readiness()
        pp = plan_patches("plan-1", dm, rr)
        assert isinstance(pp, PatchPlan)

    def test_plan_id_and_scan_id(self):
        dm = build_danger_map("s1", [], [])
        rr = self._make_readiness()
        pp = plan_patches("plan-x", dm, rr)
        assert pp.plan_id == "plan-x"
        assert pp.scan_id == "s1"

    def test_critical_danger_becomes_p0(self):
        sp = _sp("d1", "critical")
        dm = build_danger_map("s1", [sp], [])
        rr = self._make_readiness()
        pp = plan_patches("p", dm, rr)
        p0_items = [i for i in pp.items if i.priority == PatchPriority.P0]
        assert any("d1" in i.patch_id for i in p0_items)

    def test_high_danger_becomes_p1(self):
        sp = _sp("d1", "high")
        dm = build_danger_map("s1", [sp], [])
        rr = self._make_readiness()
        pp = plan_patches("p", dm, rr)
        p1_items = [i for i in pp.items if i.priority == PatchPriority.P1]
        assert any("d1" in i.patch_id for i in p1_items)

    def test_moderate_danger_becomes_p2(self):
        sp = _sp("d1", "moderate")
        dm = build_danger_map("s1", [sp], [])
        rr = self._make_readiness()
        pp = plan_patches("p", dm, rr)
        p2_items = [i for i in pp.items if i.priority == PatchPriority.P2]
        assert any("d1" in i.patch_id for i in p2_items)

    def test_low_danger_becomes_p3(self):
        sp = _sp("d1", "low")
        dm = build_danger_map("s1", [sp], [])
        rr = self._make_readiness()
        pp = plan_patches("p", dm, rr)
        p3_items = [i for i in pp.items if i.priority == PatchPriority.P3]
        assert any("d1" in i.patch_id for i in p3_items)

    def test_gap_dimensions_produce_p2_patch(self):
        dm = build_danger_map("s1", [], [])
        rr = self._make_readiness(gaps=["recovery"])
        pp = plan_patches("p", dm, rr)
        gap_items = [i for i in pp.items if "recovery" in i.patch_id]
        assert len(gap_items) == 1
        assert gap_items[0].priority == PatchPriority.P2

    def test_items_sorted_p0_first(self):
        sp_critical = _sp("d1", "critical")
        sp_low = _sp("d2", "low", resource="r2", category=SinglePointDangerCategory.MUTABLE_WITHOUT_VERSIONING)
        dm = build_danger_map("s1", [sp_critical, sp_low], [])
        rr = self._make_readiness()
        pp = plan_patches("p", dm, rr)
        priorities = [i.priority for i in pp.items]
        # Must be sorted P0 ≤ P1 ≤ P2 ≤ P3
        _order = {PatchPriority.P0: 0, PatchPriority.P1: 1, PatchPriority.P2: 2, PatchPriority.P3: 3}
        assert priorities == sorted(priorities, key=lambda p: _order[p])

    def test_compound_danger_produces_patch_with_deps(self):
        sp = _sp("d1", "high")
        cd = _compound("c1", ["d1"], severity="critical")
        dm = build_danger_map("s1", [sp], [cd])
        rr = self._make_readiness()
        pp = plan_patches("p", dm, rr)
        compound_items = [i for i in pp.items if "c1" in i.patch_id]
        assert len(compound_items) == 1
        assert "patch-d1" in compound_items[0].dependency_patch_ids

    def test_no_duplicate_patches(self):
        sp = _sp("d1", "high")
        dm = build_danger_map("s1", [sp], [])
        rr = self._make_readiness()
        pp = plan_patches("p", dm, rr)
        ids = [i.patch_id for i in pp.items]
        assert len(ids) == len(set(ids))

    def test_empty_danger_map_and_no_gaps(self):
        dm = build_danger_map("s1", [], [])
        rr = self._make_readiness()
        pp = plan_patches("p", dm, rr)
        assert pp.items == []


# ── generate_action_catalog ───────────────────────────────────────────────────


class TestGenerateActionCatalog:
    def test_returns_catalog(self):
        cat = generate_action_catalog("cat-1", "s1", [])
        assert isinstance(cat, ActionCatalog)

    def test_catalog_id_and_scan_id(self):
        cat = generate_action_catalog("cat-x", "s-99", [])
        assert cat.catalog_id == "cat-x"
        assert cat.scan_id == "s-99"

    def test_empty_observations(self):
        cat = generate_action_catalog("c", "s", [])
        assert cat.entries == []

    def test_one_entry_per_observation(self):
        obs = [
            {"http_method": "GET", "path": "/orders", "resource_type": "order"},
            {"http_method": "POST", "path": "/orders", "resource_type": "order"},
        ]
        cat = generate_action_catalog("c", "s", obs)
        assert len(cat.entries) == 2

    def test_get_infers_read_family(self):
        obs = [{"http_method": "GET", "path": "/orders", "resource_type": "order"}]
        cat = generate_action_catalog("c", "s", obs)
        assert cat.entries[0].action_family.value == "read"

    def test_post_infers_mutate_family(self):
        obs = [{"http_method": "POST", "path": "/orders", "resource_type": "order"}]
        cat = generate_action_catalog("c", "s", obs)
        assert cat.entries[0].action_family.value == "mutate"

    def test_delete_infers_mutate_family(self):
        obs = [{"http_method": "DELETE", "path": "/orders/{id}", "resource_type": "order"}]
        cat = generate_action_catalog("c", "s", obs)
        assert cat.entries[0].action_family.value == "mutate"

    def test_action_name_from_explicit_field(self):
        obs = [{"action_name": "submit_order", "resource_type": "order", "http_method": "POST", "path": "/orders"}]
        cat = generate_action_catalog("c", "s", obs)
        entry = cat.entries[0]
        assert entry.action_name.value == "submit_order"
        assert entry.action_name.evidence_source == EvidenceSource.DISCOVERED

    def test_action_name_inferred_from_method_path(self):
        obs = [{"http_method": "GET", "path": "/orders", "resource_type": "order"}]
        cat = generate_action_catalog("c", "s", obs)
        entry = cat.entries[0]
        assert "GET" in str(entry.action_name.value)
        assert entry.action_name.evidence_source == EvidenceSource.INFERRED

    def test_idempotency_discovered_when_explicit(self):
        obs = [{"http_method": "POST", "path": "/orders", "resource_type": "order", "is_idempotent": True}]
        cat = generate_action_catalog("c", "s", obs)
        entry = cat.entries[0]
        assert entry.idempotency_required.value is True
        assert entry.idempotency_required.evidence_source == EvidenceSource.DISCOVERED

    def test_idempotency_heuristic_when_not_provided(self):
        obs = [{"http_method": "POST", "path": "/orders", "resource_type": "order"}]
        cat = generate_action_catalog("c", "s", obs)
        entry = cat.entries[0]
        assert entry.idempotency_required.evidence_source == EvidenceSource.HEURISTIC

    def test_consistency_discovered_when_provided(self):
        obs = [{"http_method": "GET", "path": "/r", "resource_type": "r", "consistency": "STRONG"}]
        cat = generate_action_catalog("c", "s", obs)
        entry = cat.entries[0]
        assert entry.consistency_profile.value == "STRONG"
        assert entry.consistency_profile.evidence_source == EvidenceSource.DISCOVERED
        assert entry.consistency_profile.confidence_band is None

    def test_consistency_band_when_inferred(self):
        obs = [{"http_method": "POST", "path": "/orders", "resource_type": "order"}]
        cat = generate_action_catalog("c", "s", obs)
        entry = cat.entries[0]
        assert entry.consistency_profile.evidence_source == EvidenceSource.INFERRED
        assert entry.consistency_profile.confidence_band is not None

    def test_compensation_detected_when_has_saga(self):
        obs = [{"http_method": "POST", "path": "/t", "resource_type": "t", "has_saga": True}]
        cat = generate_action_catalog("c", "s", obs)
        assert cat.entries[0].compensation_strategy.value == "saga_handler"

    def test_compensation_none_when_simple_write(self):
        obs = [{"http_method": "POST", "path": "/t", "resource_type": "t"}]
        cat = generate_action_catalog("c", "s", obs)
        assert cat.entries[0].compensation_strategy.value == "none"

    def test_retry_none_when_not_idempotent(self):
        obs = [{"http_method": "POST", "path": "/t", "resource_type": "t", "is_idempotent": False}]
        cat = generate_action_catalog("c", "s", obs)
        assert cat.entries[0].retry_class.value == "none"

    def test_retry_safe_retry_for_idempotent_strong(self):
        obs = [{"http_method": "GET", "path": "/t", "resource_type": "t",
                "is_idempotent": True, "consistency": "STRONG"}]
        cat = generate_action_catalog("c", "s", obs)
        assert cat.entries[0].retry_class.value == "safe_retry"

    def test_side_effects_empty_when_not_observed(self):
        obs = [{"http_method": "GET", "path": "/t", "resource_type": "t"}]
        cat = generate_action_catalog("c", "s", obs)
        assert cat.entries[0].side_effects.value == []

    def test_side_effects_discovered_when_provided(self):
        obs = [{"http_method": "POST", "path": "/t", "resource_type": "t",
                "side_effects": ["emit OrderCreated event"]}]
        cat = generate_action_catalog("c", "s", obs)
        entry = cat.entries[0]
        assert "emit OrderCreated event" in entry.side_effects.value
        assert entry.side_effects.evidence_source == EvidenceSource.DISCOVERED

    def test_confidence_level_forwarded(self):
        obs = [{"http_method": "GET", "path": "/t", "resource_type": "t",
                "confidence": "confirmed"}]
        cat = generate_action_catalog("c", "s", obs)
        assert cat.entries[0].confidence_level == ConfidenceLevel.CONFIRMED

    def test_unknown_confidence_defaults_to_inferred(self):
        obs = [{"http_method": "GET", "path": "/t", "resource_type": "t",
                "confidence": "totally_unknown_value"}]
        cat = generate_action_catalog("c", "s", obs)
        assert cat.entries[0].confidence_level == ConfidenceLevel.INFERRED

    def test_risk_level_discovered_when_explicit(self):
        obs = [{"http_method": "DELETE", "path": "/t/{id}", "resource_type": "t", "risk_level": "critical"}]
        cat = generate_action_catalog("c", "s", obs)
        entry = cat.entries[0]
        assert entry.risk_level.value == "critical"
        assert entry.risk_level.evidence_source == EvidenceSource.DISCOVERED

    def test_risk_level_inferred_from_family(self):
        obs = [{"http_method": "GET", "path": "/t", "resource_type": "t"}]
        cat = generate_action_catalog("c", "s", obs)
        entry = cat.entries[0]
        assert entry.risk_level.value == "low"
        assert entry.risk_level.evidence_source == EvidenceSource.INFERRED

    def test_source_location_on_all_fields(self):
        obs = [{"http_method": "GET", "path": "/t", "resource_type": "t", "source_location": "app.py:42"}]
        cat = generate_action_catalog("c", "s", obs)
        entry = cat.entries[0]
        assert entry.source_location == "app.py:42"
        assert entry.action_name.source_location == "app.py:42"


# ── DimensionScore frozen ─────────────────────────────────────────────────────


class TestDimensionScoreFrozen:
    def test_is_frozen(self):
        ds = _dim("action_contracts", 3)
        with pytest.raises((AttributeError, TypeError)):
            ds.score = 5  # type: ignore[misc]


# ── ReadinessReport frozen ────────────────────────────────────────────────────


class TestReadinessReportFrozen:
    def test_is_frozen(self):
        rr = score_readiness("s", "t", [], generated_at=NOW)
        with pytest.raises((AttributeError, TypeError)):
            rr.scan_id = "x"  # type: ignore[misc]


# ── SinglePointDangerFinding frozen ──────────────────────────────────────────


class TestSinglePointDangerFindingFrozen:
    def test_is_frozen(self):
        sp = _sp()
        with pytest.raises((AttributeError, TypeError)):
            sp.severity = "low"  # type: ignore[misc]


# ── CompoundDangerFinding frozen ──────────────────────────────────────────────


class TestCompoundDangerFindingFrozen:
    def test_is_frozen(self):
        cd = _compound()
        with pytest.raises((AttributeError, TypeError)):
            cd.compound_severity = "low"  # type: ignore[misc]


# ── ConfidenceLevel enum ──────────────────────────────────────────────────────


class TestConfidenceLevelEnum:
    def test_all_values(self):
        values = {cl.value for cl in ConfidenceLevel}
        assert values == {"confirmed", "high_confidence", "inferred", "heuristic"}

    def test_confirmed_is_str(self):
        assert isinstance(ConfidenceLevel.CONFIRMED, str)
        assert ConfidenceLevel.CONFIRMED == "confirmed"
