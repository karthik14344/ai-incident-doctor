import React, { useState, useEffect } from 'react';
import { api } from '../services/api';

export default function Documents({ setActiveTab, setSelectedDocId }) {
  const [documents, setDocuments] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState('');
  const [error, setError] = useState(null);
  const [dragActive, setDragActive] = useState(false);

  useEffect(() => {
    fetchDocuments();
    const interval = setInterval(fetchDocuments, 3000); // Poll status updates
    return () => clearInterval(interval);
  }, []);

  const fetchDocuments = async () => {
    try {
      const data = await api.getDocuments();
      setDocuments(data);
    } catch (e) {
      console.error("Error fetching documents:", e);
    }
  };

  const handleFileUpload = async (file) => {
    if (!file) return;
    setUploading(true);
    setError(null);
    setUploadProgress('Uploading PDF file...');

    try {
      setUploadProgress('Extracting text & creating chunks...');
      const res = await api.uploadDocument(file);
      setUploadProgress('Generating vector embeddings & indexing ChromaDB...');
      
      setTimeout(() => {
        setUploading(false);
        setUploadProgress('');
        fetchDocuments();
      }, 1500);

    } catch (e) {
      setError(e.message || "Failed to upload document");
      setUploading(false);
    }
  };

  const handleDrag = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFileUpload(e.dataTransfer.files[0]);
    }
  };

  const handleDelete = async (docId) => {
    if (confirm("Are you sure you want to delete this document and its vector embeddings?")) {
      try {
        await api.deleteDocument(docId);
        fetchDocuments();
      } catch (e) {
        alert("Failed to delete document: " + e.message);
      }
    }
  };

  const handleReprocess = async (docId) => {
    try {
      await api.reprocessDocument(docId);
      fetchDocuments();
    } catch (e) {
      alert("Failed to reprocess: " + e.message);
    }
  };

  const openChunkInspector = (docId) => {
    setSelectedDocId(docId);
    setActiveTab('chunks');
  };

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Knowledge Base Documents</h1>
          <p className="text-sm text-slate-400">Upload PDFs to automatically extract text, create overlapping chunks, generate vector embeddings, and store in ChromaDB.</p>
        </div>
      </div>

      {/* Drag & Drop Upload Zone */}
      <div
        onDragEnter={handleDrag}
        onDragOver={handleDrag}
        onDragLeave={handleDrag}
        onDrop={handleDrop}
        className={`relative border-2 border-dashed rounded-2xl p-10 text-center transition-all ${
          dragActive
            ? 'border-indigo-500 bg-indigo-500/10'
            : 'border-slate-800 bg-slate-900/60 hover:border-slate-700'
        }`}
      >
        <input
          type="file"
          id="fileUpload"
          accept=".pdf,.txt,.md"
          className="hidden"
          onChange={(e) => e.target.files?.[0] && handleFileUpload(e.target.files[0])}
        />

        {uploading ? (
          <div className="space-y-4 max-w-md mx-auto py-4">
            <div className="w-12 h-12 rounded-full border-4 border-indigo-500 border-t-transparent animate-spin mx-auto"></div>
            <h3 className="text-lg font-semibold text-white">Processing Document</h3>
            <p className="text-sm text-indigo-400 font-medium">{uploadProgress}</p>
            <div className="w-full bg-slate-800 rounded-full h-2 overflow-hidden">
              <div className="bg-indigo-500 h-full animate-pulse w-3/4"></div>
            </div>
          </div>
        ) : (
          <label htmlFor="fileUpload" className="cursor-pointer space-y-4 block">
            <div className="w-16 h-16 rounded-2xl bg-indigo-600/10 text-indigo-400 border border-indigo-500/20 flex items-center justify-center mx-auto text-3xl shadow-lg shadow-indigo-500/10">
              📄
            </div>
            <div>
              <p className="text-base font-semibold text-slate-200">
                Drag & Drop PDF files here
              </p>
              <p className="text-xs text-slate-500 mt-1">
                Supports PDF, TXT, and Markdown files up to 50MB
              </p>
            </div>
            <div>
              <span className="inline-flex items-center gap-2 px-5 py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white font-semibold text-xs rounded-xl shadow-lg shadow-indigo-600/25 transition-all">
                <span>Choose Files</span>
              </span>
            </div>
          </label>
        )}
      </div>

      {error && (
        <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-400 text-sm font-medium flex items-center gap-3">
          <span>⚠️</span>
          <span>{error}</span>
        </div>
      )}

      {/* Documents Table */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between">
          <h3 className="text-base font-semibold text-white">Indexed Documents ({documents.length})</h3>
          <span className="text-xs text-slate-500">Auto-refreshing every 3s</span>
        </div>

        {documents.length === 0 ? (
          <div className="p-12 text-center text-slate-500 text-sm">
            No documents in the knowledge base yet. Upload a PDF above to get started!
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="bg-slate-950/80 border-b border-slate-800 text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  <th className="py-3.5 px-6">Document Name</th>
                  <th className="py-3.5 px-6">Pages</th>
                  <th className="py-3.5 px-6">Chunks</th>
                  <th className="py-3.5 px-6">File Size</th>
                  <th className="py-3.5 px-6">Status</th>
                  <th className="py-3.5 px-6 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 text-sm">
                {documents.map((doc) => (
                  <tr key={doc.doc_id} className="hover:bg-slate-800/40 transition-colors">
                    <td className="py-4 px-6 font-medium text-slate-200 flex items-center gap-3">
                      <span className="w-8 h-8 rounded bg-indigo-500/10 text-indigo-400 flex items-center justify-center font-bold text-xs">
                        PDF
                      </span>
                      <div>
                        <div className="font-semibold text-slate-100">{doc.filename}</div>
                        <div className="text-[11px] text-slate-500 font-mono">ID: {doc.doc_id}</div>
                      </div>
                    </td>
                    <td className="py-4 px-6 text-slate-300 font-mono">{doc.pages || 0}</td>
                    <td className="py-4 px-6 font-mono">
                      <span className="px-2 py-0.5 rounded bg-slate-800 text-indigo-300 text-xs font-semibold">
                        {doc.chunks_count || 0} chunks
                      </span>
                    </td>
                    <td className="py-4 px-6 text-slate-400 text-xs font-mono">
                      {(doc.file_size / 1024).toFixed(1)} KB
                    </td>
                    <td className="py-4 px-6">
                      <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium border capitalize ${
                        doc.status === 'processed'
                          ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                          : doc.status === 'error'
                          ? 'bg-rose-500/10 text-rose-400 border-rose-500/20'
                          : 'bg-amber-500/10 text-amber-400 border-amber-500/20 animate-pulse'
                      }`}>
                        <span className={`w-1.5 h-1.5 rounded-full ${doc.status === 'processed' ? 'bg-emerald-400' : 'bg-amber-400'}`}></span>
                        {doc.status === 'processed' ? '✓ Processed' : doc.status}
                      </span>
                    </td>
                    <td className="py-4 px-6 text-right space-x-2">
                      <button
                        onClick={() => openChunkInspector(doc.doc_id)}
                        className="px-3 py-1.5 bg-indigo-600/20 hover:bg-indigo-600/40 text-indigo-300 border border-indigo-500/30 rounded-lg text-xs font-medium transition-all"
                      >
                        View Chunks
                      </button>
                      <button
                        onClick={() => handleReprocess(doc.doc_id)}
                        className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-medium border border-slate-700 transition-all"
                      >
                        Reprocess
                      </button>
                      <button
                        onClick={() => handleDelete(doc.doc_id)}
                        className="px-3 py-1.5 bg-rose-600/20 hover:bg-rose-600/40 text-rose-400 border border-rose-500/30 rounded-lg text-xs font-medium transition-all"
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
