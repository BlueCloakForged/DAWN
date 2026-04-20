"""
DAWN Phase 9 Acceptance Tests

Run with: python3 -m dawn.runtime.test_phase9

Tests:
- Phase 9.1: Retry policy with backoff rules
- Phase 9.2: Artifact retention and pruning
- Phase 9.3: Reproducibility lockfile
- Phase 9.4: Release verification
- Phase 9.5: Documentation exists
"""

import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def test_phase_9_1_retry_policy():
    """Test: Retry policy configuration and backoff rules."""
    print("\n[TEST] Phase 9.1: Retry Policy")
    print("-" * 50)

    from dawn.policy import get_policy_loader, reset_policy_loader

    reset_policy_loader()
    loader = get_policy_loader()

    # Test retry config exists
    retry_config = loader.get_retry_config()
    assert retry_config, "Retry config should exist"
    print("  ✓ Retry config loaded")

    # Test max retries
    max_link = loader.get_max_retries_per_link()
    max_project = loader.get_max_retries_per_project()
    assert max_link == 3, f"Expected max_retries_per_link=3, got {max_link}"
    assert max_project == 10, f"Expected max_retries_per_project=10, got {max_project}"
    print(f"  ✓ Max retries: link={max_link}, project={max_project}")

    # Test backoff schedule
    delay0 = loader.get_backoff_delay(0)
    delay1 = loader.get_backoff_delay(1)
    delay2 = loader.get_backoff_delay(2)
    assert delay0 == 1, f"Expected backoff[0]=1, got {delay0}"
    assert delay1 == 5, f"Expected backoff[1]=5, got {delay1}"
    assert delay2 == 30, f"Expected backoff[2]=30, got {delay2}"
    print(f"  ✓ Backoff schedule: {delay0}s, {delay1}s, {delay2}s")

    # Test retryable errors
    assert loader.is_error_retryable("BUDGET_TIMEOUT"), "BUDGET_TIMEOUT should be retryable"
    assert loader.is_error_retryable("RUNTIME_ERROR"), "RUNTIME_ERROR should be retryable"
    assert not loader.is_error_retryable("POLICY_VIOLATION"), "POLICY_VIOLATION should not be retryable"
    assert not loader.is_error_retryable("CONTRACT_VIOLATION"), "CONTRACT_VIOLATION should not be retryable"
    print("  ✓ Retryable error detection works")

    print("  PASSED\n")
    return True


def test_phase_9_2_retention_policy():
    """Test: Artifact retention configuration and pruning tool."""
    print("\n[TEST] Phase 9.2: Artifact Retention")
    print("-" * 50)

    from dawn.policy import get_policy_loader, reset_policy_loader
    from dawn.runtime.prune import ArtifactPruner, PruningReport

    reset_policy_loader()
    loader = get_policy_loader()

    # Test retention config exists
    retention_config = loader.get_retention_config()
    assert retention_config, "Retention config should exist"
    print("  ✓ Retention config loaded")

    # Test retention values
    keep_n = loader.get_keep_last_n_runs()
    assert keep_n == 3, f"Expected keep_last_n_runs=3, got {keep_n}"
    print(f"  ✓ Keep last {keep_n} runs")

    keep_failed_days = loader.get_keep_failed_runs_days()
    assert keep_failed_days == 7, f"Expected 7 days, got {keep_failed_days}"
    print(f"  ✓ Keep failed runs for {keep_failed_days} days")

    # Test protected artifacts
    protected = loader.get_protected_artifacts()
    assert "dawn.evidence.pack" in protected
    assert "dawn.release.bundle" in protected
    print(f"  ✓ Protected artifacts: {len(protected)}")

    # Test pruner dry run
    with tempfile.TemporaryDirectory() as tmpdir:
        projects_dir = Path(tmpdir) / "projects"
        projects_dir.mkdir()

        # Create a dummy project
        project_dir = projects_dir / "test_prune"
        project_dir.mkdir()
        (project_dir / "artifact_index.json").write_text("{}")
        (project_dir / "ledger").mkdir()
        (project_dir / "ledger" / "events.jsonl").write_text("")

        pruner = ArtifactPruner(str(projects_dir))
        report = pruner.prune_project("test_prune", dry_run=True)

        assert isinstance(report, PruningReport)
        print("  ✓ Pruner dry run works")

    print("  PASSED\n")
    return True


def test_phase_9_3_lockfile():
    """Test: Reproducibility lockfile generation and verification."""
    print("\n[TEST] Phase 9.3: Reproducibility Lockfile")
    print("-" * 50)

    from dawn.runtime.lockfile import LockfileGenerator, LockfileVerifier

    with tempfile.TemporaryDirectory() as tmpdir:
        projects_dir = Path(tmpdir) / "projects"
        projects_dir.mkdir()

        # Create a minimal project
        project_dir = projects_dir / "test_lockfile"
        project_dir.mkdir()
        (project_dir / "artifact_index.json").write_text('{"test.artifact": {"path": "/tmp/test", "digest": "abc123", "link_id": "test.link"}}')

        # Create pipeline.yaml
        pipeline_content = """
pipelineId: test_pipeline
links:
  - id: ingest.generic_handoff
"""
        (project_dir / "pipeline.yaml").write_text(pipeline_content)

        # Generate lockfile
        generator = LockfileGenerator(str(projects_dir), str(PROJECT_ROOT / "dawn" / "links"))
        lockfile = generator.generate("test_lockfile")

        assert "lockfile_version" in lockfile
        assert "policy" in lockfile
        assert "pipeline" in lockfile
        assert "environment" in lockfile
        print("  ✓ Lockfile generated with required fields")

        # Check policy digest
        assert lockfile["policy"]["digest"]
        assert len(lockfile["policy"]["digest"]) == 64
        print(f"  ✓ Policy digest: {lockfile['policy']['digest'][:16]}...")

        # Check environment
        assert "python_version" in lockfile["environment"]
        assert "platform" in lockfile["environment"]
        print(f"  ✓ Environment captured")

        # Save and verify
        path = generator.save("test_lockfile", lockfile)
        assert path.exists()
        print(f"  ✓ Lockfile saved to {path.name}")

        # Verify
        verifier = LockfileVerifier(str(projects_dir), str(PROJECT_ROOT / "dawn" / "links"))
        result = verifier.verify("test_lockfile")
        # Note: Will have mismatches because we didn't run a real pipeline
        assert "verified" in result
        print("  ✓ Verification runs without error")

    print("  PASSED\n")
    return True


def test_phase_9_4_release_verification():
    """Test: Release verification command."""
    print("\n[TEST] Phase 9.4: Release Verification")
    print("-" * 50)

    from dawn.runtime.verify_release import ReleaseVerifier

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a test release ZIP
        release_dir = Path(tmpdir) / "release"
        release_dir.mkdir()

        # Create files
        (release_dir / "file1.txt").write_text("Hello World")
        (release_dir / "file2.json").write_text('{"test": true}')

        # Create manifest
        import hashlib
        file1_digest = hashlib.sha256(b"Hello World").hexdigest()
        file2_digest = hashlib.sha256(b'{"test": true}').hexdigest()

        manifest = {
            "version": "1.0.0",
            "files": {
                "file1.txt": {"digest": file1_digest},
                "file2.json": {"digest": file2_digest}
            }
        }
        (release_dir / "manifest.json").write_text(json.dumps(manifest))

        # Create ZIP
        zip_path = Path(tmpdir) / "release.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            for f in release_dir.iterdir():
                zf.write(f, f.name)

        # Verify valid release
        verifier = ReleaseVerifier()
        result = verifier.verify(str(zip_path))

        assert result["verified"], f"Expected verified=True, got errors: {result.get('errors')}"
        print("  ✓ Valid release verified successfully")

        # Test tampered release
        tampered_dir = Path(tmpdir) / "tampered"
        tampered_dir.mkdir()
        (tampered_dir / "file1.txt").write_text("Tampered!")
        (tampered_dir / "file2.json").write_text('{"test": true}')
        (tampered_dir / "manifest.json").write_text(json.dumps(manifest))

        tampered_zip = Path(tmpdir) / "tampered.zip"
        with zipfile.ZipFile(tampered_zip, "w") as zf:
            for f in tampered_dir.iterdir():
                zf.write(f, f.name)

        verifier2 = ReleaseVerifier()
        result2 = verifier2.verify(str(tampered_zip))

        assert not result2["verified"], "Tampered release should fail verification"
        assert any(e["type"] == "DIGEST_MISMATCH" for e in result2["errors"])
        print("  ✓ Tampered release detected correctly")

    print("  PASSED\n")
    return True


def test_phase_9_5_documentation():
    """Test: Documentation files exist."""
    print("\n[TEST] Phase 9.5: Documentation")
    print("-" * 50)

    docs_dir = PROJECT_ROOT / "docs"

    # Check operator guide
    operator_guide = docs_dir / "OPERATOR_GUIDE.md"
    assert operator_guide.exists(), f"Missing: {operator_guide}"
    content = operator_guide.read_text()
    assert "Quick Start" in content
    assert "Prerequisites" in content
    print("  ✓ OPERATOR_GUIDE.md exists with required sections")

    # Check agent protocol
    agent_protocol = docs_dir / "AGENT_PROTOCOL.md"
    assert agent_protocol.exists(), f"Missing: {agent_protocol}"
    content = agent_protocol.read_text()
    assert "Agent Interface" in content
    assert "JSON Input Format" in content
    print("  ✓ AGENT_PROTOCOL.md exists with required sections")

    # Check JSON schema
    schema_file = PROJECT_ROOT / "dawn" / "schemas" / "agent_protocol.json"
    assert schema_file.exists(), f"Missing: {schema_file}"
    schema = json.loads(schema_file.read_text())
    assert "definitions" in schema
    assert "link_context" in schema["definitions"]
    assert "link_result" in schema["definitions"]
    print("  ✓ agent_protocol.json schema exists")

    print("  PASSED\n")
    return True


def run_all_tests():
    """Run all Phase 9 acceptance tests."""
    print("\n" + "=" * 60)
    print(" DAWN Phase 9 Acceptance Tests")
    print("=" * 60)

    results = {}

    results["9.1_retry_policy"] = test_phase_9_1_retry_policy()
    results["9.2_retention"] = test_phase_9_2_retention_policy()
    results["9.3_lockfile"] = test_phase_9_3_lockfile()
    results["9.4_verify_release"] = test_phase_9_4_release_verification()
    results["9.5_documentation"] = test_phase_9_5_documentation()

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
