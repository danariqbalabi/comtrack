"""Read-only, bounded automation activity. Opening this API never fetches a provider."""
import json
from datetime import datetime,timedelta,timezone
from decimal import Decimal

from fastapi import APIRouter,Depends,Query,Response
from .feed_api import repository_for
from .provider_budget import daily_usage
from .quality.dates import deadline_passed
from .quality.service import visible_competitions
from .repository import Repository

router=APIRouter(prefix='/api/automation',tags=['automation activity'])


def activity_summary(repository):
    day=datetime.now(timezone.utc).date().isoformat()
    with repository.database.connection() as conn:
        requests,amount=daily_usage(conn,day)
        from .tavily_budget import usage
        free_usage=usage(conn)
        budgets=[dict(row) for row in conn.execute('''SELECT provider,count(*) requests,sum(reserved_microusd) reserved_microusd FROM (
            SELECT provider,reserved_microusd FROM provider_request_reservations WHERE day_utc=? UNION ALL
            SELECT provider,reserved_microusd FROM paid_provider_requests WHERE day_utc=?) GROUP BY provider''',(day,day))]
        candidates={row['onboarding_status']:row['count'] for row in conn.execute('SELECT onboarding_status,count(*) count FROM discovery_candidates GROUP BY onboarding_status')}
        accounts={row['status']:row['count'] for row in conn.execute('SELECT status,count(*) count FROM instagram_candidates GROUP BY status')}
        extraction={row['kind']:{'attempts':row['attempts'],'failed':row['failed'],'uncertain':row['uncertain']} for row in conn.execute('''SELECT kind,count(*) attempts,sum(status='failed') failed,sum(status='reserved') uncertain FROM extraction_attempts WHERE substr(created_at,1,10)=? GROUP BY kind''',(day,))}
        last=conn.execute('SELECT id,status,requested_at,started_at,finished_at FROM collection_jobs ORDER BY id DESC LIMIT 1').fetchone()
        results=[]
        if last:
            for row in conn.execute('SELECT result_json FROM collection_job_sources WHERE job_id=?',(last['id'],)):
                result=json.loads(row['result_json']);results.extend(result.get('competitions',[]) if 'competitions' in result else [result] if result.get('competition_id') else [])
        counts={key:sum(item.get('outcome')==key for item in results) for key in ('created','updated','unchanged')}
        counts.update({key:sum(item.get('relevance_status')==key for item in results) for key in ('relevant','needs_review','excluded')})
        source_counts={row['status']:row['count'] for row in conn.execute('SELECT status,count(*) count FROM sources GROUP BY status')}
    return {'day_utc':day,'tavily_free':free_usage,'budget':{'requests_reserved':requests,'estimated_usd_reserved':str(Decimal(amount)/1000000),'by_provider':budgets},
        'website_candidates':candidates,'instagram_candidates':accounts,'extraction':extraction,'source_statuses':source_counts,
        'last_job':{**dict(last),'counts':counts} if last else None}


@router.get('/activity')
def activity(response:Response,repository:Repository=Depends(repository_for)):
    response.headers['Cache-Control']='no-store'
    return activity_summary(repository)


@router.get('/sources')
def source_health(response:Response,repository:Repository=Depends(repository_for)):
    response.headers['Cache-Control']='no-store'
    with repository.database.connection() as conn:
        rows=conn.execute('''SELECT s.id,s.name,s.url,s.kind,s.enabled,s.status,s.last_checked_at,s.last_success_at,s.last_error,
            h.attempts,h.successes,h.failures,h.consecutive_failures,h.relevant_found,h.changes_found,h.score,h.next_check_at,h.reason
            FROM sources s LEFT JOIN source_health h ON h.source_id=s.id ORDER BY s.enabled DESC,COALESCE(h.score,0) DESC,s.id LIMIT 30''')
        return {'items':[dict(row) for row in rows]}


@router.get('/runs')
def runs(response:Response,offset:int=Query(0,ge=0),limit:int=Query(10,ge=1,le=30),repository:Repository=Depends(repository_for)):
    response.headers['Cache-Control']='no-store'
    with repository.database.connection() as conn:
        rows=conn.execute('''SELECT j.id,j.status,j.requested_at,j.finished_at,j.summary_json,a.job_id automatic
            FROM collection_jobs j LEFT JOIN automation_job_runs a ON a.job_id=j.id ORDER BY j.id DESC LIMIT ? OFFSET ?''',(limit,offset))
        items=[]
        for row in rows:
            item=dict(row);summary=json.loads(item.pop('summary_json'));item['trigger']='scheduled' if item.pop('automatic') else 'manual'
            item['sources_ok']=summary.get('sources_ok',0);item['sources_failed']=summary.get('sources_failed',0);item['sources_skipped']=summary.get('sources_skipped',0)
            item['sources']=[dict(source) for source in conn.execute('SELECT source_name,source_url,status,error FROM collection_job_sources WHERE job_id=? ORDER BY id',(row['id'],))]
            items.append(item)
        return {'items':items,'total':conn.execute('SELECT count(*) FROM collection_jobs').fetchone()[0]}


@router.get('/changes')
def changes(response:Response,offset:int=Query(0,ge=0),limit:int=Query(20,ge=1,le=100),repository:Repository=Depends(repository_for)):
    response.headers['Cache-Control']='no-store'
    with repository.database.connection() as conn:
        rows=conn.execute('''SELECT e.id,e.competition_id,c.name,e.version,e.source_id,e.changes_json,e.created_at
            FROM competition_change_events e JOIN competitions c ON c.id=e.competition_id ORDER BY e.id DESC LIMIT ? OFFSET ?''',(limit,offset))
        items=[]
        for row in rows:
            item=dict(row);item['changes']=json.loads(item.pop('changes_json'));items.append(item)
        return {'items':items,'total':conn.execute('SELECT count(*) FROM competition_change_events').fetchone()[0]}


@router.get('/deadlines')
def deadlines(response:Response,days:int=Query(7,ge=1,le=30),limit:int=Query(30,ge=1,le=100),repository:Repository=Depends(repository_for)):
    response.headers['Cache-Control']='no-store'
    now=datetime.now(timezone.utc);end=(now+timedelta(days=days)).date()
    items=[]
    for record in visible_competitions(repository,now=now):
        for entry in record.data.timeline:
            date=entry.date or (entry.at.date() if entry.at else None)
            if entry.kind!='registration' or deadline_passed(entry,now) is not False or not date or date>end:continue
            items.append({'competition_id':record.id,'name':record.data.name,'category':record.data.category,
                'date':date.isoformat(),'at':entry.at.isoformat() if entry.at else None,'timezone':entry.timezone,
                'label':entry.label,'relevance_status':record.data.relevance_status,'source_url':str(record.data.source_url)})
    items.sort(key=lambda item:(item['date'],item['competition_id']))
    return {'items':items[:limit],'total':len(items),'days':days}
