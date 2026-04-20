"""CONCORD — Catalog loader: hydrate a ContractRegistry from action_catalogs/.

Provides:
- CatalogLoadError   — raised on any file-level or validation failure
- load_catalog()     — walk a catalog root directory → populated ContractRegistry (strict)
- CatalogLoader      — class-based loader with catalog_version (SHA-256) + failures tracking

Directory layout expected:

    catalog_root/
        <resource_type>/
            state_contract.yaml          # optional; loaded first
            actions/
                <action_name>.yaml       # one per ActionContract

Rules enforced:

  - State contracts are registered before action contracts so that
    ContractRegistry cross-validation runs at register_action() time.
  - A resource_type directory with no state_contract.yaml and no actions/
    subdirectory is silently skipped.
  - YAML parse errors and Pydantic validation errors are both wrapped in
    CatalogLoadError, which carries the offending file path.
  - resource_type declared inside a YAML file must match the directory name;
    a mismatch raises CatalogLoadError.
  - The caller may pass in an existing registry (for incremental loading or
    testing); defaults to a fresh ContractRegistry.
"""

from __future__ import annotations

import hashlib
import logging
import os
import pathlib
from typing import Optional

import yaml

_LOG = logging.getLogger(__name__)

from dawn.concord.contracts_kernel import (
    ContractRegistry,
    load_action_contract,
    load_state_contract,
)

_STATE_CONTRACT_FILENAME = "state_contract.yaml"
_ACTIONS_SUBDIR = "actions"
_DEFAULT_CATALOG_ENV_VAR = "FORGE_ATLAS_CATALOG_PATH"


def _default_catalog_root() -> pathlib.Path:
    """Resolve catalog root with env override, defaulting to repo action_catalogs/."""
    env_root = os.environ.get(_DEFAULT_CATALOG_ENV_VAR)
    if env_root:
        return pathlib.Path(env_root).resolve()
    return (pathlib.Path(__file__).resolve().parents[3] / "action_catalogs").resolve()


class CatalogLoadError(Exception):
    """Raised when a catalog file cannot be parsed or fails contract validation.

    Attributes:
        path:   Absolute path of the file that caused the error.
        cause:  Original exception (yaml.YAMLError, ValueError, etc.).
    """

    def __init__(self, path: pathlib.Path, cause: Exception) -> None:
        self.path = path
        self.cause = cause
        super().__init__(f"Failed to load catalog file '{path}': {cause}")


def load_catalog(
    catalog_root: str | pathlib.Path | None,
    *,
    registry: Optional[ContractRegistry] = None,
) -> ContractRegistry:
    """Walk *catalog_root* and populate a ContractRegistry with every contract found.

    Args:
        catalog_root: Path to the root catalog directory.  Each immediate
                      subdirectory is treated as a resource_type bucket.
        registry:     Optional existing registry to load into.  A fresh
                      ContractRegistry is created when not provided.

    Returns:
        The registry (same object as *registry* if one was passed).

    Raises:
        CatalogLoadError: if any YAML file fails to parse or fails contract
                          validation (including Pydantic and cross-contract checks).
        FileNotFoundError: if *catalog_root* does not exist.
    """
    root = (
        pathlib.Path(catalog_root).resolve()
        if catalog_root is not None
        else _default_catalog_root()
    )
    if not root.exists():
        raise FileNotFoundError(f"Catalog root not found: {root}")

    if registry is None:
        registry = ContractRegistry()

    for resource_dir in sorted(root.iterdir()):
        if not resource_dir.is_dir():
            continue

        resource_type = resource_dir.name

        # ── 1. State contract (load first — enables cross-validation) ─────────
        state_path = resource_dir / _STATE_CONTRACT_FILENAME
        if state_path.exists():
            _load_state(state_path, resource_type, registry)

        # ── 2. Action contracts ────────────────────────────────────────────────
        actions_dir = resource_dir / _ACTIONS_SUBDIR
        if actions_dir.is_dir():
            for action_path in sorted(actions_dir.glob("*.yaml")):
                _load_action(action_path, resource_type, registry)

    return registry


# ── Internal helpers ──────────────────────────────────────────────────────────


def _parse_yaml(path: pathlib.Path) -> dict:
    """Parse a YAML file and return the top-level dict.

    Raises:
        CatalogLoadError: on YAML syntax error or if the result is not a dict.
    """
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise CatalogLoadError(path, exc) from exc

    if not isinstance(data, dict):
        raise CatalogLoadError(
            path,
            TypeError(f"Expected a YAML mapping at top level, got {type(data).__name__}"),
        )
    return data


def _check_resource_type(path: pathlib.Path, data: dict, expected: str) -> None:
    """Verify the resource_type declared in *data* matches the directory name.

    Raises:
        CatalogLoadError: on mismatch.
    """
    declared = data.get("resource_type")
    if declared is not None and declared != expected:
        raise CatalogLoadError(
            path,
            ValueError(
                f"resource_type mismatch: directory is '{expected}' but "
                f"file declares '{declared}'."
            ),
        )


def _load_state(
    path: pathlib.Path,
    resource_type: str,
    registry: ContractRegistry,
) -> None:
    data = _parse_yaml(path)
    _check_resource_type(path, data, resource_type)
    try:
        sc = load_state_contract(data)
        registry.register_state(sc)
    except Exception as exc:
        raise CatalogLoadError(path, exc) from exc


def _load_action(
    path: pathlib.Path,
    resource_type: str,
    registry: ContractRegistry,
) -> None:
    data = _parse_yaml(path)
    _check_resource_type(path, data, resource_type)
    try:
        ac = load_action_contract(data)
        registry.register_action(ac)
    except Exception as exc:
        raise CatalogLoadError(path, exc) from exc


# ── CatalogLoader (class-based, lenient mode) ────────────────────────────────


class CatalogLoader:
    """Resilient catalog loader: walks a root directory, skips invalid files.

    Unlike the strict `load_catalog()` function, this class catches
    per-file errors, records them in `failures`, and continues loading.
    It also computes a deterministic SHA-256 `catalog_version` from the
    sorted file paths and their contents.

    Usage::

        loader = CatalogLoader("action_catalogs/")
        registry = loader.load()
        print(loader.catalog_version)   # "sha256:abc123..."
        print(loader.failures)          # [] if all manifests are valid
        print(loader.contracts_loaded)  # number of action contracts loaded

    Attributes:
        catalog_version:   SHA-256 digest of sorted (path, content) pairs.
                           Stable for identical catalog state; changes whenever
                           any manifest is added, removed, or modified.
        failures:          List of {"path": str, "error": str} dicts for
                           every file that failed to parse or validate.
        contracts_loaded:  Number of action contracts successfully registered.
    """

    def __init__(
        self,
        catalog_root: str | pathlib.Path | None,
        *,
        registry: Optional[ContractRegistry] = None,
    ) -> None:
        self._root = (
            pathlib.Path(catalog_root).resolve()
            if catalog_root is not None
            else _default_catalog_root()
        )
        self._registry_arg = registry
        self.catalog_version: str = ""
        self.failures: list[dict] = []
        self.contracts_loaded: int = 0

    def load(self) -> ContractRegistry:
        """Walk the catalog root and return a populated ContractRegistry.

        Raises:
            FileNotFoundError: if the catalog root does not exist.

        Returns:
            ContractRegistry (the one passed to __init__ if provided, else fresh).
        """
        if not self._root.exists():
            raise FileNotFoundError(f"Catalog root not found: {self._root}")

        registry = (
            self._registry_arg
            if self._registry_arg is not None
            else ContractRegistry()
        )
        self.failures = []
        self.contracts_loaded = 0

        for resource_dir in sorted(self._root.iterdir()):
            if not resource_dir.is_dir():
                continue
            resource_type = resource_dir.name

            # State contract first (enables cross-validation on register_action)
            state_path = resource_dir / _STATE_CONTRACT_FILENAME
            if state_path.exists():
                try:
                    _load_state(state_path, resource_type, registry)
                except CatalogLoadError as exc:
                    self.failures.append(
                        {"path": str(exc.path), "error": str(exc.cause)}
                    )
                    _LOG.warning("Skipped state contract %s: %s", exc.path, exc.cause)

            # Action contracts
            actions_dir = resource_dir / _ACTIONS_SUBDIR
            if actions_dir.is_dir():
                for action_path in sorted(actions_dir.glob("*.yaml")):
                    try:
                        _load_action(action_path, resource_type, registry)
                        self.contracts_loaded += 1
                    except CatalogLoadError as exc:
                        self.failures.append(
                            {"path": str(exc.path), "error": str(exc.cause)}
                        )
                        _LOG.warning("Skipped action %s: %s", exc.path, exc.cause)

        self.catalog_version = self._compute_version()

        if not self.contracts_loaded and not any(
            resource_dir.is_dir() for resource_dir in self._root.iterdir()
        ):
            _LOG.warning("Catalog root '%s' is empty — no contracts loaded.", self._root)

        return registry

    def _compute_version(self) -> str:
        """SHA-256 of all YAML file paths (relative) + contents, sorted."""
        h = hashlib.sha256()
        for path in sorted(self._root.rglob("*.yaml")):
            rel = path.relative_to(self._root).as_posix()
            h.update(rel.encode())
            h.update(path.read_bytes())
        return f"sha256:{h.hexdigest()}"
