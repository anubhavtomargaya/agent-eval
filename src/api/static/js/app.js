
// State
const state = {
    conversations: [],
    currentConversation: null,
    currentRating: 0,
    selectedTags: new Set(),
    annotatorId: localStorage.getItem('agent_eval_annotator_id') || 'reviewer_01',
    showNeedsReviewOnly: false
};

// DOM Elements
const els = {
    sidebarList: document.getElementById('sidebar-list'),
    detailView: document.getElementById('detail-view'),
    emptyView: document.getElementById('empty-view'),
    loadingOverlay: document.getElementById('loading-overlay'),
    // Feedback inputs
    ratingInput: document.getElementById('rating-input'),
    notesInput: document.getElementById('feedback-notes'),
    submitBtn: document.getElementById('submit-btn'),
    profileInput: null
};

async function init() {
    toggleLoading(true);
    try {
        renderProfile();
        await loadStats();
        // Default to Ingest tab for demo flow
        switchTab('ingest');

        // Background load sidebar for review tab
        loadSidebar();
    } catch (e) {
        showError(e.message);
    } finally {
        toggleLoading(false);
    }
}

function updateAnnotatorId(newId) {
    if (!newId) return;
    state.annotatorId = newId;
    localStorage.setItem('agent_eval_annotator_id', newId);
    console.log("Annotator ID updated:", newId);
}

function renderProfile() {
    const input = document.getElementById('profile-id-input');
    if (input) {
        input.value = state.annotatorId;
    }
}

// --- Tab Logic ---
function switchTab(tabId) {
    // Hide all tabs
    document.querySelectorAll('.tab-content').forEach(el => el.style.display = 'none');
    document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));

    // Show selected
    document.getElementById(`tab-${tabId}`).style.display = (tabId === 'review') ? 'flex' : 'flex';
    const navItem = document.getElementById(`nav-${tabId}`);
    if (navItem) navItem.classList.add('active');

    // Specific logic per tab
    if (tabId === 'review') {
        loadSidebar();
    } else if (tabId === 'evaluate') {
        // refresh pending count?
    } else if (tabId === 'analysis') {
        loadAnalysis();
    } else if (tabId === 'feedback') {
        loadFeedbackOps();
    }
}

// --- Ingest Tab ---
async function ingestData() {
    const input = document.getElementById('ingest-input').value;
    try {
        const data = JSON.parse(input);
        const conversations = Array.isArray(data) ? data : [data];

        toggleLoading(true);
        const res = await ApiClient.ingestBatch(conversations);
        toggleLoading(false);

        alert(`Ingested ${res.success} conversations successfully!`);
        document.getElementById('ingest-input').value = ''; // clear

        if (confirm("Go to Evaluate tab?")) {
            switchTab('evaluate');
        }
    } catch (e) {
        toggleLoading(false);
        showError("Invalid JSON or Ingestion Failed: " + e.message);
    }
}

// --- Evaluate Tab ---
async function runEvaluation() {
    toggleLoading(true);
    try {
        const allConvs = await ApiClient.getConversations(100, 0);
        const idsToEval = allConvs.filter(c => !c.has_evaluation).map(c => c.conversation_id);

        if (idsToEval.length === 0) {
            alert("No pending evaluations found (or all already evaluated).");
            if (!confirm("Re-evaluate all?")) {
                toggleLoading(false);
                return;
            }
            idsToEval.push(...allConvs.map(c => c.conversation_id));
        }

        const results = await ApiClient.evaluateBatch(idsToEval);

        const container = document.getElementById('eval-results');
        container.innerHTML = `<h3>Results</h3>` + results.map(r => `
            <div style="background:var(--bg-tertiary); padding:10px; margin-bottom:8px; border-radius:4px;">
                <strong>${r.conversation_id}</strong>: Score ${r.aggregate_score.toFixed(2)} 
                (${r.issues_count} issues)
            </div>
        `).join('');

    } catch (e) {
        showError(e.message);
    } finally {
        toggleLoading(false);
    }
}

// --- Analysis Tab ---
async function loadAnalysis() {
    toggleLoading(true);
    try {
        const proposals = await ApiClient.getProposals();
        const container = document.getElementById('analysis-list');

        if (proposals.length === 0) {
            container.innerHTML = `<div style="text-align:center; color:#666;">No improvement proposals generated yet.</div>`;
            return;
        }

        container.innerHTML = proposals.map(p => `
            <div style="background:var(--bg-secondary); border:1px solid var(--border-color); padding:16px; border-radius:8px;">
                <div style="display:flex; justify-content:space-between; margin-bottom:8px;">
                    <span style="font-weight:600; color:var(--accent-color); text-transform:uppercase; font-size:12px;">${p.type} IMPROVEMENT</span>
                    <span style="font-size:12px; color:var(--text-secondary);">${new Date(p.created_at).toLocaleDateString()}</span>
                </div>
                <div style="font-weight:500; margin-bottom:8px;">${p.rationale}</div>
                
                <div style="display:flex; gap:10px; font-size:12px; font-family:var(--font-mono); background:#0d1117; padding:10px; border-radius:6px; margin-bottom:12px;">
                    <div style="flex:1; border-right:1px solid #30363d; padding-right:10px;">
                        <div style="color:#f85149; margin-bottom:4px;">ORIGINAL</div>
                        ${p.original_content}
                    </div>
                    <div style="flex:1; padding-left:10px;">
                        <div style="color:#3fb950; margin-bottom:4px;">PROPOSED</div>
                        ${p.proposed_content}
                    </div>
                </div>
                
                <div style="font-size:12px; color:var(--text-secondary);">
                    Failure Pattern: ${p.failure_pattern} • Evidence: ${p.evidence_count} cases
                </div>
                <div style="margin-top:12px; display:flex; gap:8px;">
                    <button class="primary" style="max-width:160px;" onclick="applyProposal('${p.proposal_id}')">Apply</button>
                    <button class="primary" style="max-width:180px;" onclick="verifyProposal('${p.proposal_id}')">Verify (Real)</button>
                </div>
            </div>
        `).join('');
    } catch (e) {
        showError(e.message);
    } finally {
        toggleLoading(false);
    }
}

async function runAnalysis() {
    toggleLoading(true);
    try {
        await ApiClient.runAnalysis();
        await loadAnalysis();
    } catch (e) {
        showError(e.message);
    } finally {
        toggleLoading(false);
    }
}

async function applyProposal(proposalId) {
    toggleLoading(true);
    try {
        await ApiClient.applyProposal(proposalId);
        alert("Proposal applied. Active artifacts updated.");
    } catch (e) {
        showError(e.message);
    } finally {
        toggleLoading(false);
    }
}

async function verifyProposal(proposalId) {
    toggleLoading(true);
    try {
        const report = await ApiClient.verifyProposalReal(proposalId);
        alert(`Regression complete. Improvement: ${report.overall_improvement}`);
    } catch (e) {
        showError(e.message);
    } finally {
        toggleLoading(false);
    }
}

// --- Feedback Ops Tab ---
async function loadFeedbackOps() {
    await Promise.all([
        loadDisagreements(),
        loadMetrics()
    ]);
}

async function loadDisagreements() {
    const container = document.getElementById('feedback-disagreements');
    if (!container) return;
    container.textContent = 'Loading...';
    try {
        const data = await ApiClient.getDisagreements();
        container.textContent = data.length ? JSON.stringify(data, null, 2) : 'No disagreements found.';
    } catch (e) {
        container.textContent = `Error: ${e.message}`;
    }
}

async function loadMetrics() {
    const container = document.getElementById('feedback-metrics');
    const signal = document.getElementById('metrics-signal')?.value || 'helpfulness';
    if (!container) return;
    container.textContent = 'Loading...';
    try {
        const data = await ApiClient.getAgreementMetrics(signal);
        container.textContent = JSON.stringify(data, null, 2);
    } catch (e) {
        container.textContent = `Error: ${e.message}`;
    }
}

async function loadSamples() {
    const container = document.getElementById('feedback-samples');
    const limit = document.getElementById('sample-limit')?.value || 10;
    const threshold = document.getElementById('sample-threshold')?.value || 0.8;
    if (!container) return;
    container.textContent = 'Loading...';
    try {
        const data = await ApiClient.getSamples('confidence', limit, { threshold });
        container.textContent = data.length ? JSON.stringify(data, null, 2) : 'No samples found.';
    } catch (e) {
        container.textContent = `Error: ${e.message}`;
    }
}


// --- Review Tab (Shared) ---
async function loadStats() {
    // Optional
}

function toggleNeedsReview() {
    state.showNeedsReviewOnly = !state.showNeedsReviewOnly;
    loadSidebar();
}

async function loadSidebar() {
    const listContainer = document.getElementById('sidebar-list');
    listContainer.innerHTML = '<div style="padding:20px; text-align:center; color:var(--text-secondary);">Loading...</div>';

    try {
        let list;
        if (state.showNeedsReviewOnly) {
            // Use Confidence Sampling
            const samples = await ApiClient.getSamples('confidence', 50, { threshold: 0.8 });
            // Convert samples back to lightweight conv objects for display
            list = samples.map(s => ({
                conversation_id: s.conversation_id,
                created_at: s.created_at,
                turn_count: s.turn_count,
                has_evaluation: s.aggregate_score !== null,
                is_flagged: true // Mark as flagged
            }));
        } else {
            list = await ApiClient.getConversations(100, 0);
        }
        state.conversations = list;
        renderSidebar();
    } catch (e) {
        listContainer.innerHTML = `<div style="padding:10px; color:red; font-size:12px;">Error: ${e.message}</div>`;
    }
}

function renderSidebar() {
    const container = document.getElementById('sidebar-list');
    if (!container) return;

    // Add Toggle Button if not exists
    if (!document.getElementById('sidebar-controls')) {
        const controls = document.createElement('div');
        controls.id = 'sidebar-controls';
        controls.style.padding = '8px 16px';
        controls.style.borderBottom = '1px solid var(--border-color)';
        controls.innerHTML = `
            <button id="needs-review-btn" onclick="toggleNeedsReview()" 
                style="width:100%; padding:6px; background:transparent; border:1px solid var(--border-color); border-radius:4px; color:var(--text-secondary); font-size:11px; cursor:pointer; display:flex; align-items:center; justify-content:center; gap:6px;">
                <span>⚠️</span> Show Needs Review Only
            </button>
        `;
        container.parentNode.insertBefore(controls, container);
    }

    // Update button state
    const btn = document.getElementById('needs-review-btn');
    if (btn) {
        btn.style.background = state.showNeedsReviewOnly ? 'var(--accent-color)' : 'transparent';
        btn.style.color = state.showNeedsReviewOnly ? 'white' : 'var(--text-secondary)';
        btn.style.borderColor = state.showNeedsReviewOnly ? 'var(--accent-color)' : 'var(--border-color)';
    }

    if (state.conversations.length === 0) {
        container.innerHTML = `<div style="padding:20px; text-align:center; color:var(--text-secondary); font-size:12px;">No conversations found.</div>`;
        return;
    }

    container.innerHTML = state.conversations.map(c => `
        <div class="nav-item ${state.currentConversation && state.currentConversation.conversation_id === c.conversation_id ? 'active' : ''}" 
             onclick="loadConversationDetail('${c.conversation_id}')">
            <div style="font-weight:500; display:flex; justify-content:space-between;">
                ${c.conversation_id}
                ${c.is_flagged ? '<span>⚠️</span>' : ''}
            </div>
            <div style="font-size:11px; color:var(--text-secondary); display:flex; justify-content:space-between;">
                <span>${new Date(c.created_at).toLocaleTimeString()}</span>
                <span>${c.turn_count} turns</span>
            </div>
            ${c.has_evaluation ? '<div style="font-size:10px; color:var(--success-color);">Evaluated</div>' : ''}
        </div>
    `).join('');
}

async function loadConversationDetail(id) {
    toggleLoading(true);
    try {
        const conv = await ApiClient.getConversation(id);
        state.currentConversation = conv;
        renderSidebar();
        renderDetail(conv);
    } catch (e) {
        showError(e.message);
    } finally {
        toggleLoading(false);
    }
}

function renderDetail(conv) {
    document.getElementById('empty-view').style.display = 'none';
    document.getElementById('detail-view').style.display = 'flex';

    state.currentRating = 0;
    state.selectedTags.clear();
    resetFeedbackForm();

    document.getElementById('detail-header-title').textContent = conv.conversation_id;

    fetchAndrenderScores(conv.conversation_id);

    const chatContainer = document.getElementById('chat-stream');
    chatContainer.innerHTML = conv.turns.map(renderTurn).join('');

    chatContainer.scrollTop = chatContainer.scrollHeight;

    const feedbackContainer = document.getElementById('feedback-history');
    if (feedbackContainer) {
        if (conv.feedback && conv.feedback.length > 0) {
            feedbackContainer.innerHTML = conv.feedback.map(f => {
                const isMe = f.annotator_id === state.annotatorId;
                return `
                <div style="background:${isMe ? 'rgba(88, 166, 255, 0.1)' : 'var(--bg-tertiary)'}; 
                            border:${isMe ? '1px solid var(--accent-color)' : 'none'};
                            padding:8px; border-radius:4px; margin-bottom:8px; font-size:12px;">
                    <div style="display:flex; justify-content:space-between; color:var(--text-secondary); margin-bottom:4px;">
                        <span>${f.source || 'Unknown'} ${isMe ? '(You)' : ''}</span>
                        <span>${new Date(f.timestamp).toLocaleString()}</span>
                    </div>
                    <div><strong>Rating:</strong> ${f.value}</div>
                    ${f.notes ? `<div style="margin-top:4px; color:var(--text-secondary);">${f.notes}</div>` : ''}
                </div>
             `}).join('');
            document.getElementById('feedback-history-section').style.display = 'block';
        } else {
            feedbackContainer.innerHTML = '';
            document.getElementById('feedback-history-section').style.display = 'none';
        }
    }
}

async function fetchAndrenderScores(conversationId) {
    const container = document.getElementById('auto-scores');
    container.innerHTML = '<span style="color:#666;">Loading scores...</span>';

    try {
        const data = await ApiClient.getResults(conversationId);

        let html = `<div style="font-weight:600; color:var(--text-primary); margin-right:8px;">Aggregate: ${data.aggregate_score.toFixed(2)}</div>`;

        if (data.issues && data.issues.length > 0) {
            html += data.issues.map(i => `
                <span style="background:rgba(248, 81, 73, 0.2); color:#ff7b72; padding:2px 6px; border-radius:10px; border:1px solid rgba(248, 81, 73, 0.4); margin-right:4px;">
                    ${i.issue_type}
                </span>
            `).join('');
        } else {
            html += `<span style="color:var(--success-color);">No Issues</span>`;
        }

        container.innerHTML = html;

    } catch (e) {
        container.innerHTML = '<span style="color:#666; font-style:italic;">Not evaluated yet</span>';
    }
}

function renderTurn(turn) {
    const tools = turn.tool_calls.map(tc => `
        <div class="tool-call">
            <div class="tool-header">
                <span>🔨 ${tc.tool_name}</span>
            </div>
            <div class="tool-content">${JSON.stringify(tc.parameters, null, 2)}</div>
            ${tc.result ? `<div class="tool-content" style="border-top:1px solid #30363d; color:#8b949e;">Result: ${JSON.stringify(tc.result).slice(0, 200)}...</div>` : ''}
        </div>
    `).join('');

    return `
        <div class="message ${turn.role}">
            <div class="role-label">${turn.role} <span style="float:right;">${turn.latency_ms ? turn.latency_ms + 'ms' : ''}</span></div>
            <div class="bubble">
                ${turn.content || '<span style="color:#666; font-style:italic;">(No content)</span>'}
            </div>
            ${tools}
        </div>
    `;
}

function selectRating(r) {
    state.currentRating = r;
    const btns = document.getElementById('rating-input').children;
    for (let i = 0; i < btns.length; i++) {
        btns[i].classList.toggle('selected', i + 1 === r);
    }
}

function toggleTag(btn, tag) {
    if (state.selectedTags.has(tag)) {
        state.selectedTags.delete(tag);
        btn.classList.remove('selected');
    } else {
        state.selectedTags.add(tag);
        btn.classList.add('selected');
    }
}

async function submitFeedback() {
    if (!state.currentConversation) return;
    if (state.currentRating === 0) {
        alert("Please select a rating.");
        return;
    }

    const existing = state.currentConversation.feedback?.find(f => f.annotator_id === state.annotatorId);
    if (existing) {
        if (!confirm(`You already rated this conversation (Rating: ${existing.value}) on ${new Date(existing.timestamp).toLocaleDateString()}. Overwrite?`)) {
            return;
        }
    }

    const payload = {
        signal: "user_rating",
        value: state.currentRating,
        source: "human_reviewer",
        turn_id: null,
        notes: document.getElementById('feedback-notes').value + " Tags: " + Array.from(state.selectedTags).join(','),
        confidence: 1.0,
        annotator_id: state.annotatorId
    };

    const btn = document.getElementById('submit-btn');
    btn.textContent = "Submitting...";
    btn.disabled = true;

    try {
        await ApiClient.submitFeedback(state.currentConversation.conversation_id, payload);
        await loadConversationDetail(state.currentConversation.conversation_id);
    } catch (e) {
        showError(e.message);
    } finally {
        btn.textContent = "Submit Review";
        btn.disabled = false;
    }
}

function resetFeedbackForm() {
    state.currentRating = 0;
    state.selectedTags.clear();
    const ratingBtns = document.getElementById('rating-input').children;
    for (let b of ratingBtns) b.classList.remove('selected');
    const tagBtns = document.querySelectorAll('#tags-input button');
    for (let b of tagBtns) b.classList.remove('selected');
    document.getElementById('feedback-notes').value = '';
}

function toggleLoading(show) {
    const el = document.getElementById('loading-overlay');
    if (el) el.style.display = show ? 'flex' : 'none';
}

function showError(msg) {
    alert("Error: " + msg);
}

window.loadConversationDetail = loadConversationDetail;
window.selectRating = selectRating;
window.toggleTag = toggleTag;
window.submitFeedback = submitFeedback;
window.switchTab = switchTab;
window.ingestData = ingestData;
window.runEvaluation = runEvaluation;
window.loadAnalysis = loadAnalysis;
window.runAnalysis = runAnalysis;
window.applyProposal = applyProposal;
window.verifyProposal = verifyProposal;
window.updateAnnotatorId = updateAnnotatorId;
window.toggleNeedsReview = toggleNeedsReview;
window.loadDisagreements = loadDisagreements;
window.loadMetrics = loadMetrics;
window.loadSamples = loadSamples;

document.addEventListener('DOMContentLoaded', init);
