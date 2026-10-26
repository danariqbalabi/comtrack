export type HealthResponse = {
  status: 'ok'
  service: string
  environment: string
}

const baseUrl = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '')

export async function getHealth(signal: AbortSignal): Promise<HealthResponse> {
  const response = await fetch(`${baseUrl}/health`, {
    signal,
    cache: 'no-store',
  })

  if (!response.ok) throw new Error(`Backend merespons HTTP ${response.status}.`)

  const data: unknown = await response.json()
  if (
    typeof data !== 'object' || data === null ||
    !('status' in data) || data.status !== 'ok' ||
    !('service' in data) || typeof data.service !== 'string' ||
    !('environment' in data) || typeof data.environment !== 'string'
  ) throw new Error('Respons kesehatan backend tidak sesuai.')

  return data as HealthResponse
}
