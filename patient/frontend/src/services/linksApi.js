// Links to the monitoring tools that run beside the app. The server only
// knows their host PORTS (nginx /service-links.json, filled from compose); the
// hostname is whatever the browser used to reach this app, so the links work
// on localhost, on the development laptop's shifted ports, and over the LAN.

export async function getServicePorts() {
  const res = await fetch('/service-links.json', { cache: 'no-store' });
  if (!res.ok) throw new Error(`Failed to load service links (HTTP ${res.status})`);
  return res.json();
}

export function hostUrl(port, path = '') {
  const { protocol, hostname } = window.location;
  return `${protocol}//${hostname}:${port}${path}`;
}

// Reachability only: the tools are on other origins and send no CORS headers,
// so the response is opaque. A resolved fetch means something answered; a
// rejected one (connection refused, timeout) means it did not.
export async function isReachable(url, timeoutMs = 4000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    await fetch(url, { mode: 'no-cors', cache: 'no-store', signal: controller.signal });
    return true;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}
