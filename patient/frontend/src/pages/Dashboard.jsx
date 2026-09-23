import React, { useEffect, useState } from 'react';
import { api } from '../services/api';

export default function Dashboard({ setActiveTab }) {
  const [documents, setDocuments] = useState([]);
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadDashboardData();
  }, []);

  const loadDashboardData = async () => {
    try {
      const [docsData, statusData] = await Promise.all([
        api.getDocuments(),
        api.getSystemStatus()
      ]);
      setDocuments(docsData);
      setStatus(statusData);
    } catch (e) {
      console.error("Error loading dashboard data:", e);
    } finally {
      setLoading(false);
    }
  };

  const totalChunks = documents.reduce((acc, d) => acc + (d.chunks_count || 0), 0);
  const collections = Array.from(new Set(documents.map(d => d.collection_name || 'default')));

  const services = [
    { name: 'API Gateway (Port 8000)', status: status?.gateway === 'online', type: 'FastAPI Router' },
    { name: 'Ingestion Service (Port 8001)', status: status?.ingestion === 'online', type: 'PDF & Vector Pipeline' },
    { name: 'Retrieval Service (Port 8002)', status: status?.retrieval === 'online', type: 'Similarity Search' },
    { name: 'LLM Service (Port 8003)', status: status?.llm_service === 'online', type: 'Ollama Client' },
    { name: 'Voice Service (Port 8004)', status: status?.voice === 'online', type: 'VEXYL-STT & Hindi-TTS' },
    { name: 'Ollama LLM Engine', status: status?.ollama === 'online', type: status?.ollama_models?.length ? status.ollama_models.join(', ') : 'llama3.2' },
    { name: 'ChromaDB Vector Store', status: true, type: 'Cosine Vector DB' },
  ];

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      {/* Welcome Banner */}
      <div className="relative overflow-hidden rounded-2xl bg-gradient-to-r from-slate-900 via-indigo-950/40 to-slate-900 border border-slate-800 p-8 glow-purple">
        <div className="relative z-10 max-w-3xl space-y-3">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
            <span>🚀 RAG Microservices Active</span>
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-white">
            KnowledgeAI — RAG Document Assistant
          </h1>
          <p className="text-slate-400 text-sm leading-relaxed">
            Upload PDFs, extract text, automatically chunk into vector embeddings, query with ChromaDB similarity search, and generate answers powered by local <span className="text-indigo-400 font-semibold">Llama 3.2</span>.
          </p>
          <div className="pt-2 flex items-center gap-4">
            <button
              onClick={() => setActiveTab('chat')}
              className="px-5 py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white font-medium text-sm rounded-lg shadow-lg shadow-indigo-600/30 transition-all flex items-center gap-2"
            >
              <span>Ask AI Assistant</span>
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M14 5l7 7m0 0l-7 7m7-7H3"/></svg>
            </button>
            <button
              onClick={() => setActiveTab('documents')}
              className="px-5 py-2.5 bg-slate-800 hover:bg-slate-700 text-slate-200 font-medium text-sm rounded-lg border border-slate-700 transition-all"
            >
              Upload PDF
            </button>
          </div>
        </div>
      </div>

      {/* Metrics Row */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-5">
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-2">
          <span className="text-xs font-medium text-slate-400 uppercase tracking-wider">Total Documents</span>
          <div className="text-3xl font-bold text-white flex items-center justify-between">
            <span>{documents.length}</span>
            <span className="p-2.5 bg-indigo-500/10 text-indigo-400 rounded-lg text-lg">📄</span>
          </div>
          <p className="text-xs text-slate-500">Uploaded & Processed</p>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-2">
          <span className="text-xs font-medium text-slate-400 uppercase tracking-wider">Total Vector Chunks</span>
          <div className="text-3xl font-bold text-emerald-400 flex items-center justify-between">
            <span>{totalChunks.toLocaleString()}</span>
            <span className="p-2.5 bg-emerald-500/10 text-emerald-400 rounded-lg text-lg">🧩</span>
          </div>
          <p className="text-xs text-slate-500">Indexed in ChromaDB</p>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-2">
          <span className="text-xs font-medium text-slate-400 uppercase tracking-wider">Collections</span>
          <div className="text-3xl font-bold text-purple-400 flex items-center justify-between">
            <span>{collections.length}</span>
            <span className="p-2.5 bg-purple-500/10 text-purple-400 rounded-lg text-lg">📁</span>
          </div>
          <p className="text-xs text-slate-500">Active vector namespaces</p>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-2">
          <span className="text-xs font-medium text-slate-400 uppercase tracking-wider">LLM Model</span>
          <div className="text-2xl font-bold text-indigo-300 flex items-center justify-between truncate">
            <span>Llama 3.2</span>
            <span className="p-2.5 bg-indigo-500/10 text-indigo-400 rounded-lg text-lg">🤖</span>
          </div>
          <p className="text-xs text-slate-500">Ollama API Engine</p>
        </div>
      </div>

      {/* System Status Grid & Architecture */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* System Status Panel */}
        <div className="lg:col-span-1 bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-4">
          <h3 className="text-base font-semibold text-white flex items-center justify-between">
            <span>Microservices Status</span>
            <button onClick={loadDashboardData} className="text-xs text-indigo-400 hover:underline">Refresh</button>
          </h3>
          <div className="space-y-3">
            {services.map((s, idx) => (
              <div key={idx} className="flex items-center justify-between p-3 rounded-lg bg-slate-950/60 border border-slate-800/80">
                <div className="space-y-0.5">
                  <div className="text-sm font-medium text-slate-200">{s.name}</div>
                  <div className="text-[11px] text-slate-500 font-mono">{s.type}</div>
                </div>
                <div className="flex items-center gap-2">
                  <span className={`w-2.5 h-2.5 rounded-full ${s.status ? 'bg-emerald-400 shadow-sm shadow-emerald-400/50' : 'bg-amber-400'}`}></span>
                  <span className={`text-xs font-semibold ${s.status ? 'text-emerald-400' : 'text-amber-400'}`}>
                    {s.status ? 'Online' : 'Fallback'}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Recent Knowledge Base Documents */}
        <div className="lg:col-span-2 bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-base font-semibold text-white">Recent Knowledge Base Documents</h3>
            <button onClick={() => setActiveTab('documents')} className="text-xs text-indigo-400 font-medium hover:underline">
              View All Documents &rarr;
            </button>
          </div>

          {documents.length === 0 ? (
            <div className="text-center py-12 border border-dashed border-slate-800 rounded-xl space-y-3">
              <div className="text-4xl text-slate-600">📁</div>
              <p className="text-slate-400 text-sm font-medium">No documents uploaded yet.</p>
              <button
                onClick={() => setActiveTab('documents')}
                className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-xs font-semibold"
              >
                Upload First PDF
              </button>
            </div>
          ) : (
            <div className="space-y-2.5">
              {documents.slice(0, 4).map((doc) => (
                <div key={doc.doc_id} className="p-3.5 rounded-lg bg-slate-950/60 border border-slate-800 flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="w-9 h-9 rounded-lg bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 flex items-center justify-center font-bold text-sm">
                      PDF
                    </div>
                    <div>
                      <h4 className="text-sm font-semibold text-slate-200">{doc.filename}</h4>
                      <p className="text-xs text-slate-500 font-mono">
                        {doc.pages || 0} pages &bull; {doc.chunks_count || 0} chunks &bull; {(doc.file_size / 1024).toFixed(1)} KB
                      </p>
                    </div>
                  </div>
                  <span className={`px-2.5 py-1 rounded-full text-xs font-semibold capitalize border ${
                    doc.status === 'processed'
                      ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                      : doc.status === 'error'
                      ? 'bg-rose-500/10 text-rose-400 border-rose-500/20'
                      : 'bg-amber-500/10 text-amber-400 border-amber-500/20 animate-pulse'
                  }`}>
                    {doc.status === 'processed' ? '✓ Processed' : doc.status}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
