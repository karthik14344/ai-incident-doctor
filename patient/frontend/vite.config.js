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

  return {
    plugins: [react()],
    server: {
      port: 3001,
      proxy
    }
  }
})
