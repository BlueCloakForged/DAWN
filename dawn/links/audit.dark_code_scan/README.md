# Module: audit.dark_code_scan

## Purpose
Scans the DAWN codebase for "dark code" — modules that lack documentation,
docstrings, inline context, or manifest files. Implements **Layer 2** of the
Dark Code Management Framework by checking whether every module is self-describing.

This link enables DAWN to **audit itself**, producing a risk-ranked report
that identifies comprehension gaps before they become engineering liabilities.

## Dependencies (Requires)
- Access to the `dawn/` source directory (resolved via `Path(__file__)`)
- Python stdlib only: `ast`, `pathlib`, `json`
- No external DAWN artifacts required (can run standalone)

## Dependents (Used By)
- `audit.contract_completeness` (planned — consumes this report)
- Any CI pipeline that enforces documentation thresholds
- Human review workflows (Layer 3: Comprehension Gate)

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
| `dawn/` directory not found | Returns `FAILED` with diagnostic | Verify workspace path |
| Individual `.py` file has syntax error | File flagged, scanning continues | Fix syntax error |
| Empty link directory (no `run.py`) | Skipped silently | No action needed |

## Risk Scoring
| Missing Element | Weight |
|----------------|--------|
| Module docstring | +3 |
| `README.md` / `manifest.md` | +5 |
| `link.yaml` description | +2 |
| Each undocumented public function | +1 |
| Comment density < 5% | +2 |
| Syntax error | +10 |

## Risk Tiers
- **CRITICAL** (≥10): Immediate documentation required
- **HIGH** (6–9): Should be documented before next release
- **MEDIUM** (3–5): Documentation recommended
- **LOW** (0–2): Acceptable comprehension level
