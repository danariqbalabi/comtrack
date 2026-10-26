"""Opt-in end-to-end test using one real website and a disposable database."""
import base64
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'data' / 'qa-tools'))
from playwright.sync_api import sync_playwright


def main():
    password = secrets.token_urlsafe(24)
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0)); port = probe.getsockname()[1]
    base = f'http://127.0.0.1:{port}'
    headers = {'Authorization': 'Basic ' + base64.b64encode(f'radar:{password}'.encode()).decode()}
    report = {}
    with tempfile.TemporaryDirectory(dir=ROOT / 'data', prefix='qa-real-') as folder:
        database = Path(folder) / 'radar.db'
        env = {**os.environ, 'APP_ENV':'production', 'DATABASE_PATH':str(database), 'ACCESS_USERNAME':'radar',
               'ACCESS_PASSWORD':password, 'API_ALLOWED_ORIGINS':base, 'DISCOVERY_PROVIDER_ENABLED':'false', 'INSTAGRAM_PROVIDER_ENABLED':'false'}
        log = (ROOT / 'data' / 'browser-qa.log').open('w', encoding='utf-8')
        server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'backend.app.main:app', '--host', '127.0.0.1', '--port', str(port)], cwd=ROOT, env=env, stdout=log, stderr=log)
        try:
            for _ in range(80):
                try:
                    with urllib.request.urlopen(urllib.request.Request(base + '/api/health', headers=headers), timeout=2) as response:
                        if response.status == 200: break
                except OSError: time.sleep(.25)
            else: raise RuntimeError('Server startup failed')
            with sync_playwright() as playwright:
                executable = os.getenv('BROWSER_EXECUTABLE')
                if not executable:
                    executable = r'C:\Program Files\Google\Chrome\Application\chrome.exe' if os.name == 'nt' else shutil.which('google-chrome') or shutil.which('chromium')
                browser = playwright.chromium.launch(executable_path=executable, headless=True)
                context = browser.new_context(http_credentials={'username':'radar', 'password':password}, viewport={'width':1440,'height':1000})
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(base)
                page.get_by_text('Radar siap, mulai cari peluang.').wait_for()
                page.get_by_role('link', name='Pengaturan', exact=True).click()
                page.get_by_role('button', name='+ Pakai sumber OU Festival yang sudah teruji', exact=True).click()
                page.get_by_text('Sumber OU Festival ditambahkan.', exact=True).wait_for()
                page.get_by_role('link', name='← Feed lomba', exact=True).click()
                page.get_by_role('button', name='↻ Cari sekarang', exact=True).click()
                page.get_by_text('Menunggu worker', exact=True).wait_for()
                subprocess.run([sys.executable, '-m', 'backend.app.worker', '--once'], cwd=ROOT, env=env, capture_output=True, timeout=180, check=True)
                page.get_by_text('Pencarian selesai', exact=True).wait_for(timeout=15000)
                page.locator('.card').first.wait_for()
                assert page.locator('.card').count() == 1
                page.screenshot(path=str(ROOT / 'data' / 'feed-desktop.png'), full_page=True)
                title = page.locator('.card h3').inner_text()
                page.locator('.card h3 a').click()
                page.get_by_role('heading', name='Sumber & bukti', exact=True).wait_for()
                assert page.get_by_role('link', name='Sumber asli ↗', exact=True).get_attribute('href').startswith('https://ou-festival.com/')
                page.screenshot(path=str(ROOT / 'data' / 'detail-desktop.png'), full_page=True)
                page.get_by_role('link', name='← Feed lomba', exact=True).click()
                page.get_by_label('Cari nama lomba atau penyelenggara').fill('tidak-ada-hasil')
                page.get_by_text('Belum ada yang cocok.', exact=True).wait_for()
                page.get_by_label('Cari nama lomba atau penyelenggara').fill('')
                page.locator('.card').first.wait_for()
                page.get_by_role('button', name='Hackathon', exact=True).click()
                page.get_by_text('Belum ada yang cocok.', exact=True).wait_for()
                page.get_by_role('button', name='Semua', exact=True).click()
                page.locator('.card').first.wait_for()
                page.get_by_role('link', name='Pengaturan', exact=True).click()
                page.get_by_label('Sembunyikan pendaftaran yang tutup', exact=True).uncheck()
                page.get_by_role('button', name='Simpan preferensi', exact=True).click()
                page.get_by_text('Preferensi disimpan.', exact=True).wait_for()
                page.reload()
                page.get_by_role('heading', name='Preferensi relevansi', exact=True).wait_for()
                assert not page.get_by_label('Sembunyikan pendaftaran yang tutup', exact=True).is_checked()
                page.goto(base)
                page.evaluate("navigator.serviceWorker.ready")
                cached = page.evaluate("caches.keys().then(keys => Promise.all(keys.map(key => caches.open(key).then(cache => cache.keys().then(items => items.map(item => item.url))))))")
                assert not any('/api/' in url for group in cached for url in group)
                context.set_offline(True)
                page.reload()
                page.get_by_text('Lo sedang offline.', exact=False).wait_for()
                context.set_offline(False)
                mobile = browser.new_context(http_credentials={'username':'radar', 'password':password}, viewport={'width':390,'height':844}, is_mobile=True, device_scale_factor=1)
                phone = mobile.new_page(); phone.goto(base)
                phone.locator('.card').first.wait_for()
                assert phone.evaluate('document.documentElement.scrollWidth <= innerWidth')
                phone.screenshot(path=str(ROOT / 'data' / 'feed-mobile.png'), full_page=True)
                phone.get_by_role('link', name='Pengaturan', exact=True).click()
                phone.get_by_role('heading', name='Referensi sumber (38)', exact=True).wait_for()
                assert phone.evaluate('document.documentElement.scrollWidth <= innerWidth')
                phone.screenshot(path=str(ROOT / 'data' / 'settings-mobile.png'), full_page=True)
                assert not errors, errors
                report = {'title':title, 'source':'OU Festival live', 'desktop':'passed', 'mobile':'passed', 'offline_shell':'passed', 'settings_persistence':'passed', 'api_cached':False, 'console_errors':errors}
                browser.close()
        finally:
            server.terminate(); server.wait(timeout=15); log.close()
    (ROOT / 'data' / 'browser-qa-result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__': main()
