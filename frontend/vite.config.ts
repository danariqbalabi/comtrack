import { fileURLToPath } from 'node:url'
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { readFileSync, writeFileSync, readdirSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { resolve } from 'node:path'

const envDir = fileURLToPath(new URL('..', import.meta.url))

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, envDir, 'API_')

  return {
    envDir,
    plugins: [react(), tailwindcss(), {
      name: 'lomba-radar-offline-shell',
      apply: 'build',
      closeBundle() {
        const dist = resolve(import.meta.dirname, 'dist')
        const assets = readdirSync(dist, { recursive: true }).filter((name): name is string => typeof name === 'string' && /\.(js|css|html|svg|png|webmanifest)$/.test(name) && name !== 'sw.js').map(name => '/' + name.replaceAll('\\', '/'))
        const source = readFileSync(resolve(dist, 'sw.js'), 'utf8')
        const revision = createHash('sha256').update(source + assets.join('|') + readFileSync(resolve(dist, 'index.html'), 'utf8')).digest('hex').slice(0, 16)
        writeFileSync(resolve(dist, 'sw.js'), `const ASSETS=${JSON.stringify(assets)};const CACHE='lomba-radar-${revision}';\n` + source)
      },
    }],
    server: {
      proxy: {
        '/api': {
          target: env.API_PROXY_TARGET || 'http://127.0.0.1:8000',
          changeOrigin: true,
        },
      },
    },
  }
})
