import json
import os
import requests
import time
from pathlib import Path
from typing import Dict, Any

def run(context: Dict[str, Any], link_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Judge the quality of project outputs using an LLM.
    """
    project_id = context["project_id"]
    project_root = Path(context["project_root"])
    artifact_store = context["artifact_store"]
    sandbox = context["sandbox"]
    
    config = link_config.get("spec", {}).get("config", {})
    model = config.get("model", "judge-v1")
    prompt_template = config.get("prompt_template", "Rate this project:")
    
    # 1. Collect Context
    # Get project bundle
    bundle_art = artifact_store.get("dawn.project.bundle")
    bundle_data = {}
    if bundle_art:
        with open(bundle_art["path"]) as f:
            bundle_data = json.load(f)
    
    # Get test results
    test_art = artifact_store.get("dawn.test.execution_report")
    test_data = {}
    if test_art:
        with open(test_art["path"]) as f:
            test_data = json.load(f)
    
    # 2. Call Judge Service (Mocked for now)
    # In a real integration, this would call an LLM API
    
    print(f"[judge.model] Judging project {project_id} using {model}...")
    
    # Simulate thinking
    time.sleep(1)
    
    # Mocked scoring logic
    score = 1.0
    reasoning = "All tests passed and code structure is sound."
    
    if test_data.get("failed", 0) > 0 or test_data.get("errors", 0) > 0:
        score = 0.4
        reasoning = f"Project has {test_data.get('failed')} test failures."
    
    judge_result = {
        "score": score,
        "reasoning": reasoning,
        "model": model,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "forensic_context": {
            "files_analyzed": len(bundle_data.get("files", [])),
            "test_summary": test_data.get("summary", "No tests run")
        }
    }
    
    # 3. Publish results
    sandbox.write_json("judge_score.json", judge_result)
    
    # Register artifact
    artifact_store.register(
        artifact_id="dawn.judge.score",
        abs_path=str((project_root / "artifacts" / "judge.model" / "judge_score.json").absolute()),
        schema=None,
        producer_link_id="judge.model"
    )
    
    return {
        "status": "SUCCEEDED",
        "metrics": {
            "judge_score": score,
            "model_used": model
        }
    }
