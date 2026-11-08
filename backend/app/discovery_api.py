"""Discovery activity and candidates. Read-only, never invokes a search provider."""
from datetime import datetime,timezone
from decimal import Decimal
import json
from typing import Literal

from fastapi import APIRouter,Depends,Query,Response
from .automation import AutomationStore
from .config import get_settings
from .discovery import MICRO_USD
from .feed_api import repository_for
from .repository import Repository

router = APIRouter(prefix='/api/discovery',tags=['discovery'])


def summary(repository):
    config = get_settings()
    settings = AutomationStore(repository.database).get()['settings']
    preferences = repository.get_preferences()
    day = datetime.now(timezone.utc).date().isoformat()
    with repository.database.connection() as conn:
        from .provider_budget import daily_usage
        count,amount = daily_usage(conn,day)
        last = conn.execute('''SELECT p.queries_json,s.job_id,s.status,s.error,s.result_json FROM discovery_plans p
            JOIN collection_job_sources s ON s.id=p.job_source_id ORDER BY s.job_id DESC LIMIT 1''').fetchone()
        total = conn.execute('SELECT count(*) FROM discovery_candidates').fetchone()[0]
        domains = conn.execute('SELECT count(DISTINCT domain) FROM discovery_candidates WHERE domain IS NOT NULL').fetchone()[0]
        source = conn.execute("SELECT enabled FROM sources WHERE kind='website' AND url='https://api.search.brave.com/'").fetchone()
        source_count = conn.execute('SELECT count(*) FROM sources').fetchone()[0]
    state = 'ready'
    if not preferences.discovery_enabled:
        state='disabled'
    elif not settings.enabled:
        state='automation_disabled'
    elif source is not None and not source['enabled']:
        state='source_disabled'
    elif source is None and source_count>=30:
        state='source_limit'
    elif not config.discovery_provider_enabled or not config.brave_api_key.get_secret_value():
        state='not_connected'
    elif config.brave_cost_per_request_usd is None:
        state='estimate_missing'
    elif not settings.allow_paid_providers:
        state='paid_not_allowed'
    elif count>=settings.provider_daily_request_limit or Decimal(amount)+config.brave_cost_per_request_usd*MICRO_USD>settings.provider_daily_budget_usd*MICRO_USD:
        state='budget_exhausted'
    return {'state':state,'candidates':total,'domains':domains,
        'budget':{'day_utc':day,'requests_reserved':count,'request_limit':settings.provider_daily_request_limit,
                  'estimated_usd_reserved':str(Decimal(amount)/MICRO_USD),'daily_limit_usd':str(settings.provider_daily_budget_usd),
                  'estimated_usd_per_request':str(config.brave_cost_per_request_usd) if config.brave_cost_per_request_usd is not None else None},
        'last_run':{'job_id':last['job_id'],'status':last['status'],'error':last['error'],
                    'queries':json.loads(last['queries_json']),'activity':json.loads(last['result_json']).get('discovery')} if last else None}


@router.get('')
def activity(response: Response,repository: Repository=Depends(repository_for)):
    response.headers['Cache-Control']='no-store'
    return summary(repository)


@router.get('/candidates')
def candidates(response: Response,status: Literal['verified','unverified','irrelevant','failed']|None=None,
               domain: str=Query(default='',max_length=253),offset: int=Query(default=0,ge=0),
               limit: int=Query(default=30,ge=1,le=100),repository: Repository=Depends(repository_for)):
    response.headers['Cache-Control']='no-store'
    where,values=[],[]
    if status:
        where.append('status=?');values.append(status)
    if domain:
        where.append('domain=?');values.append(domain.lower().removeprefix('www.'))
    clause=' WHERE '+' AND '.join(where) if where else ''
    with repository.database.connection() as conn:
        total=conn.execute('SELECT count(*) FROM discovery_candidates'+clause,values).fetchone()[0]
        rows=conn.execute('SELECT * FROM discovery_candidates'+clause+' ORDER BY last_seen_at DESC,id DESC LIMIT ? OFFSET ?',(*values,limit,offset))
        return {'items':[dict(row) for row in rows],'total':total,'offset':offset,'limit':limit}
