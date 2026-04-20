# External Code Healer API Specification

This document defines the API contract between DAWN's self-healing system and external code healer services (e.g., SAM, GPT-4, Claude).

## Overview

The Code Healer API is an LLM-agnostic interface for fixing code based on pytest failures. DAWN calls this API during healing cycles, passing error context and receiving corrected code.

## Endpoint Configuration

**Environment Variable**: `CODE_HEALER_URL`

Example values:
- `http://localhost:3000/api/heal` (SAM local instance)
- `https://sam-production.example.com/api/heal` (SAM production)
- `https://api.openai.com/v1/code/heal` (hypothetical GPT-4 endpoint)

## Request Schema

### HTTP Method
`POST`

### Headers
```
Content-Type: application/json
```

### Body
```json
{
  "project_id": "auto_calc_v2",
  "cycle": 1,
  "failed_files": {
    "logic.py": "def calculate(op, x, y):\n  if op == 'add':\n    return x + y\n  elif op == 'subtract':\n    return x - y",
    "test_logic.py": "from logic import calculate\n\ndef test_add():\n  assert calculate('add', 2, 2) == 4"
  },
  "pytest_errors": {
    "exit_code": 2,
    "error_count": 1,
    "error_summary": "Test collection failed (syntax error or import error)",
    "stderr": "SyntaxError: invalid syntax (logic.py, line 5)",
    "stdout": "..."
  }
}
```

### Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| `project_id` | string | Unique project identifier |
| `cycle` | integer | Current healing attempt (1-5) |
| `failed_files` | object | Map of filename → source code content |
| `pytest_errors` | object | Error context from pytest execution |
| `pytest_errors.exit_code` | integer | Pytest exit code (0=pass, 1=fail, 2=collection error) |
| `pytest_errors.error_count` | integer | Total number of errors detected |
| `pytest_errors.error_summary` | string | Human-readable error summary |
| `pytest_errors.stderr` | string | Pytest stderr output (last 1000 chars) |
| `pytest_errors.stdout` | string | Pytest stdout output (last 2000 chars) |

## Response Schema

### Success Response

HTTP Status: `200 OK`

```json
{
  "status": "healed",
  "modified_files": {
    "logic.py": "def calculate(op, x, y):\n  if op == 'add':\n    return x + y\n  elif op == 'subtract':\n    return x - y\n  else:\n    raise ValueError(f'Unknown operation: {op}')"
  },
  "changes_summary": "Fixed SyntaxError on line 5 by adding missing colon"
}
```

### Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | Must be `"healed"` for success |
| `modified_files` | object | Map of filename → corrected source code |
| `changes_summary` | string | Human-readable description of changes made |

### Failure Responses

#### Healer Timeout
HTTP Status: `504 Gateway Timeout` or connection timeout

```json
{
  "status": "timeout",
  "message": "Healer timed out after 30s"
}
```

#### Healer Error
HTTP Status: `500 Internal Server Error` or `4xx` status

```json
{
  "status": "error",
  "message": "Failed to generate fix: model returned invalid syntax"
}
```

## Timeout Configuration

DAWN uses progressive timeouts per healing cycle:

| Cycle | Timeout | Rationale |
|-------|---------|-----------|
| 1 | 30s | Quick syntax fixes |
| 2 | 45s | Moderate complexity |
| 3 | 60s | Logic errors |
| 4 | 90s | Complex refactoring |
| 5 | 120s | Last-resort deep analysis |

Healer services must respond within the configured timeout or DAWN will treat it as a failure.

## Example Interaction

### Request
```bash
curl -X POST http://localhost:3000/api/heal \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "auto_calc_v2",
    "cycle": 1,
    "failed_files": {
      "logic.py": "def add(a, b)\n  return a + b"
    },
    "pytest_errors": {
      "exit_code": 2,
      "error_count": 1,
      "error_summary": "SyntaxError: invalid syntax",
      "stderr": "SyntaxError: expected ':' (logic.py, line 1)",
      "stdout": ""
    }
  }'
```

### Response
```json
{
  "status": "healed",
  "modified_files": {
    "logic.py": "def add(a, b):\n  return a + b"
  },
  "changes_summary": "Added missing colon after function definition"
}
```

## Implementation Notes

### For Healer Service Implementers

1. **Parse Error Context**: Extract line numbers, error types, and file locations from `pytest_errors.stderr`
2. **Context-Aware Fixing**: Use all provided files for context (imports, dependencies)
3. **Minimal Changes**: Only modify what's necessary to fix errors
4. **Preserve Formatting**: Maintain original code style where possible
5. **Return All Modified Files**: Even if only one file changed, include it in response

### For DAWN Integration

1. **Idempotent Requests**: Same error context should yield consistent fixes (for debugging)
2. **Error Handling**: Gracefully handle healer failures and continue to next cycle
3. **Metrics Tracking**: Record healer response times for performance analysis
4. **Security**: Consider adding authentication headers if deploying to production

## SAM Implementation Reference

SAM implements this API at `/api/heal` endpoint. See SAM documentation for:
- Authentication requirements
- Rate limiting
- Model selection (if supporting multiple LLMs)

## Future Extensions

Potential API enhancements (not yet implemented):

- **Language Support**: `"language": "python"` field for multi-language healers
- **Test Inclusion**: Send test files separately to distinguish code under test
- **Healing History**: Include previous cycle attempts to avoid repeated failures
- **Confidence Scores**: Healer returns confidence in fix quality
