import React, { useEffect, useState } from 'react';
import { api } from '../../services/api';

/**
 * Exercise 6 — can this LLM + RAG stack answer repository-level questions?
 *
 * Each question is scored twice, and the gap between the two scores is the
 * whole finding:
 *
 *   index file recall  — did retrieval even hand over the files a correct
 *                        answer needs? A property of the architecture.
 *   answer coverage    — did the model name them? A property of the model.
 *
 * When the first number is low the second cannot be blamed on the model. That
 * is what motivates repository-level code intelligence: import graphs, call
 * graphs and reverse references are edges between files, and a flat vector
 * index over text chunks has nowhere to store an edge.
 */

function Bar({ pct, tone }) {
  const colour = tone === 'index'
    ? (pct >= 80 ? 'bg-emerald-500' : pct >= 50 ? 'bg-amber-500' : 'bg-rose-500')
    : 'bg-indigo-500';
  return (
    <div className="h-1.5 w-full rounded-full bg-slate-800 overflow-hidden">
      <div className={`h-full rounded-full ${colour} transition-all`} style={{ width: `${Math.max(2, pct)}%` }} />
    </div>
  );
}

function RepoTrace({ trace }) {
  const [open, setOpen] = useState(false);
  const index = trace.index_score;

  return (
    <div className="border-b border-slate-800/60 last:border-0">
      <button onClick={() => setOpen((v) => !v)}
              className="w-full p-4 text-left hover:bg-slate-950/40 transition-colors">
        <div className="flex items-start gap-3">
          <span className="font-mono text-[11px] text-slate-500 shrink-0 w-8 pt-0.5">{trace.id}</span>
          <div className="min-w-0 flex-1 space-y-2">
            <div>
              <p className="text-xs text-slate-200 leading-relaxed">{trace.question}</p>
              <p className="text-[11px] text-slate-500 mt-0.5">{trace.kind} · {trace.why_hard}</p>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="space-y-1">
                <div className="flex justify-between text-[10px] font-mono">
                  <span className="text-slate-500">index supplied the files</span>
                  <span className={index.file_recall_pct >= 80 ? 'text-emerald-400'
                    : index.file_recall_pct >= 50 ? 'text-amber-400' : 'text-rose-400'}>
                    {index.files_retrieved}/{index.expected_files} · {index.file_recall_pct}%
                  </span>
                </div>
                <Bar pct={index.file_recall_pct} tone="index" />
              </div>
              <div className="space-y-1">
                {trace.answers.filter((a) => a.status === 'ok').slice(0, 1).map((a) => (
                  <React.Fragment key={a.model}>
                    <div className="flex justify-between text-[10px] font-mono">
                      <span className="text-slate-500">best model named</span>
                      <span className="text-indigo-400">
                        {Math.max(...trace.answers.filter((x) => x.status === 'ok')
                          .map((x) => x.answer_score.coverage_pct))}%
                      </span>
                    </div>
                    <Bar pct={Math.max(...trace.answers.filter((x) => x.status === 'ok')
                      .map((x) => x.answer_score.coverage_pct))} tone="answer" />
                  </React.Fragment>
                ))}
              </div>
            </div>
          </div>
          <span className="text-[11px] text-slate-600 shrink-0">{open ? '−' : '+'}</span>
        </div>
      </button>

      {open && (
        <div className="px-4 pb-5 space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div className="p-3 rounded-lg bg-slate-950 border border-slate-800">
              <p className="text-[10px] uppercase font-bold text-emerald-400/80 mb-1">
                Needed and retrieved ({index.found.length})
              </p>
              {index.found.length
                ? index.found.map((f) => <p key={f} className="text-[11px] font-mono text-emerald-300">{f}</p>)
                : <p className="text-[11px] text-slate-600">none</p>}
            </div>
            <div className="p-3 rounded-lg bg-slate-950 border border-slate-800">
              <p className="text-[10px] uppercase font-bold text-rose-400/80 mb-1">
                Needed but never retrieved ({index.missing.length})
              </p>
              {index.missing.length
                ? index.missing.map((f) => <p key={f} className="text-[11px] font-mono text-rose-300">{f}</p>)
                : <p className="text-[11px] text-slate-600">none — the index supplied everything</p>}
            </div>
          </div>

          <div>
            <p className="text-[10px] uppercase font-bold text-slate-500 mb-1.5">
              Chunks that entered the prompt
            </p>
            <div className="flex flex-wrap gap-1.5">
              {trace.retrieved_sources.map((src, i) => (
                <span key={i} className={`px-2 py-0.5 rounded text-[10px] font-mono border ${
                  trace.expected_files.includes(src.file)
                    ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/25'
                    : 'bg-slate-950 text-slate-500 border-slate-800'
                }`}>
                  {src.file}:{src.first_line} ({src.similarity})
                </span>
              ))}
            </div>
          </div>

          <div className="space-y-2">
            {trace.answers.map((answer) => (
              <div key={answer.model} className="p-3 rounded-lg bg-slate-950 border border-slate-800">
                <div className="flex flex-wrap items-center gap-2 mb-1.5">
                  <span className="text-xs font-bold text-slate-200">{answer.model}</span>
                  {answer.status === 'ok' ? (
                    <>
                      <span className="text-[11px] font-mono text-slate-500">
                        named {answer.answer_score.files_named}/{answer.answer_score.expected_files} files
                        {' '}({answer.answer_score.coverage_pct}%)
                      </span>
                      {answer.limited_by_index && (
                        <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/25">
                          capped by the index, not the model
                        </span>
                      )}
                    </>
                  ) : (
                    <span className="text-[11px] text-rose-400">{answer.error}</span>
                  )}
                </div>
                {answer.status === 'ok' && (
                  <>
                    <pre className="text-[11px] text-slate-300 whitespace-pre-wrap max-h-56 overflow-y-auto leading-relaxed">
                      {answer.answer}
                    </pre>
                    {answer.answer_score.not_named.length > 0 && (
                      <p className="text-[10px] font-mono text-slate-600 mt-2 pt-2 border-t border-slate-800">
                        never mentioned: {answer.answer_score.not_named.join(', ')}
                      </p>
                    )}
                  </>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function RepoPanel({ models }) {
  const [meta, setMeta] = useState(null);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.getRepoQuestions().then(setMeta).catch((e) => setError(e.message));
    api.getRepoResult().then((r) => r && setResult(r)).catch(() => {});
  }, []);

  const buildIndex = async () => {
    setBusy('index');
    setError(null);
    try {
      const built = await api.buildRepoIndex();
      setMeta((m) => ({ ...m, index: { ...m?.index, ready: true, files: built.files_indexed, chunks: built.total_chunks } }));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  };

  const run = async () => {
    if (!models.length) {
      setError('Select at least one model on the Run tab first.');
      return;
    }
    setBusy('run');
    setError(null);
    try {
      setResult(await api.runRepoQuestions({ models, top_k: 8, max_tokens: 700 }));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  };

  const summary = result?.summary;

  return (
    <div className="space-y-6">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-4">
        <div className="border-b border-slate-800 pb-3">
          <h3 className="text-base font-semibold text-white">Repository-level understanding</h3>
          <p className="text-xs text-slate-400 max-w-3xl">
            The same pipeline, pointed at its own source tree. Seven questions that only make sense across files —
            which modules take part in ingestion, what calls the LLM service, what breaks if a function changes.
            Each is scored on whether the index even supplied the necessary files, separately from whether the
            model named them.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <div className="flex-1 min-w-[220px] p-3.5 rounded-xl bg-slate-950 border border-slate-800">
            <p className="text-[11px] text-slate-500 uppercase font-semibold">Code index</p>
            <p className="text-sm font-bold text-slate-100">
              {meta?.index?.ready
                ? `${meta.index.files} files · ${meta.index.chunks} chunks`
                : 'not built yet'}
            </p>
          </div>
          <button
            onClick={buildIndex}
            disabled={busy !== null}
            className="px-4 py-2.5 rounded-xl text-xs font-semibold bg-slate-800 hover:bg-slate-700 disabled:opacity-50 text-slate-200 border border-slate-700"
          >
            {busy === 'index' ? 'Indexing…' : meta?.index?.ready ? 'Re-index repository' : 'Index repository'}
          </button>
          <button
            onClick={run}
            disabled={busy !== null}
            className="px-5 py-2.5 rounded-xl text-xs font-semibold bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 disabled:text-slate-500 text-white"
          >
            {busy === 'run'
              ? 'Asking the repository questions…'
              : `Run 7 questions on ${models.length} model${models.length === 1 ? '' : 's'}`}
          </button>
        </div>

        {busy === 'run' && (
          <p className="text-[11px] text-slate-500">
            This request blocks until every model has answered all seven questions — roughly one to three minutes per model.
          </p>
        )}
        {error && (
          <p className="text-xs text-rose-400 font-medium">⚠️ {error}</p>
        )}
      </div>

      {/* The questions, shown even before a run */}
      {!result && meta?.questions && (
        <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden">
          <div className="p-5 border-b border-slate-800">
            <h3 className="text-sm font-semibold text-white">The questions ({meta.questions.length})</h3>
            <p className="text-xs text-slate-400">Each one needs a relationship between files that no single chunk contains.</p>
          </div>
          <div className="divide-y divide-slate-800/60">
            {meta.questions.map((q) => (
              <div key={q.id} className="p-4">
                <div className="flex items-start gap-3">
                  <span className="font-mono text-[11px] text-slate-500 shrink-0 w-8 pt-0.5">{q.id}</span>
                  <div className="min-w-0">
                    <p className="text-xs text-slate-200 leading-relaxed">{q.question}</p>
                    <p className="text-[11px] text-slate-500 mt-1">
                      <span className="text-slate-400 font-semibold">{q.kind}</span> — {q.why_hard}
                    </p>
                    <p className="text-[10px] font-mono text-slate-600 mt-1">
                      needs {q.expected_files.length} files: {q.expected_files.join(', ')}
                    </p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {summary && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div className="p-4 rounded-2xl bg-gradient-to-br from-emerald-600/20 to-emerald-600/5 border border-emerald-500/30">
              <p className="text-[10px] uppercase font-bold text-emerald-300">Index file recall (mean)</p>
              <p className="text-2xl font-bold text-white mt-1">{summary.mean_index_file_recall_pct}%</p>
              <p className="text-[11px] text-emerald-100/70">
                share of necessary files the retriever actually supplied
              </p>
            </div>
            <div className="p-4 rounded-2xl bg-gradient-to-br from-sky-600/20 to-sky-600/5 border border-sky-500/30">
              <p className="text-[10px] uppercase font-bold text-sky-300">Fully supplied</p>
              <p className="text-2xl font-bold text-white mt-1">
                {summary.questions_index_fully_supplied.length}/{summary.questions}
              </p>
              <p className="text-[11px] text-sky-100/70 font-mono">
                {summary.questions_index_fully_supplied.join(', ') || 'none'}
              </p>
            </div>
            <div className="p-4 rounded-2xl bg-gradient-to-br from-rose-600/20 to-rose-600/5 border border-rose-500/30">
              <p className="text-[10px] uppercase font-bold text-rose-300">Starved (under half)</p>
              <p className="text-2xl font-bold text-white mt-1">
                {summary.questions_index_starved.length}/{summary.questions}
              </p>
              <p className="text-[11px] text-rose-100/70 font-mono">
                {summary.questions_index_starved.join(', ') || 'none'}
              </p>
            </div>
          </div>

          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-4">
            <h3 className="text-sm font-semibold text-white border-b border-slate-800 pb-3">
              Mean file coverage per model
            </h3>
            <div className="space-y-3">
              {Object.entries(summary.per_model).map(([model, stats]) => (
                <div key={model} className="space-y-1">
                  <div className="flex justify-between text-[11px]">
                    <span className="text-slate-300 font-medium">{model}</span>
                    <span className="font-mono text-indigo-400">
                      {stats.mean_file_coverage_pct}% · {stats.fully_answered}/{stats.questions_answered} fully answered
                    </span>
                  </div>
                  <Bar pct={stats.mean_file_coverage_pct || 0} tone="answer" />
                </div>
              ))}
            </div>
            <div className="pt-3 border-t border-slate-800 space-y-2">
              {summary.verdict.map((line, i) => (
                <div key={i} className="flex gap-2.5 text-[12px] text-slate-300 leading-relaxed">
                  <span className="text-indigo-400 shrink-0">▸</span>
                  <span>{line}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden">
            <div className="p-5 border-b border-slate-800">
              <h3 className="text-sm font-semibold text-white">Per-question results</h3>
              <p className="text-xs text-slate-400">
                Green bar: what the index supplied. Blue bar: what the best model then named.
              </p>
            </div>
            <div>
              {result.traces.map((trace) => <RepoTrace key={trace.id} trace={trace} />)}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
