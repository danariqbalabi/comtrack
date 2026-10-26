import { useEffect, useState } from 'react'
import { getHealth } from './api'
import type { HealthResponse } from './api'

type Connection =
  | { state: 'loading' }
  | { state: 'connected'; data: HealthResponse }
  | { state: 'error'; message: string }

export default function App() {
  const [connection, setConnection] = useState<Connection>({ state: 'loading' })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    const timeout = window.setTimeout(() => controller.abort(), 8000)
    setConnection({ state: 'loading' })

    getHealth(controller.signal)
      .then((data) => {
        if (active) setConnection({ state: 'connected', data })
      })
      .catch((error: unknown) => {
        if (!active) return
        setConnection({
          state: 'error',
          message: controller.signal.aborted
            ? 'Backend belum merespons. Pastikan server FastAPI berjalan.'
            : error instanceof Error ? error.message : 'Backend belum terhubung.',
        })
      })
      .finally(() => window.clearTimeout(timeout))

    return () => {
      active = false
      window.clearTimeout(timeout)
      controller.abort()
    }
  }, [attempt])

  return (
    <div className="mx-auto flex min-h-dvh max-w-5xl flex-col px-6 sm:px-10">
      <header className="flex items-center gap-3 border-b border-stone-200 py-6">
        <span aria-hidden="true" className="grid size-10 place-items-center rounded-full bg-lime-200 text-2xl text-emerald-950">◎</span>
        <span className="text-lg font-bold tracking-tight">Lomba Radar</span>
      </header>

      <main className="flex flex-1 flex-col justify-center py-14 sm:py-20">
        <p className="mb-4 text-xs font-semibold tracking-[0.2em] text-stone-500">LOMBA INDONESIA · MAHASISWA</p>
        <h1 className="max-w-2xl text-4xl leading-tight font-semibold tracking-tight sm:text-6xl">Tempat peluang<br />berikutnya ditemukan.</h1>
        <p className="mt-5 max-w-lg text-base leading-7 text-stone-600">Radar pribadi untuk hackathon, business case, dan business plan competition.</p>

        <section aria-labelledby="connection-title" className="mt-10 max-w-lg rounded-2xl border border-stone-200 bg-white p-6">
          <h2 id="connection-title" className="text-base font-semibold">Koneksi aplikasi</h2>
          <div role="status" aria-live="polite" className="mt-3 text-sm leading-6">
            {connection.state === 'loading' && <p className="text-stone-600">Memeriksa koneksi backend…</p>}
            {connection.state === 'connected' && (
              <p className="text-emerald-800"><span aria-hidden="true">● </span>Backend terhubung — {connection.data.service}</p>
            )}
            {connection.state === 'error' && <p className="text-red-700">{connection.message}</p>}
          </div>
          <button
            type="button"
            disabled={connection.state === 'loading'}
            onClick={() => setAttempt((value) => value + 1)}
            className="mt-5 rounded-lg bg-emerald-950 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-emerald-800 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-emerald-800 disabled:cursor-wait disabled:opacity-50"
          >Cek koneksi lagi</button>
        </section>

        <p className="mt-5 max-w-lg text-sm leading-6 text-stone-500">Belum ada data lomba. Pengumpulan sumber dan feed akan tersedia pada tahap berikutnya.</p>
      </main>

      <footer className="border-t border-stone-200 py-5 text-xs text-stone-500">Lomba Radar · Tool pribadi</footer>
    </div>
  )
}
