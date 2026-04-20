"""
Test link: Attempts to write to src/ directory.

Expected behavior:
- In normal mode with allow_src_writes whitelist: Should fail with POLICY_VIOLATION
  (this link is not in the whitelist)
- In isolation mode: Should fail with POLICY_VIOLATION
  (all src/ writes blocked regardless of whitelist)
"""
from pathlib import Path


def run(context, config):
    project_root = Path(context["project_root"])
    src_dir = project_root / "src"
    src_dir.mkdir(parents=True, exist_ok=True)

    # Attempt to write to src/
    test_file = src_dir / "isolation_test.txt"

    print(f"test.src_write_isolation: Attempting to write to {test_file}...")

    with open(test_file, "w") as f:
        f.write("This write should be blocked in isolation mode.")

    print("test.src_write_isolation: Write succeeded (unexpected in isolation mode)")

    # Also write the expected artifact
    context["sandbox"].write_json("isolation_result.json", {
        "wrote_to_src": True,
        "status": "completed"
    })

    return {"status": "SUCCEEDED"}
