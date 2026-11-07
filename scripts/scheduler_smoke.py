"""Opt-in real OU Festival check, separate scheduler/worker, disposable database, no frontend."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from backend.app.automation import AutomationSettings, AutomationStore
from backend.app.config import ROOT
from backend.app.database import Database
from backend.app.job_queue import JobQueue
from backend.app.jobs import register_ou
from backend.app.repository import Repository


def main():
    runtime = ROOT/'data'
    runtime.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=runtime,prefix='scheduler-smoke-') as folder:
        database = Database(Path(folder)/'radar.db')
        database.migrate()
        repository = Repository(database)
        register_ou(repository)
        store = AutomationStore(database)
        store.save(AutomationSettings(enabled=True,max_pages_per_source=1),expected_version=1)
        environment = {**os.environ,'DATABASE_PATH':str(database.path),'PYTHONIOENCODING':'utf-8',
                       'INSTAGRAM_PROVIDER_ENABLED':'false','DISCOVERY_PROVIDER_ENABLED':'false'}
        def command(module):
            return subprocess.run([sys.executable,'-m',module,'--once'],cwd=ROOT,env=environment,
                                  capture_output=True,text=True,check=True,timeout=180).stdout.strip()
        first = command('backend.app.scheduler')
        queue = JobQueue(database)
        initial = queue.latest()
        assert initial and initial['status']=='queued' and initial['trigger']=='scheduled'
        second = command('backend.app.scheduler')
        assert queue.latest()['id']==initial['id']
        worker = command('backend.app.worker')
        job = queue.latest()
        assert job['status']=='succeeded',job
        assert len(repository.list_competitions())==1
        version = store.get()['version']
        store.save(AutomationSettings(enabled=False),expected_version=version)
        paused = command('backend.app.scheduler')
        assert queue.latest()['id']==job['id']
        assert store.schedule()['next_run_at'] is None
        with database.connection() as conn:
            assert not conn.execute('PRAGMA foreign_key_check').fetchall()
            assert conn.execute('SELECT count(*) FROM collection_jobs').fetchone()[0]==1
        report = {'frontend_opened':False,'api_started':False,'trigger':job['trigger'],'status':job['status'],
                  'result':job['summary']['results'][0], 'scheduler_first':first,'scheduler_restart':second,
                  'worker':worker,'paused':paused,'duplicate_jobs':False}
        (runtime/'scheduler-smoke-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=True,indent=2))


if __name__=='__main__':
    main()
