import React, { useCallback, useEffect, useRef, useState } from 'react';
import { listIncidents, getIncident, submitTicket, getAgents, startAgents, decidePullRequest } from '../services/doctorApi';
import { fixInVsCode, undoFix, CONSOLE_COMMAND } from '../services/fixApi';

const REFRESH_MS = 10000;
const IN_PROGRESS = new Set(['collecting', 'diagnosing']);

// ---------- helpers ----------

const shortSha = (sha) => (sha ? String(sha).slice(0, 7) : null);

const fmtTime = (iso) => {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? String(iso) : d.toLocaleString();
};

const fmtPct = (v) => (typeof v === 'number' && !Number.isNaN(v) ? `${Math.round(v * 100)}%` : '—');

const fmtWindow = (w) => (Array.isArray(w) && w.length === 2 ? `${fmtTime(w[0])} → ${fmtTime(w[1])}` : '—');

const STATUS_STYLES = {
  ok: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
  failed: 'bg-rose-500/10 text-rose-400 border-rose-500/20',
  collecting: 'bg-sky-500/10 text-sky-400 border-sky-500/20',
  diagnosing: 'bg-indigo-500/10 text-indigo-400 border-indigo-500/20'
};

const CLASS_STYLES = [
  [/deploy|regress|code|bug/i, 'bg-violet-500/10 text-violet-300 border-violet-500/20'],
  [/capacity|load|traffic|demand|saturat/i, 'bg-amber-500/10 text-amber-300 border-amber-500/20'],
  [/depend|upstream|network|external/i, 'bg-sky-500/10 text-sky-300 border-sky-500/20'],
  [/config|infra|resource/i, 'bg-teal-500/10 text-teal-300 border-teal-500/20']
];

const classStyle = (cls) => {
  if (!cls) return 'bg-slate-800 text-slate-400 border-slate-700';
  const hit = CLASS_STYLES.find(([re]) => re.test(cls));
  return hit ? hit[1] : 'bg-slate-700/40 text-slate-300 border-slate-600/50';
};

function Badge({ className = '', children, title }) {
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide border ${className}`}
    >
      {children}
    </span>
  );
}

function StatusBadge({ status }) {
  const style = STATUS_STYLES[status] || 'bg-slate-800 text-slate-400 border-slate-700';
  return (
    <Badge className={style}>
      {IN_PROGRESS.has(status) && <span className="w-1.5 h-1.5 rounded-full bg-current animate-pulse" />}
      {status || 'unknown'}
    </Badge>
  );
}

function Section({ title, right, children }) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-3">
      <div className="flex items-center justify-between gap-3 border-b border-slate-800 pb-2">
        <h3 className="text-sm font-semibold text-white">{title}</h3>
        {right}
      </div>
      {children}
    </div>
  );
}

function ConfidenceBar({ value }) {
  const pct = typeof value === 'number' ? Math.max(0, Math.min(1, value)) * 100 : 0;
  const color = pct >= 70 ? 'bg-emerald-500' : pct >= 40 ? 'bg-indigo-500' : 'bg-slate-500';
  return (
    <div className="flex items-center gap-2 min-w-[110px]">
      <div className="flex-1 h-1.5 rounded-full bg-slate-800 overflow-hidden">
        <div className={`h-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-mono text-slate-300 w-9 text-right">{fmtPct(value)}</span>
    </div>
  );
}

function DiffView({ diff }) {
  if (!diff) return <p className="text-xs text-slate-500 italic">No diff proposed.</p>;
  return (
    <pre className="text-xs bg-slate-950 border border-slate-800 rounded-xl p-3 overflow-x-auto leading-relaxed">
      {String(diff)
        .split('\n')
        .map((line, i) => {
          let cls = 'text-slate-400';
          if (line.startsWith('+++') || line.startsWith('---')) cls = 'text-slate-300 font-semibold';
          else if (line.startsWith('+')) cls = 'text-emerald-400 bg-emerald-500/5';
          else if (line.startsWith('-')) cls = 'text-rose-400 bg-rose-500/5';
          else if (line.startsWith('@@')) cls = 'text-indigo-400';
          return (
            <div key={i} className={`${cls} whitespace-pre`}>
              {line || ' '}
            </div>
          );
        })}
    </pre>
  );
}

// ---------- report-a-problem form ----------

function TicketForm({ onCreated }) {
  const [text, setText] = useState('');
  const [since, setSince] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async (e) => {
    e.preventDefault();
    if (!text.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const res = await submitTicket(text.trim(), since);
      setText('');
      setSince('');
      onCreated(res?.incident_id);
    } catch (err) {
      setError(err.message || 'Failed to submit ticket');
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="bg-slate-900 border border-slate-800 rounded-2xl p-4 space-y-2.5">
      <h3 className="text-sm font-semibold text-white">Report a problem</h3>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={3}
        placeholder="Describe the symptom, e.g. 'uploads fail with 500 errors'"
        className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-xl text-sm text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500 resize-y"
      />
      <input
        type="text"
        value={since}
        onChange={(e) => setSince(e.target.value)}
        placeholder="Since when? (optional, e.g. '10 minutes ago')"
        className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-xl text-sm text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500"
      />
      {error && <p className="text-xs text-rose-400">{error}</p>}
      <button
        type="submit"
        disabled={busy || !text.trim()}
        className="w-full px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold text-sm rounded-xl shadow-lg shadow-indigo-600/30 transition-all"
      >
        {busy ? 'Submitting…' : 'Submit to Incident Doctor'}
      </button>
    </form>
  );
}

// ---------- incident list ----------

function IncidentList({ incidents, selectedId, onSelect, loading, error, lastRefresh }) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl flex flex-col min-h-0">
      <div className="px-4 py-3 border-b border-slate-800 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-white">Incidents ({incidents.length})</h3>
        <span className="text-[10px] text-slate-500">
          {lastRefresh ? `refreshed ${lastRefresh.toLocaleTimeString()}` : loading ? 'loading…' : ''}
        </span>
      </div>
      {error && <div className="m-3 p-2.5 rounded-lg bg-rose-500/10 border border-rose-500/20 text-rose-400 text-xs">{error}</div>}
      <div className="overflow-y-auto max-h-[70vh] divide-y divide-slate-800/70">
        {!loading && incidents.length === 0 && !error && (
          <p className="p-4 text-xs text-slate-500">No incidents yet. Alerts and tickets will show up here.</p>
        )}
        {incidents.map((inc) => {
          const active = inc.id === selectedId;
          return (
            <button
              key={inc.id}
              onClick={() => onSelect(inc.id)}
              className={`w-full text-left px-4 py-3 transition-all ${
                active ? 'bg-indigo-600/15 border-l-2 border-indigo-500' : 'border-l-2 border-transparent hover:bg-slate-800/50'
              }`}
            >
              <div className="flex items-center gap-1.5 flex-wrap mb-1">
                <StatusBadge status={inc.status} />
                {inc.incident_class && <Badge className={classStyle(inc.incident_class)}>{inc.incident_class}</Badge>}
                {inc.resolved && <Badge className="bg-emerald-500/10 text-emerald-300 border-emerald-500/20">resolved</Badge>}
              </div>
              <div className="text-sm font-semibold text-slate-100 truncate">{inc.alertname || '(unnamed)'}</div>
              <div className="text-xs text-slate-400 truncate">{inc.service || 'unknown service'}</div>
              <div className="flex items-center justify-between mt-1 text-[11px] text-slate-500">
                <span>{fmtTime(inc.started)}</span>
                <span className="flex items-center gap-2">
                  <span className="font-mono text-slate-300">{fmtPct(inc.confidence)}</span>
                  <span className="px-1.5 py-0.5 rounded bg-slate-800 text-slate-400">{inc.trigger || '—'}</span>
                </span>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ---------- incident detail ----------

function EvidencePanel({ evidence }) {
  if (!evidence) return null;
  const alerts = evidence.related_alerts || [];
  const logs = [...(evidence.logs || [])].sort((a, b) => (b.count || 0) - (a.count || 0)).slice(0, 10);
  const deploys = evidence.deploys || [];
  const commits = evidence.candidate_commits || [];
  const windows = evidence.windows || {};

  return (
    <Section title="Evidence">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs text-slate-400">
        <div>
          <span className="text-slate-500">Incident window: </span>
          <span className="text-slate-300">{fmtWindow(windows.incident)}</span>
        </div>
        <div>
          <span className="text-slate-500">Baseline window: </span>
          <span className="text-slate-300">{fmtWindow(windows.baseline)}</span>
        </div>
      </div>

      <div>
        <h4 className="text-xs font-semibold text-slate-400 uppercase mb-1.5">Related alerts ({alerts.length})</h4>
        {alerts.length === 0 ? (
          <p className="text-xs text-slate-500">None.</p>
        ) : (
          <ul className="space-y-1">
            {alerts.map((a, i) => (
              <li key={i} className="text-xs bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5">
                <span className="font-semibold text-slate-200">{a.alertname}</span>
                {a.labels?.service && <span className="text-slate-500"> · {a.labels.service}</span>}
                <span className="text-slate-500"> · {fmtTime(a.startsAt)}</span>
                {a.summary && <div className="text-slate-400">{a.summary}</div>}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div>
        <h4 className="text-xs font-semibold text-slate-400 uppercase mb-1.5">Top log signatures</h4>
        {logs.length === 0 ? (
          <p className="text-xs text-slate-500">None.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-slate-500 border-b border-slate-800">
                  <th className="py-1.5 pr-3 font-medium">Count</th>
                  <th className="py-1.5 pr-3 font-medium">Level</th>
                  <th className="py-1.5 pr-3 font-medium">Services</th>
                  <th className="py-1.5 font-medium">Signature</th>
                </tr>
              </thead>
              <tbody>
                {logs.map((l, i) => (
                  <tr key={i} className="border-b border-slate-800/50 align-top">
                    <td className="py-1.5 pr-3 font-mono text-indigo-300">{l.count}</td>
                    <td className="py-1.5 pr-3 text-slate-400">{l.level || '—'}</td>
                    <td className="py-1.5 pr-3 text-slate-400">{(l.services || []).join(', ') || '—'}</td>
                    <td className="py-1.5 text-slate-300">
                      {l.exc_type && <span className="font-mono text-rose-300">{l.exc_type}: </span>}
                      <span className="break-words">{l.exc_message || l.message || l.signature}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div>
          <h4 className="text-xs font-semibold text-slate-400 uppercase mb-1.5">Deploys in window ({deploys.length})</h4>
          {deploys.length === 0 ? (
            <p className="text-xs text-slate-500">None.</p>
          ) : (
            <ul className="space-y-1">
              {deploys.map((d, i) => (
                <li key={i} className="text-xs bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5">
                  <span className="font-mono text-indigo-300">{d.short_sha}</span>
                  <span className="text-slate-500"> · {fmtTime(d.ts)}</span>
                  {d.outcome && <span className="text-slate-400"> · {d.outcome}</span>}
                  {d.services_changed?.length > 0 && (
                    <div className="text-slate-400">changed: {d.services_changed.join(', ')}</div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <h4 className="text-xs font-semibold text-slate-400 uppercase mb-1.5">Candidate commits ({commits.length})</h4>
          {commits.length === 0 ? (
            <p className="text-xs text-slate-500">None.</p>
          ) : (
            <ul className="space-y-1">
              {commits.map((c, i) => (
                <li key={i} className="text-xs bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5">
                  <span className="font-mono text-indigo-300">{shortSha(c.sha)}</span>
                  <span className="text-slate-300"> {c.subject}</span>
                  {c.date && <div className="text-slate-500">{fmtTime(c.date)}</div>}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </Section>
  );
}

// ---------- Fix in VS Code ----------

const FIX_HEAD = {
  applied: ['✓ Fix applied in VS Code', 'ok'],
  already: ['✓ Already in the code', 'ok'],
  preview: ['Fix opened in VS Code as a comparison', 'info'],
  none: ['No code change to apply', 'warn'],
  error: ['Could not apply the fix', 'warn']
};
const FIX_TONE = {
  ok: 'border-emerald-500/40 bg-emerald-500/5 text-emerald-300',
  info: 'border-sky-500/40 bg-sky-500/5 text-sky-300',
  warn: 'border-amber-500/40 bg-amber-500/5 text-amber-300'
};

function FixInVsCode({ incidentId }) {
  const [busy, setBusy] = useState(false);
  const [out, setOut] = useState(null);

  const run = async () => {
    setBusy(true);
    setOut(null);
    try {
      setOut(await fixInVsCode(incidentId));
    } catch (err) {
      setOut({ failed: err.message, consoleDown: !!err.consoleDown });
    } finally {
      setBusy(false);
    }
  };

  const undo = async () => {
    try {
      await undoFix();
      setOut(null);
    } catch (err) {
      setOut({ failed: err.message });
    }
  };

  const [head, tone] = out && !out.failed ? FIX_HEAD[out.mode] || [out.mode, 'warn'] : [null, 'warn'];

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <button
          onClick={run}
          disabled={busy}
          className="px-5 py-2.5 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white font-semibold text-sm rounded-xl shadow-lg shadow-indigo-600/30 transition-all"
        >
          {busy ? 'Opening VS Code…' : 'Fix in VS Code'}
        </button>
        {out?.mode === 'applied' && (
          <button onClick={undo} className="px-3 py-2 text-xs rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700">
            Undo
          </button>
        )}
        <span className="text-xs text-slate-500">Opens the file with the change made, as a diff you can review. Nothing is committed.</span>
      </div>
      {out?.failed && (
        <div className={`p-3 rounded-xl border text-xs ${FIX_TONE.warn}`}>
          <div className="font-semibold text-sm">{out.failed}</div>
          {out.consoleDown && (
            <p className="mt-1 text-slate-300">
              Start it from the repository root, then press the button again:{' '}
              <code className="font-mono text-indigo-300">{CONSOLE_COMMAND}</code>
            </p>
          )}
        </div>
      )}
      {out && !out.failed && (
        <div className={`p-3 rounded-xl border text-xs ${FIX_TONE[tone]}`}>
          <div className="font-semibold text-sm">{head}</div>
          <p className="mt-1 text-slate-300">{out.message}</p>
          {out.source && (
            <p className="mt-1 text-slate-400">
              Where the fix came from: {out.source_label}
              {out.commit && <span className="font-mono text-indigo-300"> ({shortSha(out.commit)})</span>}. {out.why}
            </p>
          )}
          {out.opened === false && out.abs_file && (
            <a className="mt-1 inline-block underline text-indigo-300" href={`vscode://file/${out.abs_file}:${out.line}`}>
              Open {out.file} in VS Code
            </a>
          )}
        </div>
      )}
    </div>
  );
}

// The answer in three boxes: what happened, why, and what to do about it.
function AnswerCard({ incidentId, report }) {
  const diagnosis = report.diagnosis || {};
  const top = [...(diagnosis.hypotheses || [])].sort((a, b) => (b.confidence || 0) - (a.confidence || 0))[0];
  const fix = diagnosis.fix || {};
  const verified = report.verification?.status === 'verified';
  const inCode =
    !!fix.unified_diff ||
    fix.kind === 'code_diff' ||
    !!top?.suspected_commit ||
    diagnosis.incident_class === 'code_defect';

  return (
    <div className="bg-slate-900 border border-indigo-500/30 rounded-2xl p-5 space-y-4">
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="space-y-2">
          <h4 className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">What happened</h4>
          <p className="text-sm text-slate-100 leading-relaxed">{diagnosis.summary || 'No summary provided.'}</p>
          <Badge className={classStyle(diagnosis.incident_class)}>{diagnosis.incident_class || 'unknown'}</Badge>
        </div>
        <div className="space-y-2">
          <h4 className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
            Most likely cause{typeof top?.confidence === 'number' ? ` · ${fmtPct(top.confidence)} sure` : ''}
          </h4>
          <p className="text-sm text-slate-100 leading-relaxed">{top?.cause || 'No cause named.'}</p>
          <p className="text-xs text-slate-400">
            {top?.component && <span className="font-mono text-slate-300">{top.component}</span>}
            {top?.suspected_commit ? (
              <span> · commit <span className="font-mono text-indigo-300">{shortSha(top.suspected_commit)}</span></span>
            ) : (
              <span> · no commit blamed</span>
            )}
          </p>
        </div>
        <div className="space-y-2">
          <h4 className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">The fix</h4>
          <p className="text-sm text-slate-100 leading-relaxed">{fix.action || fix.rationale || 'No fix proposed.'}</p>
          <Badge
            className={
              verified
                ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                : 'bg-amber-500/10 text-amber-400 border-amber-500/20'
            }
          >
            {verified ? 'tested on a spare copy' : report.verification?.status || 'not verified'}
          </Badge>
        </div>
      </div>
      {fix.unified_diff && <DiffView diff={fix.unified_diff} />}
      {inCode ? (
        <FixInVsCode incidentId={incidentId} />
      ) : (
        <p className="text-xs text-slate-500">No code to change here: the fix is an action a person takes.</p>
      )}
    </div>
  );
}

// ---------- the agent team (hierarchical stage after the doctor) ----------

const TEAM_ROLES = [
  ['manager', 'Manager', 'decides who works next'],
  ['diagnoser', 'Diagnoser', 'finds the faulty code'],
  ['fixer', 'Fixer', 'writes the patch'],
  ['tester', 'Tester', 'runs our tests on a copy'],
  ['pr', 'PR', 'opens a pull request, if you agree']
];

const TEAM_STATUS = {
  starting: ['Handing over to the team…', 'info'],
  running: ['The team is working on it…', 'info'],
  awaiting_approval: ['Patch ready and tests pass: open a pull request?', 'ok'],
  done: ['Finished', 'ok'],
  escalated: ['No code patch passed: the team wrote up what it tried', 'warn'],
  failed: ['The team could not fix it', 'warn'],
  error: ['The team hit an error', 'warn'],
  rejected: ['The team refused the input', 'warn'],
  unreachable: ['The agent team could not be reached', 'warn'],
  stalled: ['The team stopped answering', 'warn'],
  lost: ['The team no longer has this run', 'warn'],
  off: ['The agent team is switched off', 'warn']
};
const TEAM_ACTIVE = new Set(['starting', 'running']);

function AgentTeam({ incidentId }) {
  const [team, setTeam] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setTeam(await getAgents(incidentId));
      setErr(null);
    } catch (e) {
      setErr(e.message);
    }
  }, [incidentId]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!team || !(TEAM_ACTIVE.has(team.status) || team.status === 'none')) return undefined;
    const t = setInterval(load, 6000);
    return () => clearInterval(t);
  }, [team, load]);

  const act = async (fn) => {
    setBusy(true);
    try {
      await fn();
      await load();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  if (!team) return err ? <p className="text-xs text-rose-400">{err}</p> : null;
  if (team.status === 'none' && !team.enabled) return null;

  const [head, tone] = TEAM_STATUS[team.status] || [team.status === 'none' ? 'Not handed over yet' : team.status, 'info'];
  const busyAgent = TEAM_ACTIVE.has(team.status)
    ? [...(team.steps || [])].reverse().find((s) => s.status === 'in_progress')?.agent
    : null;
  const usedAgents = new Set((team.steps || []).map((s) => s.agent));

  return (
    <Section
      title="Agent team: Manager → Diagnoser → Fixer → Tester"
      right={
        team.url && (
          <a href={team.url} target="_blank" rel="noreferrer" className="text-xs text-indigo-300 underline">
            Open the team's live run ↗
          </a>
        )
      }
    >
      <p className="text-xs text-slate-400">
        After its report, the doctor hands the incident to a team of AI agents. The Manager gives the work out, and when the
        tests fail it sends the Fixer back with the failure log (up to {team.max_attempts || 3} tries).
      </p>

      <div className="flex flex-wrap gap-2">
        {TEAM_ROLES.map(([key, name, what]) => {
          const working = busyAgent === key;
          const used = usedAgents.has(key);
          return (
            <div
              key={key}
              className={`px-3 py-2 rounded-xl border text-xs ${
                working
                  ? 'border-indigo-400 bg-indigo-500/10 text-indigo-200'
                  : used
                  ? 'border-slate-600 bg-slate-800/60 text-slate-200'
                  : 'border-slate-800 text-slate-500'
              }`}
            >
              <div className="font-semibold flex items-center gap-1.5">
                {working && <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-pulse" />}
                {name}
              </div>
              <div className="text-[10px]">{what}</div>
            </div>
          );
        })}
      </div>

      <div className={`p-3 rounded-xl border text-xs ${FIX_TONE[tone]}`}>
        <div className="font-semibold text-sm flex items-center gap-2">
          {TEAM_ACTIVE.has(team.status) && <span className="w-2 h-2 rounded-full bg-current animate-pulse" />}
          {head}
        </div>
        <p className="mt-1 text-slate-400">
          {typeof team.attempts === 'number' && `Fixer attempts: ${team.attempts}/${team.max_attempts || 3}. `}
          {team.tests && `Tests: ${team.tests.total - (team.tests.failed || 0)}/${team.tests.total} passed. `}
          {typeof team.cost_usd === 'number' && `Model cost: $${team.cost_usd.toFixed(3)}.`}
        </p>
        {team.error && <p className="mt-1 font-mono text-rose-300">{team.error}</p>}
      </div>

      {team.diagnosis?.root_cause && (
        <div className="space-y-1">
          <h4 className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Team's root cause</h4>
          <p className="text-sm text-slate-100">{team.diagnosis.root_cause}</p>
          {team.diagnosis.implicated_files?.length > 0 && (
            <p className="text-xs font-mono text-slate-400">{team.diagnosis.implicated_files.join(', ')}</p>
          )}
        </div>
      )}

      {team.decisions?.length > 0 && (
        <div className="space-y-1">
          <h4 className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Manager's decisions</h4>
          <ol className="text-xs text-slate-300 space-y-1 list-decimal list-inside">
            {team.decisions.map((d, i) => (
              <li key={i}>
                <span className="text-slate-400">{d.event}</span> → <span className="font-semibold text-indigo-300">{d.choice}</span>
                {d.why && <span className="text-slate-500"> ({d.why})</span>}
              </li>
            ))}
          </ol>
        </div>
      )}

      {team.patch?.diff && (
        <div className="space-y-1">
          <h4 className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
            Team's patch{team.patch.attempt ? ` (attempt ${team.patch.attempt})` : ''}
          </h4>
          {team.patch.rationale && <p className="text-xs text-slate-400">{team.patch.rationale}</p>}
          <DiffView diff={team.patch.diff} />
        </div>
      )}

      {team.escalation && (
        <div className="space-y-1">
          <h4 className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Escalated to a person</h4>
          <p className="text-sm text-slate-200 whitespace-pre-wrap">{team.escalation.summary || team.escalation.reason}</p>
          <p className="text-xs text-slate-500">The doctor's suggested fix above still applies.</p>
        </div>
      )}

      {team.status === 'awaiting_approval' && (
        <div className="flex flex-wrap items-center gap-3">
          <button
            disabled={busy}
            onClick={() => act(() => decidePullRequest(incidentId, true))}
            className="px-5 py-2.5 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white font-semibold text-sm rounded-xl"
          >
            {busy ? 'Opening…' : 'Open pull request'}
          </button>
          <button
            disabled={busy}
            onClick={() => act(() => decidePullRequest(incidentId, false))}
            className="px-3 py-2 text-xs rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700"
          >
            No thanks
          </button>
          <span className="text-xs text-slate-500">Nothing is pushed until you press the button.</span>
        </div>
      )}

      {team.pr && (
        <p className="text-xs text-slate-300">
          {team.pr.url ? (
            <a href={team.pr.url} target="_blank" rel="noreferrer" className="underline text-emerald-300">
              Pull request: {team.pr.url}
            </a>
          ) : (
            team.pr.note || 'Pull request declined.'
          )}
        </p>
      )}

      {team.enabled && !TEAM_ACTIVE.has(team.status) && team.status !== 'awaiting_approval' && (
        <button
          disabled={busy}
          onClick={() => act(() => startAgents(incidentId))}
          className="px-3 py-2 text-xs rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700"
        >
          {team.status === 'none' ? 'Hand to the agent team' : 'Run the agent team again'}
        </button>
      )}
      {err && <p className="text-xs text-rose-400">{err}</p>}
    </Section>
  );
}

function ReportView({ report }) {
  const diagnosis = report.diagnosis || {};
  const dvc = diagnosis.demand_vs_capacity;
  const hypotheses = [...(diagnosis.hypotheses || [])].sort((a, b) => (b.confidence || 0) - (a.confidence || 0));
  const fix = diagnosis.fix;
  const verification = report.verification;
  const verified = verification?.status === 'verified';

  return (
    <>
      {dvc && (
      <Section title="Demand vs capacity">
        {dvc && (
          <div className="bg-slate-950 border border-slate-800 rounded-xl p-3 text-xs space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold text-slate-300">Demand vs capacity:</span>
              <Badge className="bg-indigo-500/10 text-indigo-300 border-indigo-500/20">{dvc.verdict || '—'}</Badge>
            </div>
            <div className="text-slate-400">
              Traffic change: <span className="text-slate-300">{dvc.traffic_change ?? '—'}</span>
              <span className="mx-2 text-slate-700">|</span>
              Deploy before onset:{' '}
              <span className="text-slate-300">
                {dvc.deploy_before_onset === true ? 'yes' : dvc.deploy_before_onset === false ? 'no' : String(dvc.deploy_before_onset ?? '—')}
              </span>
            </div>
            {dvc.reasoning && <p className="text-slate-400">{dvc.reasoning}</p>}
          </div>
        )}
      </Section>
      )}

      <Section title={`All hypotheses, ranked (${hypotheses.length})`}>
        {hypotheses.length === 0 ? (
          <p className="text-xs text-slate-500">No hypotheses.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-slate-500 border-b border-slate-800">
                  <th className="py-2 pr-3 font-medium w-8">#</th>
                  <th className="py-2 pr-3 font-medium">Confidence</th>
                  <th className="py-2 pr-3 font-medium">Component</th>
                  <th className="py-2 pr-3 font-medium">Commit</th>
                  <th className="py-2 font-medium">Cause</th>
                </tr>
              </thead>
              <tbody>
                {hypotheses.map((h, i) => (
                  <tr key={i} className="border-b border-slate-800/50 align-top">
                    <td className="py-2 pr-3 text-slate-500">{i + 1}</td>
                    <td className="py-2 pr-3">
                      <ConfidenceBar value={h.confidence} />
                    </td>
                    <td className="py-2 pr-3 text-slate-300 font-mono">{h.component || '—'}</td>
                    <td className="py-2 pr-3 font-mono">
                      {h.suspected_commit ? (
                        <span className="text-indigo-300" title={h.suspected_commit}>{shortSha(h.suspected_commit)}</span>
                      ) : (
                        <span className="text-slate-500">none</span>
                      )}
                    </td>
                    <td className="py-2 text-slate-200">
                      <div>{h.cause}</div>
                      {h.evidence?.length > 0 && (
                        <ul className="mt-1 list-disc list-inside space-y-0.5 text-slate-400">
                          {h.evidence.map((ev, j) => (
                            <li key={j}>{ev}</li>
                          ))}
                        </ul>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      {fix?.rationale && fix.action && (
        <Section
          title="Why this fix"
          right={fix.kind && <Badge className="bg-violet-500/10 text-violet-300 border-violet-500/20">{fix.kind}</Badge>}
        >
          <p className="text-xs text-slate-400">{fix.rationale}</p>
        </Section>
      )}

      {verification && (
        <Section
          title="Verification"
          right={
            <Badge
              className={
                verified
                  ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                  : 'bg-amber-500/10 text-amber-400 border-amber-500/20'
              }
            >
              {verification.status || 'unknown'}
            </Badge>
          }
        >
          {verification.reason && <p className="text-xs text-slate-300">{verification.reason}</p>}
          {verification.suite?.summary && (
            <p className="text-xs text-slate-400">
              Tests: <span className="font-mono text-slate-300">{verification.suite.summary}</span>
            </p>
          )}
        </Section>
      )}
    </>
  );
}

function CostLine({ report }) {
  const u = report.usage || {};
  const parts = [];
  if (report.provider || report.model) parts.push(`${report.provider || '?'} / ${report.model || '?'}`);
  if (u.calls != null) parts.push(`${u.calls} call${u.calls === 1 ? '' : 's'}`);
  if (u.prompt_tokens != null || u.completion_tokens != null)
    parts.push(`${u.prompt_tokens ?? 0} in / ${u.completion_tokens ?? 0} out tokens`);
  if (typeof u.cost_usd === 'number') parts.push(`$${u.cost_usd.toFixed(4)}`);
  if (typeof report.timings?.total_s === 'number') parts.push(`${report.timings.total_s.toFixed(1)} s total`);
  if (parts.length === 0) return null;
  return <p className="text-[11px] text-slate-500 font-mono">{parts.join(' · ')}</p>;
}

function IncidentDetail({ summary, detail, loading, error }) {
  const [showRaw, setShowRaw] = useState(false);

  if (!summary) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-10 text-center text-sm text-slate-500">
        Select an incident to see its diagnosis.
      </div>
    );
  }

  const report = detail?.report || null;
  const markdown = detail?.markdown || null;
  const status = summary.status;
  const inProgress = IN_PROGRESS.has(status);

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge status={status} />
          {summary.incident_class && <Badge className={classStyle(summary.incident_class)}>{summary.incident_class}</Badge>}
          {summary.resolved && <Badge className="bg-emerald-500/10 text-emerald-300 border-emerald-500/20">resolved</Badge>}
          <span className="text-[11px] text-slate-500 ml-auto font-mono">{summary.id}</span>
        </div>
        <h2 className="text-xl font-bold text-white">{summary.alertname || '(unnamed incident)'}</h2>
        <div className="text-xs text-slate-400 flex flex-wrap gap-x-4 gap-y-1">
          <span>Service: <span className="text-slate-300">{summary.service || '—'}</span></span>
          <span>Started: <span className="text-slate-300">{fmtTime(summary.started)}</span></span>
          <span>Trigger: <span className="text-slate-300">{summary.trigger || '—'}</span></span>
          <span>Confidence: <span className="text-slate-300">{fmtPct(summary.confidence)}</span></span>
          {summary.suspected_commit && (
            <span>
              Suspected commit: <span className="font-mono text-indigo-300">{shortSha(summary.suspected_commit)}</span>
            </span>
          )}
          {typeof summary.alert_to_report_s === 'number' && (
            <span>Alert → report: <span className="text-slate-300">{summary.alert_to_report_s.toFixed(1)} s</span></span>
          )}
        </div>
        {report && <CostLine report={report} />}
      </div>

      {error && (
        <div className="p-3 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-400 text-sm">{error}</div>
      )}

      {loading && !detail && <div className="text-sm text-slate-500 px-1">Loading incident…</div>}

      {inProgress && (
        <div className="p-4 rounded-xl bg-indigo-500/10 border border-indigo-500/20 text-indigo-300 text-sm flex items-center gap-3">
          <span className="w-2 h-2 rounded-full bg-indigo-400 animate-pulse" />
          {status === 'collecting' ? 'Collecting evidence…' : 'Diagnosis in progress…'} This page refreshes automatically.
        </div>
      )}

      {status === 'failed' && (
        <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-300 text-sm">
          The diagnosis failed{summary.verification ? `: ${summary.verification}` : '.'}
          {report?.error && <div className="text-xs text-rose-400 mt-1 font-mono">{String(report.error)}</div>}
        </div>
      )}

      {report?.diagnosis ? (
        <>
          <AnswerCard incidentId={summary.id} report={report} />
          <AgentTeam incidentId={summary.id} />
        </>
      ) : (
        detail && !inProgress && status !== 'failed' && (
          <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 text-slate-400 text-sm">No report available for this incident.</div>
        )
      )}

      {/* Everything behind the answer stays one click away, out of the way. */}
      {detail && (
      <details className="group">
        <summary className="cursor-pointer select-none list-none px-4 py-3 rounded-xl bg-slate-900 border border-slate-800 text-sm font-semibold text-slate-300 hover:text-white flex items-center gap-2">
          <span className="text-indigo-400 group-open:rotate-90 transition-transform">▸</span>
          Technical details
          <span className="text-xs font-normal text-slate-500">all hypotheses · verification · evidence · raw report</span>
        </summary>
        <div className="space-y-4 mt-4">
      {report?.diagnosis && <ReportView report={report} />}

      {detail?.resolution && (
        <Section title="Resolution">
          <pre className="text-xs text-slate-300 bg-slate-950 border border-slate-800 rounded-xl p-3 overflow-x-auto whitespace-pre-wrap">
            {JSON.stringify(detail.resolution, null, 2)}
          </pre>
        </Section>
      )}

      <EvidencePanel evidence={detail?.evidence} />

      {markdown && (
        <Section
          title="Raw report"
          right={
            <button
              onClick={() => setShowRaw((v) => !v)}
              className="text-xs px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700"
            >
              {showRaw ? 'Hide' : 'Show'}
            </button>
          }
        >
          {showRaw ? (
            <pre className="text-xs text-slate-300 bg-slate-950 border border-slate-800 rounded-xl p-3 overflow-x-auto whitespace-pre-wrap max-h-[60vh]">
              {markdown}
            </pre>
          ) : (
            <p className="text-xs text-slate-500">Markdown report as written by the doctor.</p>
          )}
        </Section>
      )}
        </div>
      </details>
      )}
    </div>
  );
}

// ---------- page ----------

export default function Incidents() {
  const [incidents, setIncidents] = useState([]);
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState(null);
  const [lastRefresh, setLastRefresh] = useState(null);

  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState(null);

  // Tracks the status last seen for the selected incident so the detail is
  // re-fetched when it changes (e.g. diagnosing -> ok).
  const lastStatusRef = useRef(null);
  const selectedRef = useRef(null);
  selectedRef.current = selectedId;

  const loadDetail = useCallback(async (id, { quiet = false } = {}) => {
    if (!id) return;
    if (!quiet) setDetailLoading(true);
    try {
      const d = await getIncident(id);
      if (selectedRef.current === id) {
        setDetail(d);
        setDetailError(null);
      }
    } catch (err) {
      if (selectedRef.current === id && !quiet) setDetailError(err.message || 'Failed to load incident');
    } finally {
      if (!quiet) setDetailLoading(false);
    }
  }, []);

  const loadList = useCallback(async () => {
    try {
      const data = await listIncidents();
      const sorted = [...(Array.isArray(data) ? data : [])].sort(
        (a, b) => new Date(b.started || 0).getTime() - new Date(a.started || 0).getTime()
      );
      setIncidents(sorted);
      setListError(null);
      setLastRefresh(new Date());
      return sorted;
    } catch (err) {
      setListError(err.message || 'Failed to load incidents');
      return null;
    } finally {
      setListLoading(false);
    }
  }, []);

  const selectIncident = useCallback(
    (id) => {
      setSelectedId(id);
      selectedRef.current = id;
      setDetail(null);
      setDetailError(null);
      lastStatusRef.current = null;
      loadDetail(id);
    },
    [loadDetail]
  );

  // Initial load + 10 s auto refresh.
  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      const list = await loadList();
      if (cancelled || !list) return;
      const cur = selectedRef.current;
      if (!cur) {
        if (list.length > 0) selectIncident(list[0].id);
        return;
      }
      const inc = list.find((i) => i.id === cur);
      if (!inc) return;
      // Re-fetch detail while in progress, or when the status changed.
      if (IN_PROGRESS.has(inc.status) || lastStatusRef.current !== inc.status) {
        lastStatusRef.current = inc.status;
        loadDetail(cur, { quiet: true });
      }
    };
    tick();
    const t = setInterval(tick, REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, [loadList, loadDetail, selectIncident]);

  const handleTicketCreated = async (incidentId) => {
    await loadList();
    if (incidentId) selectIncident(incidentId);
  };

  const selectedSummary =
    incidents.find((i) => i.id === selectedId) ||
    (selectedId ? { id: selectedId, status: 'diagnosing', trigger: 'ticket' } : null);

  return (
    <div className="p-6 lg:p-8 max-w-[1600px] mx-auto space-y-6">
      <div>
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 mb-2">
          <span>AI Incident Doctor</span>
        </div>
        <h1 className="text-2xl font-bold text-white">Incidents</h1>
        <p className="text-sm text-slate-400">
          Outages detected by alerts or reported by users, with the doctor's root-cause diagnosis, proposed fix and verification.
        </p>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[360px_minmax(0,1fr)] gap-6 items-start">
        <div className="space-y-4">
          <IncidentList
            incidents={incidents}
            selectedId={selectedId}
            onSelect={selectIncident}
            loading={listLoading}
            error={listError}
            lastRefresh={lastRefresh}
          />
          <TicketForm onCreated={handleTicketCreated} />
        </div>
        <IncidentDetail
          key={selectedId || 'none'}
          summary={selectedSummary}
          detail={detail}
          loading={detailLoading}
          error={detailError}
        />
      </div>
    </div>
  );
}
