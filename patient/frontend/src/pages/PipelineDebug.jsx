import React, { useState } from 'react';
import { api } from '../services/api';

export default function PipelineDebug() {
  const [question, setQuestion] = useState('What is the attendance requirement?');
  const [loading, setLoading] = useState(false);
  const [debugData, setDebugData] = useState(null);
  const [error, setError] = useState(null);

  const handleRunDebug = async (e) => {
    e.preventDefault();
    if (!question.trim()) return;
    setLoading(true);
    setError(null);

    try {
      const res = await api.debugRetrieval(question, 'default');
      setDebugData(res);
    } catch (err) {
      setError(err.message || "Failed to execute pipeline debug search");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      {/* Header */}
      <div>
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 mb-2">
          <span>🔍 RAG Inspector & Debugger</span>
        </div>
        <h1 className="text-2xl font-bold text-white">Observable RAG Pipeline Debugger</h1>
        <p className="text-sm text-slate-400">Inspect each stage of RAG execution: Query embedding dimensions, ChromaDB cosine similarity scores, Top-K chunk selection, and assembled LLM context prompt.</p>
      </div>

      {/* Query Bar */}
      <form onSubmit={handleRunDebug} className="p-6 bg-slate-900 border border-slate-800 rounded-2xl flex flex-col md:flex-row gap-4 items-center">
        <div className="flex-1 w-full">
          <label className="text-xs font-semibold text-slate-400 uppercase block mb-1.5">Test User Question:</label>
          <input
            type="text"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Type question to test RAG retrieval..."
            className="w-full px-4 py-3 bg-slate-950 border border-slate-800 rounded-xl text-sm text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500"
          />
        </div>
        <button
          type="submit"
          disabled={loading}
          className="w-full md:w-auto px-6 py-3 bg-indigo-600 hover:bg-indigo-500 text-white font-semibold text-sm rounded-xl shadow-lg shadow-indigo-600/30 transition-all flex items-center justify-center gap-2"
        >
          {loading ? (
            <span>Running Vector Search...</span>
          ) : (
            <>
              <span>Execute RAG Pipeline</span>
              <span>⚡</span>
            </>
          )}
        </button>
      </form>

      {error && (
        <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-400 text-sm font-medium">
          ⚠️ {error}
        </div>
      )}

      {/* Live Visual Pipeline Stepper */}
      {debugData && (
        <div className="space-y-6">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-6">
            <h3 className="text-base font-semibold text-white border-b border-slate-800 pb-3">
              RAG Pipeline Execution Trace
            </h3>

            {/* Pipeline Stage 1: Question Input */}
            <div className="flex items-start gap-4 p-4 rounded-xl bg-slate-950 border border-slate-800/80">
              <div className="w-8 h-8 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 flex items-center justify-center font-bold text-xs shrink-0">
                1
              </div>
              <div className="space-y-1 flex-1">
                <div className="flex items-center justify-between">
                  <h4 className="text-sm font-semibold text-slate-200">Question Received</h4>
                  <span className="text-xs text-emerald-400 font-mono">✓ STEP COMPLETED</span>
                </div>
                <p className="text-xs text-slate-400 font-mono font-semibold">"{debugData.question}"</p>
              </div>
            </div>

            {/* Pipeline Stage 2: Query Embedding */}
            <div className="flex items-start gap-4 p-4 rounded-xl bg-slate-950 border border-slate-800/80">
              <div className="w-8 h-8 rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 flex items-center justify-center font-bold text-xs shrink-0">
                2
              </div>
              <div className="space-y-1 flex-1">
                <div className="flex items-center justify-between">
                  <h4 className="text-sm font-semibold text-slate-200">Query Vector Embedding Generated</h4>
                  <span className="text-xs text-indigo-400 font-mono">✓ STEP COMPLETED</span>
                </div>
                <p className="text-xs text-slate-400">Model: <span className="font-mono text-indigo-300">nomic-embed-text</span></p>
                <div className="inline-block px-2.5 py-1 rounded bg-indigo-600/10 text-indigo-300 font-mono text-xs font-semibold border border-indigo-500/20 mt-1">
                  Vector Dimensions: {debugData.query_embedding_dim} floats
                </div>
              </div>
            </div>

            {/* Pipeline Stage 3: Vector Similarity Search */}
            <div className="flex items-start gap-4 p-4 rounded-xl bg-slate-950 border border-slate-800/80">
              <div className="w-8 h-8 rounded-full bg-purple-500/10 text-purple-400 border border-purple-500/20 flex items-center justify-center font-bold text-xs shrink-0">
                3
              </div>
              <div className="space-y-3 flex-1">
                <div className="flex items-center justify-between">
                  <h4 className="text-sm font-semibold text-slate-200">ChromaDB Vector Similarity Search</h4>
                  <span className="text-xs text-purple-400 font-mono">✓ TOP-{debugData.top_k} MATCHES FOUND</span>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {debugData.sources.map((src, idx) => (
                    <div key={idx} className="p-3.5 rounded-xl bg-slate-900 border border-slate-800 space-y-2">
                      <div className="flex items-center justify-between text-xs font-semibold">
                        <span className="text-slate-200">📄 {src.filename} (Page {src.page})</span>
                        <span className="px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 font-mono text-xs font-bold border border-emerald-500/20">
                          Score: {src.similarity}
                        </span>
                      </div>
                      <p className="text-xs text-slate-400 font-mono line-clamp-2">
                        {src.text}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* Pipeline Stage 4: Context Assembly */}
            <div className="flex items-start gap-4 p-4 rounded-xl bg-slate-950 border border-slate-800/80">
              <div className="w-8 h-8 rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/20 flex items-center justify-center font-bold text-xs shrink-0">
                4
              </div>
              <div className="space-y-2 flex-1">
                <div className="flex items-center justify-between">
                  <h4 className="text-sm font-semibold text-slate-200">Context Constructed For LLM</h4>
                  <span className="text-xs text-amber-400 font-mono">✓ PROMPT BUILT</span>
                </div>
                <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 text-xs font-mono text-slate-300 max-h-48 overflow-y-auto whitespace-pre-wrap">
                  {debugData.assembled_context}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
