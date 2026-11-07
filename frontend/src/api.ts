export type Timeline = { kind: string; label: string | null; raw_text: string; date: string | null; needs_review: boolean; timezone: string | null }
export type Competition = {
  id: number; first_seen_at: string; last_checked_at: string; version: number
  data: {
    name: string; category: string; organizer: string | null; edition: string | null; summary: string | null
    format: string; location: string | null; eligibility: string | null; team_raw: string | null
    registration_status: string; relevance_status: string; relevance_reasons: string[]; warnings: string[]
    source_url: string; registration_url: string | null; guidebook_url: string | null; official_url: string | null
    timeline: Timeline[]; fees: { raw_text: string; amount: string | null; currency: string | null; basis: string }[]
    prizes: { description: string }[]; conflicts: Record<string, unknown>[]
  }
}
export type Job = { id: number; status: string; trigger: 'manual' | 'scheduled'; requested_at: string; sources: { id: number; source_name: string; status: string; error: string | null }[]; logs: { id: number; message: string; created_at: string }[] }
export type Feed = { items: Competition[]; total: number; offset: number; limit: number }
const base = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '')
export async function api<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(`${base}${path}`, { method, cache: 'no-store', credentials: 'same-origin', signal: AbortSignal.timeout(15000),
    headers: method === 'GET' ? {} : { 'Content-Type': 'application/json', 'X-Lomba-Radar': '1' },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}) })
  if (!response.ok) {
    const error = await response.json().catch(() => null) as { detail?: unknown } | null
    throw new Error(typeof error?.detail === 'string' ? error.detail : `Permintaan gagal (HTTP ${response.status}).`)
  }
  return response.json() as Promise<T>
}
export function safeLink(url: string | null | undefined): string | undefined {
  try { const parsed = new URL(url || ''); return /^https?:$/.test(parsed.protocol) ? parsed.href : undefined } catch { return undefined }
}
export function dateTime(value: string | null | undefined): string {
  return value ? new Date(value).toLocaleString('id-ID', { dateStyle: 'medium', timeStyle: 'short' }) : 'Belum pernah'
}
export function deadline(row: Competition): string {
  return row.data.timeline.filter(item => item.kind === 'registration').map(item => item.raw_text).join(' · ') || 'Deadline belum tercantum'
}
