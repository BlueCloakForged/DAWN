"""
Test link: Writes a 20MB file to test BUDGET_OUTPUT_LIMIT enforcement.

Expected behavior:
- With max_output_bytes: 1048576 (1MB), this should fail with BUDGET_OUTPUT_LIMIT
- The failure should be recorded in the ledger with measured vs limit bytes
"""
from pathlib import Path


def run(context, config):
    # Write a 20MB file - should trigger output limit if limit is < 20MB
    file_size_mb = 20
    file_size_bytes = file_size_mb * 1024 * 1024

    print(f"test.large_output: Writing {file_size_mb}MB file...")

    # Get sandbox output path
    sandbox = context["sandbox"]
    output_dir = Path(context["project_root"]) / "artifacts" / "test.large_output"
    output_dir.mkdir(parents=True, exist_ok=True)

    large_file = output_dir / "large_file.bin"

    # Write in chunks to avoid memory issues
    chunk_size = 1024 * 1024  # 1MB chunks
    with open(large_file, "wb") as f:
        for _ in range(file_size_mb):
            f.write(b"X" * chunk_size)

    print(f"test.large_output: Wrote {file_size_bytes} bytes")

    return {
        "status": "SUCCEEDED",
        "metrics": {
            "file_size_bytes": file_size_bytes
        }
    }
