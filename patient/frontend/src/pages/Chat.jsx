import React, { useState, useEffect, useRef } from 'react';
import { api } from '../services/api';
import SuggestedQueries from '../components/SuggestedQueries';

export default function Chat({ setActiveTab }) {
  const [sessions, setSessions] = useState([]);
  const [activeSessionId, setActiveSessionId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [inputQuestion, setInputQuestion] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingTokenText, setStreamingTokenText] = useState('');
  const [streamingSources, setStreamingSources] = useState([]);
  const [streamingPipeline, setStreamingPipeline] = useState(null);

  const messagesEndRef = useRef(null);

  useEffect(() => {
    loadSessions();
  }, []);

  useEffect(() => {
    if (activeSessionId) {
      loadHistory(activeSessionId);
    }
  }, [activeSessionId]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingTokenText]);

  const loadSessions = async () => {
    try {
      const data = await api.getChatSessions();
      setSessions(data);
      if (data.length > 0 && !activeSessionId) {
        setActiveSessionId(data[0].id);
      }
    } catch (e) {
      console.error("Error loading sessions:", e);
    }
  };

  const loadHistory = async (sessId) => {
    try {
      const msgs = await api.getChatHistory(sessId);
      setMessages(msgs);
    } catch (e) {
      console.error("Error loading chat history:", e);
    }
  };

  const handleNewSession = async () => {
    try {
      const newSess = await api.createChatSession("New Conversation");
      setSessions([newSess, ...sessions]);
      setActiveSessionId(newSess.id);
      setMessages([]);
    } catch (e) {
      console.error("Error creating session:", e);
    }
  };

  const handleDeleteSession = async (sessId, e) => {
    e.stopPropagation();
    try {
      await api.deleteChatSession(sessId);
      const updated = sessions.filter(s => s.id !== sessId);
      setSessions(updated);
      if (activeSessionId === sessId) {
        setActiveSessionId(updated.length > 0 ? updated[0].id : null);
        setMessages([]);
      }
    } catch (e) {
      console.error("Error deleting session:", e);
    }
  };

  const handleSendMessage = async (e, overrideQuestion) => {
    if (e && e.preventDefault) e.preventDefault();
    const userQ = (overrideQuestion ?? inputQuestion).trim();
    if (!userQ || isStreaming) return;

    setInputQuestion('');

    // Append user message locally immediately
    const userMsgObj = {
      role: 'user',
      content: userQ,
      timestamp: new Date().toISOString()
    };
    setMessages((prev) => [...prev, userMsgObj]);

    setIsStreaming(true);
    setStreamingTokenText('');
    setStreamingSources([]);
    setStreamingPipeline(null);

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: activeSessionId,
          question: userQ,
          collection_name: 'default',
          stream: true
        })
      });

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let done = false;
      let fullText = '';
      let metaSources = [];
      let metaDebug = null;
      let newSessId = activeSessionId;

      while (!done) {
        const { value, done: readerDone } = await reader.read();
        done = readerDone;
        if (value) {
          const chunk = decoder.decode(value);
          const lines = chunk.split('\n');

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              try {
                const data = JSON.parse(line.slice(6));
                if (data.type === 'meta') {
                  metaSources = data.sources || [];
                  metaDebug = data.pipeline_debug || null;
                  if (data.session_id && data.session_id !== activeSessionId) {
                    newSessId = data.session_id;
                    setActiveSessionId(data.session_id);
                  }
                  setStreamingSources(metaSources);
                  setStreamingPipeline(metaDebug);
                } else if (data.token) {
                  fullText += data.token;
                  setStreamingTokenText((prev) => prev + data.token);
                }
              } catch (err) {
                // Ignore chunk parse error
              }
            }
          }
        }
      }

      // Add finished Assistant message to list
      const assistantMsgObj = {
        role: 'assistant',
        content: fullText,
        sources: metaSources,
        pipeline_debug: metaDebug,
        timestamp: new Date().toISOString()
      };

      setMessages((prev) => [...prev, assistantMsgObj]);
      loadSessions();

    } catch (err) {
      console.error("Stream connection error:", err);
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: '⚠️ Failed to connect to AI Assistant endpoint. Please verify backend microservices are running.',
          timestamp: new Date().toISOString()
        }
      ]);
    } finally {
      setIsStreaming(false);
      setStreamingTokenText('');
      setStreamingSources([]);
    }
  };

  return (
    <div className="flex h-[calc(100vh-4rem)] overflow-hidden">
      {/* Sessions Sidebar */}
      <div className="w-72 bg-slate-900/90 border-r border-slate-800 flex flex-col justify-between shrink-0">
        <div className="p-4 border-b border-slate-800 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-white">Chat History</h3>
          <button
            onClick={handleNewSession}
            className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-semibold flex items-center gap-1 shadow-sm transition-all"
          >
            <span>+ New Chat</span>
          </button>
        </div>

        <div className="overflow-y-auto flex-1 p-3 space-y-1">
          {sessions.length === 0 ? (
            <div className="text-center py-8 text-xs text-slate-500">No chat history</div>
          ) : (
            sessions.map((s) => {
              const isActive = s.id === activeSessionId;
              return (
                <div
                  key={s.id}
                  onClick={() => setActiveSessionId(s.id)}
                  className={`group w-full flex items-center justify-between px-3 py-2.5 rounded-lg text-xs font-medium cursor-pointer transition-all ${
                    isActive
                      ? 'bg-indigo-600/20 text-indigo-300 border border-indigo-500/30'
                      : 'text-slate-400 hover:bg-slate-800/60 hover:text-slate-200'
                  }`}
                >
                  <span className="truncate pr-2">{s.title || 'Conversation'}</span>
                  <button
                    onClick={(e) => handleDeleteSession(s.id, e)}
                    className="opacity-0 group-hover:opacity-100 text-slate-500 hover:text-rose-400 p-1"
                  >
                    ✕
                  </button>
                </div>
              );
            })
          )}
        </div>

        <div className="p-4 border-t border-slate-800">
          <button
            onClick={() => setActiveTab('pipeline')}
            className="w-full px-3 py-2 bg-slate-950 hover:bg-slate-800 border border-slate-800 rounded-lg text-xs font-medium text-slate-300 flex items-center justify-center gap-2"
          >
            <span>🔍 Debug RAG Pipeline</span>
          </button>
        </div>
      </div>

      {/* Chat Conversation Area */}
      <div className="flex-1 flex flex-col bg-slate-950 overflow-hidden">
        {/* Messages Scroll View */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {messages.length === 0 && !isStreaming ? (
            <div className="h-full flex flex-col items-center justify-center text-center space-y-4 max-w-md mx-auto">
              <div className="w-16 h-16 rounded-2xl bg-indigo-600/10 text-indigo-400 border border-indigo-500/20 flex items-center justify-center text-3xl shadow-lg">
                💬
              </div>
              <h2 className="text-xl font-bold text-white">Ask your documents...</h2>
              <p className="text-slate-400 text-xs leading-relaxed">
                KnowledgeAI retrieves top relevant chunks from ChromaDB, constructs exact context prompts, and streams factual answers using Llama 3.2.
              </p>
              <div className="pt-2 grid grid-cols-1 gap-2 w-full text-left">
                {[
                  "What is the minimum attendance policy?",
                  "Explain the rules for semester examinations.",
                  "What are the hostel regulations and timings?"
                ].map((sampleQ, idx) => (
                  <button
                    key={idx}
                    onClick={() => {
                      setInputQuestion(sampleQ);
                    }}
                    className="p-3 bg-slate-900 hover:bg-slate-800/80 border border-slate-800 rounded-xl text-xs text-indigo-300 text-left transition-all"
                  >
                    "{sampleQ}"
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <>
              {messages.map((msg, idx) => (
                <div
                  key={idx}
                  className={`flex flex-col ${msg.role === 'user' ? 'items-end' : 'items-start'}`}
                >
                  <div
                    className={`max-w-3xl rounded-2xl p-5 space-y-3 ${
                      msg.role === 'user'
                        ? 'bg-indigo-600 text-white rounded-br-none shadow-lg shadow-indigo-600/20'
                        : 'bg-slate-900 border border-slate-800 text-slate-100 rounded-bl-none'
                    }`}
                  >
                    <div className="flex items-center gap-2 text-xs font-semibold opacity-75">
                      <span>{msg.role === 'user' ? 'You' : 'KnowledgeAI Assistant'}</span>
                    </div>

                    <div className="text-sm leading-relaxed whitespace-pre-wrap font-sans">
                      {msg.content}
                    </div>

                    {/* RAG Sources Cards */}
                    {msg.role === 'assistant' && msg.sources && msg.sources.length > 0 && (
                      <div className="pt-4 border-t border-slate-800/80 space-y-2">
                        <span className="text-xs font-semibold text-indigo-400 uppercase tracking-wider block">
                          Retrieved Document Sources ({msg.sources.length})
                        </span>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                          {msg.sources.map((src, sIdx) => (
                            <div key={sIdx} className="p-3 rounded-lg bg-slate-950/80 border border-slate-800/80 space-y-1">
                              <div className="flex items-center justify-between text-xs">
                                <span className="font-semibold text-slate-200 truncate max-w-[150px]">
                                  📄 {src.filename}
                                </span>
                                <span className="px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 font-mono text-[10px] font-bold">
                                  Sim: {(src.similarity * 100).toFixed(0)}%
                                </span>
                              </div>
                              <div className="flex items-center justify-between text-[11px] text-slate-400">
                                <span>Page {src.page}</span>
                                <span>Chunk #{src.chunk_index}</span>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              ))}

              {/* Streaming state message */}
              {isStreaming && (
                <div className="flex flex-col items-start">
                  <div className="max-w-3xl rounded-2xl p-5 space-y-3 bg-slate-900 border border-slate-800 text-slate-100 rounded-bl-none w-full">
                    <div className="flex items-center gap-2 text-xs font-semibold text-indigo-400">
                      <span className="w-2 h-2 rounded-full bg-indigo-400 animate-ping"></span>
                      <span>KnowledgeAI generating response...</span>
                    </div>

                    <div className="text-sm leading-relaxed whitespace-pre-wrap font-sans">
                      {streamingTokenText || <span className="animate-pulse text-slate-500">Searching ChromaDB vectors...</span>}
                    </div>

                    {streamingSources.length > 0 && (
                      <div className="pt-3 border-t border-slate-800 space-y-2">
                        <span className="text-xs font-semibold text-indigo-400 uppercase tracking-wider block">
                          Retrieved Sources
                        </span>
                        <div className="grid grid-cols-2 gap-2">
                          {streamingSources.map((src, sIdx) => (
                            <div key={sIdx} className="p-2.5 rounded bg-slate-950 border border-slate-800 text-xs">
                              <div className="font-semibold text-slate-200">📄 {src.filename}</div>
                              <div className="text-[11px] text-emerald-400 font-mono">Page {src.page} &bull; Similarity: {src.similarity}</div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Input Bar */}
        <div className="p-4 border-t border-slate-800 bg-slate-900/60 backdrop-blur-md">
          <form onSubmit={handleSendMessage} className="max-w-4xl mx-auto flex items-center gap-3">
            <div className="flex-1 relative">
              <SuggestedQueries
                query={inputQuestion}
                disabled={isStreaming}
                onSelect={(suggestion) => handleSendMessage(null, suggestion)}
              />
              <input
                type="text"
                placeholder="Ask a question about your uploaded documents..."
                value={inputQuestion}
                onChange={(e) => setInputQuestion(e.target.value)}
                disabled={isStreaming}
                className="w-full px-5 py-3.5 bg-slate-950 border border-slate-800 rounded-xl text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500 disabled:opacity-50"
              />
            </div>

            <button
              type="submit"
              disabled={!inputQuestion.trim() || isStreaming}
              className="px-6 py-3.5 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 disabled:text-slate-500 text-white font-semibold text-sm rounded-xl shadow-lg shadow-indigo-600/30 transition-all flex items-center gap-2"
            >
              <span>Ask</span>
              <span className="text-base">➤</span>
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
