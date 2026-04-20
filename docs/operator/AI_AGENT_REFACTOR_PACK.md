# AI Agent Refactor Pack — ForgeScaffold (Local LLM Guide)

This file is intended for a local AI agent performing **refactoring-related tasks** using the ForgeScaffold framework. Treat this as a minimal, deterministic “brain pack” and follow it strictly.

## Scope
You are operating a **safe refactor supply chain**. Your job is to:
- run the CLI workflows,
- respect policy and locks,
- produce evidence artifacts,
- avoid nondeterministic outputs.

You are **not** expected to invent new features or change framework internals.

---

## What you should hand to your local agent by filepath (minimum “brain pack”)

### Operator behavior
- `docs/operator/CLI_RUNBOOK.md`
- `docs/operator/CLI_REFERENCE.md`

### Policy + safety rails
- `dawn/policy/runtime_policy.yaml`
- `dawn/policy/trusted_signers.yaml` (or your canonical trusted signers file)

### Pipelines the agent should run
- `dawn/pipelines/forgescaffold_apply_v9_cache.yaml`
- `dawn/pipelines/forgescaffold_apply_v9_cache_runnable.yaml`
  
(If your repo has newer operational defaults, use those instead.)

### The CLI entrypoint
- `scripts/forgescaffold_cli.py`

### (Optional but helpful) Verifiers
- `scripts/verify_forgescaffold_phase13c_cli.py`
- plus any phase verifiers you treat as release gates

That bundle is enough for a weaker model to operate the system like a deterministic machine.

---

## Limitations (plumbing tasks a frontier model must help integrate)

These are **framework plumbing gaps** that a frontier model should handle when integrating ForgeScaffold into real apps:
- **Ticket lifecycle binding** (work item IDs, role mapping, lifecycle transitions)
- **Index sharding + rollups** for very large evidence stores
- **Advanced CLI UX polish** (guided prompts, richer diffs, fewer operator steps)

A local model should **not** try to implement these; it should escalate.

---

## What’s not finished (but not required for your current goal)

These are the big remaining “platform” tracks:

### Track A — Ticket lifecycle integration (ForgeChain)
Not done yet. You currently produce evidence entries; you don’t yet bind them to a work item (ticket IDs, state transitions, approvals mapped to ticket roles, etc.).

### Track B — Sharding + rollups for huge indexes
Not done yet, and you likely don’t need it until evidence volume gets big. Today you’re using:
- single-project JSONL + hash chain + checkpoints
- SQLite cache acceleration
- global catalog across projects

Sharding becomes worth it when a single project’s index grows so large that cache rebuilds / scan fallbacks become operational pain, or when you need archival immutability by month.

### Track C — UX/CLI ergonomics
You’ve completed the Phase 13C CLI foundation (apply/approve/status/query/explain/doctor + exit codes + --json). Further UX work becomes incremental polish (guided prompts, better diffs, less operator typing), not core capability.

---

## Operating guidance (for local agents)

- Prefer `--mode runnable_only` unless the environment is fully provisioned.
- Use `--json` when scripting; it suppresses human stdout noise.
- Respect locks; do not force unless policy allows and you are confident the lock is stale.
- If blocked, use `explain --last` and follow exact next steps.
- Do not write outside allowed write roots defined by policy.

