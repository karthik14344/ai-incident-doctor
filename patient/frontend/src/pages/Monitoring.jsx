import React, { useCallback, useEffect, useState } from 'react';
import { getServicePorts, hostUrl, isReachable } from '../services/linksApi';

// The tools used to watch the app, in the order they are opened for a demo
// (docs/LECTURE.md). `port` names a key of /service-links.json; `self` links to
// this app. `probe` is the path used for the reachability check.
const LINKS = [
  { name: 'The app', self: true, path: '/', probe: '/healthz',
    why: 'Chat Assistant and the Incidents page (left sidebar)' },
  { name: 'Grafana dashboard', port: 'grafana', path: '/d/knowledgeai-ops/knowledgeai-operations', probe: '/api/health',
    why: 'The "car dashboard": request rate, errors, p95 latency, memory' },
  { name: 'Grafana Explore', port: 'grafana', path: '/explore', probe: '/api/health',
    why: 'Search the logs in Loki, e.g. follow one request id',
    note: 'Log in as admin first; anonymous viewers cannot use Explore.' },
  { name: 'Prometheus query', port: 'prometheus', path: '/query', probe: '/-/healthy',
    why: 'Type PromQL and graph any metric' },
  { name: 'Prometheus alerts', port: 'prometheus', path: '/alerts', probe: '/-/healthy',
    why: 'The 16 alert rules and their state (inactive / pending / firing)' },
  { name: 'Alertmanager', port: 'alertmanager', path: '/', probe: '/-/healthy',
    why: 'Alert routing: where firing alerts go' },
  { name: 'alert-sink log', port: 'alert_sink', path: '/alerts', probe: '/health',
    why: 'The raw incident trigger log (JSON), one line per alert' },
  { name: 'MLflow', port: 'mlflow', path: '/#/experiments/2', probe: '/health',
    why: 'The evaluation runs of the incident doctor' },
  { name: 'Doctor API', port: 'doctor', path: '/docs', probe: '/health',
    why: "The doctor's three doors: /incident, /ticket, and the read endpoints" },
];

function resolve(link, ports) {
  if (link.self) {
    return { url: `${window.location.origin}${link.path}`, probe: `${window.location.origin}${link.probe}` };
  }
  const port = ports?.[link.port];
  if (!port) return { url: null, probe: null };
  return { url: hostUrl(port, link.path), probe: hostUrl(port, link.probe) };
}

function StatusDot({ state }) {
  const styles = {
    up: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
    down: 'bg-rose-500/10 text-rose-400 border-rose-500/20',
    checking: 'bg-slate-500/10 text-slate-400 border-slate-500/20',
  };
  const label = { up: 'Reachable', down: 'Unreachable', checking: 'Checking…' }[state];
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[10px] font-medium border ${styles[state]}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${state === 'up' ? 'bg-emerald-400' : state === 'down' ? 'bg-rose-400' : 'bg-slate-400'}`} />
      {label}
    </span>
  );
}

export default function Monitoring() {
  const [ports, setPorts] = useState(null);
  const [error, setError] = useState(null);
  const [status, setStatus] = useState({});

  const check = useCallback(async (p) => {
    setStatus(Object.fromEntries(LINKS.map((l) => [l.name, 'checking'])));
    await Promise.all(LINKS.map(async (l) => {
      const { probe } = resolve(l, p);
      const ok = probe ? await isReachable(probe) : false;
      setStatus((s) => ({ ...s, [l.name]: ok ? 'up' : 'down' }));
    }));
  }, []);

  useEffect(() => {
    getServicePorts()
      .then((p) => { setPorts(p); check(p); })
      .catch((e) => setError(e.message));
  }, [check]);

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <h1 className="text-2xl font-bold tracking-tight text-white">Monitoring</h1>
          <p className="text-sm text-slate-400">
            The tools that watch this app. Links open in a new tab, on the same host as this page.
          </p>
        </div>
        <button
          onClick={() => ports && check(ports)}
          disabled={!ports}
          className="px-4 py-2 bg-slate-800 hover:bg-slate-700 disabled:opacity-50 text-slate-200 font-medium text-sm rounded-lg border border-slate-700 transition-all"
        >
          Check again
        </button>
      </div>

      {error && (
        <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-sm text-rose-300">{error}</div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
        {LINKS.map((link, i) => {
          const { url } = resolve(link, ports);
          return (
            <div key={link.name} className="bg-slate-900 border border-slate-800 rounded-xl p-5 flex flex-col gap-3">
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-3 min-w-0">
                  <span className="w-7 h-7 shrink-0 rounded-lg bg-indigo-500/10 text-indigo-400 text-xs font-bold flex items-center justify-center">
                    {i + 1}
                  </span>
                  <h3 className="text-sm font-semibold text-white truncate">{link.name}</h3>
                </div>
                <StatusDot state={status[link.name] || 'checking'} />
              </div>
              <p className="text-xs text-slate-400 leading-relaxed">{link.why}</p>
              {link.note && <p className="text-[11px] text-amber-400/90">{link.note}</p>}
              <div className="mt-auto pt-1 flex items-center gap-2">
                <code className="flex-1 min-w-0 truncate px-2.5 py-1.5 rounded-lg bg-slate-950 border border-slate-800 text-[11px] text-slate-300">
                  {url || '…'}
                </code>
                <a
                  href={url || undefined}
                  target="_blank"
                  rel="noreferrer"
                  className={`px-3 py-1.5 rounded-lg text-xs font-semibold text-white bg-indigo-600 hover:bg-indigo-500 transition-all ${url ? '' : 'pointer-events-none opacity-50'}`}
                >
                  Open
                </a>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
