import React, { useState, useEffect, useRef, useMemo } from 'react';
import { api } from '../services/api';
import MetricGuide from '../components/MetricGuide';

/** Per-model accent colours, assigned by position so cards and bars stay in sync. */
const ACCENTS = [
  { text: 'text-indigo-400', bg: 'bg-indigo-500', soft: 'bg-indigo-500/10', border: 'border-indigo-500/30', dot: 'bg-indigo-400' },
  { text: 'text-emerald-400', bg: 'bg-emerald-500', soft: 'bg-emerald-500/10', border: 'border-emerald-500/30', dot: 'bg-emerald-400' },
  { text: 'text-amber-400', bg: 'bg-amber-500', soft: 'bg-amber-500/10', border: 'border-amber-500/30', dot: 'bg-amber-400' },
  { text: 'text-fuchsia-400', bg: 'bg-fuchsia-500', soft: 'bg-fuchsia-500/10', border: 'border-fuchsia-500/30', dot: 'bg-fuchsia-400' },
  { text: 'text-sky-400', bg: 'bg-sky-500', soft: 'bg-sky-500/10', border: 'border-sky-500/30', dot: 'bg-sky-400' },
  { text: 'text-rose-400', bg: 'bg-rose-500', soft: 'bg-rose-500/10', border: 'border-rose-500/30', dot: 'bg-rose-400' },
];

/**
 * The evaluation matrix, restricted to the assessment criteria and nothing else.
 *
 * Earlier revisions of this page carried a house metric set — groundedness,
 * context utilisation, citation counts, and a weighted composite score that
 * declared an overall winner. All of it is gone. Those were invented here, the
 * weights were a judgement call presented as a measurement, and a single number
 * hid exactly the trade-off the comparison exists to show. What remains is the
 * five quality metrics and three performance metrics the evaluation specifies,
 * each computed by the same code that produces the full dataset evaluation.
 */
const METRIC_ROWS = [
  { group: 'Quality', label: 'Correctness / Accuracy', unit: '%', better: 'higher',
    get: (r) => r.quality?.correctness?.value,
    applicable: (r) => r.quality?.correctness?.applicable,
    sub: (r) => r.quality?.correctness?.facts_total
      ? `${r.quality.correctness.facts_hit}/${r.quality.correctness.facts_total} facts`
      : null },
  { group: 'Quality', label: 'Relevance', unit: '%', better: 'higher',
    get: (r) => r.quality?.relevance?.value,
    applicable: () => true,
    sub: (r) => `topic ${r.quality?.relevance?.topic_coverage_pct}% · on-topic ${r.quality?.relevance?.on_topic_share_pct}%` },
  { group: 'Quality', label: 'Hallucination Rate', unit: '%', better: 'lower',
    get: (r) => r.quality?.hallucination?.value,
    applicable: (r) => r.quality?.hallucination?.applicable,
    sub: (r) => r.quality?.hallucination?.claims_total
      ? `${r.quality.hallucination.claims_unsupported}/${r.quality.hallucination.claims_total} claims unsupported`
      : null },
  { group: 'Quality', label: 'Test-Pass Rate (generated code)', unit: '%', better: 'higher',
    get: (r) => r.quality?.test_pass_rate?.value,
    applicable: (r) => r.quality?.test_pass_rate?.applicable,
    sub: (r) => r.quality?.test_pass_rate?.applicable
      ? `${r.quality.test_pass_rate.tests_passed}/${r.quality.test_pass_rate.tests_total} tests · ${r.quality.test_pass_rate.status}`
      : null },

  { group: 'Performance', label: 'Response latency (total)', unit: 'ms', better: 'lower',
    get: (r) => r.timings?.total_ms, applicable: () => true },
  { group: 'Performance', label: 'Response latency (first token)', unit: 'ms', better: 'lower',
    get: (r) => r.timings?.ttft_ms, applicable: () => true },
  { group: 'Performance', label: 'Response latency (end-to-end)', unit: 'ms', better: 'lower',
    get: (r) => r.timings?.end_to_end_ms, applicable: () => true },
  { group: 'Performance', label: 'Token usage (total)', unit: '', better: 'lower',
    get: (r) => r.tokens?.total_tokens, applicable: () => true,
    sub: (r) => `${r.tokens?.prompt_tokens} in / ${r.tokens?.completion_tokens} out` },
  { group: 'Performance', label: 'Token throughput', unit: 'tok/s', better: 'higher',
    get: (r) => r.tokens?.tokens_per_sec, applicable: () => true },
  { group: 'Performance', label: 'CPU (mean during generation)', unit: '%', better: 'lower',
    get: (r) => r.resources?.cpu_percent_mean, applicable: (r) => !!r.resources },
  { group: 'Performance', label: 'Memory — Ollama RSS peak', unit: 'MB', better: 'lower',
    get: (r) => r.resources?.process_rss_peak_mb, applicable: (r) => !!r.resources },
  { group: 'Performance', label: 'Memory — system RAM peak', unit: 'MB', better: 'lower',
    get: (r) => r.resources?.system_ram_used_peak_mb, applicable: (r) => !!r.resources },
  { group: 'Performance', label: 'GPU utilisation (mean)', unit: '%', better: 'lower',
    get: (r) => r.resources?.gpu_util_mean_pct, applicable: (r) => r.resources?.gpu_measured },
  { group: 'Performance', label: 'GPU memory peak (VRAM)', unit: 'MB', better: 'lower',
    get: (r) => r.resources?.gpu_mem_peak_mb, applicable: (r) => r.resources?.gpu_measured },
];

const GROUP_ORDER = ['Quality', 'Performance'];
const GROUP_STYLE = { Quality: 'text-amber-400', Performance: 'text-sky-400' };

/** Criterion leaders shown as cards. Retrieval quality is absent by design —
 *  it belongs to the pipeline, not to any model. */
const LEADER_CARDS = [
  { key: 'correctness', label: 'Highest correctness', icon: '🎯', unit: '%', accent: 'from-emerald-600/20 to-emerald-600/5 border-emerald-500/30 text-emerald-300' },
  { key: 'relevance', label: 'Most relevant', icon: '🧭', unit: '%', accent: 'from-indigo-600/20 to-indigo-600/5 border-indigo-500/30 text-indigo-300' },
  { key: 'hallucination', label: 'Fewest hallucinations', icon: '🛡️', unit: '%', accent: 'from-fuchsia-600/20 to-fuchsia-600/5 border-fuchsia-500/30 text-fuchsia-300' },
  { key: 'test_pass_rate', label: 'Best test-pass rate', icon: '🧪', unit: '%', accent: 'from-lime-600/20 to-lime-600/5 border-lime-500/30 text-lime-300' },
  { key: 'latency', label: 'Lowest latency', icon: '⚡', unit: 'ms', accent: 'from-sky-600/20 to-sky-600/5 border-sky-500/30 text-sky-300' },
  { key: 'token_usage', label: 'Fewest tokens', icon: '🔢', unit: '', accent: 'from-amber-600/20 to-amber-600/5 border-amber-500/30 text-amber-300' },
  { key: 'cpu', label: 'Lowest CPU', icon: '🖥️', unit: '%', accent: 'from-teal-600/20 to-teal-600/5 border-teal-500/30 text-teal-300' },
  { key: 'gpu_memory', label: 'Lowest VRAM', icon: '🎛️', unit: 'MB', accent: 'from-rose-600/20 to-rose-600/5 border-rose-500/30 text-rose-300' },
];

function formatValue(value, unit) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  if (unit === 'ms') return value >= 1000 ? `${(value / 1000).toFixed(2)} s` : `${Math.round(value)} ms`;
  if (unit === '%') return `${value}%`;
  if (unit === 'MB') return `${Math.round(value)} MB`;
  if (unit === 'tok/s') return `${value}`;
  return `${value}`;
}

/** Index of the best cell in a row, or -1 when the row has no winner. */
function bestIndex(values, better) {
  const usable = values
    .map((v, i) => ({ v, i }))
    .filter(({ v }) => typeof v === 'number' && !Number.isNaN(v));
  if (usable.length < 2) return -1;
  const pick = better === 'lower'
    ? usable.reduce((a, b) => (b.v < a.v ? b : a))
    : usable.reduce((a, b) => (b.v > a.v ? b : a));
  return pick.i;
}

function MetricBar({ value, max, accent }) {
  const width = max > 0 ? Math.max(2, Math.min(100, (value / max) * 100)) : 0;
  return (
    <div className="h-1.5 w-full rounded-full bg-slate-800 overflow-hidden">
      <div className={`h-full rounded-full ${accent} transition-all duration-500`} style={{ width: `${width}%` }} />
    </div>
  );
}

export default function ModelComparison() {
  const [question, setQuestion] = useState('What is the minimum attendance percentage required to be eligible to sit for semester examinations?');
  const [datasetId, setDatasetId] = useState('Q01');
  const [dataset, setDataset] = useState(null);
  const [catalog, setCatalog] = useState(null);
  const [selected, setSelected] = useState([]);
  const [topK, setTopK] = useState(4);
  const [maxTokens, setMaxTokens] = useState(512);
  const [temperature, setTemperature] = useState(0.2);
  const [warmup, setWarmup] = useState(true);

  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState(null);
  const [error, setError] = useState(null);

  const [retrieval, setRetrieval] = useState(null);
  const [sources, setSources] = useState([]);
  const [results, setResults] = useState([]);
  const [summary, setSummary] = useState(null);
  const [runId, setRunId] = useState(null);

  const [history, setHistory] = useState([]);
  const [showTableHelp, setShowTableHelp] = useState(false);
  const [showGuide, setShowGuide] = useState(false);

  const abortRef = useRef(null);

  useEffect(() => {
    loadCatalog();
    loadHistory();
    api.getEvaluationDataset().then(setDataset).catch(() => {});
    api.getSettings()
      .then((s) => setTopK(parseInt(s.top_k, 10) || 4))
      .catch(() => {});
    return () => abortRef.current?.abort();
  }, []);

  const loadCatalog = async () => {
    try {
      const data = await api.getAvailableModels();
      setCatalog(data);
      setSelected(data.default_selection || []);
    } catch (e) {
      setError(e.message || 'Could not reach Ollama to list installed models.');
    }
  };

  const loadHistory = async () => {
    try {
      setHistory(await api.getComparisonHistory(15));
    } catch {
      // History is a convenience; a failure here shouldn't block a new run.
    }
  };

  const toggleModel = (name) => {
    setSelected((prev) =>
      prev.includes(name) ? prev.filter((m) => m !== name) : [...prev, name]
    );
  };

  /** Picking a dataset question is what unlocks correctness, retrieval quality
   *  and test-pass rate: those three need ground truth, which a free-typed
   *  question does not have. */
  const pickDatasetQuestion = (id) => {
    setDatasetId(id);
    const item = dataset?.items?.find((i) => i.id === id);
    if (item) setQuestion(item.question);
  };

  const handleRun = async (e) => {
    e?.preventDefault();
    if (!question.trim() || selected.length === 0 || running) return;

    setRunning(true);
    setError(null);
    setResults([]);
    setSummary(null);
    setRetrieval(null);
    setSources([]);
    setRunId(null);
    setProgress({ stage: 'retrieval', done: 0, total: selected.length, current: null });

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      await api.compareModels(
        {
          question,
          models: selected,
          // A dataset question's gold labels describe pages in `eval_kb`, so it
          // has to be answered from there. A free-typed question is about the
          // user's own uploaded documents, which live in `default`.
          collection_name: datasetId ? 'eval_kb' : 'default',
          dataset_id: datasetId || null,
          top_k: Number(topK),
          max_tokens: Number(maxTokens),
          temperature: Number(temperature),
          warmup,
        },
        (evt) => {
          switch (evt.type) {
            case 'start':
              setRunId(evt.run_id);
              break;
            case 'retrieval':
              setRetrieval(evt.retrieval);
              setSources(evt.sources || []);
              setProgress({ stage: 'generating', done: 0, total: selected.length, current: null });
              break;
            case 'model_start':
              setProgress({ stage: 'generating', done: evt.index, total: evt.total, current: evt.model });
              break;
            case 'model_result':
              setResults((prev) => [...prev, evt.result]);
              break;
            case 'summary':
              setResults(evt.results || []);
              setSummary(evt.summary);
              setProgress(null);
              break;
            case 'error':
              setError(evt.error);
              break;
            default:
              break;
          }
        },
        controller.signal
      );
      loadHistory();
    } catch (err) {
      if (err.name !== 'AbortError') {
        setError(err.message || 'Comparison run failed.');
      }
    } finally {
      setRunning(false);
      setProgress(null);
      abortRef.current = null;
    }
  };

  const handleCancel = () => {
    abortRef.current?.abort();
    setRunning(false);
    setProgress(null);
  };

  const loadRun = async (id) => {
    try {
      const run = await api.getComparisonRun(id);
      setQuestion(run.question);
      setRunId(run.run_id);
      setRetrieval(run.retrieval_meta);
      setSources([]);
      setResults(run.results || []);
      setSummary(run.summary);
      setSelected(run.models || []);
      setError(null);
    } catch (e) {
      setError(e.message || 'Could not load that run.');
    }
  };

  const exportJson = () => {
    const blob = new Blob(
      [JSON.stringify({ run_id: runId, question, dataset_id: datasetId, retrieval, results, summary }, null, 2)],
      { type: 'application/json' }
    );
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${runId || 'model-comparison'}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const accentFor = (model) => {
    const idx = results.findIndex((r) => r.model === model);
    return ACCENTS[(idx >= 0 ? idx : 0) % ACCENTS.length];
  };

  const okResults = useMemo(() => results.filter((r) => r.status === 'ok'), [results]);

  const chartMetrics = useMemo(() => ([
    { label: 'Correctness (higher is better)', unit: '%', get: (r) => r.quality?.correctness?.value },
    { label: 'Relevance (higher is better)', unit: '%', get: (r) => r.quality?.relevance?.value },
    { label: 'Hallucination rate (lower is better)', unit: '%', get: (r) => r.quality?.hallucination?.value },
    { label: 'Response latency (lower is better)', unit: 'ms', get: (r) => r.timings?.total_ms },
    { label: 'Token usage (lower is better)', unit: '', get: (r) => r.tokens?.total_tokens },
    { label: 'GPU memory peak (lower is better)', unit: 'MB', get: (r) => r.resources?.gpu_mem_peak_mb },
  ]), []);

  const groundTruth = !!summary?.ground_truth_available;

  return (
    <div className="p-8 max-w-[1600px] mx-auto space-y-8">
      {/* Header */}
      <div className="flex flex-col lg:flex-row lg:items-end lg:justify-between gap-4">
        <div>
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold bg-fuchsia-500/10 text-fuchsia-400 border border-fuchsia-500/20 mb-2">
            <span>⚖️ Single-question model comparison</span>
          </div>
          <h1 className="text-2xl font-bold text-white">Model Comparison Lab</h1>
          <p className="text-sm text-slate-400 max-w-3xl">
            One question, several local models, the <span className="text-slate-300 font-medium">exact same retrieved context</span>,
            scored on the evaluation criteria only: correctness, relevance, retrieval quality, hallucination rate,
            test-pass rate, response latency, token usage and CPU / GPU / memory.
            For the full 30-question comparison across all models, use the <span className="text-slate-300 font-medium">Evaluation Lab</span>.
          </p>
        </div>

        <div className="flex items-center gap-2.5 shrink-0">
          <button
            onClick={() => setShowGuide((v) => !v)}
            className={`px-4 py-2 rounded-xl text-xs font-semibold border transition-colors ${
              showGuide
                ? 'bg-indigo-600/15 text-indigo-300 border-indigo-500/30'
                : 'bg-slate-800 hover:bg-slate-700 text-slate-200 border-slate-700'
            }`}
          >
            📖 {showGuide ? 'Hide' : 'How each metric is calculated'}
          </button>

          {results.length > 0 && (
            <button
              onClick={exportJson}
              className="px-4 py-2 rounded-xl text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 transition-colors"
            >
              ⬇ Export run as JSON
            </button>
          )}
        </div>
      </div>

      {showGuide && <MetricGuide onClose={() => setShowGuide(false)} definitions={dataset?.metric_definitions} />}

      {/* Configuration */}
      <form onSubmit={handleRun} className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-6">
        {/* Dataset question picker */}
        <div>
          <label className="text-xs font-semibold text-slate-400 uppercase block mb-1.5">
            Evaluation question
          </label>
          <div className="flex flex-col sm:flex-row gap-3">
            <select
              value={datasetId}
              onChange={(e) => pickDatasetQuestion(e.target.value)}
              className="sm:w-64 px-3 py-2.5 bg-slate-950 border border-slate-800 rounded-xl text-sm text-white focus:outline-none focus:border-indigo-500"
            >
              <option value="">Ad-hoc question (no ground truth)</option>
              {(dataset?.items || []).map((item) => (
                <option key={item.id} value={item.id}>
                  {item.id} · {item.category}
                </option>
              ))}
            </select>
            <textarea
              value={question}
              onChange={(e) => { setQuestion(e.target.value); setDatasetId(''); }}
              rows={2}
              placeholder="Ask something your documents can answer…"
              className="flex-1 px-4 py-3 bg-slate-950 border border-slate-800 rounded-xl text-sm text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500 resize-none"
            />
          </div>
          <p className={`text-[11px] mt-1.5 ${datasetId ? 'text-emerald-400/80' : 'text-amber-400/80'}`}>
            {datasetId
              ? `Ground truth attached (${datasetId}) — correctness, retrieval quality and test-pass rate are computable.`
              : 'No ground truth for a free-typed question, so correctness, retrieval quality and test-pass rate report as “not applicable” rather than being guessed. Only relevance, hallucination rate and the performance metrics are measurable.'}
          </p>
        </div>

        {/* Model picker */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <label className="text-xs font-semibold text-slate-400 uppercase">
              Models ({selected.length} selected)
            </label>
            {catalog?.ollama === 'offline' && (
              <span className="text-xs text-rose-400 font-medium">Ollama offline — start it to run a comparison</span>
            )}
          </div>

          <div className="flex flex-wrap gap-2.5">
            {(catalog?.models || []).map((m, idx) => {
              const isOn = selected.includes(m.name);
              const accent = ACCENTS[idx % ACCENTS.length];
              return (
                <button
                  key={m.tag}
                  type="button"
                  onClick={() => toggleModel(m.name)}
                  className={`px-3.5 py-2.5 rounded-xl border text-left transition-all ${
                    isOn
                      ? `${accent.soft} ${accent.border} ${accent.text}`
                      : 'bg-slate-950 border-slate-800 text-slate-400 hover:border-slate-700 hover:text-slate-300'
                  }`}
                >
                  <div className="flex items-center gap-2 text-sm font-semibold">
                    <span className={`w-2 h-2 rounded-full ${isOn ? accent.dot : 'bg-slate-700'}`} />
                    {m.name}
                  </div>
                  <div className="text-[11px] text-slate-500 font-mono mt-0.5">
                    {m.parameter_size || m.family || m.tag} · {m.size_gb} GB
                  </div>
                </button>
              );
            })}

            {!catalog && <span className="text-sm text-slate-500">Loading installed models…</span>}
            {catalog && (catalog.models || []).length === 0 && (
              <span className="text-sm text-slate-500">No chat-capable models found in Ollama.</span>
            )}
          </div>
          <p className="text-[11px] text-slate-500 mt-2">
            Only models already installed locally are listed — nothing is downloaded.
          </p>
        </div>

        {/* Run parameters */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div>
            <label className="text-xs font-semibold text-slate-400 uppercase block mb-1.5">Top-K chunks</label>
            <input
              type="number" min="1" max="20" value={topK}
              onChange={(e) => setTopK(e.target.value)}
              className="w-full px-4 py-2.5 bg-slate-950 border border-slate-800 rounded-xl text-sm text-white focus:outline-none focus:border-indigo-500"
            />
            <p className="text-[11px] text-slate-500 mt-1">Chunks retrieved once and shared by every model.</p>
          </div>
          <div>
            <label className="text-xs font-semibold text-slate-400 uppercase block mb-1.5">Max output tokens</label>
            <input
              type="number" min="64" max="4096" step="64" value={maxTokens}
              onChange={(e) => setMaxTokens(e.target.value)}
              className="w-full px-4 py-2.5 bg-slate-950 border border-slate-800 rounded-xl text-sm text-white focus:outline-none focus:border-indigo-500"
            />
            <p className="text-[11px] text-slate-500 mt-1">Caps each run so one verbose model can't skew timings.</p>
          </div>
          <div>
            <label className="text-xs font-semibold text-slate-400 uppercase block mb-1.5">Temperature</label>
            <input
              type="number" min="0" max="1" step="0.1" value={temperature}
              onChange={(e) => setTemperature(e.target.value)}
              className="w-full px-4 py-2.5 bg-slate-950 border border-slate-800 rounded-xl text-sm text-white focus:outline-none focus:border-indigo-500"
            />
            <p className="text-[11px] text-slate-500 mt-1">Identical sampling settings keep the comparison fair.</p>
          </div>
        </div>

        {/* Fair-timing toggle */}
        <label className="flex items-start gap-3 p-3.5 rounded-xl bg-slate-950 border border-slate-800 cursor-pointer">
          <input
            type="checkbox"
            checked={warmup}
            onChange={(e) => setWarmup(e.target.checked)}
            className="mt-0.5 w-4 h-4 accent-indigo-500"
          />
          <span>
            <span className="text-sm font-semibold text-slate-200">Warm up each model before timing it</span>
            <span className="block text-[11px] text-slate-500 mt-0.5">
              Loads the weights first so the model that runs first isn't penalised for absorbing a cold start of tens of
              seconds. Turn this off to measure realistic first-request latency instead, where load order matters.
            </span>
          </span>
        </label>

        <div className="flex flex-wrap items-center gap-3 pt-1">
          <button
            type="submit"
            disabled={running || selected.length === 0 || !question.trim()}
            className="px-6 py-3 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 disabled:text-slate-500 disabled:shadow-none text-white font-semibold text-sm rounded-xl shadow-lg shadow-indigo-600/30 transition-all"
          >
            {running ? 'Benchmarking…' : `⚡ Run comparison on ${selected.length} model${selected.length === 1 ? '' : 's'}`}
          </button>

          {running && (
            <button
              type="button"
              onClick={handleCancel}
              className="px-4 py-3 rounded-xl text-sm font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/20 hover:bg-rose-500/20 transition-colors"
            >
              Cancel run
            </button>
          )}

          <span className="text-[11px] text-slate-500">
            Models run sequentially so they don't compete for the GPU — expect roughly 20–60 s each.
          </span>
        </div>

        {/* Live progress */}
        {progress && (
          <div className="p-4 rounded-xl bg-slate-950 border border-slate-800 space-y-2">
            <div className="flex items-center justify-between text-xs">
              <span className="text-slate-300 font-medium">
                {progress.stage === 'retrieval'
                  ? '① Retrieving shared context from ChromaDB…'
                  : `② Generating with ${progress.current || 'next model'}…`}
              </span>
              <span className="font-mono text-slate-500">{progress.done}/{progress.total} models done</span>
            </div>
            <div className="h-1.5 w-full rounded-full bg-slate-800 overflow-hidden">
              <div
                className="h-full rounded-full bg-gradient-to-r from-indigo-500 to-fuchsia-500 transition-all duration-500"
                style={{ width: `${progress.total ? (progress.done / progress.total) * 100 : 5}%` }}
              />
            </div>
          </div>
        )}
      </form>

      {error && (
        <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-400 text-sm font-medium">
          ⚠️ {error}
        </div>
      )}

      {/* Retrieval quality — the pipeline's metric, not a model's */}
      {retrieval && (
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-4">
          <div className="flex items-center justify-between border-b border-slate-800 pb-3">
            <h3 className="text-base font-semibold text-white">Retrieval Quality (shared stage)</h3>
            <span className="text-xs text-slate-500">Executed once — identical context for every model</span>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
            {[
              { label: 'Retrieval time', value: formatValue(retrieval.retrieval_ms, 'ms'), accent: 'text-emerald-400' },
              { label: 'Chunks retrieved', value: `${retrieval.results_count} / ${retrieval.top_k}`, accent: 'text-indigo-400' },
              { label: 'Embedding dims', value: retrieval.query_embedding_dim, accent: 'text-sky-400' },
              { label: 'Context size', value: `${retrieval.context_chars} chars`, accent: 'text-amber-400' },
              { label: 'Top similarity', value: retrieval.top_similarity, accent: 'text-fuchsia-400' },
              { label: 'Avg similarity', value: retrieval.avg_similarity, accent: 'text-slate-300' },
            ].map((stat) => (
              <div key={stat.label} className="p-3.5 rounded-xl bg-slate-950 border border-slate-800">
                <p className="text-[11px] text-slate-500 uppercase font-semibold">{stat.label}</p>
                <p className={`text-lg font-bold font-mono ${stat.accent}`}>{stat.value}</p>
              </div>
            ))}
          </div>

          {/* Precision / recall / MRR only exist when the question has gold chunks. */}
          {okResults[0]?.quality?.retrieval_quality?.applicable ? (
            <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
              {[
                ['Retrieval quality', `${okResults[0].quality.retrieval_quality.value}%`],
                ['Precision@k', `${okResults[0].quality.retrieval_quality.precision_at_k}%`],
                ['Recall@k', `${okResults[0].quality.retrieval_quality.recall_at_k}%`],
                ['MRR', okResults[0].quality.retrieval_quality.mrr],
                ['Context noise', `${okResults[0].quality.retrieval_quality.context_noise_pct}%`],
              ].map(([label, value]) => (
                <div key={label} className="p-3.5 rounded-xl bg-emerald-500/5 border border-emerald-500/20">
                  <p className="text-[11px] text-emerald-300/70 uppercase font-semibold">{label}</p>
                  <p className="text-lg font-bold font-mono text-emerald-300">{value}</p>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-[11px] text-slate-500 p-3.5 rounded-xl bg-slate-950 border border-slate-800">
              {okResults[0]?.quality?.retrieval_quality?.note
                || 'Precision, recall and MRR need a question with known gold chunks. Pick an evaluation question above to compute them.'}
            </p>
          )}

          {sources.length > 0 && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {sources.map((src, idx) => (
                <div key={idx} className="p-3.5 rounded-xl bg-slate-950 border border-slate-800 space-y-1.5">
                  <div className="flex items-center justify-between text-xs font-semibold">
                    <span className="text-slate-200">📄 {src.filename} (Page {src.page})</span>
                    <span className="px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 font-mono text-[11px] border border-emerald-500/20">
                      {src.similarity}
                    </span>
                  </div>
                  <p className="text-[11px] text-slate-400 font-mono">{src.text}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Per-criterion leaders — no overall winner is declared */}
      {summary && summary.models_compared > 1 && (
        <div className="space-y-3">
          <div className="flex items-baseline justify-between gap-4">
            <h3 className="text-base font-semibold text-white">Leader per criterion</h3>
            <p className="text-[11px] text-slate-500 max-w-2xl text-right">
              No single overall winner is computed. Collapsing eight criteria into one score requires weights,
              and any weighting is an opinion about what matters rather than a measurement.
            </p>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {LEADER_CARDS.map((card) => {
              const leader = summary.leaders?.[card.key];
              if (!leader) return null;
              return (
                <div key={card.key} className={`p-4 rounded-2xl bg-gradient-to-br border ${card.accent}`}>
                  <p className="text-[10px] uppercase font-bold tracking-wide opacity-80">{card.icon} {card.label}</p>
                  <p className="text-lg font-bold text-white mt-1">{leader.model}</p>
                  <p className="text-xs opacity-90 font-mono">{formatValue(leader.value, card.unit)}</p>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Per-model answers */}
      {results.length > 0 && (
        <div className="space-y-4">
          <h3 className="text-base font-semibold text-white">Answers Side by Side</h3>
          <div className={`grid gap-4 ${results.length > 2 ? 'grid-cols-1 lg:grid-cols-2 2xl:grid-cols-4' : 'grid-cols-1 lg:grid-cols-2'}`}>
            {results.map((r, idx) => {
              const accent = ACCENTS[idx % ACCENTS.length];
              const failed = r.status !== 'ok';

              return (
                <div key={`${r.model}-${idx}`} className="rounded-2xl border border-slate-800 bg-slate-900 flex flex-col">
                  <div className="p-4 border-b border-slate-800 flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2 min-w-0">
                      <span className={`w-2.5 h-2.5 rounded-full shrink-0 ${failed ? 'bg-rose-500' : accent.dot}`} />
                      <div className="min-w-0">
                        <p className="text-sm font-bold text-white truncate">{r.model}</p>
                        <p className="text-[11px] text-slate-500 font-mono truncate">{r.model_tag || '—'}</p>
                      </div>
                    </div>
                    {failed && (
                      <span className="shrink-0 px-2 py-0.5 rounded text-[10px] font-bold bg-rose-500/15 text-rose-400 border border-rose-500/30">
                        FAILED
                      </span>
                    )}
                  </div>

                  {failed ? (
                    <div className="p-4 text-xs text-rose-400 font-mono break-words">{r.error}</div>
                  ) : (
                    <>
                      <div className="grid grid-cols-2 gap-px bg-slate-800 border-b border-slate-800">
                        {[
                          { label: 'Correctness', value: r.quality.correctness.applicable ? `${r.quality.correctness.value}%` : 'n/a' },
                          { label: 'Relevance', value: `${r.quality.relevance.value}%` },
                          { label: 'Hallucination', value: r.quality.hallucination.applicable ? `${r.quality.hallucination.value}%` : 'n/a' },
                          { label: 'Latency', value: formatValue(r.timings.total_ms, 'ms') },
                        ].map((stat) => (
                          <div key={stat.label} className="bg-slate-900 p-3">
                            <p className="text-[10px] text-slate-500 uppercase font-semibold">{stat.label}</p>
                            <p className={`text-sm font-bold font-mono ${accent.text}`}>{stat.value}</p>
                          </div>
                        ))}
                      </div>

                      <div className="p-4 text-xs text-slate-300 whitespace-pre-wrap leading-relaxed max-h-72 overflow-y-auto flex-1">
                        {r.answer}
                      </div>

                      <div className="px-4 py-2.5 border-t border-slate-800 flex flex-wrap gap-1.5">
                        <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-slate-950 border border-slate-800 text-slate-400">
                          {r.tokens.completion_tokens} out / {r.tokens.prompt_tokens} in
                        </span>
                        {r.resources?.gpu_measured && (
                          <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-slate-950 border border-slate-800 text-slate-400">
                            {Math.round(r.resources.gpu_mem_peak_mb)} MB VRAM
                          </span>
                        )}
                        {r.quality.test_pass_rate.applicable && (
                          <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-lime-500/10 border border-lime-500/20 text-lime-400">
                            {r.quality.test_pass_rate.tests_passed}/{r.quality.test_pass_rate.tests_total} tests
                          </span>
                        )}
                        {r.tokens.truncated && (
                          <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-amber-500/10 border border-amber-500/20 text-amber-400">
                            hit token cap
                          </span>
                        )}
                        {r.quality.correctness.abstained && (
                          <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-sky-500/10 border border-sky-500/20 text-sky-400">
                            abstained
                          </span>
                        )}
                        {r.quality.hallucination.fabricated_numbers?.length > 0 && (
                          <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-rose-500/10 border border-rose-500/20 text-rose-400">
                            invented: {r.quality.hallucination.fabricated_numbers.join(', ')}
                          </span>
                        )}
                      </div>
                    </>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Visual metric bars */}
      {okResults.length > 1 && (
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-6">
          <h3 className="text-base font-semibold text-white border-b border-slate-800 pb-3">Criteria Side by Side</h3>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-x-10 gap-y-6">
            {chartMetrics.map((metric) => {
              const values = okResults.map((r) => metric.get(r) || 0);
              const max = Math.max(...values, 0);
              if (!max) return null;
              return (
                <div key={metric.label} className="space-y-2.5">
                  <p className="text-xs font-semibold text-slate-400 uppercase">{metric.label}</p>
                  {okResults.map((r) => {
                    const accent = accentFor(r.model);
                    const value = metric.get(r) || 0;
                    return (
                      <div key={r.model} className="space-y-1">
                        <div className="flex items-center justify-between text-[11px]">
                          <span className="text-slate-300 font-medium">{r.model}</span>
                          <span className={`font-mono ${accent.text}`}>{formatValue(value, metric.unit)}</span>
                        </div>
                        <MetricBar value={value} max={max} accent={accent.bg} />
                      </div>
                    );
                  })}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Full metric table */}
      {okResults.length > 0 && (
        <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden">
          <div className="p-6 border-b border-slate-800 flex items-center justify-between gap-4">
            <div>
              <h3 className="text-base font-semibold text-white">Evaluation Criteria Matrix</h3>
              <p className="text-xs text-slate-400">
                Best value in each row is highlighted. Retrieval quality is shown above, not per model —
                the same chunks went to everyone.
              </p>
            </div>
            <button
              onClick={() => setShowTableHelp((v) => !v)}
              className="shrink-0 px-3 py-1.5 rounded-lg text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition-colors"
            >
              {showTableHelp ? 'Hide' : 'Show'} calculations
            </button>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-slate-950/70 border-b border-slate-800">
                  <th className="text-left px-6 py-3 text-xs font-semibold text-slate-400 uppercase sticky left-0 bg-slate-950/70 min-w-[260px]">
                    Criterion
                  </th>
                  {okResults.map((r) => {
                    const accent = accentFor(r.model);
                    return (
                      <th key={r.model} className="text-right px-6 py-3 min-w-[150px]">
                        <div className="flex items-center justify-end gap-2">
                          <span className={`w-2 h-2 rounded-full ${accent.dot}`} />
                          <span className="text-xs font-bold text-slate-200">{r.model}</span>
                        </div>
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {GROUP_ORDER.map((group) => (
                  <React.Fragment key={group}>
                    <tr className="bg-slate-950/40">
                      <td
                        colSpan={okResults.length + 1}
                        className={`px-6 py-2 text-[11px] font-bold uppercase tracking-wide ${GROUP_STYLE[group]}`}
                      >
                        {group} metrics
                      </td>
                    </tr>

                    {METRIC_ROWS.filter((m) => m.group === group).map((metric) => {
                      const values = okResults.map((r) => (metric.applicable(r) ? metric.get(r) : null));
                      const winner = bestIndex(values, metric.better);
                      const definition = dataset?.metric_definitions?.find(
                        (d) => metric.label.toLowerCase().startsWith(d.name.toLowerCase().split(' ')[0])
                      );

                      return (
                        <tr key={metric.label} className="border-b border-slate-800/60 hover:bg-slate-950/40 transition-colors">
                          <td className="px-6 py-2.5 sticky left-0 bg-slate-900">
                            <p className="text-xs font-medium text-slate-300">{metric.label}</p>
                            {showTableHelp && definition && (
                              <p className="text-[11px] text-slate-500 mt-0.5 max-w-lg">{definition.formula}</p>
                            )}
                          </td>
                          {okResults.map((r, i) => (
                            <td key={i} className="px-6 py-2.5 text-right">
                              <span
                                className={`font-mono text-xs ${
                                  i === winner
                                    ? 'px-2 py-1 rounded bg-emerald-500/10 text-emerald-400 font-bold border border-emerald-500/20'
                                    : values[i] === null ? 'text-slate-600' : 'text-slate-300'
                                }`}
                              >
                                {values[i] === null ? 'n/a' : formatValue(values[i], metric.unit)}
                              </span>
                              {metric.sub && metric.applicable(r) && metric.sub(r) && (
                                <p className="text-[10px] text-slate-600 font-mono mt-0.5">{metric.sub(r)}</p>
                              )}
                            </td>
                          ))}
                        </tr>
                      );
                    })}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          </div>

          <div className="px-6 py-4 border-t border-slate-800 bg-slate-950/40 space-y-2">
            {!groundTruth && (
              <p className="text-[11px] text-amber-400/80">
                This run had no ground truth attached, so correctness, retrieval quality and test-pass rate
                read “n/a”. Pick one of the {dataset?.size || 30} evaluation questions to fill them in.
              </p>
            )}
            <p className="text-[11px] text-slate-500">
              Quality metrics are lexical, not semantic — they compare models against each other, not against an
              absolute standard.{' '}
              <button
                onClick={() => setShowGuide(true)}
                className="text-indigo-400 hover:text-indigo-300 font-semibold underline underline-offset-2"
              >
                How each metric is calculated
              </button>
            </p>
          </div>
        </div>
      )}

      {/* Past runs */}
      {history.length > 0 && (
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-3">
          <h3 className="text-base font-semibold text-white border-b border-slate-800 pb-3">Previous Comparison Runs</h3>
          <div className="space-y-2">
            {history.map((run) => (
              <div
                key={run.run_id}
                className="flex items-center justify-between gap-4 p-3.5 rounded-xl bg-slate-950 border border-slate-800 hover:border-slate-700 transition-colors"
              >
                <button onClick={() => loadRun(run.run_id)} className="flex-1 text-left min-w-0">
                  <p className="text-xs font-semibold text-slate-200 truncate">{run.question}</p>
                  <p className="text-[11px] text-slate-500 font-mono">
                    {(run.models || []).join(' · ')} — {new Date(run.created_at + 'Z').toLocaleString()}
                  </p>
                </button>
                <button
                  onClick={async () => {
                    await api.deleteComparisonRun(run.run_id);
                    loadHistory();
                  }}
                  className="shrink-0 px-2.5 py-1 rounded-lg text-[11px] font-semibold text-slate-500 hover:text-rose-400 hover:bg-rose-500/10 transition-colors"
                >
                  Delete
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
