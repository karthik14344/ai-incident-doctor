import React, { useEffect, useState } from 'react';
import { api } from '../services/api';

export default function ChunkInspector({ selectedDocId }) {
  const [documents, setDocuments] = useState([]);
  const [activeDocId, setActiveDocId] = useState(selectedDocId || '');
  const [chunks, setChunks] = useState([]);
  const [loading, setLoading] = useState(false);
  const [searchFilter, setSearchFilter] = useState('');
  const [selectedChunk, setSelectedChunk] = useState(null);

  useEffect(() => {
    loadDocumentsList();
  }, []);

  useEffect(() => {
    if (activeDocId) {
      loadChunks(activeDocId);
    }
  }, [activeDocId]);

  const loadDocumentsList = async () => {
    try {
      const data = await api.getDocuments();
      setDocuments(data);
      if (!activeDocId && data.length > 0) {
        setActiveDocId(data[0].doc_id);
      }
    } catch (e) {
      console.error("Error loading documents:", e);
    }
  };

  const loadChunks = async (docId) => {
    setLoading(true);
    try {
      const data = await api.getDocumentChunks(docId);
      setChunks(data);
      if (data.length > 0) {
        setSelectedChunk(data[0]);
      } else {
        setSelectedChunk(null);
      }
    } catch (e) {
      console.error("Error loading chunks:", e);
    } finally {
      setLoading(false);
    }
  };

  const currentDoc = documents.find(d => d.doc_id === activeDocId);

  const filteredChunks = chunks.filter(c => 
    c.text.toLowerCase().includes(searchFilter.toLowerCase()) ||
    `chunk #${c.chunk_index}`.includes(searchFilter.toLowerCase()) ||
    `page ${c.page_number}`.includes(searchFilter.toLowerCase())
  );

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Document Chunk Inspector</h1>
          <p className="text-sm text-slate-400">Inspect exact text segments, page mappings, token counts, and vector embedding dimensions generated during ingestion.</p>
        </div>

        {/* Document Selector Dropdown */}
        <div className="flex items-center gap-3">
          <label className="text-xs font-semibold text-slate-400 uppercase">Select Document:</label>
          <select
            value={activeDocId}
            onChange={(e) => setActiveDocId(e.target.value)}
            className="px-4 py-2 bg-slate-900 border border-slate-700 rounded-xl text-sm font-semibold text-white focus:outline-none focus:border-indigo-500"
          >
            {documents.map((d) => (
              <option key={d.doc_id} value={d.doc_id}>
                {d.filename} ({d.chunks_count || 0} chunks)
              </option>
            ))}
          </select>
        </div>
      </div>

      {currentDoc && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4 bg-slate-900 border border-slate-800 rounded-2xl p-5">
          <div>
            <span className="text-xs font-medium text-slate-500 uppercase">Filename</span>
            <p className="text-sm font-bold text-white truncate">{currentDoc.filename}</p>
          </div>
          <div>
            <span className="text-xs font-medium text-slate-500 uppercase">Total Pages</span>
            <p className="text-sm font-bold text-indigo-400">{currentDoc.pages || 0} Pages</p>
          </div>
          <div>
            <span className="text-xs font-medium text-slate-500 uppercase">Total Chunks</span>
            <p className="text-sm font-bold text-emerald-400">{currentDoc.chunks_count || 0} Chunks</p>
          </div>
          <div>
            <span className="text-xs font-medium text-slate-500 uppercase">Vector Collection</span>
            <p className="text-sm font-bold text-purple-400">{currentDoc.collection_name || 'default'}</p>
          </div>
        </div>
      )}

      {/* Main Chunk View & Details Split Screen */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
        {/* Left Column: Chunk List */}
        <div className="lg:col-span-5 bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden flex flex-col h-[650px]">
          <div className="p-4 border-b border-slate-800 space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-white">Chunks ({filteredChunks.length})</h3>
              <span className="text-xs text-slate-500">Click a chunk to inspect</span>
            </div>
            <input
              type="text"
              placeholder="Search in chunks text or page #..."
              value={searchFilter}
              onChange={(e) => setSearchFilter(e.target.value)}
              className="w-full px-3.5 py-2 bg-slate-950 border border-slate-800 rounded-lg text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
            />
          </div>

          <div className="divide-y divide-slate-800/60 overflow-y-auto flex-1 p-2 space-y-1">
            {loading ? (
              <div className="p-8 text-center text-slate-500 text-sm">Loading chunks...</div>
            ) : filteredChunks.length === 0 ? (
              <div className="p-8 text-center text-slate-500 text-sm">No chunks match filter.</div>
            ) : (
              filteredChunks.map((chunk) => {
                const isSelected = selectedChunk?.chunk_id === chunk.chunk_id;
                return (
                  <div
                    key={chunk.chunk_id}
                    onClick={() => setSelectedChunk(chunk)}
                    className={`p-3.5 rounded-xl cursor-pointer transition-all ${
                      isSelected
                        ? 'bg-indigo-600/15 border border-indigo-500/40 shadow-sm'
                        : 'hover:bg-slate-800/50 border border-transparent'
                    }`}
                  >
                    <div className="flex items-center justify-between text-xs font-semibold mb-1">
                      <span className={isSelected ? 'text-indigo-400' : 'text-slate-300'}>
                        Chunk #{chunk.chunk_index}
                      </span>
                      <span className="px-2 py-0.5 rounded bg-slate-950 text-slate-400 border border-slate-800 text-[10px]">
                        Page {chunk.page_number}
                      </span>
                    </div>
                    <p className="text-xs text-slate-400 line-clamp-2 leading-relaxed font-mono">
                      {chunk.text}
                    </p>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Right Column: Chunk Detail Inspector */}
        <div className="lg:col-span-7 bg-slate-900 border border-slate-800 rounded-2xl p-6 flex flex-col h-[650px] space-y-5">
          {selectedChunk ? (
            <>
              <div className="flex items-center justify-between border-b border-slate-800 pb-4">
                <div>
                  <span className="text-xs font-semibold text-indigo-400 uppercase tracking-wider">Chunk Inspector</span>
                  <h3 className="text-lg font-bold text-white">Chunk #{selectedChunk.chunk_index}</h3>
                </div>
                <div className="flex items-center gap-2">
                  <span className="px-3 py-1 bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 rounded-full text-xs font-semibold">
                    Page {selectedChunk.page_number}
                  </span>
                  <span className="px-3 py-1 bg-purple-500/10 text-purple-400 border border-purple-500/20 rounded-full text-xs font-semibold">
                    {selectedChunk.embedding_dim || 384} Dimensions
                  </span>
                </div>
              </div>

              {/* Chunk Text View */}
              <div className="space-y-2 flex-1 overflow-y-auto">
                <label className="text-xs font-semibold text-slate-400 uppercase">Extracted Text Payload:</label>
                <div className="p-4 rounded-xl bg-slate-950 border border-slate-800 font-mono text-xs text-slate-200 leading-relaxed whitespace-pre-wrap selection:bg-indigo-500/30">
                  {selectedChunk.text}
                </div>
              </div>

              {/* Metadata & Vector Details */}
              <div className="space-y-3 pt-4 border-t border-slate-800">
                <h4 className="text-xs font-semibold text-slate-400 uppercase">Vector & Chunk Metadata</h4>
                <div className="grid grid-cols-3 gap-3 text-xs">
                  <div className="p-3 bg-slate-950 rounded-lg border border-slate-800">
                    <span className="text-slate-500 block text-[10px]">CHUNK ID</span>
                    <span className="font-mono font-semibold text-slate-200 truncate block">{selectedChunk.chunk_id}</span>
                  </div>
                  <div className="p-3 bg-slate-950 rounded-lg border border-slate-800">
                    <span className="text-slate-500 block text-[10px]">WORD / TOKEN COUNT</span>
                    <span className="font-mono font-semibold text-indigo-300">{selectedChunk.token_count || selectedChunk.text.split(' ').length} words</span>
                  </div>
                  <div className="p-3 bg-slate-950 rounded-lg border border-slate-800">
                    <span className="text-slate-500 block text-[10px]">VECTOR STORE</span>
                    <span className="font-mono font-semibold text-emerald-300">ChromaDB Persistent</span>
                  </div>
                </div>
              </div>
            </>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center text-slate-500 text-sm">
              <span>Select a chunk from the left panel to inspect details</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
