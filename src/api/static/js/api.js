const API_BASE = window.location.origin;

class ApiClient {
    static async get(endpoint) {
        const res = await fetch(`${API_BASE}${endpoint}`);
        if (!res.ok) {
            throw new Error(`API Error ${res.status}: ${res.statusText}`);
        }
        return res.json();
    }

    static async post(endpoint, body) {
        const res = await fetch(`${API_BASE}${endpoint}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        if (!res.ok) {
            throw new Error(`API Error ${res.status}: ${res.statusText}`);
        }
        return res.json();
    }

    // --- Stats ---
    static async getStats() {
        return this.get('/stats');
    }

    // --- Conversations ---
    static async getConversations(limit = 100, offset = 0) {
        return this.get(`/conversations?limit=${limit}&offset=${offset}`);
    }

    static async getConversation(id) {
        return this.get(`/conversations/${id}`);
    }

    // --- Feedback ---
    static async getSamples(strategy = 'evaluation', limit = 1, kwargs = {}) {
        let url = `/feedback/samples?limit=${limit}&strategy=${strategy}`;
        for (const [key, value] of Object.entries(kwargs)) {
            url += `&${key}=${value}`;
        }
        return this.get(url);
    }

    static async submitFeedback(conversationId, payload) {
        return this.post(`/conversations/${conversationId}/feedback`, payload);
    }

    static async getDisagreements() {
        return this.get('/feedback/disagreements');
    }

    static async getAgreementMetrics(signal) {
        return this.get(`/feedback/metrics?signal=${encodeURIComponent(signal)}`);
    }

    static async resolveDisagreement(conversationId, signal, value) {
        return this.post(`/feedback/resolve?conversation_id=${conversationId}&signal=${signal}&value=${value}&resolver_id=ui_admin`, {});
    }

    // --- Ingestion ---
    static async ingestBatch(conversations) {
        return this.post('/ingest', { conversations });
    }

    // --- Evaluation ---
    static async evaluateBatch(conversationIds) {
        return this.post('/evaluate/batch', { conversation_ids: conversationIds });
    }

    // --- Analysis ---
    static async getProposals() {
        return this.get('/analysis/proposals');
    }

    static async runAnalysis() {
        return this.post('/analysis/run', {});
    }

    static async applyProposal(proposalId) {
        return this.post(`/analysis/proposals/${proposalId}/apply`, {});
    }

    static async verifyProposalReal(proposalId) {
        return this.post(`/analysis/proposals/${proposalId}/verify-real`, {});
    }

    // --- Results ---
    static async getResults(conversationId) {
        return this.get(`/results/${conversationId}`);
    }

    // --- Demo Agent ---
    static async demoAsk(message, forceError = false) {
        return this.post('/demo/ask', { message, force_error: forceError });
    }
}
