import React, { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../services/api';
import DatasetPanel from '../components/evaluation/DatasetPanel';
import ResultsMatrix from '../components/evaluation/ResultsMatrix';
import AnalysisPanel from '../components/evaluation/AnalysisPanel';
import RagTracePanel from '../components/evaluation/RagTracePanel';
import RepoPanel from '../components/evaluation/RepoPanel';

/**
 * The systematic evaluation, one tab per exercise.
 *
 * A full run is 30 questions across every selected model and takes tens of
 * minutes, so it is started as a background job on the gateway and polled here.
 * Streaming it over a single request would mean a page reload throws away half
 * an hour of GPU time; polling survives reloads and lets the run be inspected
 * while it is still going.
 */

const TABS = [
  { id: 'run', label: 'Run', exercise: 'Exercise 1' },
  { id: 'dataset', label: 'Dataset', exercise: 'Exercise 2' },
  { id: 'results', label: 'Results', exercise: 'Exercise 3' },
  { id: 'analysis', label: 'Analysis', exercise: 'Exercise 4' },
  { id: 'rag', label: 'RAG Pipeline', exercise: 'Exercise 5' },
  { id: 'repo', label: 'Repository', exercise: 'Exercise 6' },
];

const POLL_MS = 2000;

const fmtDuration = (seconds) => {
  if (!seconds) return '—';
  const m = Math.floor(seconds / 60);
  return m ? `${m}m ${Math.round(seconds % 60)}s` : `${Math.round(seconds)}s`;
};

export default function EvaluationLab() {
  const [tab, setTab] = useState('run');

  const [dataset, setDataset] = useState(null);
  const [kb, setKb] = useState(null);
  const [catalog, setCatalog] = useState(null);
  const [selected, setSelected] = useState([]);

  const [topK, setTopK] = useState(4);
  const [maxTokens, setMaxTokens] = useState(512);
  const [temperature, setTemperature] = useState(0.2);
  const [limit, setLimit] = useState('');

  const [status, setStatus] = useState(null);
  const [runs, setRuns] = useState([]);
  const [report, setReport] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const pollRef = useRef(null);
  const lastRunIdRef = useRef(null);

  const loadRuns = useCallback(async () => {
    try {
      const list = await api.getEvaluationRuns(20);
      setRuns(list);
      if (list.length && !lastRunIdRef.current) {
        lastRunIdRef.current = list[0].run_id;
        setReport(await api.getEvaluationReport(list[0].run_id));
      }
    } catch {
      // A missing run list should not blank the page.
    }
  }, []);

  useEffect(() => {
    api.getEvaluationDataset().then(setDataset).catch((e) => setError(e.message));
    api.getEvaluationKb().then(setKb).catch(() => {});
    api.getAvailableModels()
      .then((data) => { setCatalog(data); setSelected(data.default_selection || []); })
      .catch((e) => setError(e.message));
    api.getSettings().then((s) => setTopK(parseInt(s.top_k, 10) || 4)).catch(() => {});
    loadRuns();
  }, [loadRuns]);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  /**
   * One poll. Loads the finished report the first time it sees a settled run,
   * then stops the timer — including when the gateway reports `idle`, so a page
   * left open on an empty server does not poll for the rest of the day.
   */
  const tick = useCallback(async () => {
    try {
      const snapshot = await api.getEvaluationStatus();
      setStatus(snapshot);

      if (snapshot.state === 'error') {
        setError(snapshot.error);
        stopPolling();
        return;
      }
      if (snapshot.state === 'running') return;

      if ((snapshot.state === 'done' || snapshot.state === 'cancelled')
          && snapshot.run_id && snapshot.run_id !== lastRunIdRef.current) {
        lastRunIdRef.current = snapshot.run_id;
        setReport(await api.getEvaluationReport(snapshot.run_id));
        loadRuns();
        setTab('results');
      }
      stopPolling();
    } catch {
      // Gateway hiccup: keep the timer running rather than abandoning the run.
    }
  }, [loadRuns, stopPolling]);

  const startPolling = useCallback(() => {
    if (!pollRef.current) pollRef.current = setInterval(tick, POLL_MS);
  }, [tick]);

  useEffect(() => {
    tick();
    startPolling();
    return stopPolling;
  }, [tick, startPolling, stopPolling]);

  const running = status?.state === 'running';

  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.startEvaluation({
        models: selected,
        top_k: Number(topK),
        max_tokens: Number(maxTokens),
        temperature: Number(temperature),
        limit: limit ? Number(limit) : null,
      });
      // A new run means the previously loaded report is no longer the latest;
      // clearing the ref lets the next settled poll pick the new one up.
      lastRunIdRef.current = null;
      setStatus(await api.getEvaluationStatus());
      startPolling();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const cancel = async () => {
    try { await api.cancelEvaluation(); } catch (e) { setError(e.message); }
  };

  const rebuildKb = async () => {
    setBusy(true);
    try {
      await api.rebuildEvaluationKb();
      setKb(await api.getEvaluationKb());
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const openRun = async (runId) => {
    try {
      lastRunIdRef.current = runId;
      setReport(await api.getEvaluationReport(runId));
      setTab('results');
    } catch (e) {
      setError(e.message);
    }
  };

  const exportReport = () => {
    if (!report) return;
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${report.run_id}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const questionsTotal = limit ? Number(limit) : (dataset?.size || 30);
  const estimateMinutes = Math.round((questionsTotal * selected.length * 12) / 60);

  return (
    <div className="p-8 max-w-[1600px] mx-auto space-y-6">
      {/* Header */}
      <div className="flex flex-col lg:flex-row lg:items-end lg:justify-between gap-4">
        <div>
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 mb-2">
            <span>🔬 Systematic model evaluation</span>
          </div>
          <h1 className="text-2xl font-bold text-white">Evaluation Lab</h1>
          <p className="text-sm text-slate-400 max-w-3xl">
            The same {dataset?.size || 30} tasks, the same prompts, the same knowledge base and the same retrieved
            context put through every installed model, scored on correctness, relevance, retrieval quality,
            hallucination rate, test-pass rate, latency, token usage and CPU / GPU / memory.
          </p>
        </div>
        {report && (
          <button
            onClick={exportReport}
            className="shrink-0 px-4 py-2 rounded-xl text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700"
          >
            ⬇ Export report as JSON
          </button>
        )}
      </div>

      {/* Tabs */}
      <div className="flex flex-wrap gap-1.5 border-b border-slate-800 pb-3">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-4 py-2 rounded-xl text-xs font-semibold border transition-colors ${
              tab === t.id
                ? 'bg-indigo-600/15 text-indigo-300 border-indigo-500/30'
                : 'bg-slate-900 text-slate-400 border-slate-800 hover:border-slate-700 hover:text-slate-200'
            }`}
          >
            {t.label}
            <span className="block text-[10px] font-normal opacity-60">{t.exercise}</span>
          </button>
        ))}
      </div>

      {error && (
        <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-400 text-sm font-medium">
          ⚠️ {error}
        </div>
      )}

      {/* Live progress, visible on every tab while a run is going */}
      {running && (
        <div className="p-5 rounded-2xl bg-slate-900 border border-indigo-500/30 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-sm font-semibold text-white">
                Evaluating {status.progress.current_model || '…'} —
                model {status.progress.models_done + 1} of {status.progress.models_total}
              </p>
              <p className="text-[11px] text-slate-500 font-mono">{status.stage}</p>
            </div>
            <button
              onClick={cancel}
              className="px-4 py-2 rounded-xl text-xs font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/20 hover:bg-rose-500/20"
            >
              Cancel run
            </button>
          </div>
          <div className="h-1.5 w-full rounded-full bg-slate-800 overflow-hidden">
            <div
              className="h-full rounded-full bg-gradient-to-r from-indigo-500 to-emerald-500 transition-all duration-500"
              style={{
                width: `${((status.progress.models_done + (status.progress.questions_done / (status.progress.questions_total || 1)))
                  / (status.progress.models_total || 1)) * 100}%`,
              }}
            />
          </div>
          <div className="flex flex-wrap gap-2">
            {Object.entries(status.live_rows || {}).map(([model, row]) => (
              <span key={model} className="px-2.5 py-1 rounded-lg text-[11px] font-mono bg-slate-950 border border-slate-800 text-slate-400">
                {model}: {row.correct}/{row.answered} correct ·
                {' '}{Math.round(row.latency_ms / Math.max(1, row.answered))} ms avg ·
                {' '}{row.tokens.toLocaleString()} tokens
              </span>
            ))}
          </div>
        </div>
      )}

      {/* --- Run tab (Exercise 1) --- */}
      {tab === 'run' && (
        <div className="space-y-6">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-6">
            <div>
              <div className="flex items-center justify-between mb-2">
                <label className="text-xs font-semibold text-slate-400 uppercase">
                  Models to compare ({selected.length} selected)
                </label>
                {catalog?.ollama === 'offline' && (
                  <span className="text-xs text-rose-400 font-medium">Ollama offline</span>
                )}
              </div>
              <div className="flex flex-wrap gap-2.5">
                {(catalog?.models || []).map((m) => {
                  const isOn = selected.includes(m.name);
                  return (
                    <button
                      key={m.tag}
                      type="button"
                      onClick={() => setSelected((prev) =>
                        prev.includes(m.name) ? prev.filter((x) => x !== m.name) : [...prev, m.name])}
                      className={`px-3.5 py-2.5 rounded-xl border text-left transition-all ${
                        isOn
                          ? 'bg-indigo-500/10 border-indigo-500/30 text-indigo-300'
                          : 'bg-slate-950 border-slate-800 text-slate-400 hover:border-slate-700'
                      }`}
                    >
                      <div className="flex items-center gap-2 text-sm font-semibold">
                        <span className={`w-2 h-2 rounded-full ${isOn ? 'bg-indigo-400' : 'bg-slate-700'}`} />
                        {m.name}
                      </div>
                      <div className="text-[11px] text-slate-500 font-mono mt-0.5">
                        {m.parameter_size || m.family} · {m.size_gb} GB
                      </div>
                    </button>
                  );
                })}
                {!catalog && <span className="text-sm text-slate-500">Loading installed models…</span>}
              </div>
              <p className="text-[11px] text-slate-500 mt-2">
                Only models already pulled into Ollama are listed — nothing is downloaded.
                The evaluation needs at least three for a comparison to mean anything.
              </p>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-4 gap-4">
              {[
                ['Top-K chunks', topK, setTopK, 'Retrieved once per question, shared by every model.'],
                ['Max output tokens', maxTokens, setMaxTokens, 'Caps each answer so a verbose model cannot skew latency.'],
                ['Temperature', temperature, setTemperature, 'Identical sampling for every model. Seed is fixed at 42.'],
                ['Question limit', limit, setLimit, `Blank runs all ${dataset?.size || 30}. Set a small number for a smoke run.`],
              ].map(([label, value, setter, hint]) => (
                <div key={label}>
                  <label className="text-xs font-semibold text-slate-400 uppercase block mb-1.5">{label}</label>
                  <input
                    type="number" value={value} onChange={(e) => setter(e.target.value)}
                    placeholder={label === 'Question limit' ? 'all' : undefined}
                    className="w-full px-4 py-2.5 bg-slate-950 border border-slate-800 rounded-xl text-sm text-white focus:outline-none focus:border-indigo-500"
                  />
                  <p className="text-[11px] text-slate-500 mt-1">{hint}</p>
                </div>
              ))}
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <button
                onClick={start}
                disabled={running || busy || selected.length === 0}
                className="px-6 py-3 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 disabled:text-slate-500 text-white font-semibold text-sm rounded-xl shadow-lg shadow-indigo-600/30"
              >
                {running ? 'Evaluation in progress…' : `🔬 Evaluate ${selected.length} model${selected.length === 1 ? '' : 's'} on ${questionsTotal} tasks`}
              </button>
              <span className="text-[11px] text-slate-500">
                {questionsTotal * selected.length} generations, run one model at a time so they don't contend for the
                GPU — roughly {estimateMinutes} minutes. Progress survives a page reload.
              </span>
            </div>
          </div>

          {/* Knowledge base */}
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 pb-3">
              <div>
                <h3 className="text-sm font-semibold text-white">Evaluation knowledge base</h3>
                <p className="text-xs text-slate-400">
                  A dedicated collection holding one clean copy of each policy document, so retrieval precision
                  measures retrieval rather than how many duplicate uploads happen to exist.
                </p>
              </div>
              <button
                onClick={rebuildKb}
                disabled={busy || running}
                className="shrink-0 px-4 py-2 rounded-xl text-xs font-semibold bg-slate-800 hover:bg-slate-700 disabled:opacity-50 text-slate-200 border border-slate-700"
              >
                Rebuild
              </button>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {[
                ['Collection', kb?.knowledge_base?.collection || '—'],
                ['Chunks', kb?.knowledge_base?.chunks ?? '—'],
                ['Documents', kb?.knowledge_base?.documents?.length ?? '—'],
                ['Status', kb?.knowledge_base?.ready ? 'ready' : 'needs building'],
              ].map(([label, value]) => (
                <div key={label} className="p-3.5 rounded-xl bg-slate-950 border border-slate-800">
                  <p className="text-[11px] text-slate-500 uppercase font-semibold">{label}</p>
                  <p className="text-sm font-bold font-mono text-slate-200">{value}</p>
                </div>
              ))}
            </div>
            {kb?.knowledge_base?.documents && (
              <div className="flex flex-wrap gap-1.5">
                {kb.knowledge_base.documents.map((doc) => (
                  <span key={doc} className="px-2 py-0.5 rounded text-[10px] font-mono bg-slate-950 text-slate-400 border border-slate-800">
                    {doc}
                  </span>
                ))}
              </div>
            )}
          </div>

          {/* Previous runs */}
          {runs.length > 0 && (
            <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-3">
              <h3 className="text-sm font-semibold text-white border-b border-slate-800 pb-3">
                Completed evaluations
              </h3>
              <div className="space-y-2">
                {runs.map((run) => (
                  <div key={run.run_id}
                       className="flex items-center justify-between gap-4 p-3.5 rounded-xl bg-slate-950 border border-slate-800 hover:border-slate-700 transition-colors">
                    <button onClick={() => openRun(run.run_id)} className="flex-1 text-left min-w-0">
                      <p className="text-xs font-semibold text-slate-200 font-mono truncate">{run.run_id}</p>
                      <p className="text-[11px] text-slate-500 font-mono">
                        {run.models.join(' · ')} — {run.dataset_size} tasks in {fmtDuration(run.wall_seconds)} ·
                        {' '}{new Date(run.created_at + 'Z').toLocaleString()}
                      </p>
                    </button>
                    <button
                      onClick={async () => { await api.deleteEvaluationRun(run.run_id); loadRuns(); }}
                      className="shrink-0 px-2.5 py-1 rounded-lg text-[11px] font-semibold text-slate-500 hover:text-rose-400 hover:bg-rose-500/10"
                    >
                      Delete
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {tab === 'dataset' && <DatasetPanel dataset={dataset} />}

      {tab === 'results' && (report
        ? <ResultsMatrix report={report} definitions={dataset?.metric_definitions} notes={dataset?.category_metric_notes} />
        : <p className="text-sm text-slate-500">No evaluation has finished yet. Start one from the Run tab.</p>)}

      {tab === 'analysis' && (report
        ? <AnalysisPanel report={report} />
        : <p className="text-sm text-slate-500">No evaluation has finished yet. Start one from the Run tab.</p>)}

      {tab === 'rag' && (report
        ? <RagTracePanel report={report} />
        : <p className="text-sm text-slate-500">No evaluation has finished yet. Start one from the Run tab.</p>)}

      {tab === 'repo' && <RepoPanel models={selected} />}
    </div>
  );
}
