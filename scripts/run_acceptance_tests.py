#!/usr/bin/env python3
"""
DAWN Orchestrator Acceptance Test Runner

Runs all 5 acceptance tests via the orchestrator and captures evidence.
"""

import sys
import json
import subprocess
from pathlib import Path
import shutil

# Add DAWN to path
BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from dawn.runtime.orchestrator import Orchestrator

PROJECTS_DIR = BASE_DIR / "projects"
LINKS_DIR = BASE_DIR / "dawn" / "links"
PIPELINES_DIR = BASE_DIR / "dawn" / "pipelines"

def cleanup_project(project_id):
    """Remove test project"""
    project_path = PROJECTS_DIR / project_id
    if project_path.exists():
        shutil.rmtree(project_path)

def create_test_inputs(project_id, content="Test content"):
    """Create minimal test inputs"""
    inputs_dir = PROJECTS_DIR / project_id / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    
    (inputs_dir / "idea.md").write_text(f"# Test {project_id}\n{content}\n")
    (inputs_dir / "doc.txt").write_text(f"Documentation for {project_id}\n")

def run_pipeline(project_id, pipeline_path):
    """Run pipeline via orchestrator"""
    orchestrator = Orchestrator(str(LINKS_DIR), str(PROJECTS_DIR))
    try:
        orchestrator.run_pipeline(project_id, pipeline_path)
        return True, None
    except Exception as e:
        return False, str(e)

def test_a_baseline_blocked():
    """Test A: Baseline BLOCKED - no approval exists"""
    print("\n" + "="*60)
    print("Test A: Baseline BLOCKED")
    print("="*60)
    
    project_id = "test_a_baseline"
    cleanup_project(project_id)
    create_test_inputs(project_id)
    
    # Run pipeline (should block)
    success, error = run_pipeline(project_id, str(PIPELINES_DIR / "test_stub.yaml"))
    
    # Verify BLOCKED
    if success:
        print("❌ FAIL: Pipeline should have BLOCKED")
        return False
    
    if "BLOCKED" not in error:
        print(f"❌ FAIL: Expected BLOCKED error, got: {error[:200]}")
        return False
    
    print("✓ Pipeline correctly BLOCKED")
    
    # Verify approval artifact
    approval_path = PROJECTS_DIR / project_id / "artifacts" / "hitl.gate" / "approval.json"
    if not approval_path.exists():
        print(f"❌ FAIL: Approval artifact not found at {approval_path}")
        return False
    
    with open(approval_path) as f:
        approval = json.load(f)
    
    if approval.get("status") != "blocked":
        print(f"❌ FAIL: Expected status=blocked, got {approval.get('status')}")
        return False
    
    print(f"✓ Approval artifact: {approval_path}")
    print(f"  Status: {approval['status']}")
    print(f"  Bundle: {approval['bundle_sha256'][:16]}...")
    
    # Verify template
    template_path = PROJECTS_DIR / project_id / "inputs" / "hitl_approval.json"
    if not template_path.exists():
        print(f"❌ FAIL: Template not found at {template_path}")
        return False
    
    print(f"✓ Template created: {template_path}")
    
    # Verify bundle manifest
    bundle_path = PROJECTS_DIR / project_id / "artifacts" / "ingest.project_bundle" / "dawn.project.bundle.json"
    with open(bundle_path) as f:
        bundle = json.load(f)
    
    print(f"✓ Bundle manifest: {bundle_path}")
    print(f"  Files: {len(bundle['files'])}")
    print(f"  SHA256: {bundle['bundle_sha256']}")
    
    # Verify IR
    ir_path = PROJECTS_DIR / project_id / "artifacts" / "ingest.handoff" / "project_ir.json"
    with open(ir_path) as f:
        ir = json.load(f)
    
    print(f"✓ Project IR: {ir_path}")
    print(f"  Parser: {ir['parser']['id']}")
    print(f"  Confidence: {ir['confidence']['overall']}")
    print(f"  Flags: {ir['confidence']['flags']}")
    
    print("\n✅ Test A PASSED")
    return True, bundle, ir, approval

def test_b_approval_happy():
    """Test B: Approval Happy Path"""
    print("\n" + "="*60)
    print("Test B: Approval Happy Path")
    print("="*60)
    
    project_id = "test_b_approval"
    cleanup_project(project_id)
    create_test_inputs(project_id)
    
    # First run - generate template
    print("Running pipeline (will block)...")
    run_pipeline(project_id, str(PIPELINES_DIR / "test_stub.yaml"))
    
    # Approve
    template_path = PROJECTS_DIR / project_id / "inputs" / "hitl_approval.json"
    with open(template_path) as f:
        template = json.load(f)
    
    template["approved"] = True
    template["operator"] = "test_user"
    template["comment"] = "Approved for testing"
    
    with open(template_path, 'w') as f:
        json.dump(template, f, indent=2)
    
    print("✓ Approval granted")
    
    # Second run - should succeed
    success, error = run_pipeline(project_id, str(PIPELINES_DIR / "test_stub.yaml"))
    
    if not success:
        print(f"❌ FAIL: Pipeline should have succeeded, got: {error}")
        return False
    
    print("✓ Pipeline completed successfully")
    
    # Verify approved status
    approval_path = PROJECTS_DIR / project_id / "artifacts" / "hitl.gate" / "approval.json"
    with open(approval_path) as f:
        approval = json.load(f)
    
    if approval.get("status") != "approved":
        print(f"❌ FAIL: Expected status=approved, got {approval.get('status')}")
        return False
    
    print(f"✓ Approval status: {approval['status']}")
    
    print("\n✅ Test B PASSED")
    return True

def test_c_stale_approval():
    """Test C: Stale approval rejection when inputs change."""
    print("\n" + "="*60)
    print("Test C: Stale Approval Rejection")
    print("="*60)
    
    project_id = "test_c_stale"
    cleanup_project(project_id)
    
    # Create initial inputs
    create_test_inputs(project_id, "Version 1")
    
    # Run 1: Should BLOCK (no approval yet)
    success, error = run_pipeline(project_id, str(PIPELINES_DIR / "test_stub.yaml"))
    if success:
        print("❌ FAIL: Expected BLOCKED on first run")
        return False
    
    # Capture bundle SHA v1 (before approval)
    bundle_v1_path = PROJECTS_DIR / project_id / "artifacts" / "ingest.project_bundle" / "dawn.project.bundle.json"
    with open(bundle_v1_path) as f:
        bundle_v1 = json.load(f)
    bundle_sha_v1 = bundle_v1["bundle_sha256"]
    print(f"pre_bundle_sha={bundle_sha_v1}")
    
    # Grant approval (bound to bundle v1)
    template_path = PROJECTS_DIR / project_id / "inputs" / "hitl_approval.json"
    with open(template_path) as f:
        template = json.load(f)
    
    template["approved"] = True
    template["operator"] = "test_user"
    
    with open(template_path, 'w') as f:
        json.dump(template, f, indent=2)
    
    # Run 2: Should complete (approval granted)
    run_pipeline(project_id, str(PIPELINES_DIR / "test_stub.yaml"))
    print("✓ Bundle v1 approved and completed")
    
    # === MUTATION PHASE ===
    import hashlib
    from uuid import uuid4
    
    inputs_dir = PROJECTS_DIR / project_id / "inputs"
    target_file = inputs_dir / "idea.md"
    
    # Step 2.2: Record pre-mutation state
    file_content_before = target_file.read_text()
    pre_file_sha = hashlib.sha256(file_content_before.encode()).hexdigest()
    print(f"pre_file_sha={pre_file_sha[:16]}...")
    
    # Step 2.3: Mutate with UUID (cannot be no-op)
    mutation_id = uuid4()
    mutated_content = file_content_before + f"\nMUTATION:{mutation_id}\n"
    target_file.write_text(mutated_content, encoding="utf-8")
    
    # Step 2.4: Verify file content changed (hard assertion)
    file_content_after = target_file.read_text()
    post_file_sha = hashlib.sha256(file_content_after.encode()).hexdigest()
    print(f"post_file_sha={post_file_sha[:16]}...")
    
    if pre_file_sha == post_file_sha:
        print(f"❌ DIAGNOSTIC FAIL: File SHA unchanged!")
        print(f"   File: {target_file}")
        print(f"   Pre:  {pre_file_sha}")
        print(f"   Post: {post_file_sha}")
        return False
    
    print("✓ File mutation verified (SHA changed)")
    
    # Step 3: Run pipeline again (should recompute bundle)
    success, error = run_pipeline(project_id, str(PIPELINES_DIR / "test_stub.yaml"))
    
    # Verify bundle SHA changed
    with open(bundle_v1_path) as f:
        bundle_v2 = json.load(f)
    bundle_sha_v2 = bundle_v2["bundle_sha256"]
    print(f"post_bundle_sha={bundle_sha_v2}")
    
    if bundle_sha_v1 == bundle_sha_v2:
        print(f"❌ DIAGNOSTIC FAIL: Bundle SHA unchanged despite file mutation!")
        print(f"   Pre:  {bundle_sha_v1}")
        print(f"   Post: {bundle_sha_v2}")
        print(f"   Mutated file: {target_file}")
        print(f"   Bundle files: {[f['path'] for f in bundle_v2.get('files', [])]}")
        return False
    
    print(f"✓ Bundle SHA changed: {bundle_sha_v1[:16]}... → {bundle_sha_v2[:16]}...")
    
    # Step 4: Verify stale approval was detected
    if success:
        print("❌ FAIL: Pipeline should have rejected stale approval")
        print(f"   Bundle v1: {bundle_sha_v1[:16]}...")
        print(f"   Bundle v2: {bundle_sha_v2[:16]}...")
        return False
    
    if "STALE" not in error.upper():
        print(f"❌ FAIL: Error should mention STALE, got: {error[:200]}")
        return False
    
    print(f"✓ STALE APPROVAL detected (expected)")
    print(f"  Error: {error[:150]}...")
    
    print("\n✅ Test C PASSED")
    return True

def test_d_auto_mode():
    """Test D: AUTO Mode"""
    print("\n" + "="*60)
    print("Test D: AUTO Mode")
    print("="*60)
    
    # D.1: AUTO approve (high confidence, no flags)
    print("\nTest D.1: AUTO approve...")
    project_id = "test_d_auto_approve"
    cleanup_project(project_id)  # Critical: clean state
    create_test_inputs(project_id)
    
    success, error = run_pipeline(project_id, str(PIPELINES_DIR / "test_stub_auto.yaml"))
    
    if not success:
        print(f"❌ FAIL: AUTO should have approved, got: {error}")
        return False
    
    approval_path = PROJECTS_DIR / project_id / "artifacts" / "hitl.gate" / "approval.json"
    with open(approval_path) as f:
        approval = json.load(f)
    
    if approval.get("status") != "approved":
        print(f"❌ FAIL: Expected auto-approved, got {approval.get('status')}")
        return False
    
    print(f"✓ AUTO approved (mode: {approval.get('mode')})")
    print(f"  Confidence: {approval.get('notes', '')}")
    
    # D.2: AUTO block (has flags, require_no_flags=true)
    
    # D.2: AUTO block (has flags, require_no_flags=true)
    print("\nTest D.2: AUTO block due to flags...")
    project_id = "test_d_auto_flags"
    cleanup_project(project_id)
    create_test_inputs(project_id, "High confidence but has flags")
    
    success, error = run_pipeline(project_id, str(PIPELINES_DIR / "test_stub_auto_with_flags.yaml"))
    
    if success:
        print("❌ FAIL: AUTO should have blocked due to flags")
        return False
    
    # Canonical behavior: AUTO + require_no_flags + flags => BLOCKED (HITL required)
    if "BLOCKED" not in (error or "").upper():
        print(f"❌ FAIL: Expected BLOCKED error, got: {error[:200]}")
        return False
    
    # Verify approval artifact exists and is blocked
    approval_path = PROJECTS_DIR / project_id / "artifacts" / "hitl.gate" / "approval.json"
    if not approval_path.exists():
        print(f"❌ FAIL: Approval artifact not found at {approval_path}")
        return False
    
    with open(approval_path) as f:
        approval = json.load(f)
    
    if approval.get("status") != "blocked":
        print(f"❌ FAIL: Expected status=blocked, got {approval.get('status')}")
        return False
    
    # Verify HITL template was generated
    template_path = PROJECTS_DIR / project_id / "inputs" / "hitl_approval.json"
    if not template_path.exists():
        print(f"❌ FAIL: HITL template not found at {template_path}")
        return False
    
    print("✓ AUTO correctly blocked → HITL required (flags present / require_no_flags enforced)")
    
    print("✓ AUTO blocked due to flags (require_no_flags enforced)")
    
    print("\n✅ Test D PASSED")
    return True

def test_e_determinism():
    """Test E: Determinism"""
    print("\n" + "="*60)
    print("Test E: Determinism")
    print("="*60)
    
    # Use SAME project, run twice
    project_id = "test_e_determinism"
    cleanup_project(project_id)
    create_test_inputs(project_id, "Deterministic content for testing")
    
    # Run 1
    print("Run 1...")
    run_pipeline(project_id, str(PIPELINES_DIR / "test_stub.yaml"))
    
    bundle_path = PROJECTS_DIR / project_id / "artifacts" / "ingest.project_bundle" / "dawn.project.bundle.json"
    with open(bundle_path) as f:
        bundle_1 = json.load(f)
    
    sha1 = bundle_1["bundle_sha256"]
    print(f"Run 1: bundle_sha256 = {sha1}")
    
    # Wait briefly to ensure any timestamp-based logic would fail
    import time
    time.sleep(1)
    
    # Run 2 (same project, should skip and rehydrate)
    print("Run 2 (should skip with same digest)...")
    success_2, error_2 = run_pipeline(project_id, str(PIPELINES_DIR / "test_stub.yaml"))
    
    # Load bundle again (should be identical)
    with open(bundle_path) as f:
        bundle_2 = json.load(f)
    
    sha2 = bundle_2["bundle_sha256"]
    print(f"Run 2: bundle_sha256 = {sha2}")
    
    # Verify identical
    if sha1 != sha2:
        print(f"❌ FAIL: bundle_sha256 mismatch!")
        print(f"  Run 1: {sha1}")
        print(f"  Run 2: {sha2}")
        return False
    
    print("✓ Identical bundle_sha256")
    
    # Verify no timestamps in manifest
    bundle_str = json.dumps(bundle_1, indent=2)
    timestamp_keywords = ["timestamp", "created_at", "updated_at", "modified_at", "mtime"]
    found_timestamps = [kw for kw in timestamp_keywords if kw in bundle_str.lower()]
    
    if found_timestamps:
        print(f"❌ FAIL: Bundle contains timestamp keywords: {found_timestamps}")
        return False
    
    print("✓ No timestamps in bundle")
    
    # Verify structural identity
    if bundle_1 != bundle_2:
        print("❌ FAIL: Bundles not structurally identical")
        print("Diff:", json.dumps(bundle_1, indent=2) != json.dumps(bundle_2, indent=2))
        return False
    
    print("✓ Bundles structurally identical")
    
    # Check manifest persistence
    manifest_path = PROJECTS_DIR / project_id / "artifacts" / "ingest.project_bundle" / ".dawn_artifacts.json"
    if manifest_path.exists():
        with open(manifest_path) as f:
            manifest = json.load(f)
        print(f"✓ Artifact manifest persisted: {len(manifest)} artifacts")
    
    print("\n✅ Test E PASSED")
    return True

def main():
    print("="*60)
    print("DAWN Orchestrator Acceptance Test Suite")
    print("="*60)
    
    results = {}
    evidence = {}
    
    # Test A
    try:
        result = test_a_baseline_blocked()
        if isinstance(result, tuple):
            results["A"] = True
            evidence["bundle"], evidence["ir"], evidence["approval_blocked"] = result[1], result[2], result[3]
        else:
            results["A"] = result
    except Exception as e:
        print(f"❌ Test A FAILED with exception: {e}")
        results["A"] = False
    
    # Test B
    try:
        results["B"] = test_b_approval_happy()
    except Exception as e:
        print(f"❌ Test B FAILED with exception: {e}")
        results["B"] = False
    
    # Test C
    try:
        results["C"] = test_c_stale_approval()
    except Exception as e:
        print(f"❌ Test C FAILED with exception: {e}")
        results["C"] = False
    
    # Test D
    try:
        results["D"] = test_d_auto_mode()
    except Exception as e:
        print(f"❌ Test D FAILED with exception: {e}")
        results["D"] = False
    
    # Test E
    try:
        results["E"] = test_e_determinism()
    except Exception as e:
        print(f"❌ Test E FAILED with exception: {e}")
        results["E"] = False
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    for test, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"Test {test}: {status}")
    
    all_passed = all(results.values())
    
    if all_passed:
        print("\n🎉 ALL TESTS PASSED!")
        
        # Save evidence
        evidence_dir = BASE_DIR / "tests" / "acceptance_evidence"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        
        if "bundle" in evidence:
            with open(evidence_dir / "bundle_manifest.json", 'w') as f:
                json.dump(evidence["bundle"], f, indent=2)
        
        if "ir" in evidence:
            with open(evidence_dir / "project_ir.json", 'w') as f:
                json.dump(evidence["ir"], f, indent=2)
        
        if "approval_blocked" in evidence:
            with open(evidence_dir / "approval_blocked.json", 'w') as f:
                json.dump(evidence["approval_blocked"], f, indent=2)
        
        print(f"\nEvidence saved to: {evidence_dir}/")
        return 0
    else:
        print("\n❌ SOME TESTS FAILED")
        return 1

if __name__ == "__main__":
    sys.exit(main())
