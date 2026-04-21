# Module: audit.contract_completeness

## Purpose
Audits every `link.yaml` contract in `dawn/links/` for semantic completeness.
Checks whether contracts declare the fields required by Layer 2 of the Dark
Code Management Framework: description, failure modes, retry semantics,
and timeout configuration.

## Dependencies (Requires)
- Access to `dawn/links/` directory (resolved via `Path(__file__)`)
- Python stdlib only: `pathlib`, `json`, `re`
- No external DAWN artifacts required

## Dependents (Used By)
- `audit.dark_code_report` pipeline
- CI gates enforcing contract standards

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| `dawn/links/` not found | Returns `FAILED` | Verify workspace path |
| Malformed YAML in a link | Flagged as `PARSE_ERROR` (score +10), scanning continues | Fix YAML |
| Link directory has no `link.yaml` | Flagged as `MISSING_CONTRACT` (score +10) | Create contract |

## Scoring
| Missing Element | Points |
|----------------|--------|
| Missing/empty description | +5 |
| Description < 20 chars | +2 |
| No failure_modes | +3 |
| No timeout | +1 |
| No retry policy | +1 |
| No produces | +1 |
| Missing link.yaml entirely | +10 |
| Parse error | +10 |
