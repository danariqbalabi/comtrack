import { useEffect, useState } from 'react'
import { api, dateTime, safeLink, type Competition } from './api'
type DetailData = { competition: Competition; evidence: { id: number; url: string; raw_text: string; content_hash: string; fetched_at: string; last_seen_at: string }[]; history: { id: number; version: number; recorded_at: string; changes: Record<string, unknown> }[] }
export default function Detail({ id }: { id: number }) {
  const [result, setResult] = useState<DetailData | null>(null), [error, setError] = useState(''), [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let disposed = false
    setResult(null); setError('')
    api<DetailData>(`/competitions/${id}`).then(data => { if (!disposed) setResult(data) }).catch(err => { if (!disposed) setError(String(err)) })
    return () => { disposed = true }
  }, [id, attempt])
  if (error) return <div className="notice error" role="alert">{error} <button onClick={() => setAttempt(attempt + 1)}>Coba lagi</button></div>
  if (!result) return <p role="status" className="empty">Memuat detail…</p>
  const { competition: row, evidence, history } = result, data = row.data
  return <section className="detail"><p className="eyebrow">{data.category} · {data.edition || 'EDISI BELUM TERCANTUM'}</p><h1>{data.name}</h1><p className="intro">{data.organizer || 'Penyelenggara belum tercantum'}</p><div className="actions"><External url={data.source_url}>Sumber asli ↗</External><External url={data.registration_url}>Pendaftaran ↗</External><External url={data.guidebook_url}>Guidebook ↗</External></div>
  {!!data.relevance_reasons.length && <div className="notice">{data.relevance_reasons.join(' · ')}</div>}{!!data.warnings.length && <div className="notice">{data.warnings.join(' · ')}</div>}
  <div className="detail-grid"><div className="panel"><h2>Tentang lomba</h2><p>{data.summary || 'Ringkasan belum tercantum.'}</p><dl>{[['Eligibility', data.eligibility], ['Anggota tim', data.team_raw], ['Format', data.format === 'unknown' ? null : data.format], ['Lokasi', data.location]].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value || 'Belum tercantum'}</dd></div>)}</dl></div><div className="panel"><h2>Timeline</h2>{!data.timeline.length && <p>Belum tercantum.</p>}{data.timeline.map((entry, index) => <div className="timeline-item" key={index}><b>{entry.label || ({ registration: 'Pendaftaran', submission: 'Pengumpulan', final: 'Final', event: 'Pelaksanaan' } as Record<string, string>)[entry.kind] || 'Tahap lain'}</b><p>{entry.raw_text}</p><small>{entry.timezone || 'Zona waktu belum tercantum'}{entry.needs_review && ' · Tanggal perlu dicek'}</small></div>)}</div>
  <div className="panel"><h2>Biaya & hadiah</h2><h3>Biaya</h3>{data.fees.length ? data.fees.map((fee, i) => <p key={i}>{fee.raw_text}<small className="muted">Basis: {fee.basis === 'unknown' ? 'belum tercantum' : fee.basis === 'team' ? 'per tim' : 'per orang'}</small></p>) : <p>Belum tercantum.</p>}<h3>Hadiah</h3>{data.prizes.length ? data.prizes.map((prize, i) => <p key={i}>{prize.description}</p>) : <p>Belum tercantum.</p>}</div><div className="panel"><h2>Catatan radar</h2><p>Ditemukan: {dateTime(row.first_seen_at)}</p><p>Terakhir dicek: {dateTime(row.last_checked_at)}</p><p>Versi data: {row.version}</p><p>Status pendaftaran: {data.registration_status}</p><p className="muted">Waktu ditemukan mengacu ke pengamatan radar. Pastikan syarat dan perubahan terbaru lewat sumber asli.</p></div></div>
  {!!data.conflicts.length && <div className="panel"><h2>Konflik informasi</h2>{data.conflicts.map((conflict, i) => <details key={i}><summary>Perbedaan sumber #{i + 1}</summary><pre>{JSON.stringify(conflict, null, 2)}</pre></details>)}</div>}
  <div className="panel"><h2>Sumber & bukti</h2>{evidence.length ? evidence.map(item => <details key={item.id}><summary>Diamati {dateTime(item.last_seen_at)} · bukti #{item.id}</summary><p><External url={item.url}>{item.url} ↗</External></p><p className="muted">Diambil {dateTime(item.fetched_at)}</p><blockquote>{item.raw_text}</blockquote><small className="muted">SHA-256: {item.content_hash}</small></details>) : <p>Belum ada bukti tersimpan.</p>}</div>
  <div className="panel"><h2>Riwayat perubahan</h2>{history.map(item => <details key={item.id}><summary>Versi {item.version} · {dateTime(item.recorded_at)}</summary><pre>{JSON.stringify(item.changes, null, 2)}</pre></details>)}</div></section>
}
function External({ url, children }: { url: string | null; children: React.ReactNode }) {
  const href = safeLink(url)
  return href ? <a className="external" href={href} target="_blank" rel="noreferrer">{children}</a> : null
}
