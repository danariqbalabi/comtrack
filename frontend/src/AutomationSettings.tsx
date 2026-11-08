import { useEffect, useState, type FormEvent } from 'react'
import { api, dateTime } from './api'

type Controls = {
  enabled: boolean; interval_minutes: number; max_sources_per_run: number; max_new_sources_per_run: number
  max_pages_per_source: number; max_images_per_post: number; allow_paid_providers: boolean
  provider_daily_request_limit: number; provider_daily_budget_usd: string
  instagram_public_competition_accounts_only: true
}
type Snapshot = { settings: Controls; version: number; updated_at: string; runtime: {
  state: string; scheduler_available: boolean; scheduler_online: boolean; running: boolean; limits_enforced: boolean; message: string
  next_run_at: string | null; last_tick_at: string | null; last_enqueued_at: string | null; last_job_id: number | null
  providers: Record<string, { configured: boolean; automation_allowed?: boolean }>
} }
const limits: { key: keyof Controls; label: string; min: number; max: number; hint: string }[] = [
  { key: 'interval_minutes', label: 'Interval pencarian (menit)', min: 30, max: 10080, hint: '30 menit sampai 7 hari. Bawaan: 6 jam.' },
  { key: 'max_sources_per_run', label: 'Maksimal sumber per pencarian', min: 1, max: 30, hint: 'Jumlah sumber yang boleh diproses dalam satu pencarian otomatis.' },
  { key: 'max_new_sources_per_run', label: 'Maksimal sumber baru per pencarian', min: 0, max: 30, hint: 'Isi 0 untuk tidak menambahkan sumber baru. Tidak melebihi batas sumber di atas.' },
  { key: 'max_pages_per_source', label: 'Maksimal halaman per sumber', min: 1, max: 10, hint: 'Batas pengambilan halaman untuk satu sumber.' },
  { key: 'max_images_per_post', label: 'Maksimal gambar per postingan', min: 0, max: 5, hint: 'Isi 0 untuk melewati pembacaan gambar.' },
  { key: 'provider_daily_request_limit', label: 'Batas request provider per hari', min: 0, max: 10000, hint: 'Total untuk provider otomatisasi yang memakai kuota/biaya. Bawaan: 0.' },
]

export default function AutomationSettings() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [draft, setDraft] = useState<Controls | null>(null)
  const [loading, setLoading] = useState(true), [saving, setSaving] = useState(false)
  const [error, setError] = useState(''), [message, setMessage] = useState('')
  function apply(data: Snapshot) { setSnapshot(data); setDraft(data.settings) }
  async function load() {
    setLoading(true); setError(''); setMessage('')
    try { apply(await api<Snapshot>('/automation')) }
    catch (err) { setError(err instanceof Error ? err.message : 'Pengaturan belum dapat dibaca.') }
    finally { setLoading(false) }
  }
  useEffect(() => { void load() }, [])
  useEffect(() => {
    let disposed = false
    const timer = setInterval(() => {
      api<Snapshot>('/automation').then(data => { if (!disposed) setSnapshot(previous => previous ? { ...previous, runtime: data.runtime } : previous) }).catch(() => {})
    }, 10000)
    return () => { disposed = true; clearInterval(timer) }
  }, [])
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!draft || !snapshot) return
    setSaving(true); setError(''); setMessage('')
    try {
      apply(await api<Snapshot>('/automation', 'PUT', { settings: draft, expected_version: snapshot.version }))
      setMessage(draft.enabled ? 'Otomatisasi diaktifkan. Scheduler akan memproses jadwal jika prosesnya berjalan.' : 'Otomatisasi dijeda. Tidak ada job otomatis baru yang dibuat.')
    } catch (err) { setError(err instanceof Error ? err.message : 'Gagal menyimpan pengaturan.') }
    finally { setSaving(false) }
  }
  return <div className="panel" aria-labelledby="automation-title">
    <h2 id="automation-title">Otomatisasi · Tahap 6</h2>
    <p className="muted">Monitoring website/RSS dan discovery kandidat baru dijalankan scheduler/worker sesuai konfigurasi.</p>
    {error && <div className="notice error" role="alert">{error} <button disabled={saving || loading} onClick={() => void load()}>Muat ulang konfigurasi</button></div>}
    {message && <p className="notice" role="status">{message}</p>}
    {loading ? <p role="status">Memuat konfigurasi otomatisasi…</p> : draft && snapshot && <>
      <div className="notice" role="status"><strong>{({ disabled: 'Otomatisasi nonaktif', waiting_scheduler: 'Aktif · scheduler belum terdeteksi', waiting: 'Aktif · menunggu jadwal', busy: 'Aktif · menunggu job sebelumnya', no_sources: 'Belum ada website/RSS yang dapat dijadwalkan', enqueued: 'Job otomatis masuk antrean' } as Record<string, string>)[snapshot.runtime.state] || snapshot.runtime.state}</strong><p>{snapshot.runtime.message}</p>
        <p>Jadwal berikutnya: {snapshot.runtime.next_run_at ? dateTime(snapshot.runtime.next_run_at) : 'Belum dijadwalkan'}</p>
        <p>Heartbeat scheduler: {dateTime(snapshot.runtime.last_tick_at)}</p>
        <p>Job otomatis terakhir: {snapshot.runtime.last_job_id ? `#${snapshot.runtime.last_job_id} · ${dateTime(snapshot.runtime.last_enqueued_at)}` : 'Belum ada'}</p>
        {!snapshot.runtime.scheduler_online && snapshot.settings.enabled && <p>Jalankan proses scheduler dan worker di server. Status diperbarui setiap 10 detik.</p>}
      </div>
      <form onSubmit={event => void save(event)}>
        <fieldset disabled={saving} className="automation-fields">
          <label className="check"><input type="checkbox" checked={draft.enabled} onChange={e => setDraft({ ...draft, enabled: e.target.checked })} />Aktifkan otomatisasi website/RSS</label>
          {limits.map(field => <label key={field.key}>{field.label}<input type="number" required min={field.key === 'provider_daily_request_limit' && draft.allow_paid_providers ? 1 : field.min} max={field.key === 'max_new_sources_per_run' ? draft.max_sources_per_run : field.max} step="1" value={Number.isFinite(draft[field.key]) ? String(draft[field.key]) : ''} onChange={e => setDraft({ ...draft, [field.key]: e.target.value === '' ? NaN : Number(e.target.value) })} /><small className="muted">{field.hint}</small></label>)}
          <label className="check"><input type="checkbox" checked={draft.allow_paid_providers} onChange={e => setDraft({ ...draft, allow_paid_providers: e.target.checked })} />Izinkan provider berbayar untuk otomatisasi</label>
          <label>Anggaran provider per hari (USD)<input type="number" required min={draft.allow_paid_providers ? '0.01' : '0'} max="1000" step="0.01" value={draft.provider_daily_budget_usd} onChange={e => setDraft({ ...draft, provider_daily_budget_usd: e.target.value })} /><small className="muted">Bawaan: USD 0.00. Izin berbayar memerlukan anggaran dan batas request di atas nol.</small></label>
          <p className="muted">Instagram: hanya akun publik media lomba dan penyelenggara. Akun pribadi tidak dipantau otomatis.</p>
        </fieldset>
        <p className="muted">Tahap 6 menerapkan batas sumber/halaman dan reservasi kuota request serta anggaran estimasi provider bersama Brave/Instagram per hari UTC. Artikel website yang lolos verifikasi otomatis dipantau dalam batas sumber baru. Batas gambar diterapkan pada OCR website dan carousel Instagram. Cari sekarang tetap memakai alur manual sebelumnya.</p>
        <button className="primary" disabled={saving}>{saving ? 'Menyimpan…' : 'Simpan otomatisasi'}</button>
      </form>
      {snapshot.settings.enabled && <button className="subtle" disabled={saving} onClick={async () => {
        setSaving(true); setError(''); setMessage('')
        try { apply(await api<Snapshot>('/automation', 'PUT', { settings: { ...snapshot.settings, enabled: false }, expected_version: snapshot.version })); setMessage('Otomatisasi dijeda. Job terjadwal akan melewati sumber berikutnya; job manual tetap berjalan.') }
        catch (err) { setError(err instanceof Error ? err.message : 'Gagal menjeda otomatisasi.') }
        finally { setSaving(false) }
      }}>Jeda otomatisasi</button>}
      <p className="muted">Terakhir disimpan: {dateTime(snapshot.updated_at)} · versi {snapshot.version}</p>
      <h3>Kesiapan integrasi</h3>
      <p className="muted">Pemeriksaan konfigurasi lokal, tanpa memanggil provider. Credential dan kuota belum diverifikasi.</p>
      {Object.entries({ discovery: 'Discovery web', instagram: 'Instagram', ocr: 'OCR poster', ai: 'Model AI' }).map(([key, label]) => <p key={key}>{label}: <b>{snapshot.runtime.providers[key]?.configured ? 'Dikonfigurasi di server' : 'Belum terhubung'}</b></p>)}
    </>}
  </div>
}
