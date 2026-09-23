import React from 'react';

export default function Navbar({ systemStatus, activeTab }) {
  const getTabTitle = () => {
    switch (activeTab) {
      case 'dashboard': return 'System Overview & Health';
      case 'chat': return 'AI Document Assistant Chat';
      case 'documents': return 'Knowledge Base Documents';
      case 'pipeline': return 'RAG Pipeline Visualizer & Debugger';
      case 'compare': return 'Multi-Model RAG Benchmark';
      case 'settings': return 'System Settings & Config';
      default: return 'KnowledgeAI';
    }
  };

  const isOllamaOnline = systemStatus?.ollama === 'online';

  const microservices = ['gateway', 'ingestion', 'retrieval', 'llm_service'];
  const onlineCount = systemStatus
    ? microservices.filter((key) => systemStatus[key] === 'online').length
    : 0;

  return (
    <header className="h-16 border-b border-slate-800 bg-slate-900/60 backdrop-blur-md px-6 flex items-center justify-between sticky top-0 z-20">
      <div className="flex items-center gap-4">
        <h2 className="text-lg font-semibold text-slate-100">{getTabTitle()}</h2>
      </div>

      <div className="flex items-center gap-4 text-xs">
        {/* Ollama Status Pill */}
        <div className="flex items-center gap-2 bg-slate-800/80 px-3 py-1.5 rounded-full border border-slate-700/60">
          <span className={`w-2 h-2 rounded-full ${isOllamaOnline ? 'bg-emerald-400 animate-pulse' : 'bg-amber-400'}`}></span>
          <span className="text-slate-300 font-medium">
            Ollama {isOllamaOnline ? '(llama3.2 online)' : '(fallback ready)'}
          </span>
        </div>

        {/* Microservices Health Badge */}
        <div className="flex items-center gap-2 bg-slate-800/80 px-3 py-1.5 rounded-full border border-slate-700/60 text-slate-300">
          <span className={`w-2 h-2 rounded-full ${onlineCount === microservices.length ? 'bg-emerald-400' : 'bg-indigo-400'}`}></span>
          <span>{onlineCount}/{microservices.length} Microservices</span>
        </div>

        <div className="pl-2 border-l border-slate-800 flex items-center gap-2 text-slate-400">
          <span className="w-6 h-6 rounded-full bg-indigo-600/20 text-indigo-400 border border-indigo-500/30 flex items-center justify-center font-bold text-[10px]">
            ⚙
          </span>
          <span className="font-semibold text-slate-200">Admin</span>
        </div>
      </div>
    </header>
  );
}
