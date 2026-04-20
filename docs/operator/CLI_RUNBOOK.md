# ForgeScaffold Operator Runbook (CLI) — Phase 13C

This is the single-page, operator-safe “how to run it” guide using only:
`status`, `apply`, `approve`, `query`, `explain`, `doctor`.

> Conventions:
> - Replace `<project>` with your project name.
> - Prefer `--mode runnable_only` unless the environment is fully provisioned.
> - Use `--json` when scripting; it suppresses human output on stdout.
> - Known exit code: `LOCK_HELD` exits **32**.

---

## 0) Happy Path (recommended default)

### Step 1 — Check readiness
```bash
python3 scripts/forgescaffold_cli.py status --project <project>
```

If the status indicates PASS, proceed.
If it indicates WARN, proceed with runnable_only.
If it indicates FAIL/BLOCKED, go to Failure Recovery.

Step 2 — Preflight health check (quick)
```bash
python3 scripts/forgescaffold_cli.py doctor --project <project> --mode runnable_only
```

Step 3 — Apply (default safe mode)
```bash
python3 scripts/forgescaffold_cli.py apply --project <project> --mode runnable_only --yes
```

Expected outcomes:

PASS: done

WARN: acceptable in runnable_only; skips are recorded (deps/targets missing)

BLOCKED: follow the printed next step (typically approval or lock)

Step 4 — Confirm evidence was recorded
```bash
python3 scripts/forgescaffold_cli.py query --project <project> --limit 5
```

Look for the most recent entry matching:

pipeline_name (default or overridden)

verification_mode (strict vs runnable_only)

status (PASS or WARN in runnable_only)

## 1) Approval Flow (HITL)
When apply returns BLOCKED with APPROVAL_REQUIRED

The CLI will indicate what to do next. Typical flow:

Step A — Approve using the provided template/receipt path
```bash
python3 scripts/forgescaffold_cli.py approve --project <project> \
  --approval <approval_template_or_receipt_path> \
  --approver "<your name>" \
  --reason "<why this change is acceptable>" \
  --yes
```

If required, acknowledge risk:

```bash
python3 scripts/forgescaffold_cli.py approve --project <project> \
  --approval <path> --approver "<name>" --reason "<text>" --risk-ack --yes
```

If policy explicitly allows and you are overriding a high-risk block:

```bash
python3 scripts/forgescaffold_cli.py approve --project <project> \
  --approval <path> --approver "<name>" --reason "<text>" --risk-override --yes
```

Step B — Re-run apply
```bash
python3 scripts/forgescaffold_cli.py apply --project <project> --mode runnable_only --yes
```

Step C — Confirm approval was consumed (replay guard)
```bash
python3 scripts/forgescaffold_cli.py query --project <project> --limit 5
```

Look for:

approval_id_status: "consumed"

If you try to reuse the same approval, it should fail (replay protection).

## 2) Strict Mode (use when the environment is fully provisioned)

Use strict mode when deps/tests are expected to run and failures must block rollout:

```bash
python3 scripts/forgescaffold_cli.py apply --project <project> --mode strict --yes
```

If strict fails due to missing deps/targets, either install requirements or rerun runnable-only.

## 3) Failure Recovery (most common cases)
A) Another apply is running (LOCK_HELD)

Symptom:

Apply fails with LOCK_HELD

Exit code is 32

Step 1 — Inspect why it blocked
```bash
python3 scripts/forgescaffold_cli.py explain --project <project> --last
```

Step 2 — Confirm current lock state
```bash
python3 scripts/forgescaffold_cli.py status --project <project>
```

Step 3 — Retry (if active lock clears)
```bash
python3 scripts/forgescaffold_cli.py apply --project <project> --mode runnable_only --yes
```

Step 4 — Stale lock override (last resort; only if you are sure it’s dead)
```bash
python3 scripts/forgescaffold_cli.py apply --project <project> --mode runnable_only --force --yes
```

Expectation:

The index entry records lock_forced=true.

B) Policy blocks (risk/write roots/ticket requirements)

Symptom:

POLICY_BLOCKED (or similar policy code)

Step 1 — Explain the block (this should be the source of truth)
```bash
python3 scripts/forgescaffold_cli.py explain --project <project> --last
```

Step 2 — Satisfy the requirement and retry

Then:

```bash
python3 scripts/forgescaffold_cli.py apply --project <project> --mode runnable_only --yes
```

C) Approval errors (invalid/replay/missing fields)

Symptom:

APPROVAL_INVALID or APPROVAL_REPLAY_DETECTED

Step 1 — Explain the reason
```bash
python3 scripts/forgescaffold_cli.py explain --project <project> --last
```

Step 2 — Generate/obtain a fresh approval template and approve again
```bash
python3 scripts/forgescaffold_cli.py approve --project <project> \
  --approval <fresh_template_path> \
  --approver "<your name>" \
  --reason "<text>" \
  --yes
```

Step 3 — Apply again
```bash
python3 scripts/forgescaffold_cli.py apply --project <project> --mode runnable_only --yes
```

D) Integrity failures (hash/signature/tamper detection)

Symptom:

INTEGRITY_FAILED (or hash/signature mismatch codes)

Treat as a security event. Do not force apply.

Step 1 — Run doctor to capture the full diagnostic bundle
```bash
python3 scripts/forgescaffold_cli.py doctor --project <project> --mode runnable_only --json
```

Step 2 — Explain the last failure (human-readable)
```bash
python3 scripts/forgescaffold_cli.py explain --project <project> --last
```

Escalate with the printed artifact paths (index, checkpoint, signature, report).

E) Query slowness / cache fallback

Symptom:

Queries indicate a JSONL scan backend, or cache integrity warnings

Step 1 — Confirm query backend and results
```bash
python3 scripts/forgescaffold_cli.py query --project <project> --limit 20 --json
```

Step 2 — Doctor (cache binding + integrity)
```bash
python3 scripts/forgescaffold_cli.py doctor --project <project> --mode runnable_only
```

## 4) End-of-Shift Checklist (fast)
```bash
python3 scripts/forgescaffold_cli.py status  --project <project>
python3 scripts/forgescaffold_cli.py query   --project <project> --limit 10
python3 scripts/forgescaffold_cli.py doctor  --project <project> --mode runnable_only
```

If anything is odd:

```bash
python3 scripts/forgescaffold_cli.py explain --project <project> --last
```

That set is usually sufficient for safe escalation.
