import React, { useState } from 'react';

/**
 * Exercise 2 — the evaluation set, and why it is shaped the way it is.
 *
 * Questions are organised into the seven assessment categories the comparison
 * is reported on; each task also carries its internal `task_type` (the shape
 * that decides which metrics apply), shown as a secondary tag. The
 * out-of-scope probes are called out in their note — they are the only
 * questions where the correct answer is silence, and they carry most of the
 * hallucination signal.
 */

const CATEGORY_NOTES = {
  'Explanation': 'Explain a rule, procedure or consequence in the knowledge base — completeness and order matter, not just one fact.',
  'Code Retrieval': 'Read a quoted code excerpt and locate the function, file or value asked for.',
  'Dependency Understanding': 'Reason about what imports what, and what breaks when a symbol changes.',
  'Bug Analysis': 'Find and explain the defect in a quoted snippet, against the policy or the sampler it was written for.',
  'Code Generation': 'Write code against the policies, executed against a fixed pytest suite.',
  'Refactoring': 'Restructure given code with behaviour preserved — the same suite decides, so a correct refactor passes unchanged.',
  'RAG-based Question': 'The assistant\'s core job: answer — or abstain — from retrieved knowledge-base documents. Includes the hallucination-control probes.',
};

const CATEGORY_COLOR = {
  'Explanation': 'bg-indigo-500',
  'Code Retrieval': 'bg-sky-500',
  'Dependency Understanding': 'bg-fuchsia-500',
  'Bug Analysis': 'bg-rose-500',
  'Code Generation': 'bg-lime-500',
  'Refactoring': 'bg-amber-500',
  'RAG-based Question': 'bg-emerald-500',
};

const CATEGORY_ORDER = [
  'Explanation', 'Code Retrieval', 'Dependency Understanding', 'Bug Analysis',
  'Code Generation', 'Refactoring', 'RAG-based Question',
];

export default function DatasetPanel({ dataset }) {
  const [filter, setFilter] = useState('all');

  if (!dataset) {
    return <p className="text-sm text-slate-500">Loading the evaluation dataset…</p>;
  }

  const categories = Object.entries(dataset.categories || {})
    .sort((a, b) => {
      const ai = CATEGORY_ORDER.indexOf(a[0]);
      const bi = CATEGORY_ORDER.indexOf(b[0]);
      // Unknown labels (e.g. a pre-re categorisation saved view) sort last, by size.
      if (ai === -1 && bi === -1) return b[1] - a[1];
      if (ai === -1) return 1;
      if (bi === -1) return -1;
      return ai - bi;
    });
  const items = filter === 'all'
    ? dataset.items
    : dataset.items.filter((i) => i.category === filter);
  const codeTaskCount = (categories.find(([c]) => c === 'Code Generation')?.[1] || 0)
    + (categories.find(([c]) => c === 'Refactoring')?.[1] || 0);

  return (
    <div className="space-y-6">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-4">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h3 className="text-base font-semibold text-white">
            {dataset.size} tasks, identical for every model
          </h3>
          <span className="text-xs text-slate-500">
            {dataset.code_tests_total} unit tests across {codeTaskCount} code tasks
          </span>
        </div>

        {/* Distribution bar */}
        <div className="flex h-3 w-full rounded-full overflow-hidden bg-slate-950">
          {categories.map(([name, count]) => (
            <div
              key={name}
              className={CATEGORY_COLOR[name] || 'bg-slate-600'}
              style={{ width: `${(count / dataset.size) * 100}%` }}
              title={`${name}: ${count}`}
            />
          ))}
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
          {categories.map(([name, count]) => (
            <button
              key={name}
              onClick={() => setFilter(filter === name ? 'all' : name)}
              className={`p-3 rounded-xl border text-left transition-colors ${
                filter === name
                  ? 'bg-slate-800 border-slate-600'
                  : 'bg-slate-950 border-slate-800 hover:border-slate-700'
              }`}
            >
              <div className="flex items-center gap-2 mb-1">
                <span className={`w-2 h-2 rounded-full ${CATEGORY_COLOR[name] || 'bg-slate-600'}`} />
                <span className="text-xs font-semibold text-slate-200">{name}</span>
                <span className="text-[11px] font-mono text-slate-500 ml-auto">{count}</span>
              </div>
              <p className="text-[11px] text-slate-500 leading-relaxed">{CATEGORY_NOTES[name]}</p>
            </button>
          ))}
        </div>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden">
        <div className="p-5 border-b border-slate-800 flex items-center justify-between gap-3">
          <h3 className="text-sm font-semibold text-white">
            {filter === 'all' ? 'All tasks' : `Tasks in “${filter}”`} ({items.length})
          </h3>
          {filter !== 'all' && (
            <button
              onClick={() => setFilter('all')}
              className="px-3 py-1.5 rounded-lg text-[11px] font-semibold bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700"
            >
              Clear filter
            </button>
          )}
        </div>
        <div className="divide-y divide-slate-800/60 max-h-[640px] overflow-y-auto">
          {items.map((item) => (
            <div key={item.id} className="p-4 hover:bg-slate-950/40 transition-colors">
              <div className="flex items-start gap-3">
                <span className="font-mono text-[11px] text-slate-500 shrink-0 w-9 pt-0.5">{item.id}</span>
                <div className="min-w-0 flex-1">
                  <p className="text-xs text-slate-200 leading-relaxed">{item.question}</p>
                  <div className="flex flex-wrap items-center gap-1.5 mt-2">
                    <span className={`px-2 py-0.5 rounded text-[10px] font-semibold text-slate-900 ${CATEGORY_COLOR[item.category] || 'bg-slate-600'}`}>
                      {item.category}
                    </span>
                    {item.task_type && item.task_type !== item.category && (
                      <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-slate-950 text-slate-500 border border-slate-800">
                        {item.task_type}
                      </span>
                    )}
                    {!item.answerable && (
                      <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-rose-500/10 text-rose-400 border border-rose-500/20">
                        not answerable — abstention expected
                      </span>
                    )}
                    {item.expected_fact_count > 0 && (
                      <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-slate-950 text-slate-400 border border-slate-800">
                        {item.expected_fact_count} expected fact{item.expected_fact_count === 1 ? '' : 's'}
                      </span>
                    )}
                    {item.has_code_task && (
                      <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-lime-500/10 text-lime-400 border border-lime-500/20">
                        {item.test_count} unit tests
                      </span>
                    )}
                    {item.gold_sources.length > 0 && (
                      <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-slate-950 text-slate-500 border border-slate-800">
                        gold: {item.gold_sources.join(', ')}
                      </span>
                    )}
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
