// Client for the incident-doctor service. Always relative: nginx (and the
// Vite dev server) proxy /doctor-api/ to the doctor and strip the prefix.
const DOCTOR_BASE = '/doctor-api';

async function parseError(res, fallback) {
  try {
    const body = await res.json();
    return body.detail || body.error || fallback;
  } catch {
    return `${fallback} (HTTP ${res.status})`;
  }
}

export async function listIncidents() {
  const res = await fetch(`${DOCTOR_BASE}/api/incidents`);
  if (!res.ok) throw new Error(await parseError(res, 'Failed to fetch incidents'));
  return res.json();
}

export async function getIncident(id) {
  const res = await fetch(`${DOCTOR_BASE}/api/incidents/${encodeURIComponent(id)}`);
  if (!res.ok) throw new Error(await parseError(res, 'Failed to fetch incident'));
  return res.json();
}

export async function submitTicket(text, since) {
  const payload = { text };
  if (since && since.trim()) payload.since = since.trim();
  const res = await fetch(`${DOCTOR_BASE}/ticket`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  if (!res.ok) throw new Error(await parseError(res, 'Failed to submit ticket'));
  return res.json();
}

export const doctorApi = { listIncidents, getIncident, submitTicket };
