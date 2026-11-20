// Fix in VS Code. Applying a patch and opening an editor has to happen on the
// developer's own machine, so this does not go through nginx to a container:
// it calls the demo console (showcase/fault_console.py), which listens on
// 127.0.0.1 only and accepts these calls from pages served on localhost.
const CONSOLE_BASE = 'http://127.0.0.1:5500/console';

export const CONSOLE_COMMAND = '.venv/Scripts/python.exe showcase/fault_console.py';

async function call(path, body) {
  let res;
  try {
    res = await fetch(`${CONSOLE_BASE}/${path}`, body
      ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
      : { cache: 'no-store' });
  } catch {
    const err = new Error('The demo console is not running on this computer.');
    err.consoleDown = true;
    throw err;
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `The demo console answered HTTP ${res.status}`);
  return data;
}

export const fixInVsCode = (incidentId) => call('fix', { incident_id: incidentId });
export const undoFix = () => call('fix/undo', {});
export const fixStatus = () => call('fix/status');
