"""
API Schema Definitions for SAM↔DAWN Integration

This module defines Pydantic models for structured API responses,
error handling, gate management, and healing metadata.
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


# ===== Error Response Models =====

class ErrorDetail(BaseModel):
    """Structured error information for API responses."""
    code: str = Field(..., description="Error code (e.g., 'PROJECT_EXISTS', 'TEST_FAILURE')")
    category: str = Field(..., description="Error category (e.g., 'recoverable', 'sandbox_restriction')")
    message: str = Field(..., description="Human-readable error message")
    self_heal_attempted: bool = Field(default=False, description="Whether self-healing was attempted")
    self_heal_result: Optional[str] = Field(None, description="Result of self-healing: 'success', 'failed', 'not_attempted'")
    self_heal_iterations: int = Field(default=0, description="Number of self-healing iterations performed")
    retry_recommended: bool = Field(default=False, description="Whether SAM should retry with different approach")
    user_action_required: bool = Field(default=False, description="Whether user intervention is needed")
    suggestions: Optional[List[str]] = Field(None, description="Suggested actions to resolve the error")


class ErrorResponse(BaseModel):
    """Standard error response wrapper."""
    success: bool = Field(default=False)
    error: ErrorDetail


# ===== Project Models =====

class ProjectCreate(BaseModel):
    """Request body for creating a new project."""
    project_id: str = Field(..., description="Unique project identifier (snake_case)")
    pipeline_id: str = Field(..., description="Pipeline to use for this project")
    profile: str = Field(default="normal", description="Execution profile: 'normal', 'isolated', etc.")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Arbitrary metadata (e.g., trace_id, user_id)")


class ProjectRun(BaseModel):
    """Request body for running a project pipeline."""
    pipeline_id: Optional[str] = Field(None, description="Override pipeline (uses project default if not specified)")
    profile: str = Field(default="normal", description="Execution profile")
    executor: str = Field(default="local", description="Executor type: 'local', etc.")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Arbitrary metadata for the run (e.g., trace_id)")


class ProjectSummary(BaseModel):
    """Summary information for a project (used in list view)."""
    project_id: str
    status: str = Field(..., description="Current project status: 'completed', 'running', 'failed', 'gate_blocked'")
    pipeline_id: Optional[str] = None
    created_at: Optional[str] = None
    last_modified: Optional[str] = None
    gate_blocked: bool = Field(default=False, description="Whether project is blocked by a gate")
    is_running: bool = Field(default=False, description="Whether project is currently executing")


class ExistingProjectInfo(BaseModel):
    """Information about an existing project (for 409 conflict responses)."""
    project_id: str
    status: str
    created_at: str


# ===== Gate Models =====

class GateApprovalActions(BaseModel):
    """Available actions for resolving a gate."""
    approve: str = Field(..., description="API endpoint to approve the gate")
    reject: Optional[str] = Field(None, description="API endpoint to reject the gate")
    skip: Optional[str] = Field(None, description="API endpoint to skip the gate")


class GateStatus(BaseModel):
    """Status of a specific gate."""
    gate_id: str = Field(..., description="Unique gate identifier (e.g., 'hitl.gate')")
    status: str = Field(..., description="Gate status: 'BLOCKED', 'AUTO', 'SKIP', 'APPROVED'")
    reason: Optional[str] = Field(None, description="Reason for gate block")
    approval_options: Optional[GateApprovalActions] = Field(None, description="Available approval actions")
    artifacts_to_review: Optional[List[str]] = Field(None, description="Artifacts that require review")
    approved_at: Optional[str] = Field(None, description="Timestamp when gate was approved")
    approved_by: Optional[str] = Field(None, description="Who/what approved the gate")


class GatesResponse(BaseModel):
    """Response for GET /api/projects/{id}/gates."""
    gates: List[GateStatus] = Field(default_factory=list)
    blocked: bool = Field(default=False, description="Whether any gate is currently blocking")


class GateApprovalRequest(BaseModel):
    """Request body for approving a gate."""
    mode: str = Field(..., description="Approval mode: 'AUTO', 'ONCE', 'SKIP'")
    artifacts_reviewed: Optional[List[str]] = Field(None, description="List of artifact IDs that were reviewed")
    reason: Optional[str] = Field(None, description="Reason for approval")


class GateApprovalResponse(BaseModel):
    """Response for POST /api/projects/{id}/gates/{gate_id}/approve."""
    success: bool = True
    gate_id: str
    status: str = Field(default="approved")
    message: Optional[str] = None


# ===== Healing Models =====

class HealingIteration(BaseModel):
    """Details of a single self-healing iteration."""
    iteration: int = Field(..., description="Iteration number (1-indexed)")
    error_code: str = Field(..., description="Error code detected")
    error_detail: str = Field(..., description="Detailed error message")
    action_taken: str = Field(..., description="What action the healer performed")
    outcome: str = Field(..., description="Result: 'success', 'failed', 'partial'")
    tests_after: Optional[str] = Field(None, description="Test status after healing (e.g., '3/3 passing')")
    timestamp: Optional[str] = Field(None, description="When this iteration occurred")


class HealingReport(BaseModel):
    """Complete healing report for a project run."""
    healing_enabled: bool = Field(default=True)
    total_attempts: int = Field(default=0, description="Total number of healing attempts")
    final_status: str = Field(..., description="Final healing outcome: 'healed', 'failed', 'not_needed'")
    iterations: List[HealingIteration] = Field(default_factory=list)
    run_id: Optional[str] = Field(None, description="Associated run ID")


# ===== Pipeline Models =====

class PipelineInfo(BaseModel):
    """Pipeline information."""
    id: str
    description: str
    path: Optional[str] = None


class AvailablePipelines(BaseModel):
    """List of available pipelines (for validation errors)."""
    available_pipelines: List[PipelineInfo]
    suggested: str = Field(default="autofix", description="Recommended default pipeline")


# ===== Utility Functions =====

def create_error_response(
    code: str,
    message: str,
    category: str = "unknown",
    self_heal_attempted: bool = False,
    self_heal_result: Optional[str] = None,
    retry_recommended: bool = False,
    user_action_required: bool = False,
    suggestions: Optional[List[str]] = None
) -> ErrorResponse:
    """
    Helper function to create structured error responses.
    
    Args:
        code: Error code (e.g., "PROJECT_EXISTS", "TEST_FAILURE")
        message: Human-readable error message
        category: Error category (e.g., "recoverable", "sandbox_restriction")
        self_heal_attempted: Whether self-healing was attempted
        self_heal_result: Result of self-healing
        retry_recommended: Whether SAM should retry
        user_action_required: Whether user intervention is needed
        suggestions: List of suggested actions
    
    Returns:
        ErrorResponse object
    """
    return ErrorResponse(
        success=False,
        error=ErrorDetail(
            code=code,
            category=category,
            message=message,
            self_heal_attempted=self_heal_attempted,
            self_heal_result=self_heal_result or ("not_attempted" if not self_heal_attempted else "unknown"),
            retry_recommended=retry_recommended,
            user_action_required=user_action_required,
            suggestions=suggestions or []
        )
    )


def create_conflict_response(
    project_id: str,
    existing_project: Dict[str, Any]
) -> ErrorResponse:
    """
    Create a 409 Conflict error response for duplicate projects.
    
    Args:
        project_id: The project ID that already exists
        existing_project: Project index data for the existing project
    
    Returns:
        ErrorResponse with conflict details
    """
    metadata = existing_project.get("metadata", {})
    status = existing_project.get("status", {}).get("current", "UNKNOWN")
    
    return create_error_response(
        code="PROJECT_EXISTS",
        message=f"Project '{project_id}' already exists",
        category="conflict",
        user_action_required=True,
        suggestions=[
            f"Update existing: POST /api/projects/{project_id}/inputs",
            f"Create new: Use different project_id (e.g., {project_id}_v2)"
        ]
    )
