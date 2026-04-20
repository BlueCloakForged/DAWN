"""
DAWN Project Report Generator
Phase 10.3: Enhanced Audit Dashboard with pipeline graphs, dependency trees,
budget tracking, download links, and failure diagnostics
"""
import json
import yaml
import subprocess
from pathlib import Path
from datetime import datetime

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>DAWN Audit Report: {project_id}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #333; max-width: 1200px; margin: 0 auto; padding: 40px; background: #f9f9f9; }}
        h1, h2, h3 {{ color: #1a1a1a; border-bottom: 2px solid #eee; padding-bottom: 10px; }}
        .meta {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; background: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); margin-bottom: 30px; }}
        .status-pill {{ display: inline-block; padding: 4px 12px; border-radius: 20px; font-size: 0.85em; font-weight: bold; text-transform: uppercase; }}
        .status-SUCCEEDED {{ background: #e6f4ea; color: #1e7e34; }}
        .status-FAILED {{ background: #fce8e6; color: #d93025; }}
        .status-SKIPPED {{ background: #f1f3f4; color: #5f6368; }}
        table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.05); margin-bottom: 20px; }}
        th, td {{ padding: 12px 15px; text-align: left; border-bottom: 1px solid #eee; }}
        th {{ background: #f8f9fa; font-weight: bold; color: #5f6368; }}
        code {{ font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace; font-size: 0.9em; background: #f1f3f4; padding: 2px 4px; border-radius: 4px; }}
        pre {{ background: #f8f9fa; padding: 15px; border-radius: 8px; overflow-x: auto; font-size: 0.85em; }}
        .warning {{ background: #fff3cd; border-left: 4px solid #ffc107; padding: 15px; margin: 20px 0; border-radius: 4px; }}
        .error {{ background: #f8d7da; border-left: 4px solid #dc3545; padding: 15px; margin: 20px 0; border-radius: 4px; }}
        .success {{ background: #d4edda; border-left: 4px solid #28a745; padding: 15px; margin: 20px 0; border-radius: 4px; }}
        .info {{ background: #e8f4fd; border-left: 4px solid #0d6efd; padding: 15px; margin: 20px 0; border-radius: 4px; }}
        .metric-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 15px; margin: 20px 0; }}
        .metric-card {{ background: #fff; padding: 15px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }}
        .metric-value {{ font-size: 1.5em; font-weight: bold; color: #1a73e8; }}
        .metric-label {{ font-size: 0.85em; color: #5f6368; }}
        .download-link {{ display: inline-block; padding: 8px 16px; background: #1a73e8; color: white; text-decoration: none; border-radius: 4px; margin: 5px; }}
        .download-link:hover {{ background: #1557b0; }}
        .tree {{ font-family: monospace; font-size: 0.9em; line-height: 1.8; }}
        .tree-item {{ padding-left: 20px; }}
        details {{ margin: 10px 0; padding: 10px; background: #fff; border-radius: 8px; }}
        summary {{ cursor: pointer; font-weight: bold; padding: 5px; }}
    </style>
</head>
<body>
    <h1>🔍 DAWN Audit Report</h1>
    
    <div class="meta">
        <div>
            <strong>Project ID:</strong> <code>{project_id}</code><br>
            <strong>Pipeline:</strong> <code>{pipeline_id}</code> v{pipeline_version}<br>
            <strong>Profile:</strong> <code>{profile}</code>
        </div>
        <div>
            <strong>Run ID:</strong> <code>{run_id}</code><br>
            <strong>Generated:</strong> {timestamp}<br>
            <strong>Policy:</strong> v{policy_version}
        </div>
    </div>

    {overall_status_section}

    <h2>📊 Pipeline Visualization</h2>
    <details open>
        <summary>Pipeline Graph</summary>
        <pre>{pipeline_graph}</pre>
    </details>
    <div class="info">
        <strong>Pipeline Path:</strong> <code>{pipeline_path}</code><br>
        <strong>Links in Pipeline:</strong> {link_count}
    </div>

    {downloads_section}

    {failure_diagnostics_section}

    <h2>⏱️ Budget & Resource Usage</h2>
    <div class="metric-grid">
        <div class="metric-card">
            <div class="metric-value">{total_duration_ms}ms</div>
            <div class="metric-label">Total Duration</div>
        </div>
        <div class="metric-card">
            <div class="metric-value">{max_wall_time_sec}s</div>
            <div class="metric-label">Max Link Wall Time</div>
        </div>
        <div class="metric-card">
            <div class="metric-value">{max_output_mb}MB</div>
            <div class="metric-label">Max Link Output</div>
        </div>
        <div class="metric-card">
            <div class="metric-value">{total_retries}</div>
            <div class="metric-label">Total Retries</div>
        </div>
    </div>

    {budget_violations_section}
    {retry_history_section}

    <h2>🔗 Link Execution Timeline</h2>
    <table>
        <thead>
            <tr><th>Link ID</th><th>Status</th><th>Duration</th><th>Retries</th><th>Last Update</th></tr>
        </thead>
        <tbody>
            {links_html}
        </tbody>
    </table>

    <h2>🌳 Artifact Dependency Tree</h2>
    <div class="tree">
{artifact_tree}
    </div>

    <h2>📦 Artifact Index</h2>
    <table>
        <thead>
            <tr><th>Artifact ID</th><th>Producer Link</th><th>Path</th><th>Digest (short)</th></tr>
        </thead>
        <tbody>
            {artifacts_html}
        </tbody>
    </table>

    {ledger_tail_section}

    <p style="margin-top: 50px; color: #888; font-size: 0.8em; text-align: center;">
        Generated by DAWN Orchestrator v{policy_version} • Formal SDL Evidence Link
    </p>
</body>
</html>
"""


def build_artifact_tree(artifact_index, pipeline_spec, project_root):
    """Build a visual tree showing artifact dependencies."""
    tree_lines = []
    
    # Parse pipeline to understand link dependencies
    link_requires = {}
    link_produces = {}
    links_dir = project_root.parent.parent / "dawn" / "links"
    
    for link_entry in pipeline_spec.get("links", []):
        link_id = link_entry if isinstance(link_entry, str) else link_entry.get("id")
        link_yaml = links_dir / link_id / "link.yaml"
        
        if link_yaml.exists():
            with open(link_yaml, "r") as f:
                link_spec = yaml.safe_load(f)
                spec = link_spec.get("spec", {})
                
                # Track what this link requires
                requires = []
                for req in spec.get("requires", []):
                    art_id = req.get("artifactId") or req.get("artifact")
                    if art_id:
                        requires.append(art_id)
                link_requires[link_id] = requires
                
                # Track what this link produces
                produces = []
                for prod in spec.get("produces", []):
                    art_id = prod.get("artifactId") or prod.get("artifact")
                    if art_id:
                        produces.append(art_id)
                link_produces[link_id] = produces
    
    # Build tree by tracing dependencies
    processed = set()
    
    def add_artifact(art_id, depth=0):
        if art_id in processed or art_id not in artifact_index:
            return
        
        processed.add(art_id)
        indent = "  " * depth
        producer = artifact_index[art_id]["link_id"]
        digest_short = artifact_index[art_id]["digest"][:8]
        
        tree_lines.append(f"{indent}📄 <code>{art_id}</code> (by {producer}, {digest_short})")
        
        # Find links that require this artifact
        consumers = [lid for lid, reqs in link_requires.items() if art_id in reqs]
        if consumers:
            for consumer in consumers:
                produced_by_consumer = link_produces.get(consumer, [])
                if produced_by_consumer:
                    tree_lines.append(f"{indent}  ↓ used by <code>{consumer}</code> → produces:")
                    for prod_art in produced_by_consumer:
                        if prod_art in artifact_index and prod_art not in processed:
                            add_artifact(prod_art, depth + 2)
    
    # Start with root artifacts (those not required by anyone in pipeline)
    all_required = set()
    for reqs in link_requires.values():
        all_required.update(reqs)
    
    root_artifacts = [art_id for art_id in artifact_index.keys() if art_id not in all_required]
    
    if root_artifacts:
        tree_lines.append("<strong>Root Artifacts (inputs):</strong>")
        for art_id in root_artifacts[:5]:  # Limit for readability
            add_artifact(art_id, 1)
    else:
        # Fallback: show first few artifacts
        tree_lines.append("<strong>Artifacts (chronological):</strong>")
        for art_id in list(artifact_index.keys())[:10]:
            if art_id not in processed:
                add_artifact(art_id, 1)
    
    return "\n".join(tree_lines) if tree_lines else "No artifacts found."


def parse_timestamp(ts):
    """Helper to parse timestamps from various formats (int, float, ISO string)."""
    if ts is None:
        return datetime.now()
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts)
    if isinstance(ts, str):
        try:
            # Handle potential 'Z' or offset
            return datetime.fromisoformat(ts.replace('Z', '+00:00'))
        except ValueError:
            return datetime.now()
    return datetime.now()


def run(context, config):
    project_root = Path(context["project_root"])
    artifact_index = context["artifact_index"]
    pipeline_id = context.get("pipeline_id", "unknown")
    project_id = context.get("project_id", "unknown")
    run_id = context.get("pipeline_run_id", "unknown")
    profile = context.get("profile", "normal")

    # Load policy
    policy_version = "unknown"
    max_wall_time_sec = 60
    max_output_bytes = 10485760
    
    policy_path = Path(__file__).parent.parent.parent / "policy" / "runtime_policy.yaml"
    if policy_path.exists():
        with open(policy_path, "r") as f:
            policy = yaml.safe_load(f)
            policy_version = policy.get("version", "unknown")
            budgets = policy.get("budgets", {})
            per_link = budgets.get("per_link", {})
            max_wall_time_sec = per_link.get("max_wall_time_sec", 60)
            max_output_bytes = per_link.get("max_output_bytes", 10485760)

    # Load ledger
    from dawn.runtime.ledger import Ledger
    ledger = context.get("ledger") or Ledger(str(project_root))
    events = ledger.get_events()

    # Parse pipeline spec
    pipeline_path = context.get("pipeline_path", "unknown")
    pipeline_version = "1.0.0"
    pipeline_spec = {}
    
    # Try to find pipeline file
    if pipeline_path and pipeline_path != "unknown" and Path(pipeline_path).exists():
        with open(pipeline_path, "r") as f:
            pipeline_spec = yaml.safe_load(f)
    
    # Check manifest for version
    manifest_path = project_root.parent.parent / "dawn" / "pipelines" / "pipeline_manifest.json"
    if manifest_path.exists():
        with open(manifest_path, "r") as f:
            manifest = json.load(f)
            entry = next((p for p in manifest if p["id"] == pipeline_id), None)
            if entry:
                pipeline_version = entry.get("version", "1.0.0")
                if not pipeline_spec:
                    with open(entry["path"], "r") as pf:
                        pipeline_spec = yaml.safe_load(pf)
                pipeline_path = entry["path"]

    # Generate pipeline graph
    pipeline_graph = "Pipeline graph visualization:\n\n"
    links_list = pipeline_spec.get("links", [])
    for i, link_entry in enumerate(links_list, 1):
        link_id = link_entry if isinstance(link_entry, str) else link_entry.get("id")
        pipeline_graph += f"  {i}. {link_id}\n"
        if i < len(links_list):
            pipeline_graph += "     |\n     v\n"

    # Collect link statuses and retries
    link_status = {}
    link_retries = {}
    link_durations = {}
    total_retries = 0
    total_duration_ms = 0
    
    for ev in events:
        l_id = ev.get("link_id")
        if not l_id:
            continue
            
        status = ev.get("status")
        if status in ["SUCCEEDED", "FAILED", "SKIPPED"]:
            link_status[l_id] = (
                status,
                parse_timestamp(ev.get("timestamp")).strftime("%H:%M:%S")
            )
            
            # Track retries
            metrics = ev.get("metrics", {})
            attempts = metrics.get("attempt", 1)
            if attempts > 1:
                link_retries[l_id] = attempts - 1
                total_retries += attempts - 1
                
            # Track duration
            duration_ms = metrics.get("duration_ms", 0)
            if duration_ms:
                link_durations[l_id] = duration_ms
                total_duration_ms += duration_ms

    # Overall status
    overall_status = "SUCCEEDED"
    failure_link = None
    failure_error = None
    
    for l_id, (status, _) in link_status.items():
        if status == "FAILED":
            overall_status = "FAILED"
            failure_link = l_id
            # Find error in events
            for ev in reversed(events):
                if ev.get("link_id") == l_id and ev.get("errors"):
                    failure_error = ev["errors"].get("message", "Unknown error")
                    break
            break

    # Build HTML sections
    overall_status_section = f"""
    <div class="{'success' if overall_status == 'SUCCEEDED' else 'error'}">
        <h3>Overall Status: <span class="status-pill status-{overall_status}">{overall_status}</span></h3>
        <p><strong>Project execution {'' if overall_status == 'SUCCEEDED' else 'did not '}complete</strong>{'d successfully.' if overall_status == 'SUCCEEDED' else '.'}</p>
    </div>
    """

    # Downloads section
    downloads = []
    download_artifacts = [
        ("dawn.evidence.pack", "Evidence Pack"),
        ("dawn.release.bundle", "Release Bundle"),
        ("package.project_bundle.zip", "Project Bundle"),
        ("dawn.spec.srs", "Requirements (SRS)"),
        ("dawn.spec.api", "API Contracts"),
        ("dawn.project.ir", "Project IR"),
    ]
    
    for art_id, label in download_artifacts:
        if art_id in artifact_index:
            rel_path = Path(artifact_index[art_id]["path"]).relative_to(project_root)
            downloads.append(f'<a href="../../../{rel_path}" class="download-link">📥 {label}</a>')
    
    downloads_section = f"""
    <h2>⬇️ Downloads</h2>
    <div style="background: #fff; padding: 20px; border-radius: 8px;">
        {" ".join(downloads) if downloads else "No downloadable artifacts available."}
    </div>
    """ if downloads else ""

    # Failure diagnostics
    failure_diagnostics_section = ""
    if failure_link:
        failure_diagnostics_section = f"""
        <h2>❌ Failure Diagnostics</h2>
        <div class="error">
            <h3>Failure at: <code>{failure_link}</code></h3>
            <p><strong>Error:</strong> {failure_error or 'See ledger for details'}</p>
            <p><strong>What to do next:</strong></p>
            <ul>
                <li>Run: <code>python3 -m dawn.runtime.runbook --project {project_id}</code></li>
                <li>Check ledger: <code>python3 -m dawn.runtime.inspect --project {project_id}</code></li>
                <li>Review link contract: <code>dawn/links/{failure_link}/link.yaml</code></li>
            </ul>
        </div>
        """

    # Budget violations (from events)
    violations = []
    for ev in events:
        if ev.get("errors", {}).get("type") in ["BUDGET_TIMEOUT", "BUDGET_OUTPUT_LIMIT", "BUDGET_PROJECT_LIMIT"]:
            violations.append({
                "link_id": ev.get("link_id"),
                "type": ev["errors"]["type"],
                "message": ev["errors"].get("message", "")
            })
    
    budget_violations_section = ""
    if violations:
        budget_violations_section = """
        <h3>⚠️ Budget Violations</h3>
        <div class="warning">
            <strong>Warning:</strong> The following budget limits were exceeded.
        </div>
        <table>
            <thead>
                <tr><th>Link ID</th><th>Violation Type</th><th>Details</th></tr>
            </thead>
            <tbody>
        """
        for v in violations:
            budget_violations_section += f"<tr><td><code>{v['link_id']}</code></td><td><code>{v['type']}</code></td><td>{v['message']}</td></tr>"
        budget_violations_section += "</tbody></table>"

    # Retry history
    retry_history_section = ""
    if link_retries:
        retry_history_section = """
        <h3>🔄 Retry History</h3>
        <table>
            <thead>
                <tr><th>Link ID</th><th>Attempts</th><th>Retries</th></tr>
            </thead>
            <tbody>
        """
        for l_id, retry_count in link_retries.items():
            retry_history_section += f"<tr><td><code>{l_id}</code></td><td>{retry_count + 1}</td><td>{retry_count}</td></tr>"
        retry_history_section += "</tbody></table>"

    # Links table
    links_html = ""
    for l_id, (status, ts) in link_status.items():
        duration = link_durations.get(l_id, 0)
        retry_count = link_retries.get(l_id, 0)
        links_html += f"<tr><td><code>{l_id}</code></td><td><span class='status-pill status-{status}'>{status}</span></td><td>{duration}ms</td><td>{retry_count}</td><td>{ts}</td></tr>"

    # Artifacts table
    artifacts_html = ""
    for art_id, info in artifact_index.items():
        rel_path = Path(info["path"]).relative_to(project_root) if project_root in Path(info["path"]).parents else info["path"]
        short_digest = info["digest"][:12]
        artifacts_html += f"<tr><td><code>{art_id}</code></td><td><code>{info['link_id']}</code></td><td><code>{rel_path}</code></td><td><code>{short_digest}</code></td></tr>"

    # Artifact tree
    artifact_tree = build_artifact_tree(artifact_index, pipeline_spec, project_root)

    # Ledger tail (last 20 events)
    ledger_tail_section = """
    <h2>📜 Recent Ledger Events</h2>
    <details>
        <summary>Last 20 events</summary>
        <pre>
    """
    for ev in events[-20:]:
        ts_str = parse_timestamp(ev.get('timestamp')).strftime('%H:%M:%S')
        ledger_tail_section += f"{ts_str} | {ev.get('step_id', '-'):20s} | {ev.get('link_id', '-'):30s} | {ev.get('status', '-')}\n"
    ledger_tail_section += "</pre></details>"

    # Final HTML
    report_html = HTML_TEMPLATE.format(
        project_id=project_id,
        pipeline_id=pipeline_id,
        pipeline_version=pipeline_version,
        pipeline_path=pipeline_path,
        profile=profile,
        run_id=run_id[:8] if len(run_id) > 8 else run_id,
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        policy_version=policy_version,
        link_count=len(links_list),
        pipeline_graph=pipeline_graph,
        overall_status_section=overall_status_section,
        downloads_section=downloads_section,
        failure_diagnostics_section=failure_diagnostics_section,
        total_duration_ms=total_duration_ms,
        max_wall_time_sec=max_wall_time_sec,
        max_output_mb=max_output_bytes // (1024 * 1024),
        total_retries=total_retries,
        budget_violations_section=budget_violations_section,
        retry_history_section=retry_history_section,
        links_html=links_html,
        artifact_tree=artifact_tree,
        artifacts_html=artifacts_html,
        ledger_tail_section=ledger_tail_section
    )

    context["sandbox"].write_text("project_report.html", report_html)
    return {"status": "SUCCEEDED"}


if __name__ == "__main__":
    pass
