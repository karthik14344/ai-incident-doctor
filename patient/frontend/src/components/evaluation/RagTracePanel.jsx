import React, { useState } from 'react';

/**
 * Exercise 5 — QUESTION → RETRIEVED CONTEXT → LLM RESPONSE.
 *
 * The band table at the top is the argument: group questions by how well
 * retrieval did, then look at what the models produced in each group. If
 * retrieval were a checkbox to tick before the LLM, those rows would be flat.
 *
 * Below it, every question can be opened to see the actual chunks that entered
 * the prompt, which of them held the answer, and what each model then said —
 * including the case the exercise is really after: a model inventing something
 * with the correct page sitting in its context window.
 */

const LABEL_STYLE = {
  relevant_retrieved: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/25',
  irrelevant_retrieved: 'bg-amber-500/10 text-amber-400 border-amber-500/25',
  information_missed: 'bg-rose-500/10 text-rose-400 border-rose-500/25',
};

const LABEL_TEXT = {
  relevant_retrieved: 'relevant information retrieved',
  irrelevant_retrieved: 'irrelevant information retrieved',
  information_missed: 'important information missed',
};

const VERDICT_STYLE = (verdict) => {
  if (verdict.includes('hallucinated')) return 'text-rose-400';
  if (verdict.includes('correctly abstained')) return 'text-emerald-400';
  if (verdict.includes('unanswerable question')) return 'text-rose-400';
  if (verdict.includes('model used it')) return 'text-emerald-400';
  if (verdict.includes('padded')) return 'text-amber-400';
  return 'text-slate-400';
};

const HIGHLIGHT_TITLES = {
  relevant_information_retrieved: 'Relevant information was retrieved',
  irrelevant_information_retrieved: 'Irrelevant information was retrieved',
  important_information_missed: 'Important information was missed',
  llm_answered_correctly: 'The LLM produced a correct answer',
  llm_hallucinated_with_context: 'The LLM hallucinated despite having retrieved context',
};

function Highlight({ id, data }) {
  const [open, setOpen] = useState(false);
  if (!data) {
    return (
      <div className="p-4 rounded-xl bg-slate-950 border border-slate-800">
        <p className="text-xs font-semibold text-slate-300">{HIGHLIGHT_TITLES[id]}</p>
        <p className="text-[11px] text-slate-500 mt-1">
          No example of this case occurred in this run.
        </p>
      </div>
    );
  }
  return (
    <div className="rounded-xl bg-slate-950 border border-slate-800 overflow-hidden">
      <button onClick={() => setOpen((v) => !v)} className="w-full p-4 text-left">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-xs font-semibold text-slate-200">{HIGHLIGHT_TITLES[id]}</p>
            <p className="text-[11px] text-slate-500 mt-0.5">
              <span className="font-mono text-slate-400">{data.id}</span> — {data.why}
            </p>
          </div>
          <span className="text-[11px] text-slate-500 shrink-0">{open ? 'Hide' : 'Open'}</span>
        </div>
      </button>
      {open && (
        <div className="px-4 pb-4 space-y-3 border-t border-slate-800 pt-3">
          <div>
            <p className="text-[10px] uppercase font-bold text-slate-500 mb-1">Question</p>
            <p className="text-xs text-slate-200">{data.question}</p>
          </div>
          <div>
            <p className="text-[10px] uppercase font-bold text-slate-500 mb-1">Retrieved</p>
            <ul className="space-y-0.5">
              {data.retrieved.map((line, i) => (
                <li key={i} className={`text-[11px] font-mono ${line.includes('GOLD') ? 'text-emerald-400' : 'text-slate-500'}`}>
                  {line}
                </li>
              ))}
            </ul>
          </div>
          <div>
            <p className="text-[10px] uppercase font-bold text-slate-500 mb-1">Context sent to the model</p>
            <pre className="text-[11px] text-slate-400 font-mono whitespace-pre-wrap bg-slate-900 rounded-lg p-3 max-h-56 overflow-y-auto">
              {data.context_preview}
            </pre>
          </div>
          {data.answer && (
            <div>
              <p className="text-[10px] uppercase font-bold text-slate-500 mb-1">
                {data.model} responded
                {data.hallucination_rate_pct !== null && data.hallucination_rate_pct !== undefined &&
                  ` — ${data.hallucination_rate_pct}% of claims unsupported`}
                {data.fabricated_numbers?.length > 0 &&
                  ` — invented: ${data.fabricated_numbers.join(', ')}`}
              </p>
              <pre className="text-[11px] text-slate-300 whitespace-pre-wrap bg-slate-900 rounded-lg p-3 max-h-56 overflow-y-auto">
                {data.answer}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Trace({ trace }) {
  const [open, setOpen] = useState(false);
  const rq = trace.retrieval;

  return (
    <div className="border-b border-slate-800/60 last:border-0">
      <button onClick={() => setOpen((v) => !v)}
              className="w-full p-4 text-left hover:bg-slate-950/40 transition-colors">
        <div className="flex items-start gap-3">
          <span className="font-mono text-[11px] text-slate-500 shrink-0 w-9 pt-0.5">{trace.id}</span>
          <div className="min-w-0 flex-1">
            <p className="text-xs text-slate-200 leading-relaxed">{trace.question}</p>
            <div className="flex flex-wrap items-center gap-1.5 mt-2">
              {trace.labels.map((label) => (
                <span key={label} className={`px-2 py-0.5 rounded text-[10px] font-semibold border ${LABEL_STYLE[label]}`}>
                  {LABEL_TEXT[label]}
                </span>
              ))}
              {rq.applicable ? (
                <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-slate-950 text-slate-500 border border-slate-800">
                  retrieval {rq.retrieval_quality_pct}% · recall {rq.recall_at_k}% · noise {rq.context_noise_pct}%
                </span>
              ) : (
                <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-slate-950 text-slate-500 border border-slate-800">
                  no gold chunk · top similarity {rq.top_similarity}
                </span>
              )}
            </div>
          </div>
          <span className="text-[11px] text-slate-600 shrink-0">{open ? '−' : '+'}</span>
        </div>
      </button>

      {open && (
        <div className="px-4 pb-5 space-y-4">
          {/* Retrieved chunks */}
          <div>
            <p className="text-[10px] uppercase font-bold text-slate-500 mb-1.5">
              Retrieved context — gold pages: {trace.gold_sources.join(', ') || 'none exist'}
            </p>
            {trace.instruction_markers_in_context?.length > 0 && (
              <p className="text-[11px] text-orange-300/80 mb-2 leading-relaxed">
                ⚠ This context contains instructions addressed to the assistant
                (“{trace.instruction_markers_in_context.join('”, “')}”). Similarity search cannot
                tell content to answer from apart from instructions to obey.
              </p>
            )}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              {trace.retrieved_sources.map((src, i) => (
                <div key={i} className={`p-3 rounded-lg border text-[11px] ${
                  src.relevant
                    ? 'bg-emerald-500/5 border-emerald-500/25'
                    : 'bg-slate-950 border-slate-800'
                }`}>
                  <div className="flex items-center justify-between gap-2 mb-1">
                    <span className={`font-semibold ${src.relevant ? 'text-emerald-300' : 'text-slate-400'}`}>
                      #{i + 1} {src.filename} p{src.page} {src.relevant && '· holds the answer'}
                    </span>
                    <span className="font-mono text-slate-500">{src.similarity}</span>
                  </div>
                  <p className="text-slate-500 font-mono leading-relaxed">{src.preview}</p>
                </div>
              ))}
            </div>
          </div>

          {/* Responses */}
          <div className="space-y-2">
            <p className="text-[10px] uppercase font-bold text-slate-500">Model responses from that context</p>
            {trace.responses.map((response) => (
              <div key={response.model} className="p-3 rounded-lg bg-slate-950 border border-slate-800">
                <div className="flex flex-wrap items-center gap-2 mb-1.5">
                  <span className="text-xs font-bold text-slate-200">{response.model}</span>
                  {response.status === 'ok' ? (
                    <>
                      <span className={`text-[11px] font-semibold ${VERDICT_STYLE(response.verdict)}`}>
                        {response.verdict}
                      </span>
                      {response.followed_context_instruction && (
                        <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-orange-500/10 text-orange-400 border border-orange-500/25">
                          followed instructions found in the context
                        </span>
                      )}
                      <span className="text-[10px] font-mono text-slate-600 ml-auto">
                        correctness {response.correctness_pct}% · relevance {response.relevance_pct}%
                        {response.hallucination_rate_pct !== null && ` · hallucination ${response.hallucination_rate_pct}%`}
                      </span>
                    </>
                  ) : (
                    <span className="text-[11px] text-rose-400">{response.error}</span>
                  )}
                </div>
                {response.status === 'ok' && (
                  <>
                    <pre className="text-[11px] text-slate-300 whitespace-pre-wrap max-h-48 overflow-y-auto leading-relaxed">
                      {response.answer}
                    </pre>
                    {response.unsupported_examples?.length > 0 && (
                      <div className="mt-2 pt-2 border-t border-slate-800">
                        <p className="text-[10px] uppercase font-bold text-rose-400/80 mb-1">
                          Claims the context does not support
                          {response.fabricated_numbers?.length > 0 &&
                            ` — invented numbers: ${response.fabricated_numbers.join(', ')}`}
                        </p>
                        {response.unsupported_examples.map((line, i) => (
                          <p key={i} className="text-[11px] text-rose-200/70 font-mono leading-relaxed">“{line}”</p>
                        ))}
                      </div>
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

export default function RagTracePanel({ report }) {
  const [filter, setFilter] = useState('all');
  const traces = report?.rag_traces;
  if (!traces) return <p className="text-sm text-slate-500">No RAG traces in this run.</p>;

  const { counts, retrieval_to_response: bands, highlights, conclusion } = traces;

  const filtered = filter === 'all'
    ? traces.traces
    : filter === 'instruction_leak'
      // This one is a property of a response, not of the retrieval: the same
      // context was handed to every model and only some obeyed it.
      ? traces.traces.filter((t) => t.responses.some((r) => r.followed_context_instruction))
      : traces.traces.filter((t) => t.labels.includes(filter));

  return (
    <div className="space-y-6">
      {/* The relationship, as a table */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden">
        <div className="p-6 border-b border-slate-800">
          <h3 className="text-base font-semibold text-white">
            Retrieval quality → context quality → response quality
          </h3>
          <p className="text-xs text-slate-400">
            Questions grouped by how well retrieval did, then what the models produced in each group.
            If retrieval were just a checkbox before the LLM, these rows would be flat.
          </p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-950/70 border-b border-slate-800">
                <th className="text-left px-6 py-3 text-xs font-semibold text-slate-400 uppercase">Retrieval band</th>
                <th className="text-right px-6 py-3 text-xs font-semibold text-slate-400 uppercase">Questions</th>
                <th className="text-right px-6 py-3 text-xs font-semibold text-slate-400 uppercase">Answers scored</th>
                <th className="text-right px-6 py-3 text-xs font-semibold text-slate-400 uppercase">Accuracy</th>
                <th className="text-right px-6 py-3 text-xs font-semibold text-slate-400 uppercase">Mean correctness</th>
                <th className="text-right px-6 py-3 text-xs font-semibold text-slate-400 uppercase">Mean hallucination</th>
              </tr>
            </thead>
            <tbody>
              {bands.map((row) => (
                <tr key={row.band} className="border-b border-slate-800/60">
                  <td className="px-6 py-3">
                    <p className="text-xs font-medium text-slate-300">{row.band}</p>
                    {row.question_ids?.length > 0 && (
                      <p className="text-[10px] font-mono text-slate-600 mt-0.5">{row.question_ids.join(' ')}</p>
                    )}
                  </td>
                  <td className="px-6 py-3 text-right font-mono text-xs text-slate-300">{row.questions}</td>
                  <td className="px-6 py-3 text-right font-mono text-xs text-slate-500">{row.answers_scored}</td>
                  <td className="px-6 py-3 text-right font-mono text-xs text-emerald-400">
                    {row.accuracy_pct === null ? '—' : `${row.accuracy_pct}%`}
                  </td>
                  <td className="px-6 py-3 text-right font-mono text-xs text-slate-300">
                    {row.mean_correctness_pct === null ? '—' : `${row.mean_correctness_pct}%`}
                  </td>
                  <td className="px-6 py-3 text-right font-mono text-xs text-rose-400">
                    {row.mean_hallucination_pct === null ? '—' : `${row.mean_hallucination_pct}%`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="px-6 py-4 border-t border-slate-800 bg-slate-950/40 space-y-2">
          {conclusion.map((line, i) => (
            <div key={i} className="flex gap-2.5 text-[12px] text-slate-300 leading-relaxed">
              <span className="text-indigo-400 shrink-0">▸</span>
              <span>{line}</span>
            </div>
          ))}
        </div>
      </div>

      {/* One worked example of each case */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-3">
        <div className="border-b border-slate-800 pb-3">
          <h3 className="text-base font-semibold text-white">Worked examples of each case</h3>
          <p className="text-xs text-slate-400">
            Picked automatically from this run — open one to see the exact context and the exact answer.
          </p>
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          {Object.keys(HIGHLIGHT_TITLES).map((id) => (
            <Highlight key={id} id={id} data={highlights[id]} />
          ))}
        </div>
      </div>

      {/* Every trace */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden">
        <div className="p-5 border-b border-slate-800 flex flex-wrap items-center justify-between gap-3">
          <h3 className="text-sm font-semibold text-white">All traces ({filtered.length})</h3>
          <div className="flex flex-wrap gap-1.5">
            {[
              ['all', `all (${traces.traces.length})`],
              ['relevant_retrieved', `relevant retrieved (${counts.relevant_retrieved})`],
              ['irrelevant_retrieved', `irrelevant retrieved (${counts.irrelevant_retrieved})`],
              ['information_missed', `information missed (${counts.information_missed})`],
              ['instruction_leak', `instructions in context (${counts.instruction_leak ?? 0})`],
            ].map(([key, label]) => (
              <button
                key={key}
                onClick={() => setFilter(key)}
                className={`px-2.5 py-1 rounded-lg text-[11px] font-semibold border transition-colors ${
                  filter === key
                    ? 'bg-indigo-600/15 text-indigo-300 border-indigo-500/30'
                    : 'bg-slate-950 text-slate-400 border-slate-800 hover:border-slate-700'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        <div className="max-h-[720px] overflow-y-auto">
          {filtered.map((trace) => <Trace key={trace.id} trace={trace} />)}
        </div>
      </div>
    </div>
  );
}
