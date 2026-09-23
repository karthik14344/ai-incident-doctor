const API_BASE = '/api';

export const api = {
  // System Status
  getSystemStatus: async () => {
    const res = await fetch(`${API_BASE}/system/status`);
    if (!res.ok) throw new Error("Failed to fetch system status");
    return res.json();
  },

  // Documents
  getDocuments: async () => {
    const res = await fetch(`${API_BASE}/documents`);
    if (!res.ok) throw new Error("Failed to fetch documents");
    return res.json();
  },

  getDocumentDetails: async (docId) => {
    const res = await fetch(`${API_BASE}/documents/${docId}`);
    if (!res.ok) throw new Error("Failed to fetch document details");
    return res.json();
  },

  getDocumentChunks: async (docId) => {
    const res = await fetch(`${API_BASE}/documents/${docId}/chunks`);
    if (!res.ok) throw new Error("Failed to fetch document chunks");
    return res.json();
  },

  uploadDocument: async (file, collectionName = 'default') => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('collection_name', collectionName);

    const res = await fetch(`${API_BASE}/documents/upload`, {
      method: 'POST',
      body: formData
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Upload failed");
    }
    return res.json();
  },

  reprocessDocument: async (docId) => {
    const res = await fetch(`${API_BASE}/documents/${docId}/reprocess`, {
      method: 'POST'
    });
    if (!res.ok) throw new Error("Reprocess request failed");
    return res.json();
  },

  deleteDocument: async (docId) => {
    const res = await fetch(`${API_BASE}/documents/${docId}`, {
      method: 'DELETE'
    });
    if (!res.ok) throw new Error("Delete request failed");
    return res.json();
  },

  // Chat Sessions & History
  getChatSessions: async () => {
    const res = await fetch(`${API_BASE}/chat/sessions`);
    if (!res.ok) throw new Error("Failed to fetch chat sessions");
    return res.json();
  },

  createChatSession: async (title = "New Conversation") => {
    const res = await fetch(`${API_BASE}/chat/sessions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title })
    });
    if (!res.ok) throw new Error("Failed to create chat session");
    return res.json();
  },

  getChatHistory: async (sessionId) => {
    const res = await fetch(`${API_BASE}/chat/history/${sessionId}`);
    if (!res.ok) throw new Error("Failed to fetch history");
    return res.json();
  },

  deleteChatSession: async (sessionId) => {
    const res = await fetch(`${API_BASE}/chat/sessions/${sessionId}`, {
      method: 'DELETE'
    });
    if (!res.ok) throw new Error("Failed to delete session");
    return res.json();
  },

  getSuggestions: async (q, collectionName = 'default') => {
    const params = new URLSearchParams({ q, collection_name: collectionName });
    const res = await fetch(`${API_BASE}/suggestions?${params}`);
    if (!res.ok) throw new Error("Failed to fetch suggestions");
    return res.json();
  },

  // Debug Retrieval Pipeline
  debugRetrieval: async (question, collectionName = 'default') => {
    const res = await fetch(`${API_BASE}/retrieval/search`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, collection_name: collectionName })
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Retrieval search failed");
    }
    return res.json();
  },

  // Model Comparison
  getAvailableModels: async () => {
    const res = await fetch(`${API_BASE}/models/available`);
    if (!res.ok) throw new Error("Failed to fetch available models");
    return res.json();
  },

  /**
   * Streams a multi-model benchmark. A four-model run can take minutes, so
   * results arrive per model via `onEvent` instead of one final payload.
   * Pass an AbortSignal to let the user cancel a run in progress.
   */
  compareModels: async (payload, onEvent, signal) => {
    const res = await fetch(`${API_BASE}/models/compare`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal
    });

    if (!res.ok) {
      let detail = "Comparison request failed";
      try {
        const err = await res.json();
        detail = err.detail || detail;
      } catch {
        // Non-JSON error body; keep the default message.
      }
      throw new Error(detail);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const frames = buffer.split('\n\n');
      // The trailing fragment may be an incomplete frame; keep it buffered.
      buffer = frames.pop() ?? '';

      for (const frame of frames) {
        const line = frame.trim();
        if (!line.startsWith('data: ')) continue;
        try {
          onEvent(JSON.parse(line.slice(6)));
        } catch {
          // Ignore malformed frames rather than aborting the whole run.
        }
      }
    }
  },

  getComparisonHistory: async (limit = 25) => {
    const res = await fetch(`${API_BASE}/models/comparisons?limit=${limit}`);
    if (!res.ok) throw new Error("Failed to fetch comparison history");
    return res.json();
  },

  getComparisonRun: async (runId) => {
    const res = await fetch(`${API_BASE}/models/comparisons/${runId}`);
    if (!res.ok) throw new Error("Failed to fetch comparison run");
    return res.json();
  },

  deleteComparisonRun: async (runId) => {
    const res = await fetch(`${API_BASE}/models/comparisons/${runId}`, { method: 'DELETE' });
    if (!res.ok) throw new Error("Failed to delete comparison run");
    return res.json();
  },

  // Week-4 Evaluation
  //
  // A full run is 30 questions x N models and takes tens of minutes, so it is
  // started as a background job and polled, rather than streamed over one
  // request the way a single-question comparison is: a page reload during a
  // stream would throw away the whole run.
  getEvaluationDataset: async () => {
    const res = await fetch(`${API_BASE}/evaluation/dataset`);
    if (!res.ok) throw new Error("Failed to fetch the evaluation dataset");
    return res.json();
  },

  getEvaluationKb: async () => {
    const res = await fetch(`${API_BASE}/evaluation/kb`);
    if (!res.ok) throw new Error("Failed to fetch knowledge base status");
    return res.json();
  },

  rebuildEvaluationKb: async () => {
    const res = await fetch(`${API_BASE}/evaluation/kb/rebuild`, { method: 'POST' });
    if (!res.ok) throw new Error("Knowledge base rebuild failed");
    return res.json();
  },

  startEvaluation: async (payload) => {
    const res = await fetch(`${API_BASE}/evaluation/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Could not start the evaluation");
    }
    return res.json();
  },

  getEvaluationStatus: async () => {
    const res = await fetch(`${API_BASE}/evaluation/status`);
    if (!res.ok) throw new Error("Failed to fetch evaluation status");
    return res.json();
  },

  cancelEvaluation: async () => {
    const res = await fetch(`${API_BASE}/evaluation/cancel`, { method: 'POST' });
    if (!res.ok) throw new Error("No evaluation is running");
    return res.json();
  },

  getEvaluationRuns: async (limit = 20) => {
    const res = await fetch(`${API_BASE}/evaluation/runs?limit=${limit}`);
    if (!res.ok) throw new Error("Failed to fetch evaluation runs");
    return res.json();
  },

  getEvaluationReport: async (runId) => {
    const res = await fetch(`${API_BASE}/evaluation/runs/${runId}`);
    if (!res.ok) throw new Error("Failed to fetch the evaluation report");
    return res.json();
  },

  deleteEvaluationRun: async (runId) => {
    const res = await fetch(`${API_BASE}/evaluation/runs/${runId}`, { method: 'DELETE' });
    if (!res.ok) throw new Error("Failed to delete the evaluation run");
    return res.json();
  },

  // Repository-level understanding (Exercise 6)
  getRepoQuestions: async () => {
    const res = await fetch(`${API_BASE}/evaluation/repo/questions`);
    if (!res.ok) throw new Error("Failed to fetch repository questions");
    return res.json();
  },

  buildRepoIndex: async () => {
    const res = await fetch(`${API_BASE}/evaluation/repo/index`, { method: 'POST' });
    if (!res.ok) throw new Error("Repository indexing failed");
    return res.json();
  },

  runRepoQuestions: async (payload) => {
    const res = await fetch(`${API_BASE}/evaluation/repo/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Repository run failed");
    }
    return res.json();
  },

  getRepoResult: async () => {
    const res = await fetch(`${API_BASE}/evaluation/repo/result`);
    if (!res.ok) return null;
    return res.json();
  },

  // Settings
  getSettings: async () => {
    const res = await fetch(`${API_BASE}/settings`);
    if (!res.ok) throw new Error("Failed to fetch settings");
    return res.json();
  },

  updateSettings: async (settingsData) => {
    const res = await fetch(`${API_BASE}/settings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(settingsData)
    });
    if (!res.ok) throw new Error("Failed to update settings");
    return res.json();
  }
};
