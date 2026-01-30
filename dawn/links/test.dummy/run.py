import time
import json

def run(context, config):
    link_config = config.get("config", {})
    mode = link_config.get("mode", "success")
    sleep_sec = link_config.get("sleep_sec", 0)
    
    if sleep_sec > 0:
        print(f"Sleeping for {sleep_sec}s...")
        time.sleep(sleep_sec)
        
    if mode == "failure":
        raise RuntimeError("Forced failure in test.dummy link")
        
    if mode == "schema_failure":
        # Return something that doesn't match the produced artifactId metadata if needed, 
        # or just raise a specific error that the reporter can catch.
        # Actually a simple raise is enough for failure diagnostics.
        raise ValueError("SCHEMA_INVALID: Test dummy schema violation")

    context["sandbox"].write_text("dummy.txt", "This is dummy output for testing.")
    return {"status": "SUCCEEDED"}
