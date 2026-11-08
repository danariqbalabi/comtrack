"""One daily allowance across Brave and bounded Apify runs; no retry after uncertain charge."""
from datetime import datetime,timezone
from decimal import Decimal,ROUND_CEILING
import json
from urllib.parse import urlencode

from .automation import AutomationStore,AutomationSettings
from .database import utc_now
from .discovery import DiscoveryBlocked,MICRO_USD
from .repository import encode
from .collectors import providers


def daily_usage(conn,day):
    return conn.execute('''SELECT count(*),COALESCE(sum(reserved_microusd),0) FROM (
        SELECT reserved_microusd FROM provider_request_reservations WHERE day_utc=?
        UNION ALL SELECT reserved_microusd FROM paid_provider_requests WHERE day_utc=?)''',(day,day)).fetchone()


def apify_run(context,action,actor,payload,limit,sanitize):
    config=context.config
    if not config.instagram_provider_enabled or not config.apify_token.get_secret_value():
        raise providers.ProviderUnavailable('Instagram belum terhubung: atur APIFY_TOKEN dan INSTAGRAM_PROVIDER_ENABLED.')
    snapshot=context.queue.collection_settings(context.job_id) or AutomationStore(context.queue.database).get()['settings']
    day=datetime.now(timezone.utc).date().isoformat()
    cost=int((Decimal(str(config.apify_max_charge_usd))*MICRO_USD).to_integral_value(rounding=ROUND_CEILING))
    with context.queue.database.transaction() as conn:
        context.guard(conn)
        previous=conn.execute('SELECT * FROM paid_provider_requests WHERE job_source_id=? AND action_key=?',(context.source['id'],action)).fetchone()
        if previous:
            if previous['status']=='succeeded':return json.loads(previous['result_json'])
            raise DiscoveryBlocked('Request Instagram sebelumnya gagal/tidak pasti; tidak diulang pada job yang sama.')
        current=AutomationSettings.model_validate_json(conn.execute('SELECT data_json FROM automation_settings WHERE singleton=1').fetchone()[0])
        if not snapshot.allow_paid_providers or not current.allow_paid_providers:
            raise DiscoveryBlocked('Instagram memerlukan izin provider berbayar dan kuota harian.')
        count,total=daily_usage(conn,day)
        if count>=min(snapshot.provider_daily_request_limit,current.provider_daily_request_limit) or Decimal(total+cost)>min(snapshot.provider_daily_budget_usd,current.provider_daily_budget_usd)*MICRO_USD:
            raise DiscoveryBlocked('Batas request atau anggaran harian provider tercapai (UTC).')
        conn.execute("INSERT INTO paid_provider_requests(job_source_id,action_key,provider,day_utc,reserved_microusd,status,created_at) VALUES (?,?,'apify',?,?,'reserved',?)",(context.source['id'],action,day,cost,utc_now()))
    try:
        result=providers.request_json('api.apify.com','/v2/acts/'+actor+'/run-sync-get-dataset-items?'+urlencode({
            'timeout':60,'maxItems':limit,'limit':limit,'maxTotalChargeUsd':config.apify_max_charge_usd,'restartOnError':'false'}),
            token=config.apify_token.get_secret_value(),payload=payload)
        if not isinstance(result,list):raise ValueError('Format dataset Instagram provider berubah.')
        cleaned=sanitize(result[:limit])
    except ValueError:
        with context.queue.database.transaction() as conn:
            context.guard(conn)
            conn.execute("UPDATE paid_provider_requests SET status='failed' WHERE job_source_id=? AND action_key=?",(context.source['id'],action))
        raise
    with context.queue.database.transaction() as conn:
        context.guard(conn)
        conn.execute("UPDATE paid_provider_requests SET status='succeeded',result_json=? WHERE job_source_id=? AND action_key=?",(encode(cleaned),context.source['id'],action))
    return cleaned
