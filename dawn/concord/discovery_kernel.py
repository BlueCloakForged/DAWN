"""CONCORD v0.4-beta — ActionDiscovery kernel with CapabilitySet filtering.

Provides:
- is_action_permitted()  — test one ActionContract against a CapabilitySet
- execute_discovery()    — run a filtered ActionDiscoveryQuery against the registry

Normative rules enforced (spec v0.4 §Gap-3):

  Security invariant:
  - Agents MUST NOT discover actions they cannot admit.
  - The CapabilitySet is the authoritative filter; all other criteria are
    additive on top of it.

  CapabilitySet filtering (applied first, before query filters):
  - allowed_action_families: if non-empty, action.action_family.value MUST be
    in this list.  Empty = no family restriction.
  - allowed_resource_types: if non-empty, action.resource_type MUST be in this
    list.  Empty = no resource-type allowlist.
  - restricted_resource_types: action.resource_type MUST NOT appear in this
    list (deny always wins over allow).
  - exclusions: action.action_name MUST NOT appear in this list.
  - required_trust_tier (on ActionContract): if set, the agent's trust tier
    must be >= the required tier.  Tiers are ordered T0 < T1 < T2 < T3 < T4.

  Query filters (applied after CapabilitySet):
  - resource_type: exact match (None = no filter).
  - action_family: exact match (None = no filter).
  - max_results: limit applied after all other filters; total_available reflects
    the pre-truncation count.

  Advisory semantics:
  - ActionDiscoveryResponse is advisory.  Discovery of an action does NOT
    guarantee admission.  Agents must still pass full admission before mutation.
  - filtered_by in the response lists every active filter for transparency.

  Task context:
  - When query.task_context is provided, actions whose description contains any
    word from the context (case-insensitive) are ranked first.  This is a
    simple keyword-match heuristic; a real deployment would use semantic search.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from dawn.concord.contracts_kernel import ContractRegistry
from dawn.concord.types.contracts import (
    ActionContract,
    ActionDiscoveryQuery,
    ActionDiscoveryRecommendation,
    ActionDiscoveryResponse,
    ActionSummary,
)
from dawn.concord.types.entities import CapabilitySet
from dawn.concord.types.enums import TrustTier


# Trust tier ordering — higher index = higher authority.
_TRUST_ORDER: dict[TrustTier, int] = {
    TrustTier.T0_OBSERVE: 0,
    TrustTier.T1_PROPOSE: 1,
    TrustTier.T2_BOUNDED: 2,
    TrustTier.T3_PRIVILEGED: 3,
    TrustTier.T4_GOVERNED_CRITICAL: 4,
}


def is_action_permitted(
    action: ActionContract,
    capability_set: CapabilitySet,
    *,
    agent_trust_tier: Optional[TrustTier] = None,
) -> bool:
    """Return True when *action* is permitted by *capability_set*.

    Applies the following checks in order (first failure returns False):
    1. exclusions — action_name must not appear in capability_set.exclusions.
    2. restricted_resource_types — resource_type must not be restricted.
    3. allowed_resource_types — if non-empty, resource_type must be in the list.
    4. allowed_action_families — if non-empty, family must be in the list.
    5. required_trust_tier — agent must meet or exceed the action's tier requirement.

    Args:
        action:            The ActionContract to evaluate.
        capability_set:    The CapabilitySet owned by the requesting agent.
        agent_trust_tier:  The requesting agent's trust tier.  Required for
                           actions that declare required_trust_tier.  If not
                           provided and the action has a required_trust_tier, the
                           action is denied (safe default).

    Returns:
        True if permitted, False otherwise.
    """
    # 1. Hard exclusion by action name.
    if action.action_name in capability_set.exclusions:
        return False

    # 2. Restricted resource types (deny wins).
    if action.resource_type in capability_set.restricted_resource_types:
        return False

    # 3. Allowlisted resource types (empty = no restriction).
    if capability_set.allowed_resource_types:
        if action.resource_type not in capability_set.allowed_resource_types:
            return False

    # 4. Allowlisted action families (empty = no restriction).
    if capability_set.allowed_action_families:
        if action.action_family.value not in capability_set.allowed_action_families:
            return False

    # 5. Trust tier check.
    if action.required_trust_tier is not None:
        if agent_trust_tier is None:
            return False  # safe default: deny when tier is unspecified
        required_ord = _TRUST_ORDER.get(action.required_trust_tier, 0)
        agent_ord = _TRUST_ORDER.get(agent_trust_tier, 0)
        if agent_ord < required_ord:
            return False

    return True


def _action_to_summary(action: ActionContract) -> ActionSummary:
    """Convert an ActionContract to a lightweight ActionSummary."""
    guard_summary = (
        ", ".join(gp.name for gp in action.guard_predicates)
        if action.guard_predicates
        else "none"
    )
    return ActionSummary(
        action_name=action.action_name,
        resource_type=action.resource_type,
        action_family=action.action_family,
        risk_level=action.risk_level,
        description=action.description,
        guard_summary=guard_summary,
    )


def execute_discovery(
    registry: ContractRegistry,
    *,
    query: ActionDiscoveryQuery,
    capability_set: CapabilitySet,
    agent_trust_tier: Optional[TrustTier] = None,
    catalog_version: str = "1.0",
) -> ActionDiscoveryResponse:
    """Run an ActionDiscovery query against the registry with CapabilitySet filtering.

    Steps:
    1. Collect all registered actions for the queried resource_type (or all types).
    2. Apply CapabilitySet filter (is_action_permitted).
    3. Apply query.resource_type and query.action_family filters.
    4. Apply task_context keyword ranking (if provided).
    5. Truncate to query.max_results; record total_available pre-truncation.
    6. Optionally build a recommendation (highest-confidence permitted action).

    Args:
        registry:          ContractRegistry to query.
        query:             ActionDiscoveryQuery with filters and session context.
        capability_set:    CapabilitySet of the requesting agent.
        agent_trust_tier:  Trust tier of the requesting agent (for tier filtering).
        catalog_version:   Snapshot version label for cache-invalidation.

    Returns:
        Advisory ActionDiscoveryResponse (not authoritative for admission).
    """
    # ── 1. Collect candidate actions ─────────────────────────────────────────
    resource_types: set[str] = registry.registered_resource_types()
    if query.resource_type:
        resource_types = resource_types & {query.resource_type}

    candidates: list[ActionContract] = []
    for rt in sorted(resource_types):
        for action_name in registry.registered_actions(rt):
            try:
                candidates.append(registry.lookup_action(rt, action_name))
            except KeyError:
                pass

    # ── 2. CapabilitySet filter ───────────────────────────────────────────────
    permitted = [
        ac for ac in candidates
        if is_action_permitted(ac, capability_set, agent_trust_tier=agent_trust_tier)
    ]

    # ── 3. Query-level filters ────────────────────────────────────────────────
    if query.action_family is not None:
        permitted = [ac for ac in permitted if ac.action_family == query.action_family]

    # ── 4. Task-context keyword ranking ──────────────────────────────────────
    if query.task_context:
        keywords = {w.lower() for w in query.task_context.split()}

        def _relevance(ac: ActionContract) -> int:
            text = (ac.description + " " + ac.action_name).lower()
            return sum(1 for kw in keywords if kw in text)

        permitted.sort(key=_relevance, reverse=True)

    # ── 5. Record total, then truncate ────────────────────────────────────────
    total_available = len(permitted)
    truncated = permitted[: query.max_results]

    # ── 6. Convert to summaries ───────────────────────────────────────────────
    summaries = [_action_to_summary(ac) for ac in truncated]

    # ── 7. Build filters transparency dict ────────────────────────────────────
    filtered_by: dict = {
        "session_id": query.session_id,
        "capability_set_id": capability_set.id,
    }
    if query.resource_type:
        filtered_by["resource_type"] = query.resource_type
    if query.action_family:
        filtered_by["action_family"] = query.action_family.value
    if query.task_context:
        filtered_by["task_context"] = query.task_context
    filtered_by["max_results"] = query.max_results

    # ── 8. Optional recommendation (first result after sorting) ──────────────
    recommendation: Optional[ActionDiscoveryRecommendation] = None
    if summaries and query.task_context:
        top = summaries[0]
        recommendation = ActionDiscoveryRecommendation(
            action_name=top.action_name,
            rationale=f"Best keyword match for task context '{query.task_context}'.",
            confidence=0.7,
        )

    return ActionDiscoveryResponse(
        available_actions=summaries,
        filtered_by=filtered_by,
        total_available=total_available,
        catalog_version=catalog_version,
        recommendation=recommendation,
    )
