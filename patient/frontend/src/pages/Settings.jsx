import React, { useState, useEffect } from 'react';
import { api } from '../services/api';

const STT_LANGUAGES = [
  { code: 'hi-IN', name: 'Hindi' },
  { code: 'bn-IN', name: 'Bengali' },
  { code: 'ta-IN', name: 'Tamil' },
  { code: 'te-IN', name: 'Telugu' },
  { code: 'kn-IN', name: 'Kannada' },
  { code: 'ml-IN', name: 'Malayalam' },
  { code: 'mr-IN', name: 'Marathi' },
  { code: 'gu-IN', name: 'Gujarati' },
  { code: 'pa-IN', name: 'Punjabi' },
  { code: 'or-IN', name: 'Odia' },
  { code: 'as-IN', name: 'Assamese' },
  { code: 'ur-IN', name: 'Urdu' },
  { code: 'sa-IN', name: 'Sanskrit' },
  { code: 'ne-IN', name: 'Nepali' }
];

function VoiceStatusPanel({ caps }) {
  const rows = [
    {
      label: 'Speech-to-Text',
      detail: caps?.stt,
      readyHint: 'VEXYL-STT · indic-conformer-600m-multilingual',
      fallbackHint: 'Falling back to the browser Web Speech API'
    },
    {
      label: 'Text-to-Speech',
      detail: caps?.tts,
      readyHint: 'Futurix-AI/Hindi-TTS · F5-TTS @ 24 kHz',
      fallbackHint: 'Falling back to the browser speech synthesizer'
    }
  ];

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/60 divide-y divide-slate-800/80">
      {rows.map((row) => {
        const ready = row.detail?.available === true;
        return (
          <div key={row.label} className="p-4 flex items-start justify-between gap-4">
            <div className="space-y-0.5 min-w-0">
              <div className="text-sm font-medium text-slate-200">{row.label}</div>
              <div className="text-[11px] text-slate-500 font-mono truncate">
                {ready ? row.detail.model || row.readyHint : row.fallbackHint}
              </div>
              {!ready && row.detail?.reason && (
                <div className="text-[11px] text-amber-500/80">{row.detail.reason}</div>
              )}
            </div>
            <span
              className={`shrink-0 px-2.5 py-1 rounded-full text-[11px] font-semibold border ${
                ready
                  ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                  : 'bg-amber-500/10 text-amber-400 border-amber-500/20'
              }`}
            >
              {ready ? 'Model ready' : 'Browser fallback'}
            </span>
          </div>
        );
      })}
    </div>
  );
}

export default function Settings() {
  const [settings, setSettings] = useState({
    chunk_size: '800',
    chunk_overlap: '100',
    top_k: '4',
    llm_model: 'llama3.2',
    embedding_model: 'nomic-embed-text',
    ollama_base_url: 'http://localhost:11434',
    voice_input_enabled: 'true',
    voice_output_enabled: 'false',
    stt_language: 'hi-IN',
    vexyl_stt_url: 'http://localhost:8091',
    vexyl_stt_api_key: '',
    hindi_tts_url: '',
    hindi_tts_ref_audio: ''
  });
  const [loading, setLoading] = useState(true);
  const [saved, setSaved] = useState(false);
  const [voiceCaps, setVoiceCaps] = useState(null);
  const [checkingVoice, setCheckingVoice] = useState(false);

  useEffect(() => {
    loadSettings();
    refreshVoiceStatus();
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

  const refreshVoiceStatus = async () => {
    setCheckingVoice(true);
    try {
      const caps = await api.getVoiceCapabilities();
      setVoiceCaps(caps);
    } catch (e) {
      console.error("Error loading voice capabilities:", e);
      setVoiceCaps(null);
    } finally {
      setCheckingVoice(false);
    }
  };

  const handleSave = async (e) => {
    e.preventDefault();
    try {
      await api.updateSettings(settings);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
      // Voice backends are probed with the saved URLs, so re-check afterwards.
      refreshVoiceStatus();
    } catch (e) {
      alert("Failed to save settings: " + e.message);
    }
  };

  const update = (key) => (e) => setSettings({ ...settings, [key]: e.target.value });

  return (
    <div className="p-8 max-w-4xl mx-auto space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-white">System Configuration</h1>
        <p className="text-sm text-slate-400">Manage RAG chunking parameters, vector similarity limits, Ollama model options, and the speech input/output backends.</p>
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

        <h3 className="text-base font-semibold text-white border-b border-slate-800 pb-3 pt-4 flex items-center justify-between">
          <span>Voice Interface (Speech Input & Output)</span>
          <button
            type="button"
            onClick={refreshVoiceStatus}
            className="text-xs font-medium text-indigo-400 hover:underline"
          >
            {checkingVoice ? 'Checking...' : 'Re-check backends'}
          </button>
        </h3>

        <VoiceStatusPanel caps={voiceCaps} />

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="space-y-2">
            <label className="text-xs font-semibold text-slate-300 uppercase block">
              Voice Prompt Input
            </label>
            <select
              value={settings.voice_input_enabled}
              onChange={update('voice_input_enabled')}
              className="w-full px-4 py-2.5 bg-slate-950 border border-slate-800 rounded-xl text-sm text-white focus:outline-none focus:border-indigo-500"
            >
              <option value="true">Enabled — show the mic button in Chat</option>
              <option value="false">Disabled — text input only</option>
            </select>
            <p className="text-[11px] text-slate-500">Dictate questions instead of typing them</p>
          </div>

          <div className="space-y-2">
            <label className="text-xs font-semibold text-slate-300 uppercase block">
              Speak Answers Automatically
            </label>
            <select
              value={settings.voice_output_enabled}
              onChange={update('voice_output_enabled')}
              className="w-full px-4 py-2.5 bg-slate-950 border border-slate-800 rounded-xl text-sm text-white focus:outline-none focus:border-indigo-500"
            >
              <option value="false">Off — press "Listen" on a reply</option>
              <option value="true">On — read every new answer aloud</option>
            </select>
            <p className="text-[11px] text-slate-500">The "Listen" button works either way</p>
          </div>

          <div className="space-y-2">
            <label className="text-xs font-semibold text-slate-300 uppercase block">
              Default Speech Language
            </label>
            <select
              value={settings.stt_language}
              onChange={update('stt_language')}
              className="w-full px-4 py-2.5 bg-slate-950 border border-slate-800 rounded-xl text-sm text-white focus:outline-none focus:border-indigo-500"
            >
              {STT_LANGUAGES.map((lang) => (
                <option key={lang.code} value={lang.code}>
                  {lang.name} ({lang.code})
                </option>
              ))}
            </select>
            <p className="text-[11px] text-slate-500">Recognised by indic-conformer-600m-multilingual</p>
          </div>

          <div className="space-y-2">
            <label className="text-xs font-semibold text-slate-300 uppercase block">
              VEXYL-STT Server URL
            </label>
            <input
              type="text"
              value={settings.vexyl_stt_url}
              onChange={update('vexyl_stt_url')}
              placeholder="http://localhost:8091"
              className="w-full px-4 py-2.5 bg-slate-950 border border-slate-800 rounded-xl text-sm text-white focus:outline-none focus:border-indigo-500 font-mono"
            />
            <p className="text-[11px] text-slate-500">Indian-language speech-to-text server. Blank uses the VEXYL_STT_URL environment variable, then browser dictation.</p>
          </div>

          <div className="space-y-2">
            <label className="text-xs font-semibold text-slate-300 uppercase block">
              VEXYL-STT API Key
            </label>
            <input
              type="password"
              value={settings.vexyl_stt_api_key}
              onChange={update('vexyl_stt_api_key')}
              placeholder="(only if the server sets VEXYL_STT_API_KEY)"
              className="w-full px-4 py-2.5 bg-slate-950 border border-slate-800 rounded-xl text-sm text-white focus:outline-none focus:border-indigo-500 font-mono"
            />
            <p className="text-[11px] text-slate-500">Sent as the X-API-Key header</p>
          </div>

          <div className="space-y-2">
            <label className="text-xs font-semibold text-slate-300 uppercase block">
              Hindi TTS Server URL
            </label>
            <input
              type="text"
              value={settings.hindi_tts_url}
              onChange={update('hindi_tts_url')}
              placeholder="http://localhost:8092"
              className="w-full px-4 py-2.5 bg-slate-950 border border-slate-800 rounded-xl text-sm text-white focus:outline-none focus:border-indigo-500 font-mono"
            />
            <p className="text-[11px] text-slate-500">F5-TTS server hosting Futurix-AI/Hindi-TTS (24 kHz)</p>
          </div>

          <div className="space-y-2 md:col-span-2">
            <label className="text-xs font-semibold text-slate-300 uppercase block">
              Hindi TTS Reference Audio Path
            </label>
            <input
              type="text"
              value={settings.hindi_tts_ref_audio}
              onChange={update('hindi_tts_ref_audio')}
              placeholder="D:\\voices\\ref_audio.wav"
              className="w-full px-4 py-2.5 bg-slate-950 border border-slate-800 rounded-xl text-sm text-white focus:outline-none focus:border-indigo-500 font-mono"
            />
            <p className="text-[11px] text-slate-500">
              Only used by the local <span className="font-mono">f5-tts_infer-cli</span> path. F5-TTS clones the voice in this clip, so a clean 5–10 second Hindi sample works best.
            </p>
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
