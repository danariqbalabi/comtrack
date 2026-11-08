"""Scheduled discovery: search hits remain candidates until original HTML is verified."""
import time
from dataclasses import dataclass,field
from datetime import datetime,timezone
from urllib.parse import urlencode

from ..config import get_settings
from ..discovery import DiscoveryBlocked,DiscoveryContext,normalize_candidate
from . import providers
from .http import FetchError
from .public import Batch,parse_html
from ..extraction import ExtractionContext


@dataclass
class DiscoveryBatch(Batch):
    onboarding_keys: dict = field(default_factory=dict)
    extraction_activity: dict = field(default_factory=dict)
    activity: dict = field(default_factory=lambda:{'queries_requested':0,'queries_reused':0,'candidates':0,'rejected_urls':0,'pages_verified':0})


class TavilyContractError(ValueError):
    pass


def search(query,config):
    if config.discovery_provider=='tavily':
        response=providers.request_json('api.tavily.com','/search',token=config.tavily_api_key.get_secret_value(),payload={
            'query':query,'search_depth':'basic','auto_parameters':False,'topic':'general','country':'indonesia',
            'max_results':5,'include_answer':False,'include_raw_content':False,'include_images':False,'include_usage':True})
        if not isinstance(response,dict) or not isinstance(response.get('results'),list):
            raise ValueError('Format respons Tavily tidak valid.')
        reported=response.get('usage',{}).get('credits') if isinstance(response.get('usage',{}),dict) else None
        if type(reported) not in (int,float) or reported!=1:
            raise TavilyContractError('Pemakaian kredit Tavily berbeda dari Basic Search; pencarian dihentikan.')
        return [{'url':hit.get('url'),'title':str(hit.get('title',''))[:300]} for hit in response['results'][:5] if isinstance(hit,dict)]
    response = providers.request_json('api.search.brave.com','/res/v1/web/search?'+urlencode({
        'q':query,'country':'ID','search_lang':'id','count':5,'result_filter':'web','text_decorations':'false','safesearch':'strict'}),
        token=config.brave_api_key.get_secret_value(),brave=True)
    if not isinstance(response,dict) or not isinstance(response.get('web',{}),dict) or not isinstance(response.get('web',{}).get('results',[]),list):
        raise ValueError('Format respons search provider tidak valid.')
    return [{'url':hit.get('url'),'title':str(hit.get('title',''))[:300]} for hit in response.get('web',{}).get('results',[])[:5] if isinstance(hit,dict)]


def collect(queue,job_id,token,source,*,client=None):
    config = get_settings()
    tavily=config.discovery_provider=='tavily'
    key=config.tavily_api_key if tavily else config.brave_api_key
    if not config.discovery_provider_enabled or not key.get_secret_value():
        raise providers.ProviderUnavailable('Discovery belum terhubung: atur '+('TAVILY_API_KEY' if tavily else 'BRAVE_API_KEY')+' dan DISCOVERY_PROVIDER_ENABLED di server.')
    if not tavily and config.brave_cost_per_request_usd is None:
        raise DiscoveryBlocked('Isi BRAVE_COST_PER_REQUEST_USD sesuai estimasi tarif akun sebelum discovery otomatis.')
    context = DiscoveryContext(queue,job_id,token,source)
    from .. import tavily_budget
    tavily_budget.pin(context,config.discovery_provider)
    extractor = ExtractionContext(queue,job_id,token,source)
    automatic = queue.automation_settings(job_id) is not None
    batch,seen = DiscoveryBatch(),set()
    for index,query in enumerate(context.queries):
        try:
            hits = tavily_budget.reserve(context,index,query) if tavily else context.reserve(index,query,config.brave_cost_per_request_usd)
        except DiscoveryBlocked as error:
            batch.errors.append(str(error)); break
        if hits is None:
            if index:
                time.sleep(1.1)
            tavily_budget.authorize(context) if tavily else context.authorize_request()
            try:
                hits = search(query,config)
            except ValueError as error:
                if isinstance(error,TavilyContractError):tavily_budget.block(context)
                tavily_budget.finish(context,index) if tavily else context.finish_request(index)
                batch.errors.append('Search provider gagal/menolak request; cek key dan kuota. Request tidak dicoba ulang otomatis.'); break
            tavily_budget.finish(context,index,hits) if tavily else context.finish_request(index,hits)
            batch.activity['queries_requested']+=1
        else:
            batch.activity['queries_reused']+=1
        for hit in hits:
            try:
                url,key,domain = normalize_candidate(hit['url'])
            except (ValueError,TypeError,FetchError):
                batch.activity['rejected_urls']+=1; continue
            if key in seen:
                continue
            seen.add(key)
            entry = {'url':url,'canonical_key':key,'domain':domain,'title':hit['title'],'query':query,'status':'unverified','reason':None}
            context.candidate(entry)
            batch.activity['candidates']+=1
            if domain in ('instagram.com','facebook.com','tiktok.com','x.com','twitter.com','youtube.com'):
                entry['reason']='Kandidat sosial media; bukan bukti fakta lomba.'
                if domain=='instagram.com' and automatic:
                    from ..instagram import consider
                    try:
                        _,entry['reason']=consider(extractor,url,url)
                    except (ValueError,FetchError):
                        entry['reason']='URL Instagram bukan profil akun yang dapat diklasifikasikan.'
                context.candidate(entry); continue
            try:
                page = context.page_client(url,client).get(url)
                from ..instagram import discover_links
                if automatic:discover_links(extractor,page)
                if extractor.config.ai_enabled or extractor.config.ocr_enabled:
                    item = extractor.extract(page)
                else:
                    item = parse_html(page)
                from ..source_links import attach
                item = attach(item,page)
                entry.update(status='verified' if item else 'irrelevant',checked_at=datetime.now(timezone.utc).isoformat())
                batch.activity['pages_verified']+=1
                if item:
                    batch.items.append(item)
                    batch.onboarding_keys[id(item)] = key
            except FetchError as error:
                is_limit = str(error).startswith('Batas halaman otomatisasi')
                entry.update(status='unverified' if is_limit else 'failed',reason='Batas verifikasi halaman tercapai.' if is_limit else 'Halaman asli gagal diakses; kandidat belum terverifikasi.')
                if not is_limit and 'Ada halaman kandidat gagal diverifikasi.' not in batch.errors:
                    batch.errors.append('Ada halaman kandidat gagal diverifikasi.')
            except ValueError:
                entry.update(status='failed',reason='Struktur artikel belum didukung; hasil pencarian tetap kandidat.')
                if 'Ada struktur artikel kandidat belum didukung.' not in batch.errors:
                    batch.errors.append('Ada struktur artikel kandidat belum didukung.')
            context.candidate(entry)
    batch.inspected = batch.activity['pages_verified']
    batch.extraction_activity = extractor.activity
    batch.errors.extend(extractor.activity['errors'])
    return batch
