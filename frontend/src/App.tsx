import { useCallback, useEffect, useRef, useState } from 'react'
import { api, dateTime, deadline, safeLink, type Competition, type Feed, type Job } from './api'
import Detail from './Detail'
import Settings from './Settings'

const statuses: Record<string, string> = { queued: 'Menunggu worker', running: 'Sedang mencari', succeeded: 'Pencarian selesai', partial: 'Sebagian sumber berhasil', failed: 'Pencarian gagal', cancelled: 'Dibatalkan', open: 'Pendaftaran terbuka', closed: 'Pendaftaran tutup', upcoming: 'Segera dibuka', unknown: 'Tanggal perlu dicek' }

export default function App() {
  const [route, setRoute] = useState(location.hash)
  useEffect(() => { const change = () => { setRoute(location.hash); window.scrollTo(0, 0) }; addEventListener('hashchange', change); return () => removeEventListener('hashchange', change) }, [])
  const match = route.match(/^#competition\/(\d+)$/)
  if (route === '#settings') return <div className="shell"><header><a className="brand" href="#">◎ Lomba Radar</a><a href="#">← Feed lomba</a></header><main><Settings /></main></div>
  if (match) return <div className="shell"><header><a className="brand" href="#">◎ Lomba Radar</a><a href="#">← Feed lomba</a></header><main><Detail id={Number(match[1])} /></main></div>
  return <FeedPage />
}

function FeedPage() {
  const requestSequence = useRef(0)
  const [category, setCategory] = useState(''), [query, setQuery] = useState(''), [sort, setSort] = useState('newest')
  const [page, setPage] = useState(0), [feed, setFeed] = useState<Feed | null>(null), [job, setJob] = useState<Job | null>(null)
  const [loading, setLoading] = useState(true), [sending, setSending] = useState(false), [error, setError] = useState('')
  const load = useCallback(async () => {
    const sequence = ++requestSequence.current
    setLoading(true)
    try {
      const params = new URLSearchParams({ q: query, sort, offset: String(page * 30) })
      if (category) params.set('category', category)
      const result = await api<Feed>(`/competitions?${params}`)
      if (sequence === requestSequence.current) { setFeed(result); setError('') }
    } catch (err) { if (sequence === requestSequence.current) setError(err instanceof Error ? err.message : 'Backend belum terhubung.') }
    finally { if (sequence === requestSequence.current) setLoading(false) }
  }, [query, category, sort, page])
  useEffect(() => { const timer = setTimeout(() => void load(), 250); return () => clearTimeout(timer) }, [load])
  useEffect(() => { api<{ job: Job | null }>('/jobs/latest').then(result => setJob(result.job)).catch(() => {}) }, [])
  const active = job?.status === 'queued' || job?.status === 'running'
  useEffect(() => {
    if (!active || !job) return
    let disposed = false
    const timer = setInterval(() => {
      api<Job>(`/jobs/${job.id}`).then(result => {
        if (disposed) return
        setJob(result)
        if (!['queued', 'running'].includes(result.status)) void load()
      }).catch(err => { if (!disposed) setError(String(err)) })
    }, 2000)
    return () => { disposed = true; clearInterval(timer) }
  }, [active, job?.id, load])
  async function refresh() {
    setSending(true); setError('')
    try { setJob((await api<{ job: Job }>('/refresh', 'POST', {})).job) }
    catch (err) { setError(err instanceof Error ? err.message : 'Permintaan gagal.') }
    finally { setSending(false) }
  }
  return <div className="shell">
    <header><a className="brand" href="#"><span className="radar" aria-hidden="true">◎</span>Lomba Radar <small>PERSONAL</small></a><nav aria-label="Navigasi utama"><a href="#">Feed lomba</a><a href="#settings">Pengaturan</a></nav></header>
    <main><section className="hero"><div><p className="eyebrow">INDONESIA · UNTUK MAHASISWA</p><h1>Peluang berikutnya,<br /><em>ada di radar lo.</em></h1><p className="intro">Hackathon, business case, dan business plan competition.<br />Sumber asli, informasi jelas, semua di satu tempat.</p></div><div className="search-action"><button className="primary" disabled={sending || active} onClick={() => void refresh()}>{sending || active ? '◌ Memproses…' : '↻ Cari sekarang'}</button><small>Pencarian manual kapan saja.</small></div></section>
    {error && <div className="notice error" role="alert">{error} <button onClick={() => void load()}>Coba lagi</button></div>}
    {job && <section className="notice job" role="status"><div><strong>{statuses[job.status] || job.status}</strong><small>{job.trigger === 'scheduled' ? 'Otomatis terjadwal' : 'Permintaan manual'} · {dateTime(job.requested_at)} · #{job.id}</small>{job.status === 'queued' && <small>Menunggu worker di server.</small>}</div><details><summary>Aktivitas sumber</summary>{job.sources.map(source => <p key={source.id}><b>{source.source_name}</b> · {source.status}{source.error && <span className="error-text">{source.error}</span>}</p>)}{job.logs.slice(-8).map(log => <small key={log.id}>{dateTime(log.created_at)} — {log.message}</small>)}</details></section>}
    <section aria-label="Daftar lomba"><div className="section-heading"><div><p className="eyebrow">PANTAU PELUANG</p><h2>Lomba di radar <span className="count">{feed?.total ?? '—'}</span></h2></div><label>Urutan <select value={sort} onChange={e => { setSort(e.target.value); setPage(0) }}><option value="newest">Baru ditemukan</option><option value="deadline">Deadline terdekat</option></select></label></div>
    <div className="filters"><div className="tabs">{[['', 'Semua'], ['hackathon', 'Hackathon'], ['BCC', 'Business case'], ['BPC', 'Business plan']].map(([value, label]) => <button key={value} aria-pressed={category === value} className={category === value ? 'active' : ''} onClick={() => { setCategory(value); setPage(0) }}>{label}</button>)}</div><input className="query" aria-label="Cari nama lomba atau penyelenggara" placeholder="⌕ Cari nama lomba…" value={query} onChange={e => { setQuery(e.target.value); setPage(0) }} /></div>
    {loading ? <p className="empty" role="status">Memuat radar…</p> : !feed?.items.length ? <div className="empty"><span className="empty-icon" aria-hidden="true">◎</span><h3>{query || category ? 'Belum ada yang cocok.' : 'Radar siap, mulai cari peluang.'}</h3><p>{query || category ? 'Coba kata kunci atau kategori lain.' : 'Tambahkan sumber di Pengaturan, lalu tekan Cari sekarang.'}</p><a href="#settings">Atur sumber pantauan →</a></div> : <div className="grid">{feed.items.map(row => <CompetitionCard key={row.id} row={row} />)}</div>}
    {!!feed && feed.total > 30 && <div className="pagination"><button disabled={!page} onClick={() => setPage(page - 1)}>← Sebelumnya</button><span>{page + 1} / {Math.ceil(feed.total / 30)}</span><button disabled={(page + 1) * 30 >= feed.total} onClick={() => setPage(page + 1)}>Berikutnya →</button></div>}
    </section></main><footer><span>◎ Lomba Radar</span><span>Periksa ketentuan terbaru di sumber asli.</span></footer>
  </div>
}

function CompetitionCard({ row }: { row: Competition }) {
  const data = row.data
  return <article className="card"><div className="card-top"><span className="badge">{data.category}</span><span className="status">{statuses[data.registration_status]}</span></div><p className="organizer">{data.organizer || 'Penyelenggara belum tercantum'}</p><h3><a href={`#competition/${row.id}`}>{data.name}</a></h3><p className="description">{data.summary || 'Buka sumber asli untuk ketentuan lomba.'}</p><div className="deadline"><small>PENDAFTARAN</small><p>{deadline(row)}</p></div><div className="facts"><span>{data.format === 'unknown' ? 'Format belum tercantum' : data.format}</span><span>{data.fees.length ? 'Biaya per tahap di detail' : 'Biaya belum tercantum'}</span></div>{data.relevance_status === 'needs_review' && <p className="review">Syarat perlu dicek</p>}<div className="card-bottom"><small>Ditemukan {dateTime(row.first_seen_at)}</small><a href={safeLink(data.source_url)} target="_blank" rel="noreferrer">Sumber asli ↗</a></div></article>
}
