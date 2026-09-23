import React from 'react';

/**
 * Exercise 4 — the argument, not the table.
 *
 * Every claim here is rendered from `analysis` in the report, which is derived
 * from measured numbers in `evaluation/analysis.py`. Nothing on this page is
 * written by hand, so it cannot say a model won something the data does not
 * show. The evidence line under each answer is the numbers themselves.
 */

const fmtMs = (v) => (v === null || v === undefined ? 'n/a'
  : v >= 1000 ? `${(v / 1000).toFixed(1)} s` : `${Math.round(v)} ms`);

/** Quality against cost, plotted so a trade-off is visible rather than argued. */
function TradeoffPlot({ points }) {
  if (!points || points.length < 2) return null;

  const maxLatency = Math.max(...points.map((p) => p.latency));
  const minLatency = Math.min(...points.map((p) => p.latency));
  const span = maxLatency - minLatency || 1;
  const maxMemory = Math.max(...points.map((p) => p.memory)) || 1;

  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between">
        <p className="text-xs font-semibold text-slate-400 uppercase">Accuracy against latency</p>
        <p className="text-[11px] text-slate-500">bubble size = peak memory</p>
      </div>
      <div className="relative h-64 rounded-xl bg-slate-950 border border-slate-800 p-4">
        {/* Axes */}
        <div className="absolute left-12 right-4 top-4 bottom-10 border-l border-b border-slate-800">
          {[0, 25, 50, 75, 100].map((tick) => (
            <div key={tick}
                 className="absolute left-0 right-0 border-t border-slate-800/50"
                 style={{ bottom: `${tick}%` }}>
              <span className="absolute -left-10 -top-2 text-[10px] font-mono text-slate-600">{tick}%</span>
            </div>
          ))}
          {points.map((p, i) => {
            const x = ((p.latency - minLatency) / span) * 88 + 4;
            const size = 14 + (p.memory / maxMemory) * 26;
            return (
              <div key={p.model}
                   className="absolute rounded-full border-2 border-indigo-400/60 bg-indigo-500/25 flex items-center justify-center"
                   style={{
                     left: `${x}%`, bottom: `${p.accuracy}%`,
                     width: size, height: size,
                     transform: 'translate(-50%, 50%)',
                   }}
                   title={`${p.model}: ${p.accuracy}% accuracy, ${fmtMs(p.latency)}, ${Math.round(p.memory)} MB`}>
                <span className="absolute -top-5 text-[10px] font-semibold text-slate-300 whitespace-nowrap">
                  {p.model}
                </span>
              </div>
            );
          })}
        </div>
        <span className="absolute bottom-2 left-1/2 -translate-x-1/2 text-[10px] font-mono text-slate-600">
          mean response latency — {fmtMs(minLatency)} to {fmtMs(maxLatency)} →
        </span>
      </div>
    </div>
  );
}

export default function AnalysisPanel({ report }) {
  const analysis = report?.analysis;
  if (!analysis?.available) {
    return (
      <p className="text-sm text-slate-500">
        {analysis?.reason || 'No analysis is available for this run.'}
      </p>
    );
  }

  const { questions, tradeoff, recommendation, pareto, correlations, caveats } = analysis;

  return (
    <div className="space-y-6">
      {/* The questions the exercise asks */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden">
        <div className="p-6 border-b border-slate-800">
          <h3 className="text-base font-semibold text-white">The comparison questions, answered</h3>
          <p className="text-xs text-slate-400">
            Each answer is derived from the measured numbers; the line under it is the evidence it was derived from.
          </p>
        </div>
        <div className="divide-y divide-slate-800/60">
          {questions.map((entry) => (
            <div key={entry.question} className="p-5">
              <p className="text-xs font-semibold text-slate-400 mb-1.5">{entry.question}</p>
              <p className="text-sm font-bold text-white mb-1.5">{entry.answer}</p>
              <p className="text-[11px] text-slate-500 font-mono leading-relaxed">{entry.evidence}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Trade-off */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-5">
        <div className="border-b border-slate-800 pb-3">
          <h3 className="text-base font-semibold text-white">Quality, latency and resource trade-off</h3>
          <p className="text-xs text-slate-400">
            Whether accuracy was bought with time and memory, or came free.
          </p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="space-y-2.5">
            {tradeoff.summary.map((line, i) => (
              <div key={i} className="flex gap-2.5 text-[13px] text-slate-300 leading-relaxed">
                <span className="text-indigo-400 shrink-0">▸</span>
                <span>{line}</span>
              </div>
            ))}
          </div>
          <TradeoffPlot points={pareto?.points} />
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {[
            ['Accuracy vs latency', correlations?.accuracy_vs_latency],
            ['Accuracy vs peak memory', correlations?.accuracy_vs_memory],
            ['Accuracy vs hallucination', correlations?.accuracy_vs_hallucination],
          ].map(([label, value]) => (
            <div key={label} className="p-3.5 rounded-xl bg-slate-950 border border-slate-800">
              <p className="text-[11px] text-slate-500 uppercase font-semibold">{label}</p>
              <p className="text-lg font-bold font-mono text-slate-200">
                {value === null || value === undefined ? 'n/a' : `r = ${value}`}
              </p>
              <p className="text-[10px] text-slate-600">
                over {correlations?.n_models} models — a direction, not a law
              </p>
            </div>
          ))}
        </div>

        {(pareto?.pareto_front?.length > 0 || pareto?.dominated?.length > 0) && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div className="p-4 rounded-xl bg-emerald-500/5 border border-emerald-500/20">
              <p className="text-[11px] uppercase font-bold text-emerald-400 mb-1.5">
                Worth considering ({pareto.pareto_front.length})
              </p>
              <p className="text-sm text-slate-200 font-semibold">
                {pareto.pareto_front.map((p) => p.model).join(', ') || 'none'}
              </p>
              <p className="text-[11px] text-slate-400 mt-1">
                Each is best at something — nothing beats them on accuracy, latency and memory at once.
              </p>
            </div>
            <div className="p-4 rounded-xl bg-rose-500/5 border border-rose-500/20">
              <p className="text-[11px] uppercase font-bold text-rose-400 mb-1.5">
                Dominated ({pareto.dominated.length})
              </p>
              <p className="text-sm text-slate-200 font-semibold">
                {pareto.dominated.map((d) => `${d.model} → ${d.dominated_by}`).join(', ') || 'none'}
              </p>
              <p className="text-[11px] text-slate-400 mt-1">
                Another model matches or beats these on all three. Nothing argues for running them.
              </p>
            </div>
          </div>
        )}
      </div>

      {/* Recommendation */}
      <div className="rounded-2xl border border-indigo-500/30 bg-gradient-to-br from-indigo-600/15 to-fuchsia-600/5 p-6 space-y-3">
        <p className="text-[11px] uppercase font-bold tracking-wide text-indigo-300">
          Recommendation for this application
        </p>
        <p className="text-2xl font-bold text-white">{recommendation.default}</p>
        <p className="text-sm text-slate-300 leading-relaxed">{recommendation.why}</p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-1">
          {recommendation.faster_alternative && (
            <div className="p-3.5 rounded-xl bg-slate-950/60 border border-slate-800">
              <p className="text-[11px] uppercase font-semibold text-slate-500">Faster alternative</p>
              <p className="text-sm font-bold text-slate-100">{recommendation.faster_alternative.model}</p>
              <p className="text-[11px] text-slate-400">{recommendation.faster_alternative.why}</p>
            </div>
          )}
          {recommendation.interactive_pick && (
            <div className="p-3.5 rounded-xl bg-slate-950/60 border border-slate-800">
              <p className="text-[11px] uppercase font-semibold text-slate-500">If latency is the constraint</p>
              <p className="text-sm font-bold text-slate-100">{recommendation.interactive_pick}</p>
              <p className="text-[11px] text-slate-400">Lowest mean response latency in this run.</p>
            </div>
          )}
        </div>
      </div>

      {/* Caveats */}
      <div className="rounded-2xl border border-amber-500/20 bg-amber-500/5 p-6 space-y-2.5">
        <p className="text-[11px] uppercase font-bold tracking-wide text-amber-400">
          What this evidence cannot support
        </p>
        {caveats.map((line, i) => (
          <div key={i} className="flex gap-2.5 text-[12px] text-amber-100/85 leading-relaxed">
            <span className="shrink-0">▸</span>
            <span>{line}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
