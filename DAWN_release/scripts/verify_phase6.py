import subprocess
import os
import json
from pathlib import Path

def run_cmd(cmd):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result

def verify_phase6():
    print("DAWN Phase 6 Verification")
    print("=" * 60)
    
    # 1. Verify Patch Gating blocks correctly
    print("\n[1/3] Verifying Patch Gating...")
    run_cmd("rm -rf projects/v6_gate_test && mkdir -p projects/v6_gate_test/inputs")
    with open("projects/v6_gate_test/inputs/idea.md", "w") as f: f.write("test")
    
    res = run_cmd("DAWN_STRICT_ARTIFACT_ID=1 PYTHONPATH=. python3 -m dawn.runtime.main --project v6_gate_test --pipeline dawn/pipelines/app_mvp.yaml")
    if "Link gate.patch_approval reported failure: Patch approval required" in res.stdout + res.stderr:
        print("  ✓ PASS: Pipeline halted at gate.patch_approval as expected.")
    else:
        print("  ✗ FAIL: Pipeline did not halt correctly at gate.")
        print(res.stdout + res.stderr)

    # 2. Verify Idempotency
    print("\n[2/3] Verifying Idempotency...")
    # Run twice to ensure signature is recorded then skipped
    run_cmd("rm -rf projects/v6_idem_test && mkdir -p projects/v6_idem_test/inputs")
    with open("projects/v6_idem_test/inputs/human_decision.json", "w") as f: f.write('{"decision":"APPROVED"}')
    with open("projects/v6_idem_test/inputs/idea.md", "w") as f: f.write("test")
    
    # First run (establishes signature)
    run_cmd("PYTHONPATH=. python3 -m dawn.runtime.main --project v6_idem_test --pipeline dawn/pipelines/generic_handoff.yaml")
    # Second run (should skip)
    res = run_cmd("PYTHONPATH=. python3 -m dawn.runtime.main --project v6_idem_test --pipeline dawn/pipelines/generic_handoff.yaml")
    
    if "Skipping link" in res.stdout and "ALREADY_DONE" in res.stdout:
        print("  ✓ PASS: Second run skipped succeeded links.")
    else:
        print("  ✗ FAIL: Idempotency not detected.")
        print(res.stdout)

    # 3. Verify Policy Violation
    print("\n[3/3] Verifying Runtime Policy Enforcement...")
    res = run_cmd("DAWN_STRICT_ARTIFACT_ID=1 PYTHONPATH=. python3 -m dawn.runtime.main --project policy_neg --pipeline dawn/pipelines/test_policy_violation.yaml")
    if "POLICY_VIOLATION" in res.stdout + res.stderr:
        print("  ✓ PASS: Policy violation detected and halted.")
    else:
        print("  ✗ FAIL: Policy violation was NOT detected.")
        print(res.stdout + res.stderr)

    print("\nPhase 6 Verification Complete.")

if __name__ == "__main__":
    verify_phase6()
