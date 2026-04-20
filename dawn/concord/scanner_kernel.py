"""CONCORD Phase 9 — Scanner kernel.

Provides:
- DimensionScore        — per-dimension readiness evidence record
- ReadinessReport       — composite 8-dimension maturity report (Level 0–6)
- SinglePointDangerFinding — one of the 8 required danger categories
- CompoundDangerFinding — danger arising from interaction of single-point risks
- DangerMap             — container for all danger findings
- DependencyNode        — node in the resource dependency graph
- DependencyEdge        — typed edge in the resource dependency graph
- ResourceDependencyGraph — full dependency graph with hotspot/gap analysis
- PatchItem             — single recommended patch work item (P0–P3)
- PatchPlan             — full ordered patch plan derived from danger map + readiness
- DraftFieldValue       — a single inferred field value with confidence metadata
- DraftActionEntry      — draft ActionContract inferred by the scanner
- ActionCatalog         — collection of draft ActionEntries

Builder functions:
- compute_maturity_level()   — int score → MaturityLevel
- score_readiness()          — dimension observations → ReadinessReport
- build_danger_map()         — danger observations → DangerMap (enforces compound > individual severity)
- build_dependency_graph()   — edge observations → ResourceDependencyGraph
- plan_patches()             — danger map + readiness → PatchPlan
- generate_action_catalog()  — endpoint observations → ActionCatalog

Normative rules enforced:

  ReadinessReport:
  - overall_maturity_level is the *minimum* of all dimension levels (weakest-link model).
  - Each dimension_score carries an evidence_source distinguishing discovered / inferred / heuristic.
  - top_gaps: dimensions with the lowest scores (score < 3), sorted ascending by score.

  DangerMap:
  - compound_severity MUST exceed every individual contributing risk's severity.
  - Every finding (single-point or compound) MUST carry a confidence_level.
  - compound_dangers reference single-point findings by danger_id.

  ResourceDependencyGraph:
  - Exactly 6 edge types are supported (DependencyEdgeType enum).
  - consistency_mismatches: edges where source and target declared profiles differ.
  - saga_gaps: edges of type MUTATES spanning 2+ resources without compensation declared.
  - hotspots: nodes with fan_in + fan_out > 3 (high connectivity threshold).

  PatchPlan:
  - P0 items must appear before P1, P1 before P2, P2 before P3 in returned list.
  - dependency_patch_ids respected: a patch must not be scheduled before its dependencies.
  - Patches are derived from: danger findings (severity → priority) + low readiness dimensions.

  ActionCatalog:
  - Every DraftFieldValue carries an evidence_source.
  - confidence_band is emitted when confidence is LOW (< 60 %).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from dawn.concord.types.enums import (
    ConfidenceLevel,
    DangerType,
    DependencyEdgeType,
    EvidenceSource,
    MaturityLevel,
    PatchPriority,
    RiskLevel,
    SilentFailureLikelihood,
    SinglePointDangerCategory,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Severity ordering ─────────────────────────────────────────────────────────

_SEVERITY_ORDER: dict[str, int] = {
    "low": 0,
    "moderate": 1,
    "high": 2,
    "critical": 3,
}

_SEVERITY_FROM_RISK: dict[RiskLevel, str] = {
    RiskLevel.LOW: "low",
    RiskLevel.MODERATE: "moderate",
    RiskLevel.HIGH: "high",
    RiskLevel.CRITICAL: "critical",
}

_PRIORITY_FROM_SEVERITY: dict[str, PatchPriority] = {
    "critical": PatchPriority.P0,
    "high": PatchPriority.P1,
    "moderate": PatchPriority.P2,
    "low": PatchPriority.P3,
}

_NEXT_SEVERITY: dict[str, str] = {
    "low": "moderate",
    "moderate": "high",
    "high": "critical",
    "critical": "critical",   # already at max
}


# ── Readiness ─────────────────────────────────────────────────────────────────

#: Canonical dimension names (8 required).
DIMENSION_NAMES: tuple[str, ...] = (
    "action_contracts",
    "state_explicitness",
    "consistency",
    "idempotency",
    "trust_and_budget",
    "coordination",
    "recovery",
    "observability",
)


@dataclass(frozen=True)
class DimensionScore:
    """Score for one of the 8 readiness dimensions.

    Attributes:
        dimension:      One of the 8 canonical dimension names.
        score:          Integer 0–6 (maps directly to MaturityLevel).
        evidence_source: How the score was derived.
        notes:          Optional human-readable rationale.
    """

    dimension: str
    score: int           # 0–6
    evidence_source: EvidenceSource
    notes: Optional[str] = None


@dataclass(frozen=True)
class ReadinessReport:
    """Composite CONCORD readiness report across all 8 dimensions.

    Attributes:
        scan_id:                Unique scan identifier.
        target_name:            Application or service name.
        generated_at:           Report generation timestamp.
        overall_maturity_level: Minimum of all dimension scores (weakest-link).
        dimension_scores:       Per-dimension score map (dimension → DimensionScore).
        top_gaps:               Dimensions with score < 3, sorted ascending by score.
        recommended_entry_sequence: Ordered list of dimensions to address first.
    """

    scan_id: str
    target_name: str
    generated_at: datetime
    overall_maturity_level: MaturityLevel
    dimension_scores: dict[str, DimensionScore]
    top_gaps: list[str]
    recommended_entry_sequence: list[str]


def compute_maturity_level(score: int) -> MaturityLevel:
    """Map an integer score 0–6 to the corresponding MaturityLevel."""
    score = max(0, min(6, score))
    return MaturityLevel(f"level_{score}")


def score_readiness(
    scan_id: str,
    target_name: str,
    dimension_scores: list[DimensionScore],
    *,
    generated_at: Optional[datetime] = None,
) -> ReadinessReport:
    """Compute a ReadinessReport from per-dimension scores.

    Overall maturity level = minimum across all dimension scores (weakest-link).
    Top gaps = dimensions with score < 3, sorted ascending by score.
    Recommended entry sequence = gaps first (ascending score), then remainder.

    Args:
        scan_id:          Unique identifier for this scan run.
        target_name:      Human-readable application or service name.
        dimension_scores: One DimensionScore per dimension (duplicates: last wins).
        generated_at:     Report timestamp (defaults to utcnow).

    Returns:
        A fully populated ReadinessReport.
    """
    generated_at = generated_at or _utcnow()

    # Build map; last entry wins on duplicate dimension names
    score_map: dict[str, DimensionScore] = {ds.dimension: ds for ds in dimension_scores}

    # Fill missing dimensions with score 0 / heuristic
    for dim in DIMENSION_NAMES:
        if dim not in score_map:
            score_map[dim] = DimensionScore(
                dimension=dim,
                score=0,
                evidence_source=EvidenceSource.HEURISTIC,
                notes="No observations provided; defaulting to score 0.",
            )

    # Overall = weakest link
    min_score = min(ds.score for ds in score_map.values())
    overall = compute_maturity_level(min_score)

    # Gaps = dimensions with score < 3
    gaps = sorted(
        [d for d, ds in score_map.items() if ds.score < 3],
        key=lambda d: score_map[d].score,
    )

    # Recommended entry: gaps first (ascending score), then non-gap dims by score
    non_gaps = sorted(
        [d for d in score_map if d not in gaps],
        key=lambda d: score_map[d].score,
    )
    entry_sequence = gaps + non_gaps

    return ReadinessReport(
        scan_id=scan_id,
        target_name=target_name,
        generated_at=generated_at,
        overall_maturity_level=overall,
        dimension_scores=score_map,
        top_gaps=gaps,
        recommended_entry_sequence=entry_sequence,
    )


# ── Danger map ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SinglePointDangerFinding:
    """A single-point danger finding for one of the 8 required categories.

    Attributes:
        danger_id:           Unique finding identifier.
        resource_or_endpoint: Affected resource, route, or job.
        category:            Which of the 8 categories this falls into.
        severity:            'low', 'moderate', 'high', or 'critical'.
        trigger_condition:   Condition that activates the risk.
        likely_failure_mode: Predicted operational impact.
        agent_risk:          Why autonomous agents amplify the risk.
        recommended_patch:   Suggested mitigation.
        confidence_level:    PL-12 required field.
        source_location:     Optional file:line or endpoint reference.
    """

    danger_id: str
    resource_or_endpoint: str
    category: SinglePointDangerCategory
    severity: str           # 'low' | 'moderate' | 'high' | 'critical'
    trigger_condition: str
    likely_failure_mode: str
    agent_risk: str
    recommended_patch: str
    confidence_level: ConfidenceLevel
    source_location: Optional[str] = None


@dataclass(frozen=True)
class CompoundDangerFinding:
    """A danger arising from the interaction of multiple single-point risks.

    Normative: compound_severity MUST exceed every individual contributing
    risk's severity (enforced in build_danger_map).

    Attributes:
        compound_danger_id:       Unique compound finding identifier.
        contributing_risk_ids:    danger_id values of involved single-point risks.
        interaction_path:         Workflow or path where risks combine.
        compound_severity:        Must be higher than any individual severity.
        silent_failure_likelihood: Whether the failure is likely invisible.
        confidence_level:         PL-12 required field.
        recommended_patch:        Suggested mitigation.
    """

    compound_danger_id: str
    contributing_risk_ids: list[str]
    interaction_path: str
    compound_severity: str      # 'low' | 'moderate' | 'high' | 'critical'
    silent_failure_likelihood: SilentFailureLikelihood
    confidence_level: ConfidenceLevel
    recommended_patch: str = ""


@dataclass(frozen=True)
class DangerMap:
    """Container for all danger findings from a scan run.

    Attributes:
        scan_id:          Links to the ReadinessReport.
        single_point:     All single-point danger findings.
        compound:         All compound danger findings (severity > any individual).
    """

    scan_id: str
    single_point: list[SinglePointDangerFinding]
    compound: list[CompoundDangerFinding]


def build_danger_map(
    scan_id: str,
    single_point_findings: list[SinglePointDangerFinding],
    compound_candidates: list[CompoundDangerFinding],
) -> DangerMap:
    """Validate and assemble a DangerMap.

    Enforces that each CompoundDangerFinding has compound_severity strictly
    greater than every individual contributing risk.  Candidates that fail this
    check are escalated to the next severity tier.

    Args:
        scan_id:               Scan run identifier.
        single_point_findings: All single-point risks discovered in this scan.
        compound_candidates:   Proposed compound risks (severity may be adjusted).

    Returns:
        A DangerMap with validated / escalated compound findings.
    """
    # Build lookup for fast severity access
    sp_by_id: dict[str, str] = {f.danger_id: f.severity for f in single_point_findings}

    validated_compounds: list[CompoundDangerFinding] = []
    for cand in compound_candidates:
        # Severity of the highest individual contributor
        max_individual = max(
            (_SEVERITY_ORDER.get(sp_by_id.get(rid, "low"), 0) for rid in cand.contributing_risk_ids),
            default=0,
        )
        compound_ord = _SEVERITY_ORDER.get(cand.compound_severity, 0)

        if compound_ord <= max_individual:
            # Escalate: one tier above the highest individual
            max_individual_label = next(
                k for k, v in _SEVERITY_ORDER.items() if v == max_individual
            )
            escalated = _NEXT_SEVERITY[max_individual_label]
            # Rebuild as new frozen object with escalated severity
            cand = CompoundDangerFinding(
                compound_danger_id=cand.compound_danger_id,
                contributing_risk_ids=cand.contributing_risk_ids,
                interaction_path=cand.interaction_path,
                compound_severity=escalated,
                silent_failure_likelihood=cand.silent_failure_likelihood,
                confidence_level=cand.confidence_level,
                recommended_patch=cand.recommended_patch,
            )
        validated_compounds.append(cand)

    return DangerMap(
        scan_id=scan_id,
        single_point=list(single_point_findings),
        compound=validated_compounds,
    )


# ── Dependency graph ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DependencyNode:
    """A node in the resource dependency graph.

    Attributes:
        node_id:          Unique identifier for this node.
        label:            Human-readable name (resource, endpoint, external system).
        consistency_profile: Declared consistency requirement (or None if unknown).
        has_compensation: Whether compensation is declared for mutations on this node.
    """

    node_id: str
    label: str
    consistency_profile: Optional[str] = None
    has_compensation: bool = False


@dataclass(frozen=True)
class DependencyEdge:
    """A typed directed edge in the resource dependency graph.

    Attributes:
        source_id:  Source node_id.
        target_id:  Target node_id.
        edge_type:  One of the 6 required edge types.
        label:      Optional human-readable description of the relationship.
    """

    source_id: str
    target_id: str
    edge_type: DependencyEdgeType
    label: Optional[str] = None


@dataclass(frozen=True)
class ResourceDependencyGraph:
    """Full resource dependency graph with hotspot and gap analysis.

    Attributes:
        graph_id:               Unique graph identifier.
        nodes:                  All nodes.
        edges:                  All typed edges.
        consistency_mismatches: Edge IDs (source→target) where profiles differ.
        saga_gaps:              (source_id, target_id) pairs that are MUTATES edges
                                spanning multiple resources with no compensation.
        hotspots:               node_ids where fan_in + fan_out > 3.
    """

    graph_id: str
    nodes: list[DependencyNode]
    edges: list[DependencyEdge]
    consistency_mismatches: list[tuple[str, str]]   # (source_id, target_id)
    saga_gaps: list[tuple[str, str]]                # (source_id, target_id)
    hotspots: list[str]                             # node_ids


def build_dependency_graph(
    graph_id: str,
    nodes: list[DependencyNode],
    edges: list[DependencyEdge],
) -> ResourceDependencyGraph:
    """Build and analyse a ResourceDependencyGraph from raw nodes and edges.

    Analysis:
    - consistency_mismatches: MUTATES or READS_BEFORE_MUTATION edges where
      source and target have non-None, differing consistency_profile values.
    - saga_gaps: MUTATES edges where neither source nor target has has_compensation.
    - hotspots: nodes where (in-degree + out-degree) > 3.

    Args:
        graph_id: Unique identifier for this graph.
        nodes:    All DependencyNode instances.
        edges:    All DependencyEdge instances.

    Returns:
        A ResourceDependencyGraph with computed mismatches, gaps, hotspots.
    """
    node_map: dict[str, DependencyNode] = {n.node_id: n for n in nodes}

    # Fan-in / fan-out counters
    fan: dict[str, int] = {n.node_id: 0 for n in nodes}
    for e in edges:
        if e.source_id in fan:
            fan[e.source_id] += 1
        if e.target_id in fan:
            fan[e.target_id] += 1

    hotspots = [nid for nid, degree in fan.items() if degree > 3]

    consistency_mismatches: list[tuple[str, str]] = []
    saga_gaps: list[tuple[str, str]] = []

    _mutation_edges = {DependencyEdgeType.MUTATES, DependencyEdgeType.READS_BEFORE_MUTATION}

    for e in edges:
        src = node_map.get(e.source_id)
        tgt = node_map.get(e.target_id)
        if src is None or tgt is None:
            continue

        # Consistency mismatch on mutation-related edges
        if e.edge_type in _mutation_edges:
            if (
                src.consistency_profile is not None
                and tgt.consistency_profile is not None
                and src.consistency_profile != tgt.consistency_profile
            ):
                consistency_mismatches.append((e.source_id, e.target_id))

        # Saga gap: MUTATES edge where neither node declares compensation
        if e.edge_type == DependencyEdgeType.MUTATES:
            if not src.has_compensation and not tgt.has_compensation:
                saga_gaps.append((e.source_id, e.target_id))

    return ResourceDependencyGraph(
        graph_id=graph_id,
        nodes=list(nodes),
        edges=list(edges),
        consistency_mismatches=consistency_mismatches,
        saga_gaps=saga_gaps,
        hotspots=hotspots,
    )


# ── Patch plan ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PatchItem:
    """A single recommended patch work item.

    Attributes:
        patch_id:              Unique identifier.
        priority:              P0 (blocking) through P3 (nice-to-have).
        affected_assets:       Files, routes, models, or jobs needing changes.
        expected_control_gain: Safety property added by this patch.
        estimated_complexity:  'small', 'medium', or 'large'.
        dependency_patch_ids:  Predecessor patches that must be done first.
    """

    patch_id: str
    priority: PatchPriority
    affected_assets: list[str]
    expected_control_gain: str
    estimated_complexity: str       # 'small' | 'medium' | 'large'
    dependency_patch_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PatchPlan:
    """Full ordered patch plan derived from danger map and readiness report.

    Attributes:
        plan_id:   Unique identifier for this plan.
        scan_id:   Links to the ReadinessReport / DangerMap.
        items:     All PatchItems sorted by priority (P0 first) then by score.
    """

    plan_id: str
    scan_id: str
    items: list[PatchItem]


def plan_patches(
    plan_id: str,
    danger_map: DangerMap,
    readiness_report: ReadinessReport,
) -> PatchPlan:
    """Derive a PatchPlan from a DangerMap and ReadinessReport.

    Patch generation rules:
    - Each critical single-point danger → P0 patch.
    - Each high single-point danger → P1 patch.
    - Each moderate single-point danger → P2 patch.
    - Each low single-point danger → P3 patch.
    - Each compound danger → priority = one tier above highest individual
      contributor (already enforced in build_danger_map; use compound_severity).
    - Each top_gap dimension (score < 3) → P2 patch (improve readiness).
    - Items are sorted P0 → P3; within the same priority, stable insertion order.

    Args:
        plan_id:          Unique identifier for this plan.
        danger_map:       Validated DangerMap.
        readiness_report: ReadinessReport from the same scan.

    Returns:
        A PatchPlan with items sorted P0 → P3.
    """
    items: list[PatchItem] = []
    seen_ids: set[str] = set()

    # From single-point dangers
    for sp in danger_map.single_point:
        patch_id = f"patch-{sp.danger_id}"
        if patch_id in seen_ids:
            continue
        seen_ids.add(patch_id)
        priority = _PRIORITY_FROM_SEVERITY.get(sp.severity, PatchPriority.P3)
        items.append(
            PatchItem(
                patch_id=patch_id,
                priority=priority,
                affected_assets=[sp.resource_or_endpoint],
                expected_control_gain=sp.recommended_patch,
                estimated_complexity="medium",
                dependency_patch_ids=[],
            )
        )

    # From compound dangers
    for cd in danger_map.compound:
        patch_id = f"patch-{cd.compound_danger_id}"
        if patch_id in seen_ids:
            continue
        seen_ids.add(patch_id)
        priority = _PRIORITY_FROM_SEVERITY.get(cd.compound_severity, PatchPriority.P0)
        dep_ids = [f"patch-{rid}" for rid in cd.contributing_risk_ids]
        items.append(
            PatchItem(
                patch_id=patch_id,
                priority=priority,
                affected_assets=[cd.interaction_path],
                expected_control_gain=cd.recommended_patch or (
                    "Resolve interaction between contributing risks."
                ),
                estimated_complexity="large",
                dependency_patch_ids=dep_ids,
            )
        )

    # From readiness gaps
    for dim in readiness_report.top_gaps:
        patch_id = f"patch-dim-{dim}"
        if patch_id in seen_ids:
            continue
        seen_ids.add(patch_id)
        items.append(
            PatchItem(
                patch_id=patch_id,
                priority=PatchPriority.P2,
                affected_assets=[dim],
                expected_control_gain=f"Improve '{dim}' dimension readiness score.",
                estimated_complexity="medium",
                dependency_patch_ids=[],
            )
        )

    # Sort by priority: P0 < P1 < P2 < P3 using enum name order
    _priority_order = {PatchPriority.P0: 0, PatchPriority.P1: 1, PatchPriority.P2: 2, PatchPriority.P3: 3}
    items.sort(key=lambda p: _priority_order[p.priority])

    return PatchPlan(plan_id=plan_id, scan_id=danger_map.scan_id, items=items)


# ── Action catalog ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DraftFieldValue:
    """A single inferred field value in a draft ActionContract.

    Attributes:
        value:          The inferred value (may be a string or list).
        evidence_source: How this was obtained.
        confidence_band: Non-None when confidence < 60 % — a list of plausible values.
        source_location: Optional file:line or endpoint reference.
    """

    value: object
    evidence_source: EvidenceSource
    confidence_band: Optional[list[object]] = None
    source_location: Optional[str] = None


@dataclass(frozen=True)
class DraftActionEntry:
    """A draft ActionContract inferred by the scanner from observed endpoints.

    All fields carry a DraftFieldValue with evidence metadata.
    status is always 'draft' — requires human review before runtime use.

    Attributes:
        action_name:         Inferred action name.
        resource_type:       Inferred resource type.
        action_family:       Inferred ActionFamily.
        idempotency_required: Whether idempotency was detected.
        consistency_profile: Inferred consistency profile.
        risk_level:          Inferred risk level.
        compensation_strategy: Inferred compensation strategy.
        retry_class:         Inferred retry class.
        side_effects:        Inferred side effects (empty if none detected).
        source_location:     Where this action was discovered.
        confidence_level:    Overall confidence in this draft entry.
    """

    action_name: DraftFieldValue
    resource_type: DraftFieldValue
    action_family: DraftFieldValue
    idempotency_required: DraftFieldValue
    consistency_profile: DraftFieldValue
    risk_level: DraftFieldValue
    compensation_strategy: DraftFieldValue
    retry_class: DraftFieldValue
    side_effects: DraftFieldValue
    source_location: Optional[str] = None
    confidence_level: ConfidenceLevel = ConfidenceLevel.INFERRED


@dataclass(frozen=True)
class ActionCatalog:
    """Collection of draft ActionEntries inferred by the scanner.

    Attributes:
        catalog_id: Unique identifier for this catalog generation.
        scan_id:    Links to the ReadinessReport.
        entries:    All draft action entries.
    """

    catalog_id: str
    scan_id: str
    entries: list[DraftActionEntry]


def generate_action_catalog(
    catalog_id: str,
    scan_id: str,
    endpoint_observations: list[dict],
) -> ActionCatalog:
    """Generate draft ActionContract entries from endpoint observations.

    Each observation dict may contain:
        action_name       (str)   — overrides inferred name
        resource_type     (str)
        http_method       (str)   — 'GET'|'POST'|'PUT'|'PATCH'|'DELETE'
        path              (str)   — route path
        is_idempotent     (bool)  — True if @idempotent or idempotency_key detected
        consistency       (str)   — declared consistency profile
        risk_level        (str)   — declared or inferred risk
        has_compensation  (bool)  — compensation declared
        has_saga          (bool)  — participates in multi-step saga
        side_effects      (list)  — list of side effect descriptions
        source_location   (str)
        confidence        (str)   — 'confirmed'|'high_confidence'|'inferred'|'heuristic'

    Returns:
        ActionCatalog with one DraftActionEntry per observation.
    """
    entries: list[DraftActionEntry] = []

    _family_from_method = {
        "GET": "read",
        "HEAD": "read",
        "OPTIONS": "read",
        "POST": "mutate",
        "PUT": "mutate",
        "PATCH": "mutate",
        "DELETE": "mutate",
    }
    _risk_from_family = {
        "read": "low",
        "plan": "low",
        "mutate": "moderate",
        "approve": "high",
        "deploy": "critical",
        "compensate": "critical",
        "admin": "high",
    }

    for obs in endpoint_observations:
        src = obs.get("source_location")
        raw_confidence = obs.get("confidence", "inferred")
        confidence_level = ConfidenceLevel(raw_confidence) if raw_confidence in ConfidenceLevel._value2member_map_ else ConfidenceLevel.INFERRED

        http_method = (obs.get("http_method") or "").upper()
        path = obs.get("path", "")

        # Infer action name
        raw_name = obs.get("action_name") or f"{http_method}_{path}".strip("_")
        name_field = DraftFieldValue(
            value=raw_name,
            evidence_source=EvidenceSource.DISCOVERED if "action_name" in obs else EvidenceSource.INFERRED,
            source_location=src,
        )

        # Resource type
        raw_rt = obs.get("resource_type", "unknown")
        rt_evidence = EvidenceSource.DISCOVERED if "resource_type" in obs else EvidenceSource.INFERRED
        rt_field = DraftFieldValue(value=raw_rt, evidence_source=rt_evidence, source_location=src)

        # Action family
        family = _family_from_method.get(http_method, "mutate") if http_method else obs.get("action_family", "mutate")
        family_field = DraftFieldValue(
            value=family,
            evidence_source=EvidenceSource.DISCOVERED if "action_family" in obs else EvidenceSource.INFERRED,
            source_location=src,
        )

        # Idempotency
        is_idempotent: bool = obs.get("is_idempotent", http_method in ("GET", "PUT", "HEAD", "OPTIONS", "DELETE"))
        idempotency_field = DraftFieldValue(
            value=is_idempotent,
            evidence_source=EvidenceSource.DISCOVERED if "is_idempotent" in obs else EvidenceSource.HEURISTIC,
            source_location=src,
        )

        # Consistency profile
        raw_cp = obs.get("consistency", None)
        cp_evidence = EvidenceSource.DISCOVERED if raw_cp else EvidenceSource.INFERRED
        cp_value = raw_cp or ("STRONG" if family in ("mutate", "approve") else "EVENTUAL")
        cp_band = None if raw_cp else ["STRONG", "SESSION_MONOTONIC"]
        cp_field = DraftFieldValue(
            value=cp_value,
            evidence_source=cp_evidence,
            confidence_band=cp_band,
            source_location=src,
        )

        # Risk level
        raw_risk = obs.get("risk_level")
        risk_value = raw_risk or _risk_from_family.get(family, "moderate")
        risk_field = DraftFieldValue(
            value=risk_value,
            evidence_source=EvidenceSource.DISCOVERED if raw_risk else EvidenceSource.INFERRED,
            source_location=src,
        )

        # Compensation strategy
        has_comp = obs.get("has_compensation", False)
        has_saga = obs.get("has_saga", False)
        if has_comp:
            comp_value = "saga_handler"
        elif has_saga:
            comp_value = "saga_handler"
        else:
            comp_value = "none"
        comp_field = DraftFieldValue(
            value=comp_value,
            evidence_source=EvidenceSource.DISCOVERED if ("has_compensation" in obs or "has_saga" in obs) else EvidenceSource.HEURISTIC,
            source_location=src,
        )

        # Retry class
        if not is_idempotent:
            retry_value = "none"
        elif cp_value == "EVENTUAL":
            retry_value = "recheck_then_retry"
        else:
            retry_value = "safe_retry"
        retry_field = DraftFieldValue(
            value=retry_value,
            evidence_source=EvidenceSource.INFERRED,
            source_location=src,
        )

        # Side effects
        raw_se = obs.get("side_effects", [])
        se_field = DraftFieldValue(
            value=raw_se,
            evidence_source=EvidenceSource.DISCOVERED if raw_se else EvidenceSource.HEURISTIC,
            source_location=src,
        )

        entries.append(
            DraftActionEntry(
                action_name=name_field,
                resource_type=rt_field,
                action_family=family_field,
                idempotency_required=idempotency_field,
                consistency_profile=cp_field,
                risk_level=risk_field,
                compensation_strategy=comp_field,
                retry_class=retry_field,
                side_effects=se_field,
                source_location=src,
                confidence_level=confidence_level,
            )
        )

    return ActionCatalog(catalog_id=catalog_id, scan_id=scan_id, entries=entries)
