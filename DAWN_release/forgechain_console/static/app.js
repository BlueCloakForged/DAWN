// App State
let pipelines = [];
let projects = [];
let selectedProjectId = null;
let pollInterval = null;
let logSource = null;

// DOM Elements
const elPipelineList = document.getElementById('pipeline-list');
const elProjectList = document.getElementById('project-list');
const elProjectDetails = document.getElementById('project-details');

// Close Modals
document.addEventListener('click', (e) => {
    if (e.target.classList.contains('close-modal') || e.target.classList.contains('modal')) {
        document.querySelectorAll('.modal').forEach(m => m.classList.remove('open'));
    }
});

// Close Modals
document.querySelectorAll('.close-modal').forEach(btn => {
    btn.onclick = () => {
        document.querySelectorAll('.modal').forEach(m => m.classList.remove('open'));
    };
});

window.onclick = (event) => {
    if (event.target.classList.contains('modal')) {
        event.target.classList.remove('open');
    }
};
const elNewProjectPipeline = document.getElementById('new-project-pipeline');

// --- Initialization ---

async function init() {
    await loadPipelines();
    await loadProjects();

    // UI Event Listeners
    document.getElementById('btn-refresh').addEventListener('click', loadProjects);
    document.getElementById('btn-new-project').addEventListener('click', () => {
        document.getElementById('modal-new-project').classList.add('open');
    });

    document.querySelectorAll('.close-modal').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.modal').forEach(m => m.classList.remove('open'));
        });
    });

    document.getElementById('btn-create-project').addEventListener('click', createProject);

    // Global Poll for active projects
    setInterval(pollActiveProjects, 3000);
}

// --- Data Fetching ---

async function loadPipelines() {
    try {
        const response = await fetch('/api/pipelines');
        pipelines = await response.json();
        renderPipelines();
        renderPipelineSelect();
    } catch (err) {
        console.error("Failed to load pipelines", err);
    }
}

async function loadProjects() {
    try {
        const response = await fetch('/api/projects');
        projects = await response.json();
        renderProjects();
        if (selectedProjectId) {
            await selectProject(selectedProjectId);
        }
    } catch (err) {
        console.error("Failed to load projects", err);
    }
}

async function pollActiveProjects() {
    // If we have projects that are "RUNNING", refresh the list
    const hasRunning = projects.some(p => p.is_running);
    if (hasRunning) {
        await loadProjects();
    }
}

// --- Rendering ---

function renderPipelines() {
    elPipelineList.innerHTML = pipelines.map(p => `
        <div class="sidebar-item" onclick="viewPipeline('${p.id}')">
            <span class="item-id">${p.id}</span>
            <span class="item-meta">v${p.version} • ${p.estimated_duration_seconds}s</span>
        </div>
    `).join('');
    document.getElementById('pipeline-count').textContent = pipelines.length;
}

function renderPipelineSelect() {
    elNewProjectPipeline.innerHTML = pipelines.map(p => `
        <option value="${p.id}">${p.id} (v${p.version})</option>
    `).join('');
}

function viewPipeline(pipelineId) {
    const pipeline = pipelines.find(p => p.id === pipelineId);
    if (!pipeline) {
        console.error('Pipeline not found:', pipelineId);
        return;
    }

    // Display pipeline details in an alert for now
    const details = `
Pipeline: ${pipeline.id}
Version: ${pipeline.version}
Description: ${pipeline.description}
Intended Use: ${pipeline.intended_use || 'N/A'}
Est. Duration: ${pipeline.estimated_duration_seconds || 'N/A'}s
Profile: ${pipeline.profile || 'normal'}

Required Inputs:
${(pipeline.required_inputs || []).map(inp => `  • ${inp.name}${inp.optional ? ' (optional)' : ''}`).join('\n') || '  None'}

Expected Outputs:
${(pipeline.expected_outputs || []).map(art => `  • ${art}`).join('\n') || '  None'}
    `.trim();

    alert(details);
}

function renderProjects() {
    elProjectList.innerHTML = projects.map(p => {
        let overallStatus = p.last_status || "PENDING";
        if (p.is_running) overallStatus = "RUNNING";

        return `
            <div class="project-card ${selectedProjectId === p.id ? 'active' : ''}" onclick="selectProject('${p.id}')">
                <div class="card-header">
                    <span class="item-id">${p.id}</span>
                    <span class="card-status status-${overallStatus.toLowerCase()} ${overallStatus === 'RUNNING' ? 'pulse' : ''}">${overallStatus}</span>
                </div>
                <div class="card-meta">
                    <span>Pipeline: ${p.pipeline_id || 'Unknown'}</span>
                    <span style="font-size: 0.7rem;">${p.is_running ? 'RUNNING NOW' : `Updated: ${p.last_updated_at || 'Never'}`}</span>
                </div>
            </div>
        `;
    }).join('');
}

// --- Actions ---

async function selectProject(id) {
    selectedProjectId = id;
    renderProjects(); // Highlight active

    try {
        const response = await fetch(`/api/projects/${id}`);
        const data = await response.json();
        renderProjectDetails(data);
    } catch (err) {
        console.error("Failed to load project details", err);
    }
}

function renderProjectDetails(data) {
    const pipelineId = data.pipeline?.id || "Unknown";
    const status = data.runs?.last_status || "PENDING";
    const lastError = data.runs?.last_error;

    elProjectDetails.innerHTML = `
        <div class="details-header">
            <h2>${data.project_id}</h2>
            <p class="subtitle">Pipeline: ${pipelineId} (${data.pipeline?.profile || 'normal'})</p>
        </div>
        <div class="details-body">
            <div class="section">
                <p class="section-title">Status: ${status} ${data.runs?.is_running ? '(RUNNING)' : ''}</p>
                ${lastError ? `<p style="color: var(--failure); font-size: 0.8rem; margin-bottom: 12px;">Error: ${lastError}</p>` : ''}
                <div class="form-group">
                    <label>Executor</label>
                    <select id="run-executor">
                        <option value="local" ${data.pipeline?.executor === 'local' ? 'selected' : ''}>Local (In-process)</option>
                        <option value="subprocess" ${data.pipeline?.executor === 'subprocess' ? 'selected' : ''}>Subprocess (Isolated)</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>Profile</label>
                    <select id="run-profile">
                        <option value="normal" ${data.pipeline?.profile === 'normal' ? 'selected' : ''}>Normal</option>
                        <option value="isolation" ${data.pipeline?.profile === 'isolation' ? 'selected' : ''}>Isolation</option>
                    </select>
                </div>
                <button class="btn btn-primary ${data.runs?.is_running ? 'pulse' : ''}" 
                        onclick="runPipeline('${data.project_id}')" 
                        ${data.runs?.is_running ? 'disabled' : ''}>
                    ${data.runs?.is_running ? 'Executing...' : 'Run Pipeline'}
                </button>
            </div>

            <div class="section" style="margin-top: 32px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                    <p class="section-title" style="margin-bottom: 0;">Run History</p>
                    <button class="btn btn-secondary" style="font-size: 0.7rem; padding: 4px 10px;" onclick="compareRuns('${data.project_id}')">Compare Runs</button>
                </div>
                <div class="run-history-list">
                    ${(data.runs?.history || []).map(run => `
                        <div class="run-history-item ${data.is_running && run.run_id === data.runs?.last_run_id ? 'active' : ''}" 
                             onclick="showTerminal('${data.project_id}', '${run.run_id}', ${data.is_running && run.run_id === data.runs?.last_run_id})">
                            <div>
                                <span style="font-weight: 600;">${run.run_id}</span>
                                <div class="run-meta-small">${run.started_at} • ${run.executor} (${run.profile})</div>
                            </div>
                            <span class="card-status status-${(run.status || 'UNKNOWN').toLowerCase()}">${run.status || 'PENDING'}</span>
                        </div>
                    `).join('')}
                    ${!(data.runs?.history?.length) ? '<p class="subtitle" style="font-size:0.8rem; opacity:0.6;">No previous runs.</p>' : ''}
                </div>
            </div>

            <div class="section" style="margin-top: 32px;">
                <p class="section-title">Configuration / Inputs <span id="editor-dirty" class="dirty-indicator" style="display: none;">• Modified</span></p>
                <div id="inputs-browser" style="display: flex; gap: 8px; margin-bottom: 12px; overflow-x: auto; padding-bottom: 4px;">
                    <!-- Input file chips injected here -->
                </div>
                <input type="hidden" id="current-input-file" value="idea.md">
                <textarea id="input-editor" placeholder="Select a file to edit..." oninput="onEditorChange()"></textarea>
                <button id="btn-save-input" class="btn btn-secondary" style="margin-top: 8px; width: 100%;" 
                        onclick="saveInput('${data.project_id}')">Save changes</button>
            </div>

            <div class="section" style="margin-top: 32px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                    <p class="section-title" style="margin-bottom: 0;">Downloads</p>
                    ${(data.downloads?.project_report) ? `<a href="/api/projects/${data.project_id}/report" target="_blank" class="btn btn-secondary" style="font-size: 0.7rem; padding: 4px 10px;">Open Report</a>` : ''}
                </div>
                <div id="download-list">
                    ${Object.entries(data.downloads || {}).map(([kind, entry]) => {
        const relPath = typeof entry === 'string' ? entry : entry.path;
        if (!relPath) return '';
        return `
                            <a href="/api/projects/${data.project_id}/download/${kind}" class="artifact-link">
                                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                                ${kind.replace(/_/g, ' ').toUpperCase()}
                            </a>
                        `;
    }).join('')}
                    ${!(Object.keys(data.downloads || {}).length) ? '<p class="subtitle" style="font-size:0.8rem; opacity:0.6;">No stable downloads available.</p>' : ''}
                </div>
            </div>

            <div class="section" style="margin-top: 32px;">
                <p class="section-title">Artifact Registry</p>
                <div id="artifact-list">
                    ${Object.values(data.artifacts || {}).map(art => `
                        <div class="artifact-link" style="justify-content: space-between; cursor: pointer;" 
                             onclick="previewArtifact('${data.project_id}', '${art.artifactId}')">
                            <div style="display: flex; align-items: center; gap: 12px;">
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V9z"/><polyline points="13 2 13 9 20 9"/></svg>
                                <span>${art.artifactId}</span>
                            </div>
                            <span style="font-size: 0.7rem; color: var(--text-muted);">${(art.size_bytes / 1024).toFixed(1)} KB</span>
                        </div>
                    `).join('')}
                    ${!(Object.keys(data.artifacts || {}).length) ? '<p class="subtitle" style="font-size:0.8rem; opacity:0.6;">No artifacts generated yet.</p>' : ''}
                </div>
            </div>

            ${(data.status === 'BLOCKED' || data.runs?.last_status === 'FAILED') ? `
                <div class="section" style="margin-top: 24px; padding: 16px; background: rgba(245, 158, 11, 0.1); border: 1px solid var(--running); border-radius: 8px;">
                    <p style="color: var(--running); font-weight: 600; font-size: 0.9rem; margin-bottom: 8px;">Action Required</p>
                    <p class="subtitle" style="font-size: 0.8rem; margin-bottom: 12px;">A gate or approval is blocking the pipeline.</p>
                    <div style="display: flex; gap: 8px;">
                        <button class="btn btn-primary" style="font-size: 0.8rem; padding: 6px 12px;" onclick="showGateDecision('${data.project_id}', 'human_decision.json')">Resolve human_review</button>
                        <button class="btn btn-secondary" style="font-size: 0.8rem; padding: 6px 12px;" onclick="showGateDecision('${data.project_id}', 'patch_approval.json')">Resolve patch_approval</button>
                    </div>
                </div>
            ` : ''}
        </div>
    `;

    // Load inputs list
    loadInputsList(data.project_id);
}

let isEditorDirty = false;

function onEditorChange() {
    isEditorDirty = true;
    document.getElementById('editor-dirty').style.display = 'inline';
}

async function loadInputsList(projectId) {
    const browser = document.getElementById('inputs-browser');
    try {
        const response = await fetch(`/api/projects/${projectId}/inputs`);
        const data = await response.json();
        const currentFile = document.getElementById('current-input-file').value;

        browser.innerHTML = (data.files || []).map(f => `
            <div class="input-chip ${f.name === currentFile ? 'active' : ''}" 
                 onclick="switchInput('${projectId}', '${f.name}')">
                ${f.name}
            </div>
        `).join('');

        if (currentFile) loadInput(projectId, currentFile);
    } catch (err) {
        browser.innerHTML = `<span class="subtitle">Failed to load inputs.</span>`;
    }
}

async function switchInput(projectId, filename) {
    if (isEditorDirty) {
        if (!confirm("You have unsaved changes. Discard them?")) return;
    }
    document.getElementById('current-input-file').value = filename;
    isEditorDirty = false;
    document.getElementById('editor-dirty').style.display = 'none';

    // Refresh chips
    document.querySelectorAll('.input-chip').forEach(c => {
        c.classList.toggle('active', c.innerText.trim() === filename);
    });

    loadInput(projectId, filename);
}

async function loadInput(projectId, filename) {
    try {
        const textarea = document.getElementById('input-editor');
        textarea.value = "Loading...";
        const response = await fetch(`/api/projects/${projectId}/inputs/${filename}`);
        const data = await response.json();
        if (data.content !== undefined) {
            textarea.value = data.content;
        } else {
            textarea.value = "";
        }
    } catch (err) {
        console.error("Failed to load input", err);
    }
}

async function saveInput(projectId) {
    const filename = document.getElementById('current-input-file').value;
    const content = document.getElementById('input-editor').value;

    if (content.length > 50000) {
        alert("File too large (max 50KB for inline editing)");
        return;
    }

    try {
        const response = await fetch(`/api/projects/${projectId}/inputs/${filename}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content })
        });
        const res = await response.json();
        if (response.ok) {
            isEditorDirty = false;
            document.getElementById('editor-dirty').style.display = 'none';
            alert(res.message);
        } else {
            alert(res.detail || "Failed to save");
        }
    } catch (err) {
        alert("Failed to save input");
    }
}

async function runPipeline(projectId) {
    const executor = document.getElementById('run-executor').value;
    const profile = document.getElementById('run-profile').value;

    try {
        const response = await fetch(`/api/projects/${projectId}/run`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ executor, profile })
        });
        const res = await response.json();
        if (res.status === 'success') {
            await loadProjects();
            // Start streaming logs immediately
            showTerminal(projectId, res.run_id, true);
        } else {
            alert(res.detail);
        }
    } catch (err) {
        alert("Execution failed to trigger");
    }
}

// --- Terminal & Logs ---

function showTerminal(projectId, runId, isLive = false) {
    const overlay = document.getElementById('terminal-overlay');
    const output = document.getElementById('terminal-output');
    const title = document.getElementById('terminal-title');
    const badge = document.getElementById('terminal-status');

    overlay.classList.add('open');
    output.textContent = "";
    title.textContent = `Logs: ${projectId} (${runId})`;

    if (isLive) {
        badge.textContent = "LIVE";
        badge.classList.add('live');
        streamLogs(projectId, runId);
    } else {
        badge.textContent = "HISTORICAL";
        badge.classList.remove('live');
        loadRunLogs(projectId, runId);
    }
}

function hideTerminal() {
    if (logSource) {
        logSource.close();
        logSource = null;
    }
    document.getElementById('terminal-overlay').classList.remove('open');
}

function streamLogs(projectId, runId) {
    if (logSource) logSource.close();

    const output = document.getElementById('terminal-output');
    logSource = new EventSource(`/api/projects/${projectId}/runs/${runId}/logs?stream=1`);

    logSource.onmessage = (event) => {
        const line = event.data;
        output.textContent += line + "\n";
        output.scrollTop = output.scrollHeight;
    };

    logSource.onerror = (err) => {
        console.error("SSE Error", err);
        // Don't close immediately, might be transient or waiting for file
    };
}

async function loadRunLogs(projectId, runId) {
    const output = document.getElementById('terminal-output');
    try {
        const response = await fetch(`/api/projects/${projectId}/runs/${runId}/logs?stream=0`);
        const data = await response.json();
        output.textContent = data.logs || "No logs available.";
    } catch (err) {
        output.textContent = "Error loading logs.";
    }
}

// --- Artifact Preview ---

async function previewArtifact(projectId, artifactId) {
    const modal = document.getElementById('modal-artifact-preview');
    const title = document.getElementById('artifact-preview-title');
    const container = document.getElementById('artifact-content-container');
    const btnDownload = document.getElementById('btn-download-artifact');

    title.textContent = `Preview: ${artifactId}`;
    container.innerHTML = "Loading...";
    btnDownload.href = `/api/projects/${projectId}/artifact/${artifactId}`;
    modal.classList.add('open');

    try {
        const response = await fetch(`/api/projects/${projectId}/artifact/${artifactId}`);
        const contentType = response.headers.get("content-type");

        if (contentType.includes("application/json") || contentType.includes("text/plain")) {
            const text = await response.text();
            container.innerHTML = `<pre>${escapeHtml(text)}</pre>`;
        } else if (contentType.includes("text/html")) {
            container.innerHTML = `<iframe src="/api/projects/${projectId}/artifact/${artifactId}"></iframe>`;
        } else {
            container.innerHTML = `
                <div style="padding: 40px; text-align: center; width: 100%;">
                    <p>Preview not available for this file type.</p>
                    <p class="subtitle">${contentType}</p>
                </div>
            `;
        }
    } catch (err) {
        container.innerHTML = `<div style="padding: 20px;">Error loading artifact content.</div>`;
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// --- Gate Decisions ---

function showGateDecision(projectId, filename) {
    const modal = document.getElementById('modal-gate-decision');
    document.getElementById('gate-filename').value = filename;
    document.getElementById('gate-description').textContent = `Please provide a decision for ${filename} in project ${projectId}.`;
    modal.classList.add('open');
}

document.getElementById('btn-submit-gate')?.addEventListener('click', async () => {
    const projectId = selectedProjectId;
    const filename = document.getElementById('gate-filename').value;
    const decision = document.getElementById('gate-decision-select').value;
    const reason = document.getElementById('gate-reason').value;

    try {
        const response = await fetch(`/api/projects/${projectId}/gate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filename, decision, reason })
        });
        const res = await response.json();
        if (res.status === 'success') {
            document.getElementById('modal-gate-decision').classList.remove('open');
            await selectProject(projectId); // Refresh details
            alert("Decision submitted successfully. You can now re-run the pipeline.");
        } else {
            alert(res.detail);
        }
    } catch (err) {
        alert("Failed to submit decision.");
    }
});

// --- Run Comparison ---

async function compareRuns(projectId) {
    const history = (projects.find(p => p.id === projectId)?.runs?.history || []);
    if (history.length < 2) {
        alert("Need at least 2 runs to compare.");
        return;
    }

    const r1 = history[0].run_id;
    const r2 = history[1].run_id;

    try {
        const response = await fetch(`/api/projects/${projectId}/compare-runs?r1=${r1}&r2=${r2}`);
        const data = await response.json();
        const modal = document.getElementById('modal-comparison');
        const body = document.getElementById('comparison-body');

        body.innerHTML = `
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px;">
                <div style="padding: 20px; border: 1px solid var(--border-color); border-radius: 8px;">
                    <h4>Run 1: ${data.run1.run_id}</h4>
                    <p>Status: ${data.run1.status}</p>
                    <p>Profile: ${data.run1.profile}</p>
                    <p>Ended: ${data.run1.ended_at}</p>
                </div>
                <div style="padding: 20px; border: 1px solid var(--border-color); border-radius: 8px;">
                    <h4>Run 2: ${data.run2.run_id}</h4>
                    <p>Status: ${data.run2.status}</p>
                    <p>Profile: ${data.run2.profile}</p>
                    <p>Ended: ${data.run2.ended_at}</p>
                </div>
            </div>
            <div style="margin-top: 20px; padding: 15px; background: rgba(255,255,255,0.05); border-radius: 8px;">
                <h4>Diff Summary</h4>
                <ul>
                    <li>Status Changed: ${data.diff.status_changed ? 'Yes' : 'No'}</li>
                    <li>Profile Changed: ${data.diff.profile_changed ? 'Yes' : 'No'}</li>
                </ul>
            </div>
        `;
        modal.classList.add('open');
    } catch (err) {
        alert("Comparison failed.");
    }
}

async function createProject() {
    const project_id = document.getElementById('new-project-id').value;
    const pipeline_id = document.getElementById('new-project-pipeline').value;
    const profile = document.getElementById('new-project-profile').value;

    if (!project_id) return alert("Project ID is required");

    try {
        const response = await fetch('/api/projects', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ project_id, pipeline_id, profile })
        });
        const res = await response.json();
        if (response.ok && res.status === 'success' && res.data) {
            // Close modal first for better UX
            document.querySelectorAll('.modal').forEach(m => m.classList.remove('open'));

            // Refresh project list to include new project
            await loadProjects();

            // Auto-select the newly created project with full state
            selectedProjectId = res.data.project_id;

            // Render project details immediately with the index data from response
            renderProjectDetails(res.data.index);

            // Load inputs, artifacts, and runs for the new project
            await loadInputsList(res.data.project_id);

            // Highlight selected project in list
            document.querySelectorAll('.project-card').forEach(card => {
                if (card.dataset.id === res.data.project_id) {
                    card.classList.add('selected');
                } else {
                    card.classList.remove('selected');
                }
            });
        } else {
            // Keep modal open and show error
            alert(res.detail || "Failed to create project");
        }
    } catch (err) {
        // Keep modal open and show error
        console.error("Create project error:", err);
        alert("Failed to create project: " + err.message);
    }
}

init();
