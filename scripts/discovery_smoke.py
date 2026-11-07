"""Live free website plus unconfigured discovery fallback. Never calls a paid search API."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from backend.app.automation import AutomationSettings,AutomationStore
from backend.app.config import ROOT
from backend.app.database import Database
from backend.app.job_queue import JobQueue
from backend.app.jobs import register_ou
from backend.app.models import Preferences
from backend.app.repository import Repository


def main():
    runtime=ROOT/'data';runtime.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=runtime,prefix='discovery-smoke-') as folder:
        database=Database(Path(folder)/'radar.db');database.migrate()
        repository=Repository(database);register_ou(repository)
        repository.save_preferences(Preferences(discovery_enabled=True))
        AutomationStore(database).save(AutomationSettings(enabled=True,max_pages_per_source=1),expected_version=1)
        env={**os.environ,'DATABASE_PATH':str(database.path),'PYTHONIOENCODING':'utf-8',
             'DISCOVERY_PROVIDER_ENABLED':'false','BRAVE_API_KEY':'','BRAVE_COST_PER_REQUEST_USD':'',
             'INSTAGRAM_PROVIDER_ENABLED':'false'}
        for module in ('backend.app.scheduler','backend.app.worker'):
            subprocess.run([sys.executable,'-m',module,'--once'],cwd=ROOT,env=env,capture_output=True,text=True,check=True,timeout=180)
        job=JobQueue(database).latest()
        assert job['status']=='partial',job
        assert len(repository.list_competitions())==1
        assert next(source for source in repository.list_sources() if source.adapter=='brave_discovery').status=='not_connected'
        with database.connection() as conn:
            assert conn.execute('SELECT count(*) FROM provider_request_reservations').fetchone()[0]==0
        report={'trigger':job['trigger'],'status':job['status'],'website_competitions':1,
                'website':job['summary']['results'][0]['name'],'discovery':'not_connected','search_provider_called':False,
                'paid_reservations':0,'frontend_opened':False}
        (runtime/'discovery-smoke-result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report,indent=2))


if __name__=='__main__':
    main()
