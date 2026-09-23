import React, { useState, useEffect } from 'react';
import Sidebar from './components/Sidebar';
import Navbar from './components/Navbar';
import Dashboard from './pages/Dashboard';
import Chat from './pages/Chat';
import Documents from './pages/Documents';
import ChunkInspector from './pages/ChunkInspector';
import PipelineDebug from './pages/PipelineDebug';
import ModelComparison from './pages/ModelComparison';
import EvaluationLab from './pages/EvaluationLab';
import Settings from './pages/Settings';
import { api } from './services/api';

export default function App() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [selectedDocId, setSelectedDocId] = useState(null);
  const [systemStatus, setSystemStatus] = useState(null);

  useEffect(() => {
    fetchSystemStatus();
    const interval = setInterval(fetchSystemStatus, 5000);
    return () => clearInterval(interval);
  }, []);

  const fetchSystemStatus = async () => {
    try {
      const status = await api.getSystemStatus();
      setSystemStatus(status);
    } catch (e) {
      console.error("Error fetching system status:", e);
    }
  };

  const renderActivePage = () => {
    switch (activeTab) {
      case 'dashboard':
        return <Dashboard setActiveTab={setActiveTab} />;
      case 'chat':
        return <Chat setActiveTab={setActiveTab} />;
      case 'documents':
        return <Documents setActiveTab={setActiveTab} setSelectedDocId={setSelectedDocId} />;
      case 'chunks':
        return <ChunkInspector selectedDocId={selectedDocId} />;
      case 'pipeline':
        return <PipelineDebug />;
      case 'compare':
        return <ModelComparison />;
      case 'evaluation':
        return <EvaluationLab />;
      case 'settings':
        return <Settings />;
      default:
        return <Dashboard setActiveTab={setActiveTab} />;
    }
  };

  return (
    <div className="flex min-h-screen bg-[#0b0f19] text-slate-100 antialiased selection:bg-indigo-500 selection:text-white">
      <Sidebar activeTab={activeTab} setActiveTab={setActiveTab} />
      
      <div className="flex-1 flex flex-col min-w-0 overflow-x-hidden">
        <Navbar systemStatus={systemStatus} activeTab={activeTab} />
        <main className="flex-1 overflow-y-auto">
          {renderActivePage()}
        </main>
      </div>
    </div>
  );
}
