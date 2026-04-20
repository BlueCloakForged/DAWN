"""Tests for CONCORD Phase 3 — identity_kernel.py.

Covers:
- TRUST_TIER_ORDER: correct ordering of all 5 tiers
- trust_tier_sufficient(): matrix of tier comparisons
- check_capability(): allowed, denied by family / resource / restriction / trust tier
- requires_human_gate(): gate present / absent
- create_session(): success, trust tier enforcement per mode
- is_session_active(): active, expired status, past expires_at
- expire_session() / terminate_session(): success, terminal rejection
- advance_watermark(): monotonic advancement, no regression
- VALID_INTENT_TRANSITIONS: terminal statuses have no transitions
- IntentJournal.create(): new intent, duplicate rejection, non-PROPOSED rejection
- IntentJournal.transition(): valid path, invalid transition, timestamps set
- IntentJournal.get(): hit, miss
- IntentJournal.list_by_session() / list_by_resource() / list_active()
"""

from datetime import datetime, timedelta, timezone

import pytest

from dawn.concord.identity_kernel import (
    INTENT_TERMINAL_STATUSES,
    TRUST_TIER_ORDER,
    VALID_INTENT_TRANSITIONS,
    CapabilityCheckResult,
    IntentJournal,
    advance_watermark,
    check_capability,
    create_session,
    expire_session,
    is_session_active,
    requires_human_gate,
    terminate_session,
    trust_tier_sufficient,
)
from dawn.concord.types.contracts import ActionContract
from dawn.concord.types.entities import AgentClass, CapabilitySet, Intent, Session
from dawn.concord.types.enums import (
    ActionFamily,
    CompensationStrategy,
    ConflictResolutionStrategy,
    ConsistencyProfile,
    IdempotencyScope,
    IntentStatus,
    RetryClass,
    RiskLevel,
    SessionMode,
    SessionStatus,
    TrustTier,
)


NOW = datetime.now(timezone.utc)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_agent_class(
    id="ac-read",
    trust_tier=TrustTier.T2_BOUNDED,
    capability_set_ids=None,
    prod_allowed=False,
    requires_human_gate_for=None,
) -> AgentClass:
    return AgentClass(
        id=id,
        name=id,
        trust_tier=trust_tier,
        budget_profile_id="bp-default",
        capability_set_ids=capability_set_ids or [],
        requires_human_gate_for=requires_human_gate_for or [],
        prod_allowed=prod_allowed,
    )


def make_capability_set(
    id="cs-cr",
    allowed_action_families=None,
    allowed_resource_types=None,
    restricted_resource_types=None,
) -> CapabilitySet:
    return CapabilitySet(
        id=id,
        allowed_action_families=allowed_action_families or ["read", "mutate"],
        allowed_resource_types=allowed_resource_types or ["change_request"],
        restricted_resource_types=restricted_resource_types or [],
    )


def make_action_contract(
    action_name="update",
    action_family=ActionFamily.MUTATE,
    resource_type="change_request",
    required_trust_tier=None,
    risk_level=RiskLevel.LOW,
) -> ActionContract:
    return ActionContract(
        action_name=action_name,
        description="test action",
        resource_type=resource_type,
        action_family=action_family,
        input_schema_ref="s/in",
        output_schema_ref="s/out",
        required_capabilities=[],
        idempotency_required=True,
        risk_level=risk_level,
        consistency_profile=ConsistencyProfile.STRONG,
        conflict_resolution_strategy=ConflictResolutionStrategy.DEFAULT,
        compensation_strategy=CompensationStrategy.INVERSE_ACTION,
        participates_in_saga=False,
        required_trust_tier=required_trust_tier,
    )


def make_intent(
    id="intent-1",
    session_id="session-1",
    resource_id="cr-1",
    resource_type="change_request",
    action_name="update",
    status=IntentStatus.PROPOSED,
) -> Intent:
    return Intent(
        id=id,
        session_id=session_id,
        resource_type=resource_type,
        resource_id=resource_id,
        action_name=action_name,
        idempotency_key=f"idem-{id}",
        status=status,
        consistency_profile=ConsistencyProfile.STRONG,
        risk_level=RiskLevel.LOW,
        participates_in_saga=False,
        created_at=NOW,
    )


# ── Trust tier ordering ────────────────────────────────────────────────────────


class TestTrustTierOrder:
    def test_five_tiers_in_order(self):
        assert len(TRUST_TIER_ORDER) == 5

    def test_t0_is_lowest(self):
        assert TRUST_TIER_ORDER[0] == TrustTier.T0_OBSERVE

    def test_t4_is_highest(self):
        assert TRUST_TIER_ORDER[-1] == TrustTier.T4_GOVERNED_CRITICAL

    def test_order_is_ascending(self):
        values = [t.value for t in TRUST_TIER_ORDER]
        assert values == sorted(values)


class TestTrustTierSufficient:
    def test_same_tier_is_sufficient(self):
        assert trust_tier_sufficient(TrustTier.T2_BOUNDED, TrustTier.T2_BOUNDED) is True

    def test_higher_tier_is_sufficient(self):
        assert trust_tier_sufficient(TrustTier.T3_PRIVILEGED, TrustTier.T2_BOUNDED) is True

    def test_t4_sufficient_for_all(self):
        for tier in TRUST_TIER_ORDER:
            assert trust_tier_sufficient(TrustTier.T4_GOVERNED_CRITICAL, tier) is True

    def test_lower_tier_is_not_sufficient(self):
        assert trust_tier_sufficient(TrustTier.T1_PROPOSE, TrustTier.T2_BOUNDED) is False

    def test_t0_insufficient_for_all_above(self):
        for tier in TRUST_TIER_ORDER[1:]:
            assert trust_tier_sufficient(TrustTier.T0_OBSERVE, tier) is False

    def test_t0_sufficient_only_for_t0(self):
        assert trust_tier_sufficient(TrustTier.T0_OBSERVE, TrustTier.T0_OBSERVE) is True


# ── Capability check ──────────────────────────────────────────────────────────


class TestCheckCapability:
    def test_allowed_when_all_rules_pass(self):
        ac = make_agent_class()
        cs = make_capability_set()
        contract = make_action_contract()
        result = check_capability(ac, [cs], contract, "change_request")
        assert result.allowed is True
        assert result.error_code is None

    def test_denied_when_family_not_in_any_set(self):
        ac = make_agent_class()
        cs = make_capability_set(allowed_action_families=["read"])  # mutate not included
        contract = make_action_contract(action_family=ActionFamily.MUTATE)
        result = check_capability(ac, [cs], contract, "change_request")
        assert result.allowed is False
        assert result.error_code == "NOT_AUTHORIZED_FOR_AGENT_CLASS"
        assert "action_family" in result.reason

    def test_allowed_when_family_in_second_set(self):
        ac = make_agent_class()
        cs1 = make_capability_set(id="cs1", allowed_action_families=["read"])
        cs2 = make_capability_set(id="cs2", allowed_action_families=["mutate"])
        contract = make_action_contract(action_family=ActionFamily.MUTATE)
        result = check_capability(ac, [cs1, cs2], contract, "change_request")
        assert result.allowed is True

    def test_denied_when_resource_type_restricted(self):
        ac = make_agent_class()
        cs = make_capability_set(restricted_resource_types=["change_request"])
        contract = make_action_contract()
        result = check_capability(ac, [cs], contract, "change_request")
        assert result.allowed is False
        assert result.error_code == "NOT_AUTHORIZED_FOR_AGENT_CLASS"
        assert "restricted" in result.reason

    def test_restriction_overrides_allow(self):
        ac = make_agent_class()
        cs = make_capability_set(
            allowed_resource_types=["change_request"],
            restricted_resource_types=["change_request"],
        )
        contract = make_action_contract()
        result = check_capability(ac, [cs], contract, "change_request")
        assert result.allowed is False

    def test_denied_when_resource_type_not_in_allowlist(self):
        ac = make_agent_class()
        cs = make_capability_set(allowed_resource_types=["deployment"])
        contract = make_action_contract()
        result = check_capability(ac, [cs], contract, "change_request")
        assert result.allowed is False
        assert "allowed_resource_types" in result.reason

    def test_allowed_when_resource_allowlist_empty(self):
        # Empty allowed_resource_types = no per-resource restriction
        ac = make_agent_class()
        cs = make_capability_set(allowed_resource_types=[])
        contract = make_action_contract()
        result = check_capability(ac, [cs], contract, "change_request")
        assert result.allowed is True

    def test_denied_when_trust_tier_insufficient(self):
        ac = make_agent_class(trust_tier=TrustTier.T1_PROPOSE)
        cs = make_capability_set()
        contract = make_action_contract(required_trust_tier=TrustTier.T3_PRIVILEGED)
        result = check_capability(ac, [cs], contract, "change_request")
        assert result.allowed is False
        assert "trust_tier" in result.reason

    def test_allowed_when_trust_tier_exactly_meets_requirement(self):
        ac = make_agent_class(trust_tier=TrustTier.T3_PRIVILEGED)
        cs = make_capability_set()
        contract = make_action_contract(required_trust_tier=TrustTier.T3_PRIVILEGED)
        result = check_capability(ac, [cs], contract, "change_request")
        assert result.allowed is True

    def test_allowed_when_no_required_trust_tier(self):
        ac = make_agent_class(trust_tier=TrustTier.T0_OBSERVE)
        cs = make_capability_set()
        contract = make_action_contract(required_trust_tier=None)
        result = check_capability(ac, [cs], contract, "change_request")
        assert result.allowed is True

    def test_returns_capability_check_result(self):
        ac = make_agent_class()
        cs = make_capability_set()
        result = check_capability(ac, [cs], make_action_contract(), "change_request")
        assert isinstance(result, CapabilityCheckResult)

    def test_denied_with_empty_capability_sets(self):
        ac = make_agent_class()
        contract = make_action_contract()
        result = check_capability(ac, [], contract, "change_request")
        assert result.allowed is False


# ── requires_human_gate ───────────────────────────────────────────────────────


class TestRequiresHumanGate:
    def test_gate_required_for_listed_action(self):
        ac = make_agent_class(requires_human_gate_for=["deploy", "approve"])
        assert requires_human_gate(ac, "deploy") is True

    def test_gate_not_required_for_unlisted_action(self):
        ac = make_agent_class(requires_human_gate_for=["deploy"])
        assert requires_human_gate(ac, "update") is False

    def test_gate_not_required_when_list_empty(self):
        ac = make_agent_class(requires_human_gate_for=[])
        assert requires_human_gate(ac, "approve") is False


# ── Session lifecycle ─────────────────────────────────────────────────────────


class TestCreateSession:
    def test_creates_active_session(self):
        ac = make_agent_class(trust_tier=TrustTier.T2_BOUNDED)
        s = create_session(
            id="s-1", agent_id="agent-1", agent_class=ac,
            mode=SessionMode.EXECUTE, budget_profile_id="bp-1",
        )
        assert isinstance(s, Session)
        assert s.status == SessionStatus.ACTIVE
        assert s.watermark == 0

    def test_session_fields_populated(self):
        ac = make_agent_class(trust_tier=TrustTier.T2_BOUNDED)
        s = create_session(
            id="s-1", agent_id="agent-42", agent_class=ac,
            mode=SessionMode.EXECUTE, budget_profile_id="bp-1",
            task_id="task-99",
        )
        assert s.id == "s-1"
        assert s.agent_id == "agent-42"
        assert s.agent_class_id == ac.id
        assert s.trust_tier == TrustTier.T2_BOUNDED
        assert s.task_id == "task-99"

    def test_read_only_allowed_at_t0(self):
        ac = make_agent_class(trust_tier=TrustTier.T0_OBSERVE)
        s = create_session(
            id="s-1", agent_id="a", agent_class=ac,
            mode=SessionMode.READ_ONLY, budget_profile_id="bp-1",
        )
        assert s.status == SessionStatus.ACTIVE

    def test_propose_only_allowed_at_t1(self):
        ac = make_agent_class(trust_tier=TrustTier.T1_PROPOSE)
        s = create_session(
            id="s-1", agent_id="a", agent_class=ac,
            mode=SessionMode.PROPOSE_ONLY, budget_profile_id="bp-1",
        )
        assert s.status == SessionStatus.ACTIVE

    def test_execute_mode_requires_t2(self):
        ac = make_agent_class(trust_tier=TrustTier.T1_PROPOSE)
        with pytest.raises(ValueError, match="execute"):
            create_session(
                id="s-1", agent_id="a", agent_class=ac,
                mode=SessionMode.EXECUTE, budget_profile_id="bp-1",
            )

    def test_execute_mode_allowed_at_t2(self):
        ac = make_agent_class(trust_tier=TrustTier.T2_BOUNDED)
        s = create_session(
            id="s-1", agent_id="a", agent_class=ac,
            mode=SessionMode.EXECUTE, budget_profile_id="bp-1",
        )
        assert s.mode == SessionMode.EXECUTE

    def test_supervised_mode_requires_t1(self):
        ac = make_agent_class(trust_tier=TrustTier.T0_OBSERVE)
        with pytest.raises(ValueError, match="supervised"):
            create_session(
                id="s-1", agent_id="a", agent_class=ac,
                mode=SessionMode.SUPERVISED, budget_profile_id="bp-1",
            )

    def test_optional_fleet_and_env_id(self):
        ac = make_agent_class()
        s = create_session(
            id="s-1", agent_id="a", agent_class=ac,
            mode=SessionMode.EXECUTE, budget_profile_id="bp-1",
            environment_id="env-99", fleet_id="fleet-42",
        )
        assert s.environment_id == "env-99"
        assert s.fleet_id == "fleet-42"


class TestSessionActiveCheck:
    def test_active_session_is_active(self):
        ac = make_agent_class()
        s = create_session(
            id="s-1", agent_id="a", agent_class=ac,
            mode=SessionMode.EXECUTE, budget_profile_id="bp-1",
        )
        assert is_session_active(s) is True

    def test_expired_status_is_not_active(self):
        ac = make_agent_class()
        s = create_session(
            id="s-1", agent_id="a", agent_class=ac,
            mode=SessionMode.EXECUTE, budget_profile_id="bp-1",
        )
        s = expire_session(s)
        assert is_session_active(s) is False

    def test_terminated_status_is_not_active(self):
        ac = make_agent_class()
        s = create_session(
            id="s-1", agent_id="a", agent_class=ac,
            mode=SessionMode.EXECUTE, budget_profile_id="bp-1",
        )
        s = terminate_session(s)
        assert is_session_active(s) is False

    def test_past_expires_at_is_not_active(self):
        ac = make_agent_class()
        past = datetime.now(timezone.utc) - timedelta(seconds=1)
        s = create_session(
            id="s-1", agent_id="a", agent_class=ac,
            mode=SessionMode.EXECUTE, budget_profile_id="bp-1",
            expires_at=past,
        )
        assert is_session_active(s) is False

    def test_future_expires_at_is_active(self):
        ac = make_agent_class()
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        s = create_session(
            id="s-1", agent_id="a", agent_class=ac,
            mode=SessionMode.EXECUTE, budget_profile_id="bp-1",
            expires_at=future,
        )
        assert is_session_active(s) is True


class TestSessionTransitions:
    def setup_method(self):
        ac = make_agent_class()
        self.session = create_session(
            id="s-1", agent_id="a", agent_class=ac,
            mode=SessionMode.EXECUTE, budget_profile_id="bp-1",
        )

    def test_expire_returns_expired_session(self):
        s = expire_session(self.session)
        assert s.status == SessionStatus.EXPIRED
        assert s.id == "s-1"  # id preserved

    def test_terminate_returns_terminated_session(self):
        s = terminate_session(self.session)
        assert s.status == SessionStatus.TERMINATED

    def test_expire_already_expired_raises(self):
        s = expire_session(self.session)
        with pytest.raises(ValueError, match="terminal"):
            expire_session(s)

    def test_terminate_already_terminated_raises(self):
        s = terminate_session(self.session)
        with pytest.raises(ValueError, match="terminal"):
            terminate_session(s)

    def test_expire_then_terminate_raises(self):
        s = expire_session(self.session)
        with pytest.raises(ValueError, match="terminal"):
            terminate_session(s)

    def test_original_session_unchanged(self):
        expire_session(self.session)
        assert self.session.status == SessionStatus.ACTIVE


class TestAdvanceWatermark:
    def setup_method(self):
        ac = make_agent_class()
        self.session = create_session(
            id="s-1", agent_id="a", agent_class=ac,
            mode=SessionMode.EXECUTE, budget_profile_id="bp-1",
        )

    def test_advances_to_higher_version(self):
        s = advance_watermark(self.session, 5)
        assert s.watermark == 5

    def test_no_regression_below_current(self):
        s = advance_watermark(self.session, 10)
        s2 = advance_watermark(s, 3)
        assert s2.watermark == 10

    def test_same_version_no_change(self):
        s = advance_watermark(self.session, 0)
        assert s is self.session  # same object returned when no change

    def test_sequential_advances(self):
        s = advance_watermark(self.session, 1)
        s = advance_watermark(s, 3)
        s = advance_watermark(s, 2)  # regression — ignored
        assert s.watermark == 3

    def test_original_unchanged(self):
        advance_watermark(self.session, 10)
        assert self.session.watermark == 0


# ── Intent status machine ─────────────────────────────────────────────────────


class TestIntentTransitions:
    def test_all_statuses_have_transition_entry(self):
        for status in IntentStatus:
            assert status in VALID_INTENT_TRANSITIONS

    def test_terminal_statuses_have_no_outbound(self):
        for status in INTENT_TERMINAL_STATUSES:
            assert VALID_INTENT_TRANSITIONS[status] == frozenset()

    def test_proposed_can_reach_admitted(self):
        assert IntentStatus.ADMITTED in VALID_INTENT_TRANSITIONS[IntentStatus.PROPOSED]

    def test_executing_can_reach_committed(self):
        assert IntentStatus.COMMITTED in VALID_INTENT_TRANSITIONS[IntentStatus.EXECUTING]

    def test_proposed_cannot_jump_to_committed(self):
        assert IntentStatus.COMMITTED not in VALID_INTENT_TRANSITIONS[IntentStatus.PROPOSED]

    def test_committed_is_terminal(self):
        assert IntentStatus.COMMITTED in INTENT_TERMINAL_STATUSES

    def test_compensated_is_terminal(self):
        assert IntentStatus.COMPENSATED in INTENT_TERMINAL_STATUSES

    def test_failed_is_terminal(self):
        assert IntentStatus.FAILED in INTENT_TERMINAL_STATUSES

    def test_expired_is_terminal(self):
        assert IntentStatus.EXPIRED in INTENT_TERMINAL_STATUSES


# ── IntentJournal ─────────────────────────────────────────────────────────────


class TestIntentJournalCreate:
    def test_create_returns_intent(self):
        journal = IntentJournal()
        intent = make_intent()
        result = journal.create(intent)
        assert isinstance(result, Intent)
        assert result.id == "intent-1"

    def test_create_increments_len(self):
        journal = IntentJournal()
        journal.create(make_intent())
        assert len(journal) == 1

    def test_create_duplicate_raises(self):
        journal = IntentJournal()
        intent = make_intent()
        journal.create(intent)
        with pytest.raises(ValueError, match="already exists"):
            journal.create(intent)

    def test_create_non_proposed_raises(self):
        journal = IntentJournal()
        intent = make_intent(status=IntentStatus.ADMITTED)
        with pytest.raises(ValueError, match="PROPOSED"):
            journal.create(intent)

    def test_returned_is_copy(self):
        journal = IntentJournal()
        intent = make_intent()
        result = journal.create(intent)
        assert result is not intent

    def test_original_not_stored_by_reference(self):
        journal = IntentJournal()
        intent = make_intent()
        journal.create(intent)
        # Mutating original should not affect journal
        intent.idempotency_key = "tampered"
        fetched = journal.get("intent-1")
        assert fetched.idempotency_key != "tampered"


class TestIntentJournalTransition:
    def setup_method(self):
        self.journal = IntentJournal()
        self.journal.create(make_intent())

    def test_valid_transition_proposed_to_admitted(self):
        updated = self.journal.transition("intent-1", IntentStatus.ADMITTED)
        assert updated.status == IntentStatus.ADMITTED

    def test_admitted_at_set_on_first_admission(self):
        updated = self.journal.transition("intent-1", IntentStatus.ADMITTED)
        assert updated.admitted_at is not None

    def test_executed_at_set_on_executing(self):
        self.journal.transition("intent-1", IntentStatus.ADMITTED)
        updated = self.journal.transition("intent-1", IntentStatus.EXECUTING)
        assert updated.executed_at is not None

    def test_full_happy_path(self):
        j = self.journal
        j.transition("intent-1", IntentStatus.ADMITTED)
        j.transition("intent-1", IntentStatus.EXECUTING)
        result = j.transition("intent-1", IntentStatus.COMMITTED)
        assert result.status == IntentStatus.COMMITTED

    def test_invalid_transition_raises(self):
        with pytest.raises(ValueError, match="proposed.*committed"):
            self.journal.transition("intent-1", IntentStatus.COMMITTED)

    def test_transition_from_terminal_raises(self):
        self.journal.transition("intent-1", IntentStatus.FAILED)
        with pytest.raises(ValueError, match="terminal"):
            self.journal.transition("intent-1", IntentStatus.ADMITTED)

    def test_missing_intent_raises_key_error(self):
        with pytest.raises(KeyError, match="ghost"):
            self.journal.transition("ghost", IntentStatus.ADMITTED)

    def test_transition_returns_copy(self):
        r1 = self.journal.transition("intent-1", IntentStatus.ADMITTED)
        r2 = self.journal.get("intent-1")
        assert r1 is not r2
        assert r1.status == r2.status

    def test_queued_path(self):
        self.journal.transition("intent-1", IntentStatus.ADMITTED)
        self.journal.transition("intent-1", IntentStatus.QUEUED)
        result = self.journal.transition("intent-1", IntentStatus.ADMITTED)
        assert result.status == IntentStatus.ADMITTED

    def test_blocked_path(self):
        self.journal.transition("intent-1", IntentStatus.ADMITTED)
        result = self.journal.transition("intent-1", IntentStatus.BLOCKED)
        assert result.status == IntentStatus.BLOCKED

    def test_compensated_path(self):
        self.journal.transition("intent-1", IntentStatus.ADMITTED)
        self.journal.transition("intent-1", IntentStatus.EXECUTING)
        result = self.journal.transition("intent-1", IntentStatus.COMPENSATED)
        assert result.status == IntentStatus.COMPENSATED


class TestIntentJournalGet:
    def test_get_existing(self):
        journal = IntentJournal()
        journal.create(make_intent())
        result = journal.get("intent-1")
        assert result.id == "intent-1"

    def test_get_missing_raises(self):
        journal = IntentJournal()
        with pytest.raises(KeyError, match="ghost"):
            journal.get("ghost")

    def test_get_returns_copy(self):
        journal = IntentJournal()
        journal.create(make_intent())
        r1 = journal.get("intent-1")
        r2 = journal.get("intent-1")
        assert r1 is not r2


class TestIntentJournalListMethods:
    def setup_method(self):
        self.journal = IntentJournal()
        self.journal.create(make_intent(id="i1", session_id="s1", resource_id="cr-1"))
        self.journal.create(make_intent(id="i2", session_id="s1", resource_id="cr-2"))
        self.journal.create(make_intent(id="i3", session_id="s2", resource_id="cr-1"))

    def test_list_by_session_returns_correct_intents(self):
        results = self.journal.list_by_session("s1")
        assert {i.id for i in results} == {"i1", "i2"}

    def test_list_by_session_empty_for_unknown(self):
        assert self.journal.list_by_session("s999") == []

    def test_list_by_resource_returns_correct_intents(self):
        results = self.journal.list_by_resource("cr-1")
        assert {i.id for i in results} == {"i1", "i3"}

    def test_list_by_resource_empty_for_unknown(self):
        assert self.journal.list_by_resource("cr-999") == []

    def test_list_active_excludes_terminal(self):
        self.journal.transition("i1", IntentStatus.ADMITTED)
        self.journal.transition("i1", IntentStatus.FAILED)
        active = self.journal.list_active("s1")
        ids = {i.id for i in active}
        assert "i1" not in ids
        assert "i2" in ids

    def test_list_active_includes_non_terminal(self):
        self.journal.transition("i1", IntentStatus.ADMITTED)
        active = self.journal.list_active("s1")
        ids = {i.id for i in active}
        assert "i1" in ids

    def test_list_active_empty_when_all_terminal(self):
        self.journal.transition("i1", IntentStatus.FAILED)
        self.journal.transition("i2", IntentStatus.EXPIRED)
        active = self.journal.list_active("s1")
        assert active == []
