"""Free Basic Search only: persistent one-credit reservations, independent of paid USD allowance."""
import json
from datetime import datetime,timezone
from .automation import AutomationSettings
from .discovery import DiscoveryBlocked
from .job_queue import SourceDisabledError
from .repository import encode


def usage(conn,now=None):
    now=now or datetime.now(timezone.utc);day=now.date().isoformat();month=day[:7]
    daily=conn.execute('SELECT COALESCE(sum(credits),0) FROM tavily_request_reservations WHERE day_utc=?',(day,)).fetchone()[0]
    monthly=conn.execute('SELECT COALESCE(sum(credits),0) FROM tavily_request_reservations WHERE month_utc=?',(month,)).fetchone()[0]
    return {'day_utc':day,'month_utc':month,'daily_reserved':daily,'monthly_reserved':monthly}


def pin(context,provider):
    with context.queue.database.transaction() as conn:
        context.guard(conn)
        # Old jobs/tests may have already made a Brave reservation before this upgrade.
        previous=conn.execute('SELECT provider FROM discovery_provider_runs WHERE job_source_id=?',(context.source['id'],)).fetchone()
        if previous is None and conn.execute('SELECT 1 FROM provider_request_reservations WHERE job_source_id=?',(context.source['id'],)).fetchone():
            conn.execute("INSERT INTO discovery_provider_runs VALUES (?,'brave')",(context.source['id'],))
            previous=('brave',)
        if previous and previous[0]!=provider:
            raise DiscoveryBlocked('Provider job sudah ditetapkan; jalankan job baru setelah mengganti provider, tanpa fallback berbayar otomatis.')
        conn.execute('INSERT OR IGNORE INTO discovery_provider_runs VALUES (?,?)',(context.source['id'],provider))


def authorize(context):
    with context.queue.database.transaction() as conn:
        context.guard(conn)
        if conn.execute('SELECT blocked FROM tavily_safety WHERE singleton=1').fetchone()[0]:
            raise SourceDisabledError('Tavily ditahan karena kontrak kredit berubah; perlu pemeriksaan integrasi.')
        settings=AutomationSettings.model_validate_json(conn.execute('SELECT data_json FROM automation_settings WHERE singleton=1').fetchone()[0])
        if not context.snapshot.tavily_free_enabled or not settings.tavily_free_enabled:
            raise SourceDisabledError('Tavily Free dijeda pada pengaturan.')


def reserve(context,index,query,*,now=None):
    if index<0 or index>=len(context.queries) or context.queries[index]!=query:raise ValueError('Query harus sesuai rencana tersimpan.')
    pin(context,'tavily')
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:raise ValueError('Waktu harus menyertakan zona waktu.')
    now=now.astimezone(timezone.utc)
    with context.queue.database.transaction() as conn:
        context.guard(conn)
        if conn.execute('SELECT blocked FROM tavily_safety WHERE singleton=1').fetchone()[0]:
            raise DiscoveryBlocked('Tavily ditahan karena kontrak kredit berubah; perlu pemeriksaan integrasi.')
        settings=AutomationSettings.model_validate_json(conn.execute('SELECT data_json FROM automation_settings WHERE singleton=1').fetchone()[0])
        if not context.snapshot.tavily_free_enabled or not settings.tavily_free_enabled:
            raise DiscoveryBlocked('Tavily Free dijeda pada pengaturan.')
        previous=conn.execute('SELECT * FROM tavily_request_reservations WHERE job_source_id=? AND query_index=?',(context.source['id'],index)).fetchone()
        if previous:
            if previous['status']=='succeeded':return json.loads(previous['results_json'])
            raise DiscoveryBlocked('Request Tavily sebelumnya gagal/tidak pasti; tidak dikirim ulang pada job yang sama.')
        used=usage(conn,now)
        if used['daily_reserved']>=min(context.snapshot.tavily_daily_credit_limit,settings.tavily_daily_credit_limit):
            raise DiscoveryBlocked('Batas kredit Tavily harian tercapai (UTC).')
        if used['monthly_reserved']>=min(context.snapshot.tavily_monthly_credit_limit,settings.tavily_monthly_credit_limit):
            raise DiscoveryBlocked('Batas kredit Tavily bulanan tercapai (UTC).')
        conn.execute("INSERT INTO tavily_request_reservations(job_source_id,query_index,day_utc,month_utc,status,created_at) VALUES (?,?,?,?,'reserved',?)",
            (context.source['id'],index,used['day_utc'],used['month_utc'],now.isoformat()))
    return None


def finish(context,index,results=None):
    with context.queue.database.transaction() as conn:
        context.guard(conn)
        conn.execute('''UPDATE tavily_request_reservations SET status=?,results_json=? WHERE job_source_id=? AND query_index=? AND status='reserved' ''',
            ('failed' if results is None else 'succeeded',None if results is None else encode(results),context.source['id'],index))


def block(context):
    with context.queue.database.transaction() as conn:
        context.guard(conn)
        conn.execute('UPDATE tavily_safety SET blocked=1 WHERE singleton=1')
