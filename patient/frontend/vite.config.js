import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// The repository root holds the single .env every part of the stack reads.
const REPO_ROOT = path.resolve(__dirname, '../..')

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  // '' prefix: load every variable, not only VITE_*. process.env wins so a
  // value set in the shell or in compose overrides the file.
  const env = { ...loadEnv(mode, REPO_ROOT, ''), ...process.env }

  const gatewayUrl = env.GATEWAY_URL
  if (!gatewayUrl) {
    throw new Error(
      `GATEWAY_URL is not set. Add it to ${path.join(REPO_ROOT, '.env')} ` +
        'or export it in the environment (e.g. GATEWAY_URL=http://127.0.0.1:8000).'
    )
  }

  const proxy = {
    '/api': {
      target: gatewayUrl,
      changeOrigin: true,
      secure: false
    }
  }

  const doctorUrl = env.DOCTOR_URL
  if (doctorUrl) {
    proxy['/doctor-api'] = {
      target: doctorUrl,
      changeOrigin: true,
      secure: false,
      rewrite: (p) => p.replace(/^\/doctor-api/, '')
    }
  }

  // The dev-server twin of nginx's /service-links.json: the same host ports,
  // read from the repo .env with compose's defaults.
  const linkPorts = {
    grafana: env.GRAFANA_HOST_PORT || '3000',
    prometheus: env.PROMETHEUS_HOST_PORT || '9090',
    alertmanager: env.ALERTMANAGER_HOST_PORT || '9093',
    alert_sink: env.ALERT_SINK_HOST_PORT || '9095',
    mlflow: env.MLFLOW_HOST_PORT || '5000',
    doctor: env.DOCTOR_HOST_PORT || '8100'
  }
  const serviceLinks = {
    name: 'service-links',
    configureServer(server) {
      server.middlewares.use('/service-links.json', (_req, res) => {
        res.setHeader('Content-Type', 'application/json')
        res.end(JSON.stringify(Object.fromEntries(
          Object.entries(linkPorts).map(([k, v]) => [k, Number(v)]))))
      })
    }
  }

  return {
    plugins: [react(), serviceLinks],
    server: {
      port: 3001,
      proxy
    }
  }
})
