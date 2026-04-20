"""
Test link: Sleeps for 10 seconds to test BUDGET_TIMEOUT enforcement.

Expected behavior:
- With max_wall_time_sec: 2, this should fail with BUDGET_TIMEOUT
- The project lock should be cleanly released after timeout
"""
import time


def run(context, config):
    # Sleep for 10 seconds - should trigger timeout if limit is < 10s
    sleep_duration = 10

    print(f"test.sleep_long: Sleeping for {sleep_duration} seconds...", flush=True)
    time.sleep(sleep_duration)
    print("test.sleep_long: Sleep completed (should not reach here if timeout works)", flush=True)

    context["sandbox"].write_json("sleep_result.json", {
        "slept_for_seconds": sleep_duration,
        "status": "completed"
    })

    # Added for Phase 10.7 verification
    context["sandbox"].write_text("verification_artifact.txt", "This is a test artifact for Phase 10.7")

    return {"status": "SUCCEEDED"}
