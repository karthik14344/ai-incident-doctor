import React, { useState, useEffect } from 'react';
import { api } from '../services/api';

export default function Settings() {
  const [settings, setSettings] = useState({
    chunk_size: '800',
    chunk_overlap: '100',
    top_k: '4',
    llm_model: 'llama3.2',
    embedding_model: 'nomic-embed-text',
    ollama_base_url: ''
  });
  const [loading, setLoading] = useState(true);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    loadSettings();
  }, []);

  const loadSettings = async () => {
    try {
      const data = await api.getSettings();
      setSettings((prev) => ({ ...prev, ...data }));
    } catch (e) {
      console.error("Error loading settings:", e);
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async (e) => {
    e.preventDefault();
    try {
      await api.updateSettings(settings);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (e) {
      alert("Failed to save settings: " + e.message);
    }
  };

  return (
    <div className="p-8 max-w-4xl mx-auto space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-white">System Configuration</h1>
        <p className="text-sm text-slate-400">Manage RAG chunking parameters, vector similarity limits, and Ollama model options.</p>
      </div>

      <form onSubmit={handleSave} className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-6">
        <h3 className="text-base font-semibold text-white border-b border-slate-800 pb-3">
          Document Chunking Strategy
        </h3>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="space-y-2">
            <label className="text-xs font-semibold text-slate-300 uppercase block">
              Chunk Size (Tokens / Chars)
            </label>
            <input
              type="number"
              value={settings.chunk_size}
              onChange={(e) => setSettings({ ...settings, chunk_size: e.target.value })}
              className="w-full px-4 py-2.5 bg-slate-950 border border-slate-800 rounded-xl text-sm text-white focus:outline-none focus:border-indigo-500"
            />
            <p className="text-[11px] text-slate-500">Recommended: 800 tokens per chunk</p>
          </div>

          <div className="space-y-2">
            <label className="text-xs font-semibold text-slate-300 uppercase block">
              Chunk Overlap
            </label>
            <input
              type="number"
              value={settings.chunk_overlap}
              onChange={(e) => setSettings({ ...settings, chunk_overlap: e.target.value })}
              className="w-full px-4 py-2.5 bg-slate-950 border border-slate-800 rounded-xl text-sm text-white focus:outline-none focus:border-indigo-500"
            />
            <p className="text-[11px] text-slate-500">Preserves context continuity between chunks</p>
          </div>
        </div>

        <h3 className="text-base font-semibold text-white border-b border-slate-800 pb-3 pt-4">
          Vector Store & LLM Model Config
        </h3>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="space-y-2">
            <label className="text-xs font-semibold text-slate-300 uppercase block">
              Top-K Context Chunks
            </label>
            <input
              type="number"
              value={settings.top_k}
              onChange={(e) => setSettings({ ...settings, top_k: e.target.value })}
              className="w-full px-4 py-2.5 bg-slate-950 border border-slate-800 rounded-xl text-sm text-white focus:outline-none focus:border-indigo-500"
            />
            <p className="text-[11px] text-slate-500">Number of top relevant chunks passed to LLM context</p>
          </div>

          <div className="space-y-2">
            <label className="text-xs font-semibold text-slate-300 uppercase block">
              Local LLM Model
            </label>
            <select
              value={settings.llm_model}
              onChange={(e) => setSettings({ ...settings, llm_model: e.target.value })}
              className="w-full px-4 py-2.5 bg-slate-950 border border-slate-800 rounded-xl text-sm text-white focus:outline-none focus:border-indigo-500"
            >
              <option value="llama3.2">llama3.2 (Installed)</option>
              <option value="codellama">codellama</option>
              <option value="mistral">mistral</option>
              <option value="llama3">llama3</option>
            </select>
            <p className="text-[11px] text-slate-500 font-mono">Ollama model for response generation</p>
          </div>

          <div className="space-y-2">
            <label className="text-xs font-semibold text-slate-300 uppercase block">
              Embedding Model
            </label>
            <input
              type="text"
              value={settings.embedding_model}
              onChange={(e) => setSettings({ ...settings, embedding_model: e.target.value })}
              className="w-full px-4 py-2.5 bg-slate-950 border border-slate-800 rounded-xl text-sm text-white focus:outline-none focus:border-indigo-500 font-mono"
            />
            <p className="text-[11px] text-slate-500">Nomic embedding model for ChromaDB vectors</p>
          </div>

          <div className="space-y-2">
            <label className="text-xs font-semibold text-slate-300 uppercase block">
              Ollama Base Endpoint
            </label>
            <input
              type="text"
              value={settings.ollama_base_url}
              onChange={(e) => setSettings({ ...settings, ollama_base_url: e.target.value })}
              className="w-full px-4 py-2.5 bg-slate-950 border border-slate-800 rounded-xl text-sm text-white focus:outline-none focus:border-indigo-500 font-mono"
            />
            <p className="text-[11px] text-slate-500">Local Ollama HTTP host API address</p>
          </div>
        </div>

        <div className="pt-4 flex items-center justify-between border-t border-slate-800">
          {saved && (
            <span className="text-xs font-semibold text-emerald-400">✓ Settings saved successfully!</span>
          )}
          <button
            type="submit"
            className="ml-auto px-6 py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white font-semibold text-sm rounded-xl shadow-lg shadow-indigo-600/30 transition-all"
          >
            Save Settings
          </button>
        </div>
      </form>
    </div>
  );
}
