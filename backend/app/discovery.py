"""Preference-derived query plans and fenced, durable provider budget reservations."""
import json
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .automation import AutomationSettings
from .collectors.http import public_url
from .job_queue import SourceDisabledError
from .models import Preferences
from .quality.identity import canonical_url
from .repository import encode

MICRO_USD = Decimal(1000000)


class DiscoveryBlocked(ValueError):
    pass


def query_pool(preferences: Preferences, year: int):
    categories = [key for key in ('hackathon','BCC','BPC') if key in preferences.categories]
    labels = {'hackathon':('hackathon','hackathon'), 'BCC':('kompetisi kasus bisnis business case','business case competition'),
              'BPC':('lomba rencana bisnis business plan','business plan competition')}
    participant = 'mahasiswa' if preferences.education_level=='university' else 'peserta'
    english = 'university students' if preferences.education_level=='university' else 'participants'
    queries = []
    for variant in range(5):
        for category in categories:
            indonesian,international = labels[category]
            query = [f'{indonesian} Indonesia {participant} pendaftaran {year}',
                     f'{international} Indonesia {english} registration {year}',
                     f'{indonesian} {participant} pendaftaran site:ac.id {year}',
                     f'info lomba {international} Indonesia deadline {year}',
                     f'info lomba {international} Indonesia {participant} site:instagram.com {year}'][variant]
            queries.append(query)
    return queries


def attach_plan(conn, source_id, preferences, year):
    pool = query_pool(preferences,year)
    cursor = conn.execute('SELECT next_index FROM discovery_rotation WHERE singleton=1').fetchone()[0]
    count = min(3,len(pool))
    selected = [pool[(cursor+index)%len(pool)] for index in range(count)]
    conn.execute('INSERT INTO discovery_plans(job_source_id,queries_json,preferences_json) VALUES (?,?,?)',
                 (source_id,encode(selected),encode(preferences.model_dump(mode='json'))))
    conn.execute('UPDATE discovery_rotation SET next_index=? WHERE singleton=1',((cursor+count)%len(pool),))


def normalize_candidate(url):
    if not isinstance(url,str) or len(url)>2000:
        raise ValueError('URL kandidat tidak valid.')
    host = urlsplit(url).hostname
    clean = public_url(url,frozenset({host}))
    parsed = urlsplit(clean)
    query = [(key,value) for key,value in parse_qsl(parsed.query,keep_blank_values=True)
             if not key.lower().startswith('utm_') and key.lower() not in ('fbclid','gclid')]
    clean = urlunsplit((parsed.scheme,parsed.netloc,parsed.path,urlencode(sorted(query)),urlsplit(url).fragment))
    return clean, canonical_url(clean), parsed.hostname.lower().removeprefix('www.')


class DiscoveryContext:
    def __init__(self, queue, job_id, token, source):
        self.queue,self.job_id,self.token,self.source = queue,job_id,token,source
        with queue.database.connection() as conn:
            row = conn.execute('SELECT queries_json FROM discovery_plans WHERE job_source_id=?',(source['id'],)).fetchone()
            if row is None:
                raise DiscoveryBlocked('Job discovery tidak memiliki rencana pencarian tersimpan.')
            self.queries = json.loads(row['queries_json'])
        self.snapshot = queue.collection_settings(job_id)
        if self.snapshot is None:
            raise DiscoveryBlocked('Rencana discovery otomatis memerlukan snapshot konfigurasi job.')

    def guard(self,conn):
        self.queue.source_guard(conn,self.job_id,self.token,self.source)
        preferences = Preferences.model_validate_json(conn.execute('SELECT data_json FROM preferences WHERE singleton=1').fetchone()[0])
        if not preferences.discovery_enabled:
            raise SourceDisabledError('Discovery dijeda pada preferensi; pengambilan dilewati.')

    def reserve(self,index,query,cost,*,now=None):
        if index<0 or index>=len(self.queries) or self.queries[index]!=query:
            raise ValueError('Query harus sesuai rencana tersimpan.')
        now = now or datetime.now(timezone.utc)
        day = now.astimezone(timezone.utc).date().isoformat()
        with self.queue.database.transaction() as conn:
            self.guard(conn)
            previous = conn.execute('SELECT * FROM provider_request_reservations WHERE job_source_id=? AND query_index=?',(self.source['id'],index)).fetchone()
            if previous:
                if previous['status']=='succeeded':
                    return json.loads(previous['results_json'])
                raise DiscoveryBlocked('Request sebelumnya gagal atau statusnya tidak pasti; tidak diulang otomatis untuk menghindari biaya ganda.')
            current = AutomationSettings.model_validate_json(conn.execute('SELECT data_json FROM automation_settings WHERE singleton=1').fetchone()[0])
            if not self.snapshot.allow_paid_providers or not current.allow_paid_providers:
                raise DiscoveryBlocked('Discovery otomatis memerlukan izin provider berbayar dan batas harian positif.')
            allowance = min(self.snapshot.provider_daily_request_limit,current.provider_daily_request_limit)
            budget = min(self.snapshot.provider_daily_budget_usd,current.provider_daily_budget_usd)*MICRO_USD
            reserved = int(cost*MICRO_USD)
            if reserved<=0:
                raise DiscoveryBlocked('Estimasi biaya request belum valid.')
            from .provider_budget import daily_usage
            count,total = daily_usage(conn,day)
            if count>=allowance or Decimal(total+reserved)>budget:
                raise DiscoveryBlocked('Batas request atau anggaran estimasi harian discovery telah tercapai (UTC).')
            conn.execute('''INSERT INTO provider_request_reservations
                (job_source_id,query_index,query_text,provider,day_utc,reserved_microusd,status,created_at)
                VALUES (?,?,?,'brave',?,?,'reserved',?)''',(self.source['id'],index,query,day,reserved,now.isoformat()))
            return None

    def authorize_request(self):
        with self.queue.database.transaction() as conn:
            self.guard(conn)
            current = AutomationSettings.model_validate_json(conn.execute('SELECT data_json FROM automation_settings WHERE singleton=1').fetchone()[0])
            if not current.allow_paid_providers:
                raise SourceDisabledError('Izin provider berbayar dicabut; discovery dilewati.')

    def finish_request(self,index,results=None):
        with self.queue.database.transaction() as conn:
            self.guard(conn)
            conn.execute('''UPDATE provider_request_reservations SET status=?,results_json=?
                WHERE job_source_id=? AND query_index=? AND status='reserved' ''',
                ('failed' if results is None else 'succeeded',None if results is None else encode(results),self.source['id'],index))

    def candidate(self,entry):
        with self.queue.database.transaction() as conn:
            self.guard(conn)
            old = conn.execute('SELECT * FROM discovery_candidates WHERE canonical_key=?',(entry['canonical_key'],)).fetchone()
            if old is None:
                old = conn.execute('SELECT * FROM discovery_candidates WHERE url=?',(entry['url'],)).fetchone()
            stamp = datetime.now(timezone.utc).isoformat()
            status,reason = entry['status'],entry.get('reason')
            if old and old['checked_at'] and status=='unverified':
                status=old['status']
                reason=(reason+' Status mempertahankan pemeriksaan sebelumnya.') if reason else old['reason']
            checked=entry.get('checked_at') or (old['checked_at'] if old else None)
            values = (entry['title'],status,reason,stamp,self.job_id,entry['canonical_key'],entry['domain'],entry['query'],checked)
            if old:
                conn.execute('''UPDATE discovery_candidates SET title=?,status=?,reason=?,last_seen_at=?,job_id=?,canonical_key=?,domain=?,discovered_query=?,checked_at=? WHERE id=?''',(*values,old['id']))
            else:
                conn.execute('''INSERT INTO discovery_candidates
                    (title,status,reason,last_seen_at,job_id,canonical_key,domain,discovered_query,checked_at,url,first_seen_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)''',(*values,entry['url'],stamp))

    def page_client(self,url,delegate=None):
        from .scheduled_collection import ScheduledPageClient
        return ScheduledPageClient(url,self.snapshot.max_pages_per_source,delegate,
            reserve=lambda:self.queue.reserve_scheduled_page(self.job_id,self.token,self.source))
