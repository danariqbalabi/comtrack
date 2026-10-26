import { useEffect, useState } from 'react'
type InstallEvent = Event & { prompt: () => Promise<void>; userChoice: Promise<{ outcome: string }> }
export default function Pwa() {
  const [offline, setOffline] = useState(!navigator.onLine), [install, setInstall] = useState<InstallEvent | null>(null)
  useEffect(() => {
    const online = () => setOffline(!navigator.onLine)
    const prompt = (event: Event) => { event.preventDefault(); setInstall(event as InstallEvent) }
    const installed = () => setInstall(null)
    addEventListener('online', online); addEventListener('offline', online); addEventListener('beforeinstallprompt', prompt); addEventListener('appinstalled', installed)
    if (import.meta.env.PROD && 'serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {})
    return () => { removeEventListener('online', online); removeEventListener('offline', online); removeEventListener('beforeinstallprompt', prompt); removeEventListener('appinstalled', installed) }
  }, [])
  return <>{offline && <div className="notice" role="status">Lo sedang offline. Pencarian dan data terbaru memerlukan koneksi ke server.</div>}{install && <button className="install" onClick={() => { void install.prompt().then(() => install.userChoice).then(() => setInstall(null)) }}>＋ Pasang Lomba Radar</button>}</>
}
