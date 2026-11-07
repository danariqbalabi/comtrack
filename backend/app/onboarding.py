"""Fenced website subscription after ingestion; quota and decisions are atomic."""
from datetime import datetime, timezone

from .automation import AutomationSettings
from .collectors.discovered import ADAPTER
from .collectors.http import FetchError
from .discovery import normalize_candidate
from .models import Preferences
from .quality.dates import deadline_passed
from .quality.prepare import prepare
from .quality.relevance import evaluate
from .repository import encode, competition_record

SOCIAL = ('instagram.com','facebook.com','tiktok.com','x.com','twitter.com','youtube.com')


def qualify(queue, job_id, token, source, item, saved, candidate_key):
    """No network here. Only an automatic discovery observation with stored proof qualifies."""
    snapshot = queue.automation_settings(job_id)
    if snapshot is None or source['adapter'] != 'brave_discovery':
        return None
    now = datetime.now(timezone.utc)
    stamp = now.isoformat()
    with queue.database.transaction() as conn:
        queue.source_guard(conn, job_id, token, source)
        candidate = conn.execute('SELECT * FROM discovery_candidates WHERE canonical_key=?', (candidate_key,)).fetchone()
        if candidate is None:
            return None

        def decision(status, reason, source_id=None):
            conn.execute('''UPDATE discovery_candidates SET onboarding_status=?,onboarding_reason=?,
                onboarding_checked_at=?,onboarded_source_id=? WHERE id=?''',
                (status,reason,stamp,source_id,candidate['id']))
            return {'status':status,'reason':reason,'source_id':source_id,'candidate_id':candidate['id']}

        if candidate['status'] != 'verified':
            return decision('held','Artikel belum berhasil diverifikasi.')
        try:
            url,key,domain = normalize_candidate(str(item.data.source_url))
        except (ValueError, FetchError):
            return decision('rejected','URL artikel tidak aman.')
        if any(domain == host or domain.endswith('.'+host) for host in SOCIAL):
            return decision('held','Sumber sosial media belum memenuhi klasifikasi akun lomba.')
        if domain != candidate['domain']:
            return decision('held','Domain tujuan berbeda dari kandidat; perlu diperiksa.')
        proof = conn.execute('SELECT id FROM evidence WHERE competition_id=? AND url=? AND content_hash=?',
                             (saved.id,str(item.data.source_url),item.content_hash)).fetchone()
        if not proof:
            return decision('held','Bukti observasi belum tersimpan.')
        preferences = Preferences.model_validate_json(conn.execute('SELECT data_json FROM preferences WHERE singleton=1').fetchone()[0])
        observation = evaluate(prepare(item.data),preferences,now=now)
        current = competition_record(conn.execute('SELECT * FROM competitions WHERE id=?',(saved.id,)).fetchone())
        assessed = evaluate(current.data,preferences,now=now)
        if observation.relevance_status == 'excluded':
            return decision('rejected',' '.join(observation.relevance_reasons))
        if observation.relevance_status != 'relevant' or assessed.relevance_status != 'relevant':
            return decision('held',' '.join(dict.fromkeys(observation.relevance_reasons+assessed.relevance_reasons)) or 'Kelayakan belum pasti.')
        if observation.content_kind != 'competition' or observation.registration_status == 'closed':
            return decision('held','Bukti pendaftaran lomba aktif belum cukup.')
        if not any(entry.kind=='registration' and deadline_passed(entry,now) is False for entry in observation.timeline):
            return decision('held','Tanggal akhir pendaftaran yang belum lewat belum terverifikasi.')

        # Preserve manually disabled sources and user configuration, including www/tracking aliases.
        for existing in conn.execute("SELECT id,url,enabled FROM sources WHERE kind='website'"):
            try:
                existing_key = normalize_candidate(existing['url'])[1]
            except (ValueError, FetchError):
                continue
            if key == existing_key:
                return decision('existing','Sumber sudah terdaftar; pilihan aktif/nonaktif dipertahankan.',existing['id'])
        current_settings = AutomationSettings.model_validate_json(conn.execute('SELECT data_json FROM automation_settings WHERE singleton=1').fetchone()[0])
        limit = min(snapshot.max_new_sources_per_run,current_settings.max_new_sources_per_run)
        used = conn.execute('SELECT count(*) FROM website_onboardings WHERE job_id=?',(job_id,)).fetchone()[0]
        if used >= limit:
            return decision('limited','Batas sumber baru per job tercapai; menunggu penemuan ulang.')
        if conn.execute('SELECT count(*) FROM sources').fetchone()[0] >= 30:
            return decision('limited','Batas total 30 sumber tercapai.')
        # If removed during this job, do not re-create it and consume quota twice.
        if conn.execute('SELECT 1 FROM website_onboardings WHERE job_id=? AND canonical_key=?',(job_id,key)).fetchone():
            return decision('held','Sumber ini sudah didaftarkan pada job ini; penghapusan dipertahankan.')
        cursor = conn.execute('''INSERT INTO sources(name,kind,url,adapter,config_json,enabled,created_at,updated_at)
            VALUES (?,'website',?,?,?,1,?,?)''',
            (observation.name,url,ADAPTER,encode({'mode':'single_article','version':1}),stamp,stamp))
        source_id = cursor.lastrowid
        conn.execute('INSERT INTO website_onboardings(job_id,candidate_id,source_id,canonical_key,created_at) VALUES (?,?,?,?,?)',
                     (job_id,candidate['id'],source_id,key,stamp))
        return decision('active','Artikel Indonesia sesuai preferensi, bukti tersimpan, deadline belum lewat; dipantau mulai job berikutnya.',source_id)
