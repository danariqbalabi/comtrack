"""Persistent productivity, capped retry delay, and evidence-backed material change events."""
import json
from datetime import datetime,timedelta,timezone
from .automation import AutomationSettings
from .repository import encode


def record(conn,source,result,error,*,now=None):
    now=now or datetime.now(timezone.utc);stamp=now.isoformat()
    if source['source_id'] is None:return
    inserted=conn.execute('INSERT OR IGNORE INTO source_health_events(job_source_id,created_at) VALUES (?,?)',(source['id'],stamp))
    if not inserted.rowcount:return
    conn.execute('INSERT OR IGNORE INTO source_health(source_id) VALUES (?)',(source['source_id'],))
    old=dict(conn.execute('SELECT * FROM source_health WHERE source_id=?',(source['source_id'],)).fetchone())
    result=result or {}
    items=result.get('competitions',[]) if 'competitions' in result else [result] if result.get('competition_id') else []
    relevant=[item for item in items if item.get('relevance_status')=='relevant']
    created=sum(item.get('outcome')=='created' for item in relevant)
    changed=sum(item.get('outcome')=='updated' for item in relevant)
    failed=bool(error)
    streak=old['consecutive_failures']+1 if failed else 0
    unchanged=0 if created or changed else old['unchanged_runs']+1
    settings=AutomationSettings.model_validate_json(conn.execute('SELECT data_json FROM automation_settings WHERE singleton=1').fetchone()[0])
    delay=settings.interval_minutes
    if failed:
        delay*=2**min(streak,6)
        if '429' in error or 'rate limit' in error.lower():delay=max(delay,settings.interval_minutes*4)
        reason='Sumber gagal; jeda bertambah sampai berhasil. Cari sekarang dapat mencoba ulang.'
    elif created or changed:
        reason='Sumber menghasilkan lomba relevan/perubahan; interval normal.'
    else:
        delay*=min(4,1+unchanged)
        reason='Belum ada lomba relevan baru/perubahan; interval diperjarang.'
    delay=max(30,min(10080,delay))
    score=max(0,min(100,old['score']*.8+created*5+changed*2-(5 if failed else 0)))
    conn.execute('''UPDATE source_health SET attempts=attempts+1,successes=successes+?,failures=failures+?,
        consecutive_failures=?,unchanged_runs=?,relevant_found=relevant_found+?,changes_found=changes_found+?,score=?,
        last_attempt_at=?,next_check_at=?,reason=? WHERE source_id=?''',
        (int(not failed),int(failed),streak,unchanged,created,changed,score,stamp,(now+timedelta(minutes=delay)).isoformat(),reason,source['source_id']))
    for item in items:
        if item.get('outcome')!='updated':continue
        history=conn.execute('SELECT version,data_json FROM competition_history WHERE competition_id=? AND version<=? ORDER BY version DESC LIMIT 2',
            (item['competition_id'],item['version'])).fetchall()
        if len(history)!=2:continue
        new,previous=(json.loads(row['data_json']) for row in history)
        changes={field:{'before':previous.get(field),'after':new.get(field)} for field in ('timeline','fees','registration_status','eligibility') if previous.get(field)!=new.get(field)}
        if changes:
            conn.execute('INSERT OR IGNORE INTO competition_change_events(competition_id,version,source_id,changes_json,created_at) VALUES (?,?,?,?,?)',
                (item['competition_id'],item['version'],source['source_id'],encode(changes),stamp))
