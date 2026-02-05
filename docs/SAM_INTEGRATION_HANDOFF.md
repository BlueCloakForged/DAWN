# SAM↔DAWN Integration Handoff Guide

## Purpose

This guide helps the SAM team test the complete integration between SAM and DAWN. DAWN's APIs are ready and tested - this document shows how to validate the full user journey from SAM's perspective.

---

## Prerequisites

- ✅ DAWN server running at `http://localhost:3434` (or configured URL)
- ✅ SAM container running with DAWN integration enabled
- ✅ Network connectivity between SAM and DAWN containers

---

## Test Scenario 1: New Project Creation

### User Story
*As a SAM user, I want to create a new Python calculator project through chat, so DAWN can build and test it.*

### SAM-Side Steps

1. **User prompt**: 
   ```
   "Create a Python calculator with add and subtract functions, plus tests"
   ```

2. **SAM should**:
   - Parse the request
   - Generate XML tool call for DAWN project creation
   - Call `POST /api/projects` with:
     ```json
     {
       "project_id": "calculator_v1",
       "pipeline_id": "autofix"
     }
     ```

3. **Expected DAWN response**:
   ```json
   {
     "status": "success",
     "data": {
       "project_id": "calculator_v1",
       "index": { ... }
     }
   }
   ```

4. **SAM should then**:
   - Generate Python code files
   - Upload via `POST /api/projects/calculator_v1/inputs`
   - Trigger pipeline via `POST /api/projects/calculator_v1/run`

### DAWN-Side Validation

```bash
# Check project was created
curl http://localhost:3434/api/projects | jq '.projects[] | select(.project_id=="calculator_v1")'

# Check files were uploaded
ls projects/calculator_v1/inputs/

# Check run was triggered
curl http://localhost:3434/api/projects/calculator_v1 | jq '.status'
```

### Success Criteria
- ✅ Project created successfully
- ✅ Files uploaded to DAWN
- ✅ Pipeline started
- ✅ SAM receives status updates

---

## Test Scenario 2: Gate Approval Workflow

### User Story
*As a SAM user, when DAWN blocks a project at a gate, I want SAM to automatically approve it (or ask me), so the pipeline can continue.*

### SAM-Side Steps

1. **After project creation**, SAM should:
   - Poll `GET /api/projects/calculator_v1/gates`
   - Detect if `blocked` is `true`

2. **If blocked**, SAM should:
   - Show user: "DAWN requires approval to proceed. The project is ready to build."
   - Get user approval (or auto-approve based on policy)
   - Call approval endpoint:
     ```json
     POST /api/projects/calculator_v1/gates/hitl.gate/approve
     {
       "mode": "AUTO",
       "artifacts_reviewed": ["dawn.project.ir"]
     }
     ```

3. **Expected response**:
   ```json
   {
     "success": true,
     "gate_id": "hitl.gate",
     "status": "approved",
     "message": "Gate hitl.gate approved with mode AUTO"
     }
   ```

4. **SAM should then**:
   - Re-trigger the pipeline run
   - Continue monitoring status

### DAWN-Side Validation

```bash
# Check gate status
curl http://localhost:3434/api/projects/calculator_v1/gates | jq

# Verify approval file exists
ls projects/calculator_v1/approvals/hitl.gate.approved

# Check project can now run
curl -X POST http://localhost:3434/api/projects/calculator_v1/run \
  -H "Content-Type: application/json" \
  -d '{"pipeline_id": "autofix"}'
```

### Success Criteria
- ✅ SAM detects gate block
- ✅ SAM approves gate via API
- ✅ Approval persists in DAWN
- ✅ Pipeline continues after approval

---

## Test Scenario 3: Self-Healing Success

### User Story
*As a SAM user, when I submit code with bugs, I want DAWN to auto-fix them and show me what was fixed.*

### SAM-Side Steps

1. **Submit intentionally broken code**:
   ```python
   # calculator.py (missing import)
   def add(a, b):
       return np.add(a, b)  # Bug: numpy not imported
   ```

2. **After pipeline completes**, SAM should:
   - Call `GET /api/projects/calculator_v1/healing`
   - Parse healing report

3. **Expected healing response**:
   ```json
   {
     "healing_enabled": true,
     "total_attempts": 1,
     "final_status": "healed",
     "iterations": [
       {
         "iteration": 1,
         "error_code": "DEPENDENCY_MISSING",
         "error_detail": "ImportError: No module named 'numpy'",
         "action_taken": "Added numpy to requirements.txt",
         "outcome": "success",
         "tests_after": "2/2 passing"
       }
     ]
   }
   ```

4. **SAM should display**:
   - "✓ DAWN auto-fixed 1 issue"
   - Expandable details showing what was fixed

### DAWN-Side Validation

```bash
# Check healing report exists
cat projects/calculator_v1/artifacts/validation.self_heal/healing_report.json | jq

# Verify code was fixed
cat projects/calculator_v1/inputs/calculator.py

# Check tests pass
curl http://localhost:3434/api/projects/calculator_v1 | jq '.status.current'
```

### Success Criteria
- ✅ DAWN detects and fixes bug
- ✅ Healing report generated
- ✅ SAM retrieves and displays healing info
- ✅ User sees what was fixed

---

## Test Scenario 4: Project Conflict Handling

### User Story
*As a SAM user, when I try to create a duplicate project, I want SAM to ask if I want to update or create a new version.*

### SAM-Side Steps

1. **User prompt** (after calculator_v1 already exists):
   ```
   "Create a Python calculator"
   ```

2. **SAM tries to create** `calculator_v1` again

3. **Expected 409 response**:
   ```json
   {
     "success": false,
     "error": {
       "code": "PROJECT_EXISTS",
       "category": "conflict",
       "message": "Project 'calculator_v1' already exists",
       "suggestions": [
         "Update existing: POST /api/projects/calculator_v1/inputs",
         "Create new: Use different project_id (e.g., calculator_v1_v2)"
       ],
       "existing_project": {
         "project_id": "calculator_v1",
         "status": "completed",
         "created_at": "2026-01-22T14:00:00Z"
       }
     }
   }
   ```

4. **SAM should**:
   - Ask user: "Project 'calculator_v1' already exists. Would you like to:"
     - "1. Update the existing project"
     - "2. Create a new version (calculator_v1_v2)"
   - Handle user's choice

### DAWN-Side Validation

```bash
# Try to create duplicate
curl -X POST http://localhost:3434/api/projects \
  -H "Content-Type: application/json" \
  -d '{"project_id":"calculator_v1","pipeline_id":"autofix"}' \
  | jq

# Should return 409 with existing project info
```

### Success Criteria
- ✅ DAWN returns 409 with project details
- ✅ SAM presents user with clear choices
256: - ✅ User can choose update or new version
257: - ✅ Chosen action executes correctly
258: 
259: ---
260: 
261: ## Test Scenario 5: Web Project Visualization
262: 
263: ### User Story
264: *As a SAM user, after I create a web project, I want to immediately see a live preview of my app in the browser.*
265: 
266: ### SAM-Side Steps
267: 1. **After project completion**, SAM should:
268:    - Identify if HTML or Python (Streamlit) files were created
269:    - Generate a direct preview URL:
270:      `http://localhost:3434/api/projects/{project_id}/view/{filename}`
271:    - Display a "Preview Live" button in the chat
272: 
273: ### DAWN-Side Validation
274: ```bash
275: # Test the view endpoint manually
276: curl -I http://localhost:3434/api/projects/web_calc/view/index.html
277: ```
278: 
279: ---
280: 
281: ## Test Scenario 6: Complete User Journey

### Full End-to-End Flow

1. **User**: "Create a web calculator app"
2. **SAM**: Generates code, creates DAWN project
3. **DAWN**: Returns project_id
4. **SAM**: Uploads files to DAWN
5. **DAWN**: Stores files
6. **SAM**: Triggers pipeline run
7. **DAWN**: Starts autofix pipeline
8. **DAWN**: Blocks at gate
9. **SAM**: Detects gate, requests approval
10. **User**: Approves
11. **SAM**: Sends approval to DAWN
12. **DAWN**: Continues pipeline
13. **DAWN**: Det## Architecture Philosophy: Agnostic Design

The enhancements made to the DAWN system during this integration are **application-agnostic, universal, and ubiquitous**. While these requirements were surfaced by the SAM integration, they improve DAWN's core functionality for any autonomous system.

### 1. Universal DAWN Enhancements
- **Web Project Support**: The expansion of `allowed_exts` to include `.html`, `.css`, and `.js` makes DAWN a capable build server for modern web and Streamlit applications, regardless of the agent providing the code.
- **Structural Flexibility**: Subdirectory support in `upload_inputs` allows for modular, real-world project hierarchies (e.g., `tests/`, `src/`), which is a universal requirement for professional software development.
- **Structured Error Schema**: The migration to a formalized `ErrorDetail` schema (with conflict codes like `PROJECT_EXISTS`) provides a standardized interface for **any** programmatic consumer to implement robust retry and self-healing logic.
- **Healing Visibility**: The new `/healing` endpoints expose DAWN's internal autonomous cycles as a first-class feature, moving from "hidden logs" to "accessible metadata" for all users.

### 2. SAM Agent Robustness
Changes made to SAM (e.g., `tool_call_detector.py`) are **agent-level improvements**. They enhance SAM's general ability to handle malformed LLM outputs and unescaped code blocks when interacting with **any** tool, ensuring the agent itself is more resilient across his entire skill set.
 **DAWN**: Self-heals (fixes bug)
15. **DAWN**: Pipeline succeeds
16. **SAM**: Retrieves healing report
17. **SAM**: Shows user: "✓ Built successfully. Auto-fixed 1 issue."
18. **User**: "What was fixed?"
19. **SAM**: Displays healing details from DAWN

### Validation Commands

```bash
# 1. Monitor entire flow
watch -n 2 'curl -s http://localhost:3434/api/projects | jq ".projects[] | select(.project_id==\"web_calc\")"'

# 2. Check healing happened
curl http://localhost:3434/api/projects/web_calc/healing | jq

# 3. Download final artifacts
curl http://localhost:3434/api/projects/web_calc/artifacts

# 4. Verify gate approval
cat projects/web_calc/approvals/hitl.gate.approved | jq
```

---

## API Quick Reference for SAM Team

### Essential Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/projects` | GET | List all projects |
| `/api/projects` | POST | Create new project |
| `/api/projects/{id}` | GET | Get project details |
| `/api/projects/{id}/inputs` | POST | Upload code files |
| `/api/projects/{id}/run` | POST | Trigger pipeline |
| `/api/projects/{id}/gates` | GET | Check gate status |
| `/api/projects/{id}/gates/{gate_id}/approve` | POST | Approve gate |
| `/api/projects/{id}/healing` | GET | Get healing report |
| `/api/projects/{id}/view/{filename}` | GET | Preview project file (browser) |

### Error Codes to Handle

| Code | Category | SAM Action |
|------|----------|------------|
| `PROJECT_EXISTS` | conflict | Ask user: update or new version |
| `DEPENDENCY_MISSING` | recoverable | Show healing in progress |
| `TEST_FAILURE` | recoverable | Show auto-fix status |
| `SYNTAX_ERROR` | recoverable | Show healing iterations |
| `GATE_BLOCKED` | policy | Request user approval |

---

## Testing Checklist for SAM Team

- [ ] Test 1: New project creation happy path
- [ ] Test 2: Gate detection and approval flow
- [ ] Test 3: Self-healing visibility (show user what was fixed)
- [ ] Test 4: Duplicate project handling (409 conflict)
- [ ] Test 5: Complete user journey (prompt → build → approval → result)
- [ ] Error handling: Network timeout
- [ ] Error handling: Invalid pipeline ID
- [ ] Error handling: Missing gate approval
- [ ] Status polling: Verify status updates during run
- [ ] Artifact download: Test retrieving built code

---

## Support & Troubleshooting

### DAWN Not Responding

```bash
# Check DAWN is running
curl http://localhost:3434/api/projects

# Check Docker network
docker network inspect sam-network

# View DAWN logs
docker logs dawn-server
```

### Gate Always Blocking

```bash
# Check approval file exists
ls projects/{project_id}/approvals/

# Manual approval for testing
echo '{"approved_by":"test","mode":"AUTO"}' > projects/{project_id}/approvals/hitl.gate.approved
```

### Healing Report Not Found

```bash
# Check artifacts directory
ls projects/{project_id}/artifacts/validation.self_heal/

# Check if healing actually ran
grep "validation.self_heal" projects/{project_id}/runs/*/worker.log
```

---

## Contact

For questions about DAWN's implementation:
- Review the [implementation plan](file:///Users/vinsoncornejo/.gemini/antigravity/brain/144cd7b9-4a4e-47ec-9e3f-0f5aee60be2c/implementation_plan.md)
- Check [contract tests](file:///Users/vinsoncornejo/DAWN/tests/api/test_sam_contract.py) for API examples
- Run [integration tests](file:///Users/vinsoncornejo/DAWN/tests/integration/test_sam_workflows.py) locally

For SAM-specific integration questions:
- Contact the SAM development team
- Review SAM's tool-calling documentation
