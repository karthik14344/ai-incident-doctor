import React, { useMemo, useState } from 'react';

/**
 * Exercise 3 — the quantitative comparison, one column per model.
 *
 * Every row states how it was calculated (from the evaluation service, not from
 * a copy kept here) and how many questions it averaged over. The counts matter:
 * hallucination rate skips greetings and code tasks, correctness on the
 * out-of-scope probes scores abstention rather than facts, and an average over
 * 26 questions is not comparable with one over 30 unless it says so.
 *
 * Below the overall matrix sits the category-wise comparison: the same run
 * broken down by the seven assessment categories, per model, with the metric
 * the category is being read on. A metric with nothing to measure in a
 * category reads "n/a" there — it is never folded in as a zero.
 */

/** The seven assessment categories, in report order. A saved run recorded
 *  before the re-categorisation can carry older labels — those are appended
 *  rather than dropped, so history still renders. */
const CATEGORY_ORDER = [
  'Explanation', 'Code Retrieval', 'Dependency Understanding', 'Bug Analysis',
  'Code Generation', 'Refactoring', 'RAG-based Question',
];

/** One selectable view of the category table. `sub` explains what the number
 *  averaged over, or why the cell has no number at all. */
const CATEGORY_METRICS = [
  { key: 'accuracy_pct', label: 'Accuracy', unit: '%', better: 'higher',
    sub: (b) => `${b.correct}/${b.n} correct` },
  { key: 'correctness_pct', label: 'Correctness (mean)', unit: '%', better: 'higher' },
  { key: 'relevance_pct', label: 'Relevance (mean)', unit: '%', better: 'higher' },
  { key: 'hallucination_rate_pct', label: 'Hallucination rate', unit: '%', better: 'lower',
    sub: (b) => b.hallucination_n
      ? `over ${b.hallucination_n} question${b.hallucination_n === 1 ? '' : 's'}`
      : 'not measured here' },
  { key: 'retrieval_quality_pct', label: 'Retrieval quality', unit: '%', better: 'higher',
    sub: (b) => b.retrieval_quality_n
      ? `over ${b.retrieval_quality_n} question${b.retrieval_quality_n === 1 ? '' : 's'}`
      : 'no gold chunk applies' },
  { key: 'test_pass_rate_pct', label: 'Test-pass rate', unit: '%', better: 'higher',
    sub: (b) => b.tests_total
      ? `${b.tests_passed}/${b.tests_total} unit tests · ${b.code_tasks_fully_passing}/${b.code_tasks_total} tasks fully passing`
      : 'no code task here' },
  { key: 'latency_ms_mean', label: 'Latency (mean)', unit: 'ms', better: 'lower' },
  { key: 'ttft_ms_mean', label: 'First token (mean)', unit: 'ms', better: 'lower' },
  { key: 'total_tokens', label: 'Token usage (total)', unit: 'tokens', better: 'lower' },
];

/** Which applicability note describes each category metric (latency and token
 *  usage apply to every category, so they have none). */
const METRIC_NOTE_KEY = {
  accuracy_pct: 'correctness',
  correctness_pct: 'correctness',
  relevance_pct: 'relevance',
  hallucination_rate_pct: 'hallucination',
  retrieval_quality_pct: 'retrieval_quality',
  test_pass_rate_pct: 'test_pass_rate',
};

const fmt = (value, unit) => {
  if (value === null || value === undefined) return 'n/a';
  if (unit === 'ms') return value >= 1000 ? `${(value / 1000).toFixed(2)} s` : `${Math.round(value)} ms`;
  if (unit === '%') return `${value}%`;
  if (unit === 'MB') return `${Math.round(value).toLocaleString()} MB`;
  if (unit === 'tokens') return Number(value).toLocaleString();
  return `${value}`;
};

/**
 * `def` names the METRIC_DEFINITIONS entry this row is scored by, so the formula
 * shown is the one that produced the number rather than whatever a fuzzy name
 * match happened to land on. `plain` says in ordinary words what the row asks;
 * three rows share the correctness definition but ask different questions of it,
 * so each states its own.
 */
const ROWS = [
  { group: 'Quality', label: 'Accuracy', key: 'accuracy_pct', unit: '%', better: 'higher',
    def: 'correctness_pct',
    plain: 'Out of the 30 questions, how many did the model get right? A question counts as right when its answer scored 70 or above.',
    detail: (a) => `${a.questions_ok} questions scored` },
  { group: 'Quality', label: 'Correctness (mean)', key: 'correctness_pct', unit: '%', better: 'higher',
    def: 'correctness_pct',
    plain: 'Averaged across every question, how complete were the answers? Accuracy only asks pass or fail; this shows how much of each answer was there.',
    detail: (a) => `over ${a.correctness_n} questions` },
  { group: 'Quality', label: 'Relevance (mean)', key: 'relevance_pct', unit: '%', better: 'higher',
    def: 'relevance_pct',
    detail: (a) => `over ${a.relevance_n} questions` },
  { group: 'Quality', label: 'Hallucination rate (mean)', key: 'hallucination_rate_pct', unit: '%', better: 'lower',
    def: 'hallucination_rate_pct',
    detail: (a) => `over ${a.hallucination_n} questions (greetings and code tasks excluded)` },
  { group: 'Quality', label: 'Correct abstentions', key: 'abstention_correct', unit: '', better: 'higher',
    def: 'correctness_pct',
    plain: 'Three questions have no answer anywhere in the documents. Did the model say it did not know, instead of inventing something?',
    detail: (a) => `of ${a.abstention_total} out-of-scope probes` },
  { group: 'Quality', label: 'Test-pass rate', key: 'test_pass_rate_pct', unit: '%', better: 'higher',
    def: 'test_pass_rate_pct',
    detail: (a) => `${a.tests_passed}/${a.tests_total} unit tests · ${a.code_tasks_fully_passing}/${a.code_tasks_total} tasks fully passing` },

  { group: 'Latency', label: 'Response latency (mean)', key: 'latency_ms_mean', unit: 'ms', better: 'lower',
    def: 'latency_ms_mean',
    plain: 'The typical wait for a complete answer.' },
  { group: 'Latency', label: 'Response latency (median)', key: 'latency_ms_median', unit: 'ms', better: 'lower',
    plain: 'The middle wait. Unlike the mean, one very slow answer cannot drag it.' },
  { group: 'Latency', label: 'Response latency (p95)', key: 'latency_ms_p95', unit: 'ms', better: 'lower',
    plain: 'The slow tail: 19 answers out of 20 arrived faster than this.' },
  { group: 'Latency', label: 'Time to first token (mean)', key: 'ttft_ms_mean', unit: 'ms', better: 'lower',
    plain: 'How long before the first word appears. This is what a user experiences as responsiveness.' },
  { group: 'Latency', label: 'End-to-end incl. retrieval (mean)', key: 'end_to_end_ms_mean', unit: 'ms', better: 'lower',
    plain: 'The whole round trip, including searching the documents, not just the model writing.' },

  { group: 'Tokens', label: 'Total tokens (dataset)', key: 'total_tokens', unit: 'tokens', better: 'lower',
    def: 'total_tokens' },
  { group: 'Tokens', label: 'Prompt tokens (total)', key: 'prompt_tokens_total', unit: 'tokens', better: 'lower',
    plain: 'Text going in: the question plus the retrieved pages. Every model read the same pages, so differences here are only the tokenizer.' },
  { group: 'Tokens', label: 'Completion tokens (total)', key: 'completion_tokens_total', unit: 'tokens', better: 'lower',
    plain: 'Text coming out. A high number means long, wordy answers, not better ones.' },
  { group: 'Tokens', label: 'Throughput (mean)', key: 'tokens_per_sec_mean', unit: '', better: 'higher',
    plain: 'Writing speed. A model can be fast per word yet slow overall if it writes too much.',
    detail: () => 'tokens per second' },

  { group: 'Resources', label: 'CPU (mean during generation)', key: 'cpu_percent_mean', unit: '%', better: 'lower',
    def: 'gpu_mem_peak_mb',
    plain: 'How hard the processor worked while answering. Machine-wide, so read it against the idle baseline below.' },
  { group: 'Resources', label: 'CPU over idle baseline', key: 'cpu_percent_over_baseline', unit: '%', better: 'lower',
    plain: 'The same figure with the background load subtracted.',
    detail: () => 'what this model added to an already-busy machine' },
  { group: 'Resources', label: 'CPU (peak)', key: 'cpu_percent_peak', unit: '%', better: 'lower',
    plain: 'The single busiest moment of the run.' },
  { group: 'Resources', label: 'Ollama processes RSS (peak)', key: 'process_rss_peak_mb', unit: 'MB', better: 'lower',
    plain: 'Ordinary memory held by the model server at its highest point.',
    detail: () => 'ollama serve plus its llama-server runner, where the weights live' },
  { group: 'Resources', label: 'Ollama RSS over idle baseline', key: 'process_rss_over_baseline_mb', unit: 'MB', better: 'lower',
    plain: 'The same figure minus what was already held before the run started.' },
  { group: 'Resources', label: 'System RAM in use (peak)', key: 'system_ram_used_peak_mb', unit: 'MB', better: 'lower',
    plain: 'Total memory in use across the whole machine, not just the model.' },
  { group: 'Resources', label: 'System RAM over idle baseline', key: 'system_ram_over_baseline_mb', unit: 'MB', better: 'lower',
    plain: 'How much extra memory the machine needed once this model started.' },
  { group: 'Resources', label: 'GPU utilisation (mean)', key: 'gpu_util_mean_pct', unit: '%', better: 'lower',
    plain: 'How busy the graphics card was. Near zero would mean the model ran on the CPU instead.' },
  { group: 'Resources', label: 'GPU memory (peak VRAM)', key: 'gpu_mem_peak_mb', unit: 'MB', better: 'lower',
    plain: 'Graphics-card memory in use at its highest point. This is the figure that decides whether a model fits on the card at all.' },
  { group: 'Resources', label: 'GPU memory over idle baseline', key: 'gpu_mem_over_baseline_mb', unit: 'MB', better: 'lower',
    plain: 'Graphics memory this model claimed for itself, with anything already resident subtracted.',
    detail: () => 'the VRAM this model actually claimed' },
];

const GROUPS = ['Quality', 'Latency', 'Tokens', 'Resources'];
const GROUP_STYLE = {
  Quality: 'text-amber-400',
  Latency: 'text-sky-400',
  Tokens: 'text-emerald-400',
  Resources: 'text-fuchsia-400',
};

function bestIndex(values, better) {
  const usable = values.map((v, i) => ({ v, i }))
    .filter(({ v }) => typeof v === 'number' && !Number.isNaN(v));
  if (usable.length < 2) return -1;
  return (better === 'lower'
    ? usable.reduce((a, b) => (b.v < a.v ? b : a))
    : usable.reduce((a, b) => (b.v > a.v ? b : a))).i;
}

/**
 * The plain-language line and the formula for a row, both from the API.
 *
 * A row's own `plain` wins over the definition's, because several rows share one
 * definition while asking different questions of it — accuracy and correctness
 * are both scored by the correctness formula, but one is a pass rate and the
 * other a mean, and printing the same sentence under both explains neither.
 */
function describe(row, definitions) {
  const def = row.def && definitions
    ? definitions.find((d) => d.key === row.def)
    : null;
  return { plain: row.plain || def?.plain || null, formula: def?.formula || null };
}

export default function ResultsMatrix({ report, definitions, notes }) {
  const [showFormulas, setShowFormulas] = useState(false);
  const [openCategory, setOpenCategory] = useState(true);
  const [categoryMetricKey, setCategoryMetricKey] = useState('accuracy_pct');

  const aggregates = report.aggregates || [];
  const retrieval = report.retrieval?.summary || {};
  const baseline = report.machine_baseline || {};
  const categories = useMemo(() => {
    const observed = [...new Set(aggregates.flatMap((a) => Object.keys(a.by_category || {})))];
    return [
      ...CATEGORY_ORDER.filter((c) => observed.includes(c)),
      ...observed.filter((c) => !CATEGORY_ORDER.includes(c)),
    ];
  }, [aggregates]);
  const categoryMetric = CATEGORY_METRICS.find((m) => m.key === categoryMetricKey) || CATEGORY_METRICS[0];

  /** Categories where the selected metric has no measurement, with the reason
   *  recorded by the evaluation service rather than a guessed one. */
  const notApplicableHere = useMemo(() => {
    const noteKey = METRIC_NOTE_KEY[categoryMetric.key];
    if (!noteKey) return [];
    return categories
      .map((cat) => {
        const note = notes?.[cat];
        if (!note || note[noteKey] != null) return null;
        const reason = (note.n_a || []).find((entry) => entry.startsWith(noteKey));
        return { category: cat, reason: reason ? reason.slice(noteKey.length + 3) : 'not applicable here' };
      })
      .filter(Boolean);
  }, [categories, notes, categoryMetric]);

  const exportCategoriesCsv = () => {
    const header = ['category', 'questions',
      ...aggregates.flatMap((a) => CATEGORY_METRICS.map((m) => `${a.model} - ${m.label}`))];
    const escape = (v) => `"${String(v).replace(/"/g, '""')}"`;
    const rows = categories.map((cat) => [
      cat,
      aggregates.find((a) => a.by_category?.[cat])?.by_category[cat]?.n ?? 0,
      ...aggregates.flatMap((a) => CATEGORY_METRICS.map((m) => {
        const bucket = a.by_category?.[cat];
        const value = bucket ? bucket[m.key] : null;
        return value === null || value === undefined ? 'n/a' : value;
      })),
    ]);
    const csv = [header, ...rows].map((r) => r.map(escape).join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${report.run_id}-category-comparison.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  if (!aggregates.length) {
    return <p className="text-sm text-slate-500">This run produced no scored models.</p>;
  }

  return (
    <div className="space-y-6">
      {/* Retrieval quality — pipeline-level, shared by every model */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-4">
        <div className="flex flex-wrap items-baseline justify-between gap-3 border-b border-slate-800 pb-3">
          <h3 className="text-base font-semibold text-white">Retrieval Quality — the shared stage</h3>
          <span className="text-xs text-slate-500">
            Run once per question; identical context reached every model, so this is not a model score
          </span>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
          {[
            ['Retrieval quality', `${retrieval.retrieval_quality_pct}%`, 'text-emerald-400'],
            ['Hit rate @k', `${retrieval.hit_rate_pct}%`, 'text-emerald-400'],
            ['Precision@k (raw)', `${retrieval.precision_at_k_mean}%`, 'text-amber-400'],
            ['Recall@k', `${retrieval.recall_at_k_mean}%`, 'text-sky-400'],
            ['MRR', retrieval.mrr_mean, 'text-indigo-400'],
          ].map(([label, value, accent]) => (
            <div key={label} className="p-3.5 rounded-xl bg-slate-950 border border-slate-800">
              <p className="text-[11px] text-slate-500 uppercase font-semibold">{label}</p>
              <p className={`text-lg font-bold font-mono ${accent}`}>{value}</p>
            </div>
          ))}
        </div>
        <p className="text-[11px] text-slate-500 leading-relaxed">
          Scored on {retrieval.questions_scored} questions; {retrieval.questions_skipped} skipped because no chunk in
          the corpus can answer them. Raw precision is low by construction — most questions are answered by one page
          while top-k retrieves four, so three slots are noise even when retrieval is perfect. The composite uses
          precision normalised against that ceiling.
          {retrieval.misses?.length > 0 && <> Retrieval missed entirely on: <span className="font-mono text-rose-400">{retrieval.misses.join(', ')}</span>.</>}
          {retrieval.partial?.length > 0 && <> Partial recall on: <span className="font-mono text-amber-400">{retrieval.partial.join(', ')}</span>.</>}
        </p>
      </div>

      {/* The matrix */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden">
        <div className="p-6 border-b border-slate-800 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-base font-semibold text-white">Quantitative Comparison</h3>
            <p className="text-xs text-slate-400">
              {report.dataset_size} identical tasks per model · top-k {report.config?.top_k} ·
              max {report.config?.max_tokens} tokens · temperature {report.config?.temperature} ·
              seed {report.config?.seed}
            </p>
          </div>
          <button
            onClick={() => setShowFormulas((v) => !v)}
            className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700"
          >
            {showFormulas ? 'Hide' : 'Show'} how each is calculated
          </button>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-950/70 border-b border-slate-800">
                <th className="text-left px-6 py-3 text-xs font-semibold text-slate-400 uppercase sticky left-0 bg-slate-950/70 min-w-[280px]">
                  Metric
                </th>
                {aggregates.map((a) => (
                  <th key={a.model} className="text-right px-6 py-3 min-w-[150px]">
                    <span className="text-xs font-bold text-slate-200">{a.model}</span>
                    {a.questions_failed > 0 && (
                      <span className="block text-[10px] font-mono text-rose-400">
                        {a.questions_failed} failed
                      </span>
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {GROUPS.map((group) => (
                <React.Fragment key={group}>
                  <tr className="bg-slate-950/40">
                    <td colSpan={aggregates.length + 1}
                        className={`px-6 py-2 text-[11px] font-bold uppercase tracking-wide ${GROUP_STYLE[group]}`}>
                      {group}
                    </td>
                  </tr>
                  {ROWS.filter((r) => r.group === group).map((row) => {
                    const values = aggregates.map((a) => a[row.key]);
                    const winner = bestIndex(values, row.better);
                    const { plain, formula } = describe(row, definitions);
                    return (
                      <tr key={row.key} className="border-b border-slate-800/60 hover:bg-slate-950/40 transition-colors">
                        <td className="px-6 py-2.5 sticky left-0 bg-slate-900 align-top">
                          <p className="text-xs font-medium text-slate-300">{row.label}</p>
                          {plain && (
                            <p className="text-[11px] text-slate-400 mt-1 max-w-xl leading-relaxed">{plain}</p>
                          )}
                          {showFormulas && formula && (
                            <p className="text-[11px] text-slate-500 mt-1 max-w-xl leading-relaxed border-l-2 border-slate-700 pl-2.5">
                              {formula}
                            </p>
                          )}
                        </td>
                        {aggregates.map((a, i) => (
                          <td key={a.model} className="px-6 py-2.5 text-right align-top">
                            <span className={`font-mono text-xs ${
                              i === winner
                                ? 'px-2 py-1 rounded bg-emerald-500/10 text-emerald-400 font-bold border border-emerald-500/20'
                                : values[i] === null || values[i] === undefined ? 'text-slate-600' : 'text-slate-300'
                            }`}>
                              {fmt(values[i], row.unit)}
                            </span>
                            {row.detail && (
                              <p className="text-[10px] text-slate-600 font-mono mt-0.5">{row.detail(a)}</p>
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

        <div className="px-6 py-4 border-t border-slate-800 bg-slate-950/40">
          <p className="text-[11px] text-slate-500">
            Machine baseline before the run: CPU {baseline.cpu_percent}% ·
            RAM {Math.round(baseline.system_ram_used_mb || 0).toLocaleString()} /
            {' '}{Math.round(baseline.system_ram_total_mb || 0).toLocaleString()} MB ·
            {baseline.gpu_present
              ? ` GPU ${Math.round(baseline.gpu_mem_used_mb).toLocaleString()} / ${Math.round(baseline.gpu_mem_total_mb).toLocaleString()} MB idle`
              : ' no NVIDIA GPU detected'}.
            {' '}CPU and system RAM are machine-wide, so read them against this baseline rather than as absolutes.
          </p>
        </div>
      </div>

      {/* Category-wise comparison — the overall row, broken down */}
      {categories.length > 0 && (
        <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden">
          <button
            onClick={() => setOpenCategory((v) => !v)}
            className="w-full p-6 border-b border-slate-800 flex items-center justify-between gap-3 text-left"
          >
            <div>
              <h3 className="text-base font-semibold text-white">Category-wise comparison</h3>
              <p className="text-xs text-slate-400">
                The same run broken down by the seven assessment categories, per model — a model can lead
                overall and still lose an entire category, which the overall score alone hides.
              </p>
            </div>
            <span className="text-xs text-slate-500 shrink-0">{openCategory ? 'Hide' : 'Show'}</span>
          </button>
          {openCategory && (
            <div className="space-y-1">
              {/* Which metric the category table is read on */}
              <div className="px-6 pt-5 flex flex-wrap gap-1.5">
                {CATEGORY_METRICS.map((m) => (
                  <button
                    key={m.key}
                    onClick={() => setCategoryMetricKey(m.key)}
                    className={`px-3 py-1.5 rounded-lg text-[11px] font-semibold border transition-colors ${
                      m.key === categoryMetricKey
                        ? 'bg-indigo-600/15 text-indigo-300 border-indigo-500/30'
                        : 'bg-slate-950 text-slate-400 border-slate-800 hover:border-slate-700 hover:text-slate-300'
                    }`}
                  >
                    {m.label}{m.unit ? ` (${m.unit})` : ''}
                  </button>
                ))}
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-slate-950/70 border-b border-slate-800">
                      <th className="text-left px-6 py-3 text-xs font-semibold text-slate-400 uppercase min-w-[240px]">
                        {categoryMetric.label} by category
                      </th>
                      {aggregates.map((a) => (
                        <th key={a.model} className="text-right px-6 py-3 text-xs font-bold text-slate-200">{a.model}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {categories.map((category) => {
                      const buckets = aggregates.map((a) => a.by_category?.[category]);
                      const values = buckets.map((b) => (b ? b[categoryMetric.key] ?? null : null));
                      const winner = bestIndex(values, categoryMetric.better);
                      const n = buckets.find(Boolean)?.n;
                      const note = notes?.[category];
                      const noteKey = METRIC_NOTE_KEY[categoryMetric.key];
                      const how = note && noteKey ? note[noteKey] : null;
                      return (
                        <tr key={category} className="border-b border-slate-800/60 hover:bg-slate-950/40 transition-colors">
                          <td className="px-6 py-2.5">
                            <span className="text-xs text-slate-300">{category}</span>
                            {n !== undefined && <span className="text-[10px] text-slate-600 font-mono ml-2">n={n}</span>}
                            {how && (
                              <p className="text-[10px] text-slate-600 mt-0.5 max-w-md">{how}</p>
                            )}
                          </td>
                          {values.map((value, i) => {
                            const bucket = buckets[i];
                            return (
                              <td key={i} className="px-6 py-2.5 text-right align-top">
                                <span className={`font-mono text-xs ${
                                  i === winner
                                    ? 'px-2 py-1 rounded bg-emerald-500/10 text-emerald-400 font-bold border border-emerald-500/20'
                                    : value === null || value === undefined ? 'text-slate-600' : 'text-slate-300'
                                }`}>
                                  {value === null || value === undefined ? 'n/a' : fmt(value, categoryMetric.unit)}
                                </span>
                                {bucket && categoryMetric.sub && (
                                  <p className="text-[10px] text-slate-600 font-mono mt-0.5">{categoryMetric.sub(bucket)}</p>
                                )}
                              </td>
                            );
                          })}
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              <div className="px-6 py-4 border-t border-slate-800 bg-slate-950/40 space-y-2">
                {notApplicableHere.length > 0 && (
                  <div className="space-y-1">
                    <p className="text-[11px] font-semibold text-slate-400">
                      {categoryMetric.label}: not applicable in {notApplicableHere.length === categories.length ? 'every' : `${notApplicableHere.length}`} categor{notApplicableHere.length === 1 ? 'y' : 'ies'} — reported as n/a, never counted as zero:
                    </p>
                    <ul className="space-y-0.5">
                      {notApplicableHere.map(({ category, reason }) => (
                        <li key={category} className="text-[11px] text-slate-500">
                          <span className="text-slate-400 font-medium">{category}</span> — {reason}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <p className="text-[11px] text-slate-500 max-w-3xl">
                    Category averages cover only the questions where the metric applies — the n= counts above say
                    what each cell averaged over, so a category cell is never quietly averaged over fewer questions
                    than it claims.
                  </p>
                  <button
                    onClick={exportCategoriesCsv}
                    className="shrink-0 px-3 py-1.5 rounded-lg text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition-colors"
                  >
                    ⬇ Export category breakdown (CSV)
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
