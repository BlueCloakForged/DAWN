# Phase 10 Example Artifacts (Index Integrity + Checkpoints)

This folder contains a minimal reference pack for Phase 10 index integrity:
- `evidence_index.jsonl` with hash chaining
- a checkpoint JSON + signature
- PASS and FAIL integrity reports

## How to reproduce

1) Enable checkpoints in policy (temporary for the run):
```
# dawn/policy/runtime_policy.yaml
forgescaffold:
  index_integrity:
    checkpoint_enabled: true
```

2) Run the integrity-enabled pipeline:
```
python3 -m dawn.runtime.main --project forgescaffold_phase10_ci \
  --pipeline dawn/pipelines/forgescaffold_apply_v8_integrity_runnable.yaml \
  --profile forgescaffold_apply_lowrisk
```

3) Validate index integrity:
```
python3 scripts/verify_forgescaffold_phase10.py --project forgescaffold_phase10_ci --bootstrap \
  --profile forgescaffold_apply_lowrisk
```

## What the reports mean

PASS report (`index_integrity_report_pass.json`) asserts:
- hash chain is intact
- checkpoint matches the last entry hash
- checkpoint signatures are valid and trusted

FAIL report (`index_integrity_report_fail.json`) demonstrates tamper detection:
- `ENTRY_HASH_MISMATCH` indicates a line was edited after indexing
- `first_bad_line` points to the first corrupted line (1-based)

## Included files

- `evidence_index.jsonl`
- `checkpoint_*.json`
- `checkpoint_*.signature.json`
- `index_integrity_report_pass.json`
- `index_integrity_report_fail.json`
