# ForgeScaffold app_mvp Examples (Phase 4)

## What hunks are

Hunks are anchored, minimal edits applied to existing files without replacing the whole file. They use anchors to find a stable region, then apply a small change (insert/replace/delete) with integrity checks.

## Supported anchor types

- `literal`: exact substring match
- `regex`: deterministic regex match
- `line_range`: line span, e.g. `"1:3"` or `"L1-L3"`

## Supported actions

- `insert_before`
- `insert_after`
- `replace`
- `delete`

## Conflict codes

- `CONFLICT_ANCHOR_NOT_FOUND`
- `CONFLICT_ANCHOR_AMBIGUOUS`
- `CONFLICT_BEFORE_HASH_MISMATCH`
- `CONFLICT_AFTER_HASH_MISMATCH`

## Rollback behavior

Every applied hunk generates an inverse hunk in `rollback_patchset.json`. Applying the rollback patchset restores the original bytes.

## How to run Phase 4 pipeline

```bash
python3 -m dawn.runtime.main --project app_mvp --pipeline dawn/pipelines/forgescaffold_apply_v2_hunks.yaml --profile forgescaffold_apply_lowrisk
```
