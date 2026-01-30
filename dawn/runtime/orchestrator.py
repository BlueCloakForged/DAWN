"""
DAWN Orchestrator - Pipeline Execution Engine
Phases 8.3-8.5: Resource Budgets, Observability, Isolation Mode
"""

import yaml
import importlib.util
import os
import uuid
import json
import hashlib
import time
import datetime
import socket
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional
from filelock import FileLock, Timeout
from .registry import Registry
from .ledger import Ledger
from .artifact_store import ArtifactStore
from ..policy import get_policy_loader, PolicyValidationError

# Optional psutil for best-effort CPU/memory tracking
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


class BudgetTimeoutError(Exception):
    """Raised when a link exceeds its wall time budget."""
    pass


class Orchestrator:
    def __init__(self, links_dir: str, projects_dir: str, profile: Optional[str] = None):
        self.registry = Registry(links_dir)
        self.registry.discover_links()
        self.projects_dir = Path(projects_dir)
        self.projects_dir.mkdir(parents=True, exist_ok=True)

        # Load Runtime Policy via PolicyLoader (Phase 8.3/8.5)
        try:
            self.policy_loader = get_policy_loader()
            self.runtime_policy = self.policy_loader.policy
        except PolicyValidationError as e:
            print(f"FATAL: Policy validation failed: {e}")
            raise

        # Profile override (Phase 8.5)
        self._profile = profile or self.runtime_policy.get("default_profile", "normal")

        # Worker identity (Phase 8.4)
        self._worker_id = f"{socket.gethostname()}:{os.getpid()}"

    def run_pipeline(self, project_id: str, pipeline_path: str, profile: Optional[str] = None):
        """Run a pipeline for a project. Acquires project lock."""
        project_root = self.projects_dir / project_id
        project_root.mkdir(parents=True, exist_ok=True)

        # Use provided profile or instance default
        active_profile = profile or self._profile

        # Acquire project lock to prevent concurrent execution
        lock_file = project_root / ".lock"
        lock = FileLock(lock_file, timeout=0)
        lock_wait_start = time.time()

        try:
            with lock:
                lock_wait_time = time.time() - lock_wait_start
                return self._run_pipeline_locked(
                    project_id, pipeline_path, project_root,
                    active_profile, lock_wait_time
                )
        except Timeout:
            raise RuntimeError(f"Project {project_id} is currently locked by another process (BUSY)")

    def _run_pipeline_locked(self, project_id: str, pipeline_path: str, project_root: Path,
                              profile: str, lock_wait_time: float):
        """Internal pipeline execution with lock already acquired."""
        # Generate run-level identifiers (Phase 8.4.1)
        pipeline_run_id = str(uuid.uuid4())
        pipeline_start_time = time.time()

        ledger = Ledger(str(project_root))
        artifact_store = ArtifactStore(str(project_root))

        with open(pipeline_path, "r") as f:
            pipeline_config = yaml.safe_load(f)

        pipeline_id = pipeline_config.get("pipelineId", "default")
        links = pipeline_config.get("links", [])
        overrides = pipeline_config.get("overrides", {})

        print(f"Starting pipeline {pipeline_id} for project {project_id} [profile={profile}]")

        # Phase 8.3.1: Check per-project size budget BEFORE any link runs
        project_size_check = self._check_project_size_budget(project_root, ledger, project_id, pipeline_id, pipeline_run_id)
        if project_size_check is not None:
            raise RuntimeError(project_size_check)

        # Load Artifact Index if exists
        artifact_index = {}
        index_path = project_root / "artifact_index.json"
        if index_path.exists():
            with open(index_path, "r") as f:
                artifact_index = json.load(f)

        # Build project context with run-level info
        project_context = {
            "project_id": project_id,
            "pipeline_id": pipeline_id,
            "pipeline_run_id": pipeline_run_id,
            "worker_id": self._worker_id,
            "project_root": str(project_root),
            "registry": self.registry,
            "ledger": ledger,
            "artifact_store": artifact_store,
            "artifact_index": artifact_index,
            "status_index": {},
            "profile": profile,
            "link_durations": {},
            "budget_violations": [],
            "lock_wait_time_ms": int(lock_wait_time * 1000),
        }

        pipeline_failed = False
        failure_link = None
        failure_error = None

        for link_info in links:
            link_id = link_info if isinstance(link_info, str) else link_info.get("id")
            link_metadata = self.registry.get_link(link_id)

            if not link_metadata:
                print(f"Error: Link {link_id} not found in registry")
                continue

            link_config = link_metadata["metadata"]
            if link_id in overrides:
                self._apply_overrides(link_config, overrides[link_id])

            # Merge per-link config and overrides from pipeline YAML
            if isinstance(link_info, dict):
                if "config" in link_info:
                    if "config" not in link_config:
                        link_config["config"] = {}
                    self._apply_overrides(link_config["config"], link_info["config"])
                if "overrides" in link_info:
                    self._apply_overrides(link_config, link_info["overrides"])

            # Check 'when' conditions
            when = link_config.get("spec", {}).get("when", {}).get("condition", "always")
            if not self._evaluate_condition(project_context, when, link_id):
                print(f"Skipping link {link_id} due to condition: {when}")
                ledger.log_event(
                    project_id, pipeline_id, link_id, "",
                    "evaluate_condition", "SKIPPED",
                    metrics={"condition": when, "run_id": pipeline_run_id, "worker_id": self._worker_id}
                )
                ledger.log_event(
                    project_id, pipeline_id, link_id, "",
                    "link_complete", "SKIPPED",
                    metrics={"condition": when, "run_id": pipeline_run_id, "worker_id": self._worker_id}
                )
                project_context["status_index"][link_id] = "SKIPPED"
                project_context["link_durations"][link_id] = {"duration_ms": 0, "skipped": True, "reason": when}
                continue

            try:
                link_start = time.time()
                self._execute_link(project_context, link_id, link_metadata["path"], link_config)
                link_duration = time.time() - link_start

                if project_context["status_index"].get(link_id) != "SKIPPED":
                    project_context["status_index"][link_id] = "SUCCEEDED"
                    project_context["link_durations"][link_id] = {
                        "duration_ms": int(link_duration * 1000),
                        "skipped": False
                    }
            except Exception as e:
                link_duration = time.time() - link_start
                project_context["status_index"][link_id] = "FAILED"
                project_context["link_durations"][link_id] = {
                    "duration_ms": int(link_duration * 1000),
                    "skipped": False,
                    "error": str(e)
                }
                pipeline_failed = True
                failure_link = link_id
                failure_error = str(e)
                break

        pipeline_end_time = time.time()
        pipeline_duration_ms = int((pipeline_end_time - pipeline_start_time) * 1000)

        # Persist Artifact Index
        index_path = project_root / "artifact_index.json"
        with open(index_path, "w") as f:
            json.dump(project_context["artifact_index"], f, indent=2)

        # Persist Pipeline YAML for introspection
        with open(project_root / "pipeline.yaml", "w") as f:
            yaml.dump(pipeline_config, f)

        # Phase 8.4.2: Generate run_summary artifact
        self._generate_run_summary(
            project_context, project_root, pipeline_path,
            pipeline_start_time, pipeline_end_time, pipeline_duration_ms,
            pipeline_failed, failure_link, failure_error
        )

        if pipeline_failed:
            raise RuntimeError(f"Pipeline failed at link {failure_link}: {failure_error}")

        return project_context

    def _check_project_size_budget(self, project_root: Path, ledger: Ledger,
                                    project_id: str, pipeline_id: str, run_id: str) -> Optional[str]:
        """Phase 8.3.1: Check project size before any link runs."""
        max_project_bytes = self.policy_loader.get_budget("per_project", "max_project_bytes")
        if not max_project_bytes:
            return None

        # Calculate total project size
        total_bytes = 0
        for p in project_root.rglob("*"):
            if p.is_file():
                try:
                    total_bytes += p.stat().st_size
                except OSError:
                    pass

        if total_bytes > max_project_bytes:
            error_msg = (
                f"BUDGET_PROJECT_LIMIT: Project size {total_bytes} bytes exceeds "
                f"limit of {max_project_bytes} bytes"
            )
            ledger.log_event(
                project_id=project_id,
                pipeline_id=pipeline_id,
                link_id="__preflight__",
                run_id=run_id,
                step_id="budget_check",
                status="FAILED",
                errors={
                    "type": "BUDGET_PROJECT_LIMIT",
                    "message": error_msg,
                    "measured_bytes": total_bytes,
                    "limit_bytes": max_project_bytes
                },
                metrics={"run_id": run_id, "worker_id": self._worker_id}
            )
            return error_msg

        return None

    def _evaluate_condition(self, context: Dict, condition: str, link_id: str) -> bool:
        if condition == "always":
            return True
        elif condition.startswith("on_success("):
            target = condition[11:-1]
            return context["status_index"].get(target) == "SUCCEEDED"
        elif condition.startswith("on_failure("):
            target = condition[11:-1]
            return context["status_index"].get(target) == "FAILED"
        elif condition.startswith("if_artifact_exists("):
            target_artifact = condition[19:-1]
            return target_artifact in context["artifact_index"]
        return True

    def _apply_overrides(self, base: Dict, override: Dict):
        for k, v in override.items():
            if isinstance(v, dict) and k in base and isinstance(base[k], dict):
                self._apply_overrides(base[k], v)
            else:
                base[k] = v

    def _get_strict_mode(self) -> bool:
        return os.environ.get("DAWN_STRICT_ARTIFACT_ID") == "1"

    def _execute_link(self, context: Dict, link_id: str, link_path: str, link_config: Dict):
        """Execute a single link with budget enforcement and profile-aware sandbox."""
        run_id = str(uuid.uuid4())
        profile = context.get("profile", "normal")

        policy_versions = {
            "contractVersion": link_config.get("contractVersion", "1.0.0"),
            "policyVersion": self.policy_loader.version,
            "policyDigest": self.policy_loader.digest,
            "profile": profile
        }
        strict_mode = self._get_strict_mode()

        # 1. Calculate Input Signature for Idempotency
        input_signature = self._calculate_input_signature(context, link_id, link_path, link_config)

        # Check for alwaysRun flag (ground truth links that should never skip)
        always_run = link_config.get("spec", {}).get("runtime", {}).get("alwaysRun", False)
        
        # Check if already done (unless alwaysRun is set)
        should_skip = False
        skip_reason = None
        
        if not always_run:
            previous_events = context["ledger"].get_events(link_id)
            last_complete = None
            for ev in reversed(previous_events):
                if ev.get("step_id") == "link_complete":
                    last_complete = ev
                    break

            if last_complete and last_complete.get("status") == "SUCCEEDED":
                if last_complete.get("metrics", {}).get("input_signature") == input_signature:
                    should_skip = True
                    skip_reason = "ALREADY_DONE"
            else:
                # If signature doesn't match, it's not ALREADY_DONE, so we don't skip based on this.
                # We proceed to re-execute the link.
                pass

            if should_skip:
                print(f"Skipping link {link_id}: ALREADY_DONE with matching signature.")
                # Rehydrate artifact registry from previous run
                rehydrated_count = context["artifact_store"].rehydrate_from_link_dir(link_id)
                
                # Verify rehydration for links with produces
                produces = link_config.get("spec", {}).get("produces", [])
                required_artifacts = [p for p in produces if not p.get("optional", False)]
                
                if required_artifacts and rehydrated_count == 0:
                    error_msg = (
                        f"Link {link_id} marked ALREADY_DONE but no artifacts rehydrated. "
                        f"Expected artifacts from contract: {[p.get('artifact') or p.get('artifactId') for p in required_artifacts]}. "
                        f"This suggests artifact manifest is missing or corrupted."
                    )
                    context["ledger"].log_event(
                        context["project_id"], context["pipeline_id"], link_id, run_id,
                        "validate_skip", "FAILED",
                        errors={"type": "REHYDRATION_FAILED", "message": error_msg},
                        policy_versions=policy_versions
                    )
                    raise Exception(error_msg)
                
                context["ledger"].log_event(
                    context["project_id"], context["pipeline_id"], link_id, run_id,
                    "skip", "SUCCEEDED",
                    metrics={"reason": skip_reason, "rehydrated_artifacts": rehydrated_count},
                    policy_versions=policy_versions
                )
                context["status_index"][link_id] = "SKIPPED"
                return {
                    "status": "SKIPPED",
                    "reason": skip_reason,
                    "rehydrated_artifacts": rehydrated_count
                }

        context["ledger"].log_event(
            project_id=context["project_id"],
            pipeline_id=context["pipeline_id"],
            link_id=link_id,
            run_id=run_id,
            step_id="link_start",
            status="STARTED",
            metrics={
                "input_signature": input_signature,
                "run_id": context["pipeline_run_id"],
                "worker_id": self._worker_id
            },
            policy_versions=policy_versions
        )

        print(f"Executing link: {link_id}")

        try:
            # 1. Validate Inputs (Contract Enforcement - Before)
            self._validate_inputs(context, link_id, link_config, run_id, policy_versions, strict_mode)

            # 2. Run Link with timeout (Phase 8.3.2)
            run_py_path = Path(link_path) / "run.py"
            spec = importlib.util.spec_from_file_location(f"{link_id}.run", run_py_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Inject Sandbox helper into context
            from .sandbox import Sandbox
            sandbox = Sandbox(context["project_root"], link_id)
            sandbox.artifact_store = context["artifact_store"]  # Enable artifact registration
            context["sandbox"] = sandbox

            # Snapshot filesystem state for best-effort leak detection
            pre_run_files = self._get_fs_snapshot(context["project_root"])

            # Get effective timeout based on profile, with per-link override support
            timeout_sec = link_config.get("max_wall_time_sec") or self.policy_loader.get_effective_timeout(profile)

            # Track resource usage (best-effort)
            resource_metrics = {"cpu_sec": "unavailable", "mem_mb_peak": "unavailable"}

            # Execute with timeout
            result = self._execute_with_timeout(module, context, link_config, timeout_sec, link_id, run_id, policy_versions)
            print(f"[DEBUG] After _execute_with_timeout for {link_id}: type={type(result)}, is_dict={isinstance(result, dict)}")

            # Best-effort resource tracking (Phase 8.3.4)
            if PSUTIL_AVAILABLE:
                try:
                    proc = psutil.Process(os.getpid())
                    cpu_times = proc.cpu_times()
                    resource_metrics["cpu_sec"] = cpu_times.user + cpu_times.system
                    resource_metrics["mem_mb_peak"] = proc.memory_info().rss / (1024 * 1024)
                except Exception:
                    pass

            # Post-run Scan: Detect leaks outside allowed roots (Profile-aware - Phase 8.5)
            post_run_files = self._get_fs_snapshot(context["project_root"])
            self._check_sandbox_violations(
                context, link_id, run_id, policy_versions, profile,
                pre_run_files, post_run_files
            )

            # Phase 8.3.3: Check output size budget AFTER link runs
            self._check_output_size_budget(context, link_id, run_id, policy_versions)

            # 3. Handle Link Result
            print(f"[DEBUG] About to call result.get() for {link_id}: type={type(result)}")
            link_status = result.get("status", "SUCCEEDED")
            if link_status == "FAILED":
                failure_info = result.get("errors", {})
                if "type" not in failure_info: failure_info["type"] = "RUNTIME_ERROR"
                if "step_id" not in failure_info: failure_info["step_id"] = "run"

                context["ledger"].log_event(
                    project_id=context["project_id"],
                    pipeline_id=context["pipeline_id"],
                    link_id=link_id,
                    run_id=run_id,
                    step_id="link_complete",
                    status="FAILED",
                    errors=failure_info,
                    metrics={"run_id": context["pipeline_run_id"], "worker_id": self._worker_id},
                    policy_versions=policy_versions
                )

                error_msg = f"Link {link_id} reported failure: {failure_info.get('message', 'No error message')}"
                raise Exception(error_msg)

            # 4. Validate Outputs (Contract Enforcement - After)
            print(f"[DEBUG] About to call _validate_outputs for {link_id}: link_config type={type(link_config)}")
            try:
                outputs = self._validate_outputs(
                    context, link_id, link_config, run_id, policy_versions, strict_mode, profile
                )
            except Exception as e:
                import traceback
                print(f"[ERROR] Exception in _validate_outputs for {link_id}:")
                print(f"  Type: {type(e)}")
                print(f"  Message: {str(e)}")
                print(f"  Full traceback:")
                traceback.print_exc()
                raise
            
            # Save artifact manifest for future rehydration
            context["artifact_store"].save_manifest(link_id)
            
            # Update artifact index for this link
            context["artifact_index"].update(outputs)

            # Finalize ledger for this link
            metrics = result.get("metrics", {})
            metrics["input_signature"] = input_signature
            metrics["run_id"] = context["pipeline_run_id"]
            metrics["worker_id"] = self._worker_id
            metrics.update(resource_metrics)

            context["ledger"].log_event(
                project_id=context["project_id"],
                pipeline_id=context["pipeline_id"],
                link_id=link_id,
                run_id=run_id,
                step_id="link_complete",
                status="SUCCEEDED",
                outputs=outputs,
                metrics=metrics,
                errors=result.get("errors", {}),
                policy_versions=policy_versions
            )

            # Update link_durations with metrics (Phase 1.3)
            if link_id in context["link_durations"]:
                context["link_durations"][link_id]["metrics"] = metrics

        except BudgetTimeoutError as e:
            error_msg = str(e)
            print(f"BUDGET_TIMEOUT for link {link_id}: {error_msg}")
            context["budget_violations"].append({
                "link_id": link_id,
                "type": "BUDGET_TIMEOUT",
                "message": error_msg
            })
            raise

        except Exception as e:
            error_msg = str(e)
            print(f"Error executing link {link_id}: {error_msg}")

            # If not already logged, log as runtime error
            if not getattr(e, "_logged", False):
                context["ledger"].log_event(
                    project_id=context["project_id"],
                    pipeline_id=context["pipeline_id"],
                    link_id=link_id,
                    run_id=run_id,
                    step_id="link_failed",
                    status="FAILED",
                    errors={"type": "RUNTIME_ERROR", "message": error_msg, "step_id": "run"},
                    metrics={"run_id": context["pipeline_run_id"], "worker_id": self._worker_id},
                    policy_versions=policy_versions
                )
            raise

    def _normalize_artifact_spec(self, spec: Dict) -> Dict:
        """
        Normalize artifact specification to canonical form.
        
        Supports:
          - artifact: <id>
          - artifactId: <id> (legacy)
        
        Returns: {artifact_id: str, schema: str|None, path: str|None, ...}
        """
        # DEFENSIVE: Handle case where spec is a string (old-style shorthand)
        if isinstance(spec, str):
            # Assume it's just the artifact ID
            return {
                "artifact_id": spec,
                "schema": None,
                "path": None,
                "optional": False,
                "check": None,
                "from_link": None
            }
        
        artifact_id = spec.get("artifact") or spec.get("artifactId")
        return {
            "artifact_id": artifact_id,
            "schema": spec.get("schema"),
            "path": spec.get("path"),
            "optional": spec.get("optional", False),
            "check": spec.get("check"),
            "from_link": spec.get("from_link")
        }

    def _log_validation_error(self, context: Dict, link_id: str, run_id: str,
                              step_id: str, error_msg: str, policy_versions: Dict):
        """Helper to log validation errors."""
        context["ledger"].log_event(
            context["project_id"], context["pipeline_id"], link_id, run_id,
            step_id, "FAILED",
            errors={"type": "VALIDATION_ERROR", "message": error_msg, "step_id": step_id},
            policy_versions=policy_versions
        )

    def _validate_inputs(self, context: Dict, link_id: str, link_config: Dict,
                         run_id: str, policy_versions: Dict, strict_mode: bool):
        """Validate required inputs exist before link execution."""
        requires = link_config.get("spec", {}).get("requires", [])
        
        for req in requires:
            norm = self._normalize_artifact_spec(req)
            artifact_id = norm["artifact_id"]
            
            if not artifact_id:
                continue
            
            # Try artifact registry first
            artifact_meta = context["artifact_store"].get(artifact_id)
            
            if artifact_meta:
                # Found in registry - verify file exists
                artifact_path = Path(artifact_meta["path"])
                if not artifact_path.exists():
                    error_msg = f"Artifact {artifact_id} registered but file missing: {artifact_path}"
                    self._log_validation_error(context, link_id, run_id, "validate_inputs", error_msg, policy_versions)
                    raise Exception(error_msg)
                continue
            
            # Not in registry - check if optional
            if norm["optional"]:
                continue
            
            # Required but not found
            error_msg = f"MISSING_REQUIRED_ARTIFACT: {artifact_id}"
            if norm["from_link"]:
                error_msg += f" (expected from {norm['from_link']})"
            
            self._log_validation_error(context, link_id, run_id, "validate_inputs", error_msg, policy_versions)
            raise Exception(error_msg)

    def _execute_with_timeout(self, module, context: Dict, link_config: Dict,
                               timeout_sec: int, link_id: str, run_id: str,
                               policy_versions: Dict) -> Dict:
        """Execute link with wall-clock timeout enforcement (Phase 8.3.2)."""
        result = {}
        exception_holder = [None]

        def run_link():
            nonlocal result
            try:
                result = module.run(context, link_config)
                print(f"[DEBUG] Link {link_id} returned: type={type(result)}, value={result if isinstance(result, dict) else repr(result)[:200]}")
            except Exception as e:
                exception_holder[0] = e

        thread = threading.Thread(target=run_link)
        thread.start()
        thread.join(timeout=timeout_sec)

        if thread.is_alive():
            # Timeout occurred - thread is still running
            # Log the timeout and raise
            error_msg = f"BUDGET_TIMEOUT: Link {link_id} exceeded wall time limit of {timeout_sec}s"
            context["ledger"].log_event(
                project_id=context["project_id"],
                pipeline_id=context["pipeline_id"],
                link_id=link_id,
                run_id=run_id,
                step_id="link_complete",
                status="FAILED",
                errors={
                    "type": "BUDGET_TIMEOUT",
                    "message": error_msg,
                    "timeout_sec": timeout_sec
                },
                metrics={"run_id": context["pipeline_run_id"], "worker_id": self._worker_id},
                policy_versions=policy_versions
            )
            exc = BudgetTimeoutError(error_msg)
            exc._logged = True
            raise exc

        if exception_holder[0] is not None:
            raise exception_holder[0]

        print(f"[DEBUG] _execute_with_timeout returning: type={type(result)}, keys={result.keys() if isinstance(result, dict) else 'NOT_A_DICT'}")
        return result or {"status": "SUCCEEDED"}

    def _check_sandbox_violations(self, context: Dict, link_id: str, run_id: str,
                                   policy_versions: Dict, profile: str,
                                   pre_run_files: Dict, post_run_files: Dict):
        """Check for unauthorized file writes (Profile-aware - Phase 8.5)."""
        leaks = []

        # Build allowed prefixes based on profile
        allowed_prefixes = [
            os.path.join("artifacts", link_id),
            "ledger",
            "runs",
            "healing",  # Allow healing audit trail (versioned code snapshots)
            "inputs"    # Allow self-healing to update source files
        ]

        # Phase 8.5: In isolation mode, src/ writes are ALWAYS blocked
        profile_config = self.policy_loader.get_profile(profile)
        if profile_config.get("allow_src_writes", True):
            # Normal mode: check security whitelist
            if self.policy_loader.is_src_write_allowed(link_id, profile):
                allowed_prefixes.append("src")
        # else: isolation mode - src/ not added to allowed_prefixes

        # Phase 8.5.2: artifact_only_outputs enforcement
        if profile_config.get("artifact_only_outputs", False):
            # In isolation mode, only artifacts/<link_id>/ and ledger/ allowed
            # (already the case without src/)
            pass

        # System files that the orchestrator updates during link execution
        # These should not trigger POLICY_VIOLATION
        def is_ignored_system_file(filepath):
            """Check if file is system metadata updated by orchestrator."""
            # Ignore root metadata files
            if filepath in {"artifact_index.json", "project_index.json", "pipeline.yaml", ".lock"}:
                return True
            # Ignore logs and run data
            if filepath.startswith("runs/") or filepath.startswith("ledger/"):
                return True
            # Ignore artifact registries and metrics (orchestrator updates these)
            if filepath.endswith(".dawn_artifacts.json") or "package.metrics" in filepath:
                return True
            return False
        
        for path, mtime in post_run_files.items():
            # Ignore common ephemeral files
            if "__pycache__" in path or path.endswith(".pyc"):
                continue
            
            # Ignore system metadata files updated by orchestrator
            if is_ignored_system_file(path):
                continue

            is_allowed = any(path.startswith(prefix) for prefix in allowed_prefixes)

            if not is_allowed:
                if path not in pre_run_files or post_run_files[path] != pre_run_files.get(path):
                    leaks.append(path)

        if leaks:
            error_msg = f"POLICY_VIOLATION: Link {link_id} modified files outside allowed sandbox roots: {leaks}"
            context["ledger"].log_event(
                project_id=context["project_id"],
                pipeline_id=context["pipeline_id"],
                link_id=link_id,
                run_id=run_id,
                step_id="sandbox_check",
                status="FAILED",
                errors={"type": "POLICY_VIOLATION", "message": error_msg, "leaked_paths": leaks},
                metrics={"run_id": context["pipeline_run_id"], "worker_id": self._worker_id},
                policy_versions=policy_versions
            )
            exc = Exception(error_msg)
            exc._logged = True
            raise exc

    def _check_output_size_budget(self, context: Dict, link_id: str, run_id: str,
                                   policy_versions: Dict):
        """Phase 8.3.3: Check output size after link runs."""
        max_output_bytes = self.policy_loader.get_budget("per_link", "max_output_bytes")
        if not max_output_bytes:
            return

        # Calculate total size of link's output directory
        output_dir = Path(context["project_root"]) / "artifacts" / link_id
        if not output_dir.exists():
            return

        total_bytes = 0
        for p in output_dir.rglob("*"):
            if p.is_file():
                try:
                    total_bytes += p.stat().st_size
                except OSError:
                    pass

        if total_bytes > max_output_bytes:
            error_msg = (
                f"BUDGET_OUTPUT_LIMIT: Link {link_id} output size {total_bytes} bytes "
                f"exceeds limit of {max_output_bytes} bytes"
            )
            context["ledger"].log_event(
                project_id=context["project_id"],
                pipeline_id=context["pipeline_id"],
                link_id=link_id,
                run_id=run_id,
                step_id="budget_check",
                status="FAILED",
                errors={
                    "type": "BUDGET_OUTPUT_LIMIT",
                    "message": error_msg,
                    "measured_bytes": total_bytes,
                    "limit_bytes": max_output_bytes
                },
                metrics={"run_id": context["pipeline_run_id"], "worker_id": self._worker_id},
                policy_versions=policy_versions
            )
            context["budget_violations"].append({
                "link_id": link_id,
                "type": "BUDGET_OUTPUT_LIMIT",
                "measured_bytes": total_bytes,
                "limit_bytes": max_output_bytes
            })
            exc = Exception(error_msg)
            exc._logged = True
            raise exc

    def _validate_outputs(self, context: Dict, link_id: str, link_config: Dict,
                          run_id: str, policy_versions: Dict, strict_mode: bool,
                          profile: str = None) -> Dict:
        """Validate produced outputs exist and conform to schemas."""
        # DEFENSIVE: Handle case where link_config is a string
        if not isinstance(link_config, dict):
            print(f"[ERROR] _validate_outputs received link_config as {type(link_config)}, expected dict")
            link_config = {}
        
        produces = link_config.get("spec", {}).get("produces", [])
        outputs_resolved = {}

        for prod in produces:
            norm = self._normalize_artifact_spec(prod)
            artifact_id = norm["artifact_id"]
            
            if not artifact_id:
                continue
            
            # Check if artifact was registered during link execution
            artifact_meta = context["artifact_store"].get(artifact_id)
            
            if artifact_meta:
                # Registered via sandbox.publish - validate it exists
                artifact_path = Path(artifact_meta["path"])
                if not artifact_path.exists():
                    error_msg = f"Artifact {artifact_id} registered but file missing: {artifact_path}"
                    self._log_validation_error(context, link_id, run_id, "validate_outputs", error_msg, policy_versions)
                    raise Exception(error_msg)
                
                # Update legacy artifact index
                outputs_resolved[artifact_id] = artifact_meta
                continue
            
            # Not registered - check if path was provided for legacy support
            if norm["path"]:
                file_path = Path(context["project_root"]) / "artifacts" / link_id / norm["path"]
                if file_path.exists():
                    # Auto-register for this run
                    context["artifact_store"].register(
                        artifact_id=artifact_id,
                        abs_path=str(file_path.absolute()),
                        schema=norm["schema"],
                        producer_link_id=link_id
                    )
                    artifact_meta = context["artifact_store"].get(artifact_id)
                    outputs_resolved[artifact_id] = artifact_meta
                    
                    # Continue with schema validation below
                    # Fall through to legacy validation code
                    path_name = norm["path"]
                else:
                    # Path specified but doesn't exist
                    if not norm["optional"]:
                        error_msg = f"PRODUCED_ARTIFACT_MISSING: {artifact_id} at {norm['path']}"
                        self._log_validation_error(context, link_id, run_id, "validate_outputs", error_msg, policy_versions)
                        raise Exception(error_msg)
                    continue
            else:
                # No registration and no path - check if optional
                if norm["optional"]:
                    continue
                    
                # Required but not published
                error_msg = (
                    f"PRODUCED_ARTIFACT_MISSING: {artifact_id}\n"
                    f"Link {link_id} did not call sandbox.publish('{artifact_id}', ...) "
                    f"and no path was provided in contract."
                )
                self._log_validation_error(context, link_id, run_id, "validate_outputs", error_msg, policy_versions)
                raise Exception(error_msg)

            # Legacy schema validation (only if we got here via path-based lookup)
            file_path = Path(context["project_root"]) / "artifacts" / link_id / path_name

            # Schema Validation (JSON)
            schema = prod.get("schema", {})
            
            # DEFENSIVE FIX: schema can be either a string ("json") or a dict ({"type": "json", "ref": "..."})
            if isinstance(schema, str):
                # Simple string schema like "json" - convert to dict format
                schema = {"type": schema}
            
            if schema.get("type") == "json":
                try:
                    with open(file_path, "r") as f:
                        artifact_data = json.load(f)
                except Exception as e:
                    error_msg = f"SCHEMA_INVALID: {artifact_id} is not valid JSON. {str(e)}"
                    context["ledger"].log_event(
                        context["project_id"], context["pipeline_id"], link_id, run_id,
                        "validate_outputs", "FAILED",
                        errors={"type": "SCHEMA_INVALID", "message": error_msg, "step_id": "validate_outputs"},
                        policy_versions=policy_versions
                    )
                    raise Exception(error_msg)

                # Structural validation if Ref exists
                schema_ref = schema.get("ref")
                if schema_ref:
                    from .schemas import SCHEMA_REGISTRY
                    target_schema = SCHEMA_REGISTRY.get(schema_ref)
                    if target_schema:
                        try:
                            from jsonschema import validate
                            validate(instance=artifact_data, schema=target_schema)
                        except Exception as ve:
                            error_msg = f"SCHEMA_INVALID: {artifact_id} failed validation against '{schema_ref}': {str(ve)}"
                            context["ledger"].log_event(
                                context["project_id"], context["pipeline_id"], link_id, run_id,
                                "validate_outputs", "FAILED",
                                errors={"type": "SCHEMA_INVALID", "message": error_msg, "step_id": "validate_outputs", "schema_ref": schema_ref},
                                policy_versions=policy_versions
                            )
                            raise Exception(error_msg)

            # Log digest and update index
            digest = context["artifact_store"].get_digest(file_path)
            artifact_entry = {
                "path": str(file_path), 
                "digest": digest, 
                "link_id": link_id,
                "run_id": context["pipeline_run_id"],
                "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
            }
            context["artifact_index"][artifact_id] = artifact_entry
            outputs_resolved[artifact_id] = artifact_entry

        return outputs_resolved

    def _generate_run_summary(self, context: Dict, project_root: Path,
                               pipeline_path: str, start_time: float, end_time: float,
                               duration_ms: int, failed: bool, failure_link: Optional[str],
                               failure_error: Optional[str]):
        """Phase 8.4.2: Generate dawn.metrics.run_summary artifact."""
        # Compute pipeline digest
        try:
            with open(pipeline_path, "rb") as f:
                pipeline_digest = hashlib.sha256(f.read()).hexdigest()
        except Exception:
            pipeline_digest = "unknown"

        summary = {
            "run_id": context["pipeline_run_id"],
            "worker_id": context["worker_id"],
            "project_id": context["project_id"],
            "pipeline_id": context["pipeline_id"],
            "pipeline_path": str(pipeline_path),
            "pipeline_digest": pipeline_digest,
            "profile": context["profile"],
            "policy": {
                "version": self.policy_loader.version,
                "digest": self.policy_loader.digest,
            },
            "timing": {
                "started_at": start_time,
                "ended_at": end_time,
                "duration_ms": duration_ms,
                "lock_wait_time_ms": context.get("lock_wait_time_ms", 0),
            },
            "links": context["link_durations"],
            "status": "FAILED" if failed else "SUCCEEDED",
            "failure": {
                "link_id": failure_link,
                "error": failure_error
            } if failed else None,
            "budget_violations": context.get("budget_violations", []),
            "budgets_enforced": {
                "per_link": {
                    "max_wall_time_sec": self.policy_loader.get_budget("per_link", "max_wall_time_sec"),
                    "max_output_bytes": self.policy_loader.get_budget("per_link", "max_output_bytes"),
                },
                "per_project": {
                    "max_project_bytes": self.policy_loader.get_budget("per_project", "max_project_bytes"),
                }
            }
        }

        # Write to artifacts/package.metrics/run_summary.json
        metrics_dir = project_root / "artifacts" / "package.metrics"
        metrics_dir.mkdir(parents=True, exist_ok=True)
        summary_path = metrics_dir / "run_summary.json"

        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)

        # Register in artifact index
        digest = context["artifact_store"].get_digest(summary_path)
        context["artifact_index"]["dawn.metrics.run_summary"] = {
            "path": str(summary_path),
            "digest": digest,
            "link_id": "package.metrics"
        }

    def _calculate_input_signature(self, context: Dict, link_id: str, link_path: str, link_config: Dict) -> str:
        """
        Calculate input signature for skip decisions.
        
        CRITICAL: This signature determines ALREADY_DONE decisions.
        Must include:
        - Link config (so config changes force re-run)
        - Bundle SHA (so input changes force re-run of dependent links)
        """
        sig_parts = []
        
        # 1. Link identifier
        sig_parts.append(f"link={link_id}")
        
        # 2. Config hash (forces re-run on config change)
        config_data = link_config.get("config", {})
        config_json = json.dumps(config_data, sort_keys=True)
        config_hash = hashlib.sha256(config_json.encode()).hexdigest()[:16]
        sig_parts.append(f"cfg={config_hash}")
        
        # 3. Bundle SHA (forces re-run when inputs change)
        try:
            bundle_meta = context["artifact_store"].get("dawn.project.bundle")
            if bundle_meta and Path(bundle_meta["path"]).exists():
                with open(bundle_meta["path"]) as f:
                    bundle_data = json.load(f)
                    bundle_sha = bundle_data.get("bundle_sha256")
                    if bundle_sha:
                        sig_parts.append(f"bundle={bundle_sha}")
        except Exception:
            pass  # Bundle not available - skip this part
        
        # Combine and hash
        combined = "|".join(sig_parts)
        return hashlib.sha256(combined.encode()).hexdigest()[:32]

    def _get_fs_snapshot(self, root_dir: str) -> Dict[str, float]:
        """Returns a mapping of relative file paths to their modification times."""
        snapshot = {}
        root = Path(root_dir)
        for p in root.rglob("*"):
            if p.is_file():
                try:
                    rel_path = str(p.relative_to(root))
                    snapshot[rel_path] = p.stat().st_mtime
                except OSError:
                    pass
        return snapshot
