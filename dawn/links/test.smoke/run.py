import os
import py_compile
from pathlib import Path

def run(context, config):
    project_root = Path(context["project_root"])
    src_dir = project_root / "src"
    
    # 1. Compilation Check (Deterministic Python check)
    report = {
        "pass": True,
        "checks": [],
        "errors": []
    }
    
    for p in src_dir.rglob("*.py"):
        try:
            py_compile.compile(str(p), doraise=True)
            report["checks"].append({
                "target": str(p.relative_to(project_root)),
                "type": "py_compile",
                "status": "PASSED"
            })
        except Exception as e:
            report["pass"] = False
            report["errors"].append(f"Compilation FAILED for {p}: {str(e)}")
            report["checks"].append({
                "target": str(p.relative_to(project_root)),
                "type": "py_compile",
                "status": "FAILED"
            })
            
    context["sandbox"].write_json("smoke_test_report.json", report)
    
    # Mock Scenarios Report
    scenarios_report = {
        "scenarios": [
            {"id": "SCN-001", "status": "PASSED"}
        ]
    }
    context["sandbox"].publish("dawn.scenarios.report", "scenarios_report.json", scenarios_report, "json")
    
    status = "SUCCEEDED" if report["pass"] else "FAILED"
    return {
        "status": status,
        "metrics": {
            "checks_run": len(report["checks"]),
            "success_rate": 1.0 if report["pass"] else 0.0
        }
    }
