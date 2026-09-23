import React from 'react';

/**
 * How every reported number is calculated.
 *
 * The formulas are not written here. They come from `METRIC_DEFINITIONS` in
 * `evaluation/metrics.py`, served by `/api/evaluation/dataset`, so the
 * explanation the page shows and the code that produces the number are the same
 * artefact. A hand-written copy would drift the first time a threshold changed,
 * and a benchmark whose documentation quietly disagrees with its implementation
 * is worse than one with no documentation at all.
 */

/** Shown when the API has not answered yet, so the panel is never empty. */
const FALLBACK = [
  { group: 'Quality', name: 'Correctness / Accuracy', unit: '%', better: 'higher',
    formula: 'Loading definitions from the evaluation service…' },
];

const GROUP_STYLE = {
  Quality: { accent: 'text-amber-400', ring: 'border-amber-500/20 bg-amber-500/5' },
  Performance: { accent: 'text-sky-400', ring: 'border-sky-500/20 bg-sky-500/5' },
};

const APPLICABILITY = [
  ['Correctness', 'Needs ground truth, so only on the evaluation questions. Out-of-scope probes score on abstaining instead of on facts; code-generation and refactoring tasks score their test-pass rate.'],
  ['Relevance', 'Always available. On an ad-hoc question the topic terms come from the question itself, which is weaker — a model can score by echoing you.'],
  ['Retrieval quality', 'Needs the (filename, page) that truly holds the answer. Reported once per question, never per model: retrieval runs once and every model receives the identical chunks. Not applicable on questions whose evidence is quoted in the question itself (the code-excerpt categories) — no chunk can be the right chunk there.'],
  ['Hallucination rate', 'Skipped on greetings (a welcome message asserts nothing to check) and on code tasks — generated code is judged by its tests, and the code-excerpt categories discuss code quoted in the question, not claims grounded in the retrieved pages.'],
  ['Test-pass rate', 'Only on code-generation and refactoring tasks — 30 unit tests across 6 tasks.'],
  ['CPU / GPU / memory', 'Sampled machine-wide every 200 ms during generation. An idle baseline is recorded before the run so the readings can be taken as a delta.'],
];

export default function MetricGuide({ onClose, definitions }) {
  const metrics = definitions?.length ? definitions : FALLBACK;
  const groups = [...new Set(metrics.map((m) => m.group))];

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden">
      <div className="p-6 border-b border-slate-800 flex items-start justify-between gap-4">
        <div>
          <h3 className="text-base font-semibold text-white">How each metric is calculated</h3>
          <p className="text-xs text-slate-400 max-w-3xl mt-1">
            Every metric below is deterministic and lexical — no second model sits in judgement, so scoring a run
            costs nothing and cannot perturb the timings it reports on. These formulas are read from the evaluation
            service, so they are the ones actually running.
          </p>
        </div>
        <button
          onClick={onClose}
          className="shrink-0 px-3 py-1.5 rounded-lg text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition-colors"
        >
          Close
        </button>
      </div>

      <div className="p-6 space-y-6">
        {groups.map((group) => {
          const style = GROUP_STYLE[group] || GROUP_STYLE.Quality;
          return (
            <div key={group} className="space-y-3">
              <h4 className={`text-xs font-bold uppercase tracking-wide ${style.accent}`}>
                {group} metrics
              </h4>
              <div className="space-y-2.5">
                {metrics.filter((m) => m.group === group).map((metric) => (
                  <div key={metric.key || metric.name} className={`p-4 rounded-xl border ${style.ring}`}>
                    <div className="flex items-baseline justify-between gap-3 mb-1.5">
                      <span className="text-sm font-semibold text-slate-100">{metric.name}</span>
                      <span className="text-[11px] font-mono text-slate-500 shrink-0">
                        {metric.unit} · {metric.better === 'lower' ? 'lower is better' : 'higher is better'}
                      </span>
                    </div>
                    {metric.plain && (
                      <p className="text-[12px] text-slate-300 leading-relaxed mb-2">{metric.plain}</p>
                    )}
                    <p className="text-[11px] text-slate-400 leading-relaxed border-l-2 border-slate-700 pl-2.5">
                      {metric.formula}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          );
        })}

        <div className="space-y-3">
          <h4 className="text-xs font-bold uppercase tracking-wide text-slate-400">
            When each metric applies
          </h4>
          <div className="rounded-xl border border-slate-800 bg-slate-950 divide-y divide-slate-800">
            {APPLICABILITY.map(([name, note]) => (
              <div key={name} className="p-3.5 flex flex-col sm:flex-row sm:gap-4">
                <span className="text-xs font-semibold text-slate-200 sm:w-44 shrink-0">{name}</span>
                <span className="text-[12px] text-slate-400 leading-relaxed">{note}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="p-4 rounded-xl border border-amber-500/20 bg-amber-500/5 space-y-2">
          <p className="text-xs font-bold uppercase tracking-wide text-amber-400">What these numbers cannot tell you</p>
          <ul className="text-[12px] text-amber-100/80 leading-relaxed list-disc pl-5 space-y-1">
            <li>
              They are word-overlap measures, not comprehension. An answer that is correct but phrased entirely in
              synonyms of the ground truth scores lower than it deserves.
            </li>
            <li>
              They compare models against each other under identical conditions. They are not an absolute standard,
              and a score of 80 here does not mean 80% of users would be satisfied.
            </li>
            <li>
              One run per question. Ollama is not bit-deterministic even at a fixed seed, so a few points between two
              models on a single question is noise — only the aggregate across the dataset carries weight.
            </li>
            <li>
              No overall winner is computed. Merging eight criteria into one score requires weights, and choosing
              those weights is an opinion about what matters, not a measurement.
            </li>
          </ul>
        </div>
      </div>
    </div>
  );
}
