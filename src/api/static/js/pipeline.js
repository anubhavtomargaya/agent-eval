/**
 * Pipeline Demo - Unprocessed conversations via backend API
 */

const API_BASE = window.location.origin === 'null'
    ? 'http://localhost:8000'
    : window.location.origin;

let conversationList = [];
let activeConversation = null;
let activeConversationId = null;
let ingestedConversationId = null;
let proposals = [];
const rawByStage = {};

document.addEventListener('DOMContentLoaded', () => {
    loadConversationList();
});

async function loadConversationList() {
    try {
        const res = await fetch(`${API_BASE}/demo/unprocessed-conversations`);
        const data = await res.json();
        conversationList = data.conversations || [];
        renderSidebar();
        if (conversationList.length > 0) {
            await setActiveConversation(conversationList[0].id, false);
        }
    } catch (e) {
        console.error('Failed to load conversations:', e);
        document.getElementById('conv-count').textContent = '0';
        document.getElementById('conv-list').innerHTML = `<div class="conv-item issue">Failed to load</div>`;
    }
}

function renderSidebar() {
    const list = document.getElementById('conv-list');
    document.getElementById('conv-count').textContent = conversationList.length;

    if (conversationList.length === 0) {
        list.innerHTML = `<div class="conv-item issue">No conversations</div>`;
        return;
    }

    list.innerHTML = conversationList.map(c => `
        <div class="conv-item ${c.type || 'issue'}" onclick="showConversation('${c.id}')">
            <span class="conv-dot ${c.type || 'issue'}"></span>
            <span>${c.id}</span>
        </div>
    `).join('');
}

async function showConversation(id) {
    await setActiveConversation(id, true);
}

async function setActiveConversation(id, openModal) {
    try {
        const res = await fetch(`${API_BASE}/demo/unprocessed-conversations/${id}`);
        const conv = await res.json();
        activeConversationId = id;
        activeConversation = conv;
        resetPipeline();
        renderSelectedConversation();
        if (openModal) {
            renderConversationModal(conv);
            document.getElementById('conv-modal').classList.add('active');
        }
    } catch (e) {
        console.error('Failed to load conversation:', e);
    }
}

function renderSelectedConversation() {
    const el = document.getElementById('s1-out');
    if (!activeConversation) {
        el.textContent = 'Select a conversation from the sidebar.';
        return;
    }

    const meta = activeConversation.metadata || {};
    const metaBits = [];
    if (meta.scenario) metaBits.push(`scenario=${meta.scenario}`);
    if (meta.agent_version) metaBits.push(`agent_version=${meta.agent_version}`);

    el.textContent = [
        `📄 Selected: ${activeConversation.conversation_id || activeConversationId}`,
        `🧾 Turns: ${(activeConversation.turns || []).length}`,
        metaBits.length ? `🏷️ ${metaBits.join(' • ')}` : null,
        ``,
        `Click "Run Pipeline" or run stages individually by expanding each stage.`
    ].filter(Boolean).join('\n');
    el.classList.add('active');
}

function resetPipeline() {
    ingestedConversationId = null;
    proposals = [];
    rawByStage[1] = null;
    rawByStage[2] = null;
    rawByStage[3] = null;
    rawByStage[4] = null;
    rawByStage[5] = null;

    setStatus(1, 'ready', 'Ready');
    setStatus(2, 'ready', 'Waiting');
    setStatus(3, 'ready', 'Waiting');
    setStatus(4, 'ready', 'Waiting');
    setStatus(5, 'ready', 'Waiting');

    document.getElementById('s2-out').classList.remove('active');
    document.getElementById('s3-out').classList.remove('active');
    document.getElementById('s4-out').classList.remove('active');
    document.getElementById('s5-out').classList.remove('active');

    document.getElementById('proposals').innerHTML = '';
    document.getElementById('stats').style.display = 'none';
    document.getElementById('s-conv').textContent = '1';
    document.getElementById('s-issues').textContent = '0';
    document.getElementById('s-score').textContent = '0.00';
    document.getElementById('s-prop').textContent = '0';
}

function toggleStage(n) {
    document.getElementById(`stage-${n}`).classList.toggle('expanded');
}

function setStatus(n, type, text) {
    const el = document.getElementById(`s${n}-status`);
    el.className = 'stage-status ' + type;
    el.innerHTML = type === 'running' ? `<span class="spinner"></span> ${text}` : text;

    const stage = document.getElementById(`stage-${n}`);
    stage.classList.remove('active', 'complete', 'error');
    if (type === 'running') stage.classList.add('active');
    if (type === 'success') stage.classList.add('complete');
    if (type === 'error') stage.classList.add('error');
}

function setOut(n, txt) {
    const el = document.getElementById(`s${n}-out`);
    el.textContent = txt;
    el.classList.add('active');
    el.scrollTop = el.scrollHeight;
}

function appendOut(n, txt) {
    const el = document.getElementById(`s${n}-out`);
    if (!el.classList.contains('active')) {
        el.textContent = '';
        el.classList.add('active');
    }
    el.textContent += txt + '\n';
    el.scrollTop = el.scrollHeight;
}

function formatMs(ms) {
    if (ms === null || ms === undefined) return '—';
    if (ms >= 1000) return `${(ms / 1000).toFixed(2)}s`;
    return `${ms.toFixed(1)}ms`;
}

function truncate(text, maxLen) {
    if (!text) return '';
    if (text.length <= maxLen) return text;
    return text.slice(0, Math.max(0, maxLen - 1)) + '…';
}

function formatScores(scores) {
    if (!scores) return '';
    const entries = Object.entries(scores);
    if (entries.length === 0) return '';
    return entries.map(([k, v]) => `${k}=${typeof v === 'number' ? v.toFixed(2).replace(/\\.00$/, '') : v}`).join(' ');
}

function summarizeIssues(issues) {
    if (!issues || issues.length === 0) return ['✅ No issues'];
    return issues.map(i => {
        const turn = i.turn_id !== null && i.turn_id !== undefined ? ` (turn ${i.turn_id})` : '';
        const sev = i.severity ? `[${i.severity}] ` : '';
        return `- ${sev}${i.issue_type}${turn}: ${truncate(i.description || '', 140)}`.trim();
    });
}

async function apiCall(endpoint, method = 'GET', body = null) {
    const url = endpoint.startsWith('http') ? endpoint : `${API_BASE}${endpoint}`;
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body) opts.body = JSON.stringify(body);
    const res = await fetch(url, opts);
    if (!res.ok) throw new Error(await res.text());
    return res.json();
}

async function runPipeline() {
    const btn = document.getElementById('run-btn');
    btn.disabled = true;
    btn.textContent = '⏳ Running...';

    try {
        await stage1();
        await stage2();
        await stage3();
        await stage4();
        if (proposals.length > 0) {
            await stage5();
        }

        document.getElementById('stats').style.display = 'flex';
    } catch (e) {
        console.error(e);
    }

    btn.disabled = false;
    btn.textContent = '▶ Run Pipeline';
}

async function stage1() {
    document.getElementById('stage-1').classList.add('expanded');
    if (!activeConversation) {
        setStatus(1, 'error', 'Missing');
        setOut(1, 'No conversation selected.');
        throw new Error('No conversation selected');
    }

    setStatus(1, 'running', 'Ingesting...');
    try {
        setOut(1, '');
        appendOut(1, `📄 Selected: ${activeConversation.conversation_id || activeConversationId}`);
        appendOut(1, `🧾 Turns: ${(activeConversation.turns || []).length}`);
        if (activeConversation.metadata?.scenario) appendOut(1, `🏷️ scenario=${activeConversation.metadata.scenario}`);
        if (activeConversation.metadata?.agent_version) appendOut(1, `🏷️ agent_version=${activeConversation.metadata.agent_version}`);
        appendOut(1, '');
        appendOut(1, `➡️ POST /ingest`);

        const res = await apiCall('/ingest', 'POST', { conversations: [activeConversation] });
        rawByStage[1] = res;
        ingestedConversationId = res.conversation_ids?.[0] || null;
        appendOut(1, `✅ Ingested: ${ingestedConversationId || '(unknown id)'}`);
        appendOut(1, `   total=${res.total} success=${res.success} failed=${res.failed}`);
        setStatus(1, 'success', ingestedConversationId ? 'Ingested' : 'Done');
        setStatus(2, 'ready', 'Ready');
    } catch (e) {
        setStatus(1, 'error', 'Error');
        setOut(1, e.message);
        throw e;
    }
}

async function stage2() {
    document.getElementById('stage-2').classList.add('expanded');
    if (!ingestedConversationId) {
        setStatus(2, 'error', 'Missing');
        setOut(2, 'Run Stage 1 first.');
        throw new Error('Stage 1 required');
    }

    setStatus(2, 'running', 'Evaluating...');
    try {
        setOut(2, '');
        appendOut(2, `➡️ POST /evaluate/batch`);
        appendOut(2, `   conversation_id=${ingestedConversationId}`);
        const res = await apiCall('/evaluate/batch', 'POST', { conversation_ids: [ingestedConversationId] });
        const r = res?.[0];
        rawByStage[2] = r;

        const aggregate = r?.aggregate_score ?? 0;
        const issuesCount = r?.issues_count ?? 0;
        appendOut(2, `✅ Completed`);
        appendOut(2, `   aggregate_score=${aggregate.toFixed(2)} issues=${issuesCount}`);
        appendOut(2, `   status=${r?.status || 'completed'} latency≈${formatMs(Object.values(r?.evaluations || {}).reduce((acc, ev) => acc + (ev.latency_ms || 0), 0))}`);
        appendOut(2, '');
        appendOut(2, `Evaluators:`)

        const evalEntries = Object.entries(r?.evaluations || {}).sort((a, b) => a[0].localeCompare(b[0]));
        for (const [name, ev] of evalEntries) {
            const scoreLine = formatScores(ev.scores);
            const issueN = ev.issues?.length ?? 0;
            appendOut(2, `- ${name}: latency=${formatMs(ev.latency_ms)} confidence=${(ev.confidence ?? 0).toFixed(2)} issues=${issueN}${scoreLine ? ` | ${scoreLine}` : ''}`);
        }

        appendOut(2, '');
        appendOut(2, `Issues:`)
        for (const line of summarizeIssues(r?.issues || [])) {
            appendOut(2, line);
        }

        setStatus(2, 'success', `Score ${aggregate.toFixed(2)} | Issues ${issuesCount}`);
        setStatus(3, 'ready', 'Ready');

        document.getElementById('s-issues').textContent = String(r?.issues_count ?? 0);
        document.getElementById('s-score').textContent = (r?.aggregate_score ?? 0).toFixed(2);
    } catch (e) {
        setStatus(2, 'error', 'Error');
        setOut(2, e.message);
        throw e;
    }
}

async function stage3() {
    document.getElementById('stage-3').classList.add('expanded');
    if (!ingestedConversationId) {
        setStatus(3, 'error', 'Missing');
        setOut(3, 'Run Stage 1 first.');
        throw new Error('Stage 1 required');
    }

    setStatus(3, 'running', 'Submitting...');
    try {
        setOut(3, '');
        appendOut(3, `➡️ POST /conversations/${ingestedConversationId}/feedback`);
        const payload = {
            signal: 'user_rating',
            value: 2,
            source: 'human_reviewer',
            annotator_id: 'demo_reviewer',
            confidence: 1.0,
            notes: 'Demo feedback from pipeline UI'
        };
        appendOut(3, `   signal=${payload.signal} value=${payload.value} source=${payload.source} annotator_id=${payload.annotator_id}`);
        const res = await apiCall(`/conversations/${ingestedConversationId}/feedback`, 'POST', payload);
        rawByStage[3] = res;
        appendOut(3, `✅ Feedback stored`);
        setStatus(3, 'success', 'Submitted');
        setStatus(4, 'ready', 'Ready');
    } catch (e) {
        setStatus(3, 'error', 'Error');
        setOut(3, e.message);
        throw e;
    }
}

async function stage4() {
    document.getElementById('stage-4').classList.add('expanded');
    setStatus(4, 'running', 'Analyzing...');
    try {
        setOut(4, '');
        document.getElementById('proposals').innerHTML = '';
        appendOut(4, `➡️ POST /analysis/run?limit=100`);
        const res = await apiCall('/analysis/run?limit=100', 'POST');
        proposals = res || [];
        rawByStage[4] = proposals;

        appendOut(4, `✅ Generated ${proposals.length} proposal(s)`);
        if (proposals.length > 0) {
            appendOut(4, '');
            appendOut(4, `Top proposals:`)
            for (const p of proposals.slice(0, 5)) {
                appendOut(4, `- ${p.type} (${p.evidence_count} conv, conf ${(p.confidence ?? 0).toFixed(2)}): ${truncate(p.failure_pattern || '', 140)}`);
            }
        }

        document.getElementById('proposals').innerHTML = proposals.map((p, i) => `
            <div class="proposal">
                <div class="proposal-header">
                    <span class="proposal-type">${p.type}</span>
                    <span style="font-size:10px;color:var(--muted)">${p.evidence_count} conv</span>
                </div>
                <div class="proposal-title">${i + 1}. ${truncate(p.failure_pattern || '', 90)}</div>
                <div class="proposal-desc">${truncate(p.proposed_content || '', 180)}</div>
            </div>
        `).join('');

        document.getElementById('s-prop').textContent = String(proposals.length);
        setStatus(4, 'success', `${proposals.length} proposals`);
        setStatus(5, proposals.length > 0 ? 'ready' : 'success', proposals.length > 0 ? 'Ready' : 'Skipped');
    } catch (e) {
        setStatus(4, 'error', 'Error');
        setOut(4, e.message);
        throw e;
    }
}

async function stage5() {
    document.getElementById('stage-5').classList.add('expanded');
    if (proposals.length === 0) {
        setStatus(5, 'success', 'Skipped');
        setOut(5, 'No proposals to verify.');
        return;
    }

    setStatus(5, 'running', 'Verifying...');
    try {
        setOut(5, '');
        const proposalId = proposals[0].proposal_id;
        appendOut(5, `➡️ POST /analysis/proposals/${proposalId}/verify`);
        const res = await apiCall(`/analysis/proposals/${proposalId}/verify`, 'POST');
        rawByStage[5] = res;
        const improvements = res.score_deltas ? res.score_deltas.filter(d => d.is_improvement).length : 0;
        appendOut(5, `✅ Completed`);
        appendOut(5, `   test_cases=${res.test_cases_count ?? 0} improvements=${improvements}`);
        setStatus(5, 'success', `Tested ${res.test_cases_count ?? 0}`);
    } catch (e) {
        setStatus(5, 'error', 'Error');
        setOut(5, e.message);
        throw e;
    }
}

function showDocsModal() {
    document.getElementById('docs-modal').classList.add('active');
}

function closeModal(id) {
    document.getElementById(id).classList.remove('active');
}

function showRawModal(stageNumber) {
    const value = rawByStage[stageNumber];
    document.getElementById('raw-modal-title').textContent = `Raw Output: Stage ${stageNumber}`;
    document.getElementById('raw-modal-body').textContent = value ? JSON.stringify(value, null, 2) : 'No output yet.';
    document.getElementById('raw-modal').classList.add('active');
}

function renderConversationModal(conv) {
    document.getElementById('conv-modal-title').textContent = conv.conversation_id || activeConversationId || 'Conversation';
    document.getElementById('conv-modal-body').innerHTML = (conv.turns || []).map(t => `
        <div class="conv-turn">
            <div class="conv-role ${t.role}">${t.role}</div>
            <div class="conv-content">${t.content}</div>
            ${t.tool_calls && t.tool_calls.length > 0 ? t.tool_calls.map(tc => `
                <div class="conv-tool">
                    <span class="conv-tool-name">${tc.tool_name}</span>
                    <pre>${JSON.stringify(tc.parameters, null, 2)}</pre>
                    ${tc.result?.error ? `<div style="color:var(--error);margin-top:4px">Error: ${tc.result.error}</div>` : ''}
                    ${tc.result?.status === 'success' ? `<div style="color:var(--success);margin-top:4px">✓ Success</div>` : ''}
                </div>
            `).join('') : ''}
        </div>
    `).join('');
}

document.addEventListener('click', e => {
    if (e.target.classList.contains('modal-overlay')) {
        e.target.classList.remove('active');
    }
});

window.runPipeline = runPipeline;
window.toggleStage = toggleStage;
window.showConversation = showConversation;
window.showDocsModal = showDocsModal;
window.closeModal = closeModal;
window.showRawModal = showRawModal;
