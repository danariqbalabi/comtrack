"""Production API/static/auth startup in an isolated database. No external provider calls."""
import base64
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError,URLError
from urllib.request import Request,urlopen

from backend.app.config import ROOT
from backend.app.database import Database


def main():
    if not (ROOT/'frontend/dist/index.html').is_file():raise SystemExit('Build frontend dahulu: npm.cmd --prefix frontend run build')
    runtime=ROOT/'data';runtime.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=runtime,prefix='system-smoke-') as folder:
        path=Path(folder)/'radar.db'
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        password='fixture-production-password-32chars'
        env={**os.environ,'DATABASE_PATH':str(path),'APP_ENV':'production','ACCESS_USERNAME':'fixture','ACCESS_PASSWORD':password,
            'DISCOVERY_PROVIDER_ENABLED':'false','BRAVE_API_KEY':'','INSTAGRAM_PROVIDER_ENABLED':'false','APIFY_TOKEN':'',
            'AI_ENABLED':'false','OCR_ENABLED':'false','API_ALLOWED_ORIGINS':f'http://127.0.0.1:{port}'}
        base=f'http://127.0.0.1:{port}'
        token=base64.b64encode(('fixture:'+password).encode()).decode()
        def request(path,*,auth=True,method='GET',body=None,header=True):
            headers={'Authorization':'Basic '+token} if auth else {}
            if header:headers['X-Lomba-Radar']='1'
            if body is not None:headers['Content-Type']='application/json'
            req=Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers=headers,method=method)
            try:
                with urlopen(req,timeout=5) as response:return response.status,response.read(),dict(response.headers)
            except HTTPError as error:return error.code,error.read(),dict(error.headers)
        with (Path(folder)/'server.log').open('wb') as log:
            child=subprocess.Popen([sys.executable,'-m','uvicorn','backend.app.main:app','--host','127.0.0.1','--port',str(port),'--no-proxy-headers'],
                cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            try:
                for _ in range(100):
                    if child.poll() is not None:raise RuntimeError('Server fixture berhenti sebelum siap.')
                    try:
                        status,body,_=request('/api/health')
                        if status==200:break
                    except (URLError,OSError):pass
                    time.sleep(.1)
                else:raise RuntimeError('Server fixture tidak siap dalam batas waktu.')
                schema=json.loads(body)['schema_version']
                assert request('/api/health',auth=False)[0]==401
                assert request('/',auth=False)[0]==401
                status,html,_=request('/');assert status==200 and b'<html' in html.lower()
                assert request('/api/competitions')[0]==200
                assert request('/api/automation/activity')[0]==200
                assert request('/api/instagram/candidates')[0]==200
                assert request('/api/refresh',method='POST',body={},header=False)[0]==403
                assert request('/api/refresh',method='POST',body={})[0]==409
                assert request('/api/unknown-route')[0]==404
                report={'test':'isolated production HTTP smoke','schema':schema,'basic_auth':True,'static_frontend':True,'write_guard':True,
                    'activity_api':True,'external_provider_calls':0,'main_database_modified':False}
            finally:
                child.terminate()
                try:child.wait(timeout=10)
                except subprocess.TimeoutExpired:child.kill();child.wait(timeout=5)
        database=Database(path)
        with database.connection() as conn:
            assert conn.execute('SELECT count(*) FROM collection_jobs').fetchone()[0]==0
            assert not conn.execute('PRAGMA foreign_key_check').fetchall()
        (runtime/'system-smoke-result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report,indent=2))


if __name__=='__main__':main()
