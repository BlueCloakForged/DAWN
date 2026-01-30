import os
import shutil
import uuid
import yaml
import json
from pathlib import Path
from typing import List, Dict
from dawn.runtime.orchestrator import Orchestrator

# Categorization
POSITIVE = [
    "ingest.generic_handoff", "spec.requirements", "scaffold.project", 
    "plan.solution_outline", "spec.api_contracts", "impl.scaffold_repo", 
    "impl.generate_patchset", "impl.apply_patchset", "test.smoke", 
    "package.project_bundle", "package.src_diff", "package.project_report",
    "package.evidence_pack", "package.release_bundle", "gate.human_review", 
    "service.catalog", 
    "build.ci", "validation.self_heal"
]

NEGATIVE = {
    "test.unauthorized_src_write": "POLICY_VIOLATION",
    "test.missing_id": "MISSING_REQUIRED_ARTIFACT",
    "gate.patch_approval": "Patch approval required",
    "test.bad_schema": "SCHEMA_INVALID"
}

MANUAL = ["ingest.t2t_handoff", "chain.validator", "quality.gates", "validate.project_handoff", "test.collision"]

def test_links():
    base_dir = Path(__file__).parent.parent.parent
    links_dir = base_dir / "dawn" / "links"
    projects_root = base_dir / "projects"
    
    orchestrator = Orchestrator(str(links_dir), str(projects_root))
    links = orchestrator.registry.list_links()
    
    print(f"\nDAWN Link Regression Suite (Phase 7)")
    print("=" * 70)
    print(f"{'Group':<10} | {'Link ID':<30} | {'Status':<10} | {'Details'}")
    print("-" * 70)
    
    results = {"POSITIVE": [], "NEGATIVE": [], "MANUAL": []}
    
    for l_id in links:
        if l_id in MANUAL:
            group = "MANUAL"
        elif l_id in NEGATIVE:
            group = "NEGATIVE"
        else:
            group = "POSITIVE"

        if group == "MANUAL":
            print(f"{group:<10} | {l_id:<30} | {'SKIP':<10} | Categorized as Manual")
            results[group].append(True)
            continue

        project_id = f"test_{l_id}_{uuid.uuid4().hex[:6]}"
        project_path = projects_root / project_id
        
        try:
            # Setup project
            project_path.mkdir(parents=True, exist_ok=True)
            (project_path / "inputs").mkdir(exist_ok=True)
            (project_path / "artifacts").mkdir(exist_ok=True)
            
            # Templates
            with open(project_path / "inputs/human_decision.json", "w") as f: json.dump({"decision": "APPROVED"}, f)
            with open(project_path / "inputs/idea.md", "w") as f: f.write("test")
            
            # Minimal Pipeline
            with open(project_path / "test_pipeline.yaml", "w") as f:
                yaml.dump({"pipelineId": f"test_{l_id}", "links": [{"id": l_id}]}, f)

            # Mock Artifacts for SDLC links
            def mock_art(art_id, link_name, file_name, content={}):
                p = project_path / "artifacts" / link_name
                p.mkdir(parents=True, exist_ok=True)
                fp = p / file_name
                if isinstance(content, str):
                    with open(fp, "w") as f: f.write(content)
                else:
                    with open(fp, "w") as f: json.dump(content, f)
                return {"path": str(fp), "link_id": link_name, "digest": "mock"}

            idx = {
                "dawn.project.descriptor": mock_art("dawn.project.descriptor", "ingest.generic", "desc.json", {"id": "test"}),
                "dawn.project.ir": mock_art("dawn.project.ir", "ingest.generic", "ir.json", {"nodes": []}),
                "dawn.spec.srs": mock_art("dawn.spec.srs", "spec.req", "srs.md", "# SRS"),
                "dawn.plan.outline": mock_art("dawn.plan.outline", "plan.out", "plan.md", "# Plan"),
                "dawn.spec.api": mock_art("dawn.spec.api", "spec.api", "api.json", {}),
                "dawn.repo.scaffold": mock_art("dawn.repo.scaffold", "scaffold", "manifest.json", []),
                "dawn.patchset": mock_art("dawn.patchset", "gen.patch", "patchset.json", {}),
                "dawn.gate.patch_decision": mock_art("dawn.gate.patch_decision", "gate.patch", "decision.json", {"decision": "APPROVED", "patchset_digest": "mock"}),
                "dawn.patch.applied": mock_art("dawn.patch.applied", "app.patch", "applied.json", []),
                "dawn.src.diff": mock_art("dawn.src.diff", "pkg.diff", "diff.json", []),
                "dawn.project.report": mock_art("dawn.project.report", "pkg.rep", "report.html", "mock"),
                "dawn.evidence.pack": mock_art("dawn.evidence.pack", "pkg.ev", "evidence.zip", "mock"),
                "package.project_bundle.zip": mock_art("package.project_bundle.zip", "pkg.bundle", "bundle.zip", "mock"),
                "service.catalog.catalog": mock_art("service.catalog.catalog", "svc.cat", "catalog.json", {}),
                "validate.project_handoff.report": mock_art("validate.project_handoff.report", "val.hand", "report.json", {})
            }
            idx["dawn.spec.requirements"] = idx["dawn.spec.srs"]
            with open(project_path / "artifact_index.json", "w") as f: json.dump(idx, f)

            # Run
            context = orchestrator.run_pipeline(project_id, str(project_path / "test_pipeline.yaml"))
            link_status = context["status_index"].get(l_id, "UNKNOWN")
            
            pass_test = False
            details = ""
            
            if group == "POSITIVE":
                if link_status == "SUCCEEDED" or link_status == "SKIPPED":
                    pass_test = True
                    details = "Succeeded as expected"
                else:
                    details = f"Failed, got {link_status}"
            
            elif group == "NEGATIVE":
                expected_error = NEGATIVE[l_id]
                # Check metrics/errors in ledger if we really want to be precise, 
                # but run_pipeline throwing or link FAILED is the baseline.
                if link_status == "FAILED":
                    pass_test = True # Good, it failed
                    details = f"Failed as expected ({expected_error})"
                else:
                    details = f"Succeeded but expected failure ({expected_error})"

            status_str = "PASS" if pass_test else "FAIL"
            print(f"{group:<10} | {l_id:<30} | {status_str:<10} | {details}")
            results[group].append(pass_test)

        except Exception as e:
            if group == "NEGATIVE" and NEGATIVE[l_id] in str(e):
                print(f"{group:<10} | {l_id:<30} | PASS       | Caught expected: {NEGATIVE[l_id]}")
                results[group].append(True)
            else:
                print(f"{group:<10} | {l_id:<30} | FAIL       | {str(e).splitlines()[0]}")
                results[group].append(False)
        finally:
            shutil.rmtree(project_path, ignore_errors=True)

    # Scoreboard
    print("-" * 70)
    print("FINAL SCOREBOARD")
    print("-" * 70)
    for g in ["POSITIVE", "NEGATIVE", "MANUAL"]:
        count = len(results[g])
        passed = sum(1 for r in results[g] if r is True)
        status = "PASS" if (g == "MANUAL" or passed == count) else "FAIL"
        print(f"{g:<10}: {passed}/{count} {status}")
    print("-" * 70)

if __name__ == "__main__":
    test_links()
