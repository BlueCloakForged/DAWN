import argparse
import yaml
import os
from pathlib import Path
from typing import List, Dict, Set
from .registry import Registry

class Weaver:
    def __init__(self, links_dir: str):
        self.registry = Registry(links_dir)
        self.registry.discover_links()

    def lint(self, pipeline_path: str) -> bool:
        """Statically validates a pipeline YAML."""
        with open(pipeline_path, "r") as f:
            pipeline = yaml.safe_load(f)
        
        links = pipeline.get("links", [])
        overrides = pipeline.get("overrides", {})
        strict_mode = os.environ.get("DAWN_STRICT_ARTIFACT_ID") == "1"
        
        print(f"Linting pipeline: {pipeline_path}")
        
        # 1. Check link existence
        resolved_metas = []
        for l_info in links:
            l_id = l_info if isinstance(l_info, str) else l_info.get("id")
            meta = self.registry.get_link(l_id)
            if not meta:
                print(f"  ✗ FAIL: Link '{l_id}' not found in registry.")
                return False
            
            # Apply overrides to metadata for linting
            link_meta = meta["metadata"].copy()
            if l_id in overrides:
                self._apply_overrides(link_meta, overrides[l_id])
            resolved_metas.append({"id": l_id, "meta": link_meta})
            
        # 2. Check producers and ambiguity
        producers = {} # artifactId -> link_id
        for entry in resolved_metas:
            l_id = entry["id"]
            produces = entry["meta"].get("spec", {}).get("produces", [])
            for p in produces:
                art_id = p.get("artifactId")
                if strict_mode and (not art_id or not p.get("path")):
                    print(f"  ✗ FAIL: Link '{l_id}' produced artifact missing 'artifactId' or 'path' (STRICT MODE).")
                    return False
                if not art_id: continue
                
                if art_id in producers:
                    print(f"  ✗ FAIL: Ambiguous Producer: '{art_id}' produced by both '{producers[art_id]}' and '{l_id}'.")
                    return False
                producers[art_id] = l_id

        # 3. Check requirements
        for entry in resolved_metas:
            l_id = entry["id"]
            requires = entry["meta"].get("spec", {}).get("requires", [])
            for r in requires:
                art_id = r.get("artifactId")
                art_name = r.get("artifact")
                optional = r.get("optional", False)
                preferred_link = r.get("from_link")
                
                if strict_mode and not art_id:
                    print(f"  ✗ FAIL: Link '{l_id}' requirement missing 'artifactId' (STRICT MODE).")
                    return False
                
                target_id = art_id or art_name
                if not target_id: continue
                
                # If preferred_link is specified, verify it exists and produces the artifact
                if preferred_link:
                    pref_meta = next((m for m in resolved_metas if m["id"] == preferred_link), None)
                    if not pref_meta:
                        print(f"  ✗ FAIL: Link '{l_id}' requires '{target_id}' from '{preferred_link}', but '{preferred_link}' is not in the pipeline.")
                        return False
                    pref_produces = pref_meta["meta"].get("spec", {}).get("produces", [])
                    if not any(p.get("artifactId") == target_id or p.get("artifact") == target_id for p in pref_produces):
                        print(f"  ✗ FAIL: Link '{l_id}' requires '{target_id}' from '{preferred_link}', but '{preferred_link}' does not produce it.")
                        return False
                elif not producers.get(target_id) and not optional:
                    print(f"  ✗ FAIL: Link '{l_id}' requires '{target_id}', but no producer found in pipeline.")
                    return False

        # 4. Validate 'when' references
        for entry in resolved_metas:
            l_id = entry["id"]
            when = entry["meta"].get("spec", {}).get("when", {}).get("condition", "always")
            import re
            matches = re.findall(r"on_(?:success|failure)\(([^)]+)\)", when)
            for target in matches:
                if not any(m["id"] == target for m in resolved_metas):
                    print(f"  ✗ FAIL: Link '{l_id}' condition '{when}' references unknown link '{target}'.")
                    return False

        print("  ✓ Pipeline OK")
        return True

    def graph(self, pipeline_path: str):
        """Prints an ASCII dependency graph."""
        with open(pipeline_path, "r") as f:
            pipeline = yaml.safe_load(f)
        
        links = pipeline.get("links", [])
        overrides = pipeline.get("overrides", {})
        
        resolved_metas = []
        producers = {}
        for l_info in links:
            l_id = l_info if isinstance(l_info, str) else l_info.get("id")
            meta = self.registry.get_link(l_id)
            if not meta: continue
            
            link_meta = meta["metadata"].copy()
            if l_id in overrides:
                self._apply_overrides(link_meta, overrides[l_id])
            resolved_metas.append({"id": l_id, "meta": link_meta})
            
            for p in link_meta.get("spec", {}).get("produces", []):
                if p.get("artifactId"):
                    producers[p["artifactId"]] = l_id

        print(f"\nDAWN Pipeline Graph: {pipeline_path}")
        print("=" * 60)
        
        for entry in resolved_metas:
            l_id = entry["id"]
            when = entry["meta"].get("spec", {}).get("when", {}).get("condition", "always")
            
            print(f"[{l_id}]")
            if when != "always":
                print(f"  └─ when: {when}")
            
            requires = entry["meta"].get("spec", {}).get("requires", [])
            for r in requires:
                art_id = r.get("artifactId") or r.get("artifact")
                if not art_id: continue
                source = producers.get(art_id, "EXTERNAL")
                print(f"  ← ({art_id}) from {source}")
            
            produces = entry["meta"].get("spec", {}).get("produces", [])
            for p in produces:
                art_id = p.get("artifactId") or p.get("artifact")
                print(f"  → produces: {art_id}")
            print("")

    def _apply_overrides(self, base: Dict, override: Dict):
        for k, v in override.items():
            if isinstance(v, dict) and k in base and isinstance(base[k], dict):
                self._apply_overrides(base[k], v)
            else:
                base[k] = v

    def weave(self, link_ids: List[str], output_path: str = None) -> str:
        links_to_weave = []
        for lid in link_ids:
            meta = self.registry.get_link(lid)
            if not meta:
                raise ValueError(f"Link {lid} not found in registry.")
            links_to_weave.append(meta)

        # 1. Contract Validation & Dependency Graph
        producers = {} # artifactId -> link_id
        for meta in links_to_weave:
            l_id = meta["metadata"]["metadata"]["name"]
            produces = meta["metadata"].get("spec", {}).get("produces", [])
            for p in produces:
                art_id = p.get("artifactId")
                if art_id in producers:
                    raise ValueError(f"Ambiguous Artifact Producer: {art_id} produced by both {producers[art_id]} and {l_id}")
                producers[art_id] = l_id

        # 2. Check for missing requirements and build edges
        adj = {meta["metadata"]["metadata"]["name"]: [] for meta in links_to_weave}
        for meta in links_to_weave:
            l_id = meta["metadata"]["metadata"]["name"]
            requires = meta["metadata"].get("spec", {}).get("requires", [])
            for r in requires:
                art_id = r.get("artifactId")
                optional = r.get("optional", False)
                if not art_id and r.get("artifact"): # Legacy
                    art_id = r.get("artifact")
                
                if not art_id: continue
                
                producer_id = producers.get(art_id)
                if not producer_id:
                    if not optional:
                        raise ValueError(f"Missing Required Artifact: {art_id} required by {l_id} but not produced by any link in the set.")
                else:
                    adj[producer_id].append(l_id)

        # 3. Cycle Detection (DFS)
        visited = set()
        rec_stack = set()
        
        def has_cycle(u):
            visited.add(u)
            rec_stack.add(u)
            for v in adj[u]:
                if v not in visited:
                    if has_cycle(v): return True
                elif v in rec_stack:
                    return True
            rec_stack.remove(u)
            return False

        for u in adj:
            if u not in visited:
                if has_cycle(u):
                    raise ValueError(f"Dependency Cycle Detected starting at link {u}")

        # 4. Topological Sort (Order links)
        sorted_links = []
        visited = set()
        
        def topo_sort(u):
            visited.add(u)
            for v in adj[u]:
                if v not in visited:
                    topo_sort(v)
            sorted_links.insert(0, u)

        for u in adj:
            if u not in visited:
                topo_sort(u)

        # 5. Generate Pipeline YAML
        pipeline = {
            "pipelineId": "weaved_pipeline",
            "spec": {
                "description": f"Generated pipeline for links: {', '.join(sorted_links)}"
            },
            "links": [{"id": lid} for lid in sorted_links],
            "overrides": {}
        }
        
        # Add basic success conditions for ordering
        for i in range(1, len(sorted_links)):
            prev = sorted_links[i-1]
            curr = sorted_links[i]
            pipeline["overrides"][curr] = {
                "spec": {
                    "when": {
                        "condition": f"on_success({prev})"
                    }
                }
            }

        yaml_str = yaml.dump(pipeline, sort_keys=False)
        
        if output_path:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, "w") as f:
                f.write(yaml_str)
            print(f"Pipeline weaved successfully to {output_path}")
            
        return yaml_str

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DAWN Pipeline Weaver")
    subparsers = parser.add_subparsers(dest="command")

    # weave command (default for backward compatibility)
    weave_parser = subparsers.add_parser("weave", help="Generate pipeline from link IDs")
    weave_parser.add_argument("--links", "-l", required=True, help="Comma-separated link IDs")
    weave_parser.add_argument("--output", "-o", help="Output YAML path")

    # lint command
    lint_parser = subparsers.add_parser("lint", help="Statically validate a pipeline")
    lint_parser.add_argument("--pipeline", "-p", required=True, help="Path to pipeline YAML")

    # graph command
    graph_parser = subparsers.add_parser("graph", help="Visualize pipeline dependencies")
    graph_parser.add_argument("--pipeline", "-p", required=True, help="Path to pipeline YAML")

    parser.add_argument("--links-dir", default="dawn/links", help="Directory containing links")
    
    args = parser.parse_args()
    
    # Handle direct script execution without command for backward compatibility
    if not args.command:
        # Check if -l was provided via manual parsing or just prompt user
        import sys
        if "-l" in sys.argv or "--links" in sys.argv:
            args.command = "weave"
        else:
            parser.print_help()
            exit(0)

    weaver = Weaver(args.links_dir)
    try:
        if args.command == "weave":
            l_ids = [lid.strip() for lid in args.links.split(",")]
            result = weaver.weave(l_ids, args.output)
            if not args.output:
                print(result)
        elif args.command == "lint":
            if not weaver.lint(args.pipeline):
                exit(1)
        elif args.command == "graph":
            weaver.graph(args.pipeline)
            
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        # traceback.print_exc()
        exit(1)
