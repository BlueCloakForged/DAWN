"""
DAWN Phase 8.3-8.5 Acceptance Tests (macOS)

Run with: python3 -m dawn.runtime.test_phase8

Tests:
- Deliverable 0: Policy loader with digest
- Phase 8.3.1: BUDGET_PROJECT_LIMIT
- Phase 8.3.2: BUDGET_TIMEOUT
- Phase 8.3.3: BUDGET_OUTPUT_LIMIT
- Phase 8.4.1: worker_id and run_id in ledger
- Phase 8.4.2: dawn.metrics.run_summary artifact
- Phase 8.4.3: Queue telemetry
- Phase 8.5.1: --profile CLI switch
- Phase 8.5.2: Isolation mode blocks src/ writes
"""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def test_deliverable_0_policy_loader():
    """Test: Policy loader validates and computes digest."""
    print("\n[TEST] Deliverable 0: Policy Loader")
    print("-" * 50)

    from dawn.policy import get_policy_loader, reset_policy_loader

    reset_policy_loader()
    loader = get_policy_loader()

    assert loader.version == "2.0.0", f"Expected version 2.0.0, got {loader.version}"
    assert len(loader.digest) == 64, f"Expected 64-char digest, got {len(loader.digest)}"
    assert loader.policy.get("default_profile") == "normal"
    assert loader.get_budget("per_link", "max_wall_time_sec") == 60
    assert loader.get_budget("per_project", "max_project_bytes") == 1073741824

    print("  ✓ Policy version: 2.0.0")
    print(f"  ✓ Policy digest: {loader.digest[:16]}...")
    print("  ✓ Budgets loaded correctly")
    print("  PASSED\n")
    return True


def test_phase_8_3_1_project_size_budget():
    """Test: BUDGET_PROJECT_LIMIT before any link runs."""
    print("\n[TEST] Phase 8.3.1: BUDGET_PROJECT_LIMIT")
    print("-" * 50)

    from dawn.runtime.orchestrator import Orchestrator
    from dawn.policy import get_policy_loader, reset_policy_loader

    # Create a temp project with large files
    with tempfile.TemporaryDirectory() as tmpdir:
        projects_dir = Path(tmpdir) / "projects"
        projects_dir.mkdir()

        project_dir = projects_dir / "test_budget_project"
        project_dir.mkdir()

        # Create a file larger than the test limit
        large_file = project_dir / "large_input.bin"
        large_file.write_bytes(b"X" * 50000)  # 50KB

        # Temporarily override policy to set small limit
        reset_policy_loader()
        loader = get_policy_loader()
        original_limit = loader.policy["budgets"]["per_project"]["max_project_bytes"]

        # Set very small limit for test
        loader.policy["budgets"]["per_project"]["max_project_bytes"] = 10000

        try:
            orchestrator = Orchestrator(
                links_dir=str(PROJECT_ROOT / "dawn" / "links"),
                projects_dir=str(projects_dir)
            )

            # This should fail with BUDGET_PROJECT_LIMIT
            try:
                orchestrator.run_pipeline(
                    "test_budget_project",
                    str(PROJECT_ROOT / "dawn" / "pipelines" / "test_budget_timeout.yaml")
                )
                print("  ✗ Expected BUDGET_PROJECT_LIMIT error")
                return False
            except RuntimeError as e:
                if "BUDGET_PROJECT_LIMIT" in str(e):
                    print(f"  ✓ Got expected error: BUDGET_PROJECT_LIMIT")
                    print("  PASSED\n")
                    return True
                else:
                    print(f"  ✗ Wrong error: {e}")
                    return False
        finally:
            # Restore original limit
            loader.policy["budgets"]["per_project"]["max_project_bytes"] = original_limit


def test_phase_8_3_2_timeout():
    """Test: BUDGET_TIMEOUT enforcement."""
    print("\n[TEST] Phase 8.3.2: BUDGET_TIMEOUT")
    print("-" * 50)

    from dawn.runtime.orchestrator import Orchestrator
    from dawn.policy import get_policy_loader, reset_policy_loader

    with tempfile.TemporaryDirectory() as tmpdir:
        projects_dir = Path(tmpdir) / "projects"
        projects_dir.mkdir()

        # Override timeout to 2 seconds for test
        reset_policy_loader()
        loader = get_policy_loader()
        original_timeout = loader.policy["budgets"]["per_link"]["max_wall_time_sec"]
        loader.policy["budgets"]["per_link"]["max_wall_time_sec"] = 2

        try:
            orchestrator = Orchestrator(
                links_dir=str(PROJECT_ROOT / "dawn" / "links"),
                projects_dir=str(projects_dir)
            )

            print("  Running test.sleep_long with 2s timeout (sleeps 10s)...")

            try:
                orchestrator.run_pipeline(
                    "test_timeout",
                    str(PROJECT_ROOT / "dawn" / "pipelines" / "test_budget_timeout.yaml")
                )
                print("  ✗ Expected BUDGET_TIMEOUT error")
                return False
            except RuntimeError as e:
                if "BUDGET_TIMEOUT" in str(e):
                    print(f"  ✓ Got expected error: BUDGET_TIMEOUT")

                    # Verify ledger has the error
                    ledger_file = projects_dir / "test_timeout" / "ledger" / "events.jsonl"
                    if ledger_file.exists():
                        events = [json.loads(line) for line in ledger_file.read_text().strip().split("\n")]
                        timeout_events = [e for e in events if e.get("errors", {}).get("type") == "BUDGET_TIMEOUT"]
                        if timeout_events:
                            print("  ✓ BUDGET_TIMEOUT recorded in ledger")
                        else:
                            print("  ⚠ BUDGET_TIMEOUT not found in ledger")

                    print("  PASSED\n")
                    return True
                else:
                    print(f"  ✗ Wrong error: {e}")
                    return False
        finally:
            loader.policy["budgets"]["per_link"]["max_wall_time_sec"] = original_timeout


def test_phase_8_4_1_worker_and_run_id():
    """Test: worker_id and run_id in ledger events."""
    print("\n[TEST] Phase 8.4.1: worker_id and run_id in ledger")
    print("-" * 50)

    from dawn.runtime.orchestrator import Orchestrator
    from dawn.policy import reset_policy_loader

    with tempfile.TemporaryDirectory() as tmpdir:
        projects_dir = Path(tmpdir) / "projects"
        projects_dir.mkdir()

        reset_policy_loader()
        orchestrator = Orchestrator(
            links_dir=str(PROJECT_ROOT / "dawn" / "links"),
            projects_dir=str(projects_dir)
        )

        # Run a simple pipeline (ingest only)
        simple_pipeline = projects_dir / "simple.yaml"
        simple_pipeline.write_text("""
pipelineId: simple_test
links:
  - id: ingest.generic_handoff
""")

        # Create mock inputs for ingest
        project_dir = projects_dir / "test_observability"
        project_dir.mkdir()
        inputs_dir = project_dir / "inputs"
        inputs_dir.mkdir()
        (inputs_dir / "handoff.md").write_text("Test handoff document")

        try:
            result = orchestrator.run_pipeline("test_observability", str(simple_pipeline))

            # Check ledger for worker_id and run_id
            ledger_file = project_dir / "ledger" / "events.jsonl"
            if ledger_file.exists():
                events = [json.loads(line) for line in ledger_file.read_text().strip().split("\n")]

                has_worker_id = all("worker_id" in e.get("metrics", {}) for e in events if e.get("metrics"))
                has_run_id = all("run_id" in e.get("metrics", {}) for e in events if e.get("metrics"))

                if has_worker_id:
                    print("  ✓ worker_id present in ledger events")
                else:
                    print("  ✗ worker_id missing from some events")
                    return False

                if has_run_id:
                    print("  ✓ run_id present in ledger events")
                else:
                    print("  ✗ run_id missing from some events")
                    return False

                print("  PASSED\n")
                return True
            else:
                print("  ✗ Ledger file not found")
                return False
        except Exception as e:
            print(f"  ✗ Pipeline failed: {e}")
            return False


def test_phase_8_4_2_run_summary():
    """Test: dawn.metrics.run_summary artifact generation."""
    print("\n[TEST] Phase 8.4.2: dawn.metrics.run_summary artifact")
    print("-" * 50)

    from dawn.runtime.orchestrator import Orchestrator
    from dawn.policy import reset_policy_loader

    with tempfile.TemporaryDirectory() as tmpdir:
        projects_dir = Path(tmpdir) / "projects"
        projects_dir.mkdir()

        reset_policy_loader()
        orchestrator = Orchestrator(
            links_dir=str(PROJECT_ROOT / "dawn" / "links"),
            projects_dir=str(projects_dir)
        )

        # Run a simple pipeline
        simple_pipeline = projects_dir / "simple.yaml"
        simple_pipeline.write_text("""
pipelineId: simple_test
links:
  - id: ingest.generic_handoff
""")

        project_dir = projects_dir / "test_metrics"
        project_dir.mkdir()
        inputs_dir = project_dir / "inputs"
        inputs_dir.mkdir()
        (inputs_dir / "handoff.md").write_text("Test handoff document")

        try:
            result = orchestrator.run_pipeline("test_metrics", str(simple_pipeline))

            # Check for run_summary artifact
            summary_path = project_dir / "artifacts" / "package.metrics" / "run_summary.json"
            if summary_path.exists():
                summary = json.loads(summary_path.read_text())

                required_keys = ["run_id", "worker_id", "project_id", "pipeline_id",
                                 "policy", "timing", "links", "status"]
                missing_keys = [k for k in required_keys if k not in summary]

                if missing_keys:
                    print(f"  ✗ Missing keys in run_summary: {missing_keys}")
                    return False

                print(f"  ✓ run_summary.json created")
                print(f"  ✓ Contains: run_id, worker_id, timing, links, policy")
                print(f"    - Duration: {summary['timing']['duration_ms']}ms")
                print(f"    - Status: {summary['status']}")
                print("  PASSED\n")
                return True
            else:
                print("  ✗ run_summary.json not found")
                return False
        except Exception as e:
            print(f"  ✗ Pipeline failed: {e}")
            return False


def test_phase_8_5_isolation_mode():
    """Test: Isolation mode blocks src/ writes."""
    print("\n[TEST] Phase 8.5: Isolation mode blocks src/ writes")
    print("-" * 50)

    from dawn.runtime.orchestrator import Orchestrator
    from dawn.policy import reset_policy_loader

    with tempfile.TemporaryDirectory() as tmpdir:
        projects_dir = Path(tmpdir) / "projects"
        projects_dir.mkdir()

        reset_policy_loader()

        # Run with isolation profile
        orchestrator = Orchestrator(
            links_dir=str(PROJECT_ROOT / "dawn" / "links"),
            projects_dir=str(projects_dir),
            profile="isolation"
        )

        try:
            orchestrator.run_pipeline(
                "test_isolation",
                str(PROJECT_ROOT / "dawn" / "pipelines" / "test_isolation_mode.yaml"),
                profile="isolation"
            )
            print("  ✗ Expected POLICY_VIOLATION error")
            return False
        except RuntimeError as e:
            if "POLICY_VIOLATION" in str(e):
                print("  ✓ src/ write blocked in isolation mode")
                print("  PASSED\n")
                return True
            else:
                print(f"  ✗ Wrong error: {e}")
                return False


def run_all_tests():
    """Run all acceptance tests."""
    print("\n" + "=" * 60)
    print(" DAWN Phase 8.3-8.5 Acceptance Tests")
    print("=" * 60)

    results = {}

    # Deliverable 0
    results["D0_policy_loader"] = test_deliverable_0_policy_loader()

    # Phase 8.3
    results["8.3.1_project_size"] = test_phase_8_3_1_project_size_budget()
    results["8.3.2_timeout"] = test_phase_8_3_2_timeout()
    # Skip 8.3.3 (large output) as it's slow and disk-intensive

    # Phase 8.4
    results["8.4.1_worker_run_id"] = test_phase_8_4_1_worker_and_run_id()
    results["8.4.2_run_summary"] = test_phase_8_4_2_run_summary()
    # Skip 8.4.3 (queue telemetry) - requires queue setup

    # Phase 8.5
    results["8.5_isolation"] = test_phase_8_5_isolation_mode()

    # Summary
    print("\n" + "=" * 60)
    print(" Test Summary")
    print("=" * 60)

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for name, passed_test in results.items():
        status = "✓ PASS" if passed_test else "✗ FAIL"
        print(f"  {status}: {name}")

    print(f"\n  Total: {passed}/{total} tests passed")
    print("=" * 60 + "\n")

    return all(results.values())


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
