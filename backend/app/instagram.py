"""Discover public competition accounts; verify biography before touching post content."""
import hashlib
import re
from dataclasses import replace
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from .automation import AutomationSettings
from .database import utc_now
from .discovery import DiscoveryBlocked
from .extraction import ExtractionContext
from .provider_budget import apify_run
from .repository import encode
from .collectors import providers
from .collectors.http import public_url,FetchError
from .collectors.public import Batch,from_text


def profile_url(url):
    public_url(url,frozenset({'instagram.com','www.instagram.com'}))
    parsed=urlsplit(url);username=parsed.path.strip('/').lower()
    if not re.fullmatch(r'[a-z0-9_.]{1,30}',username) or username in ('p','reel','reels','stories','explore','accounts','direct'):
        raise ValueError('Discovery Instagram memerlukan URL profil akun, bukan postingan/hashtag.')
    return username,'https://www.instagram.com/'+username+'/'


def candidate(context,url,origin):
    username,url=profile_url(url);stamp=utc_now()
    with context.queue.database.transaction() as conn:
        context.guard(conn)
        conn.execute('''INSERT INTO instagram_candidates(username,url,discovered_from,first_seen_at,last_seen_at)
            VALUES (?,?,?,?,?) ON CONFLICT(username) DO UPDATE SET last_seen_at=excluded.last_seen_at''',(username,url,origin,stamp,stamp))
    return username,url


def record(context,username,status,reason,profile=None,source_id=None):
    with context.queue.database.transaction() as conn:
        context.guard(conn)
        conn.execute('''UPDATE instagram_candidates SET status=?,reason=?,profile_json=COALESCE(?,profile_json),source_id=?,checked_at=? WHERE username=?''',
            (status,reason,encode(profile) if profile else None,source_id,utc_now(),username))
    return status,reason


def classify(profile,username):
    if profile.get('username','').lower()!=username:return 'held','Identitas profil provider tidak cocok.'
    privacy=[profile[key] for key in ('private','isPrivate') if key in profile]
    if any(value is True for value in privacy):return 'rejected','Akun private; postingan tidak diproses.'
    if not privacy or any(value is not False for value in privacy):return 'held','Status publik akun belum terverifikasi.'
    bio=profile.get('biography','')
    if re.search(r'\b(?:personal|pribadi|diary|blogger)\b',bio,re.I):return 'rejected','Bio menunjukkan akun pribadi.'
    media=re.search(r'\b(?:info(?:rmasi)?\s+(?:lomba|kompetisi)|media\s+(?:lomba|kompetisi)|competition\s+(?:information|updates)|platform.{0,30}(?:lomba|kompetisi))\b',bio,re.I)
    organizer=re.search(r'\b(?:penyelenggara|organizer|official)\b.{0,80}\b(?:hackathon|business (?:case|plan)|BCC|BPC|kompetisi|lomba)\b',bio,re.I)
    if media or organizer:return 'approved','Akun publik dengan bio eksplisit media lomba/penyelenggara.'
    return 'held','Publik saja belum cukup; bio belum jelas sebagai media lomba/penyelenggara.'


def verify(context,username):
    def sanitize(rows):
        return [{key:row[key] for key in ('username','biography','private','isPrivate') if key in row}
                for row in rows if isinstance(row,dict)]
    rows=apify_run(context,'profile:'+username,'apify~instagram-profile-scraper',{'usernames':[username]},1,sanitize)
    profile=rows[0] if rows else {}
    if not isinstance(profile.get('username',''),str) or not isinstance(profile.get('biography',''),str):
        return {},'held','Struktur profil provider tidak valid.'
    profile['biography']=profile.get('biography','')[:4000]
    status,reason=classify(profile,username)
    return profile,status,reason


def onboard(context,username,url,profile):
    with context.queue.database.transaction() as conn:
        context.guard(conn)
        for existing in conn.execute("SELECT id,url FROM sources WHERE kind='instagram'"):
            try:account=profile_url(existing['url'])[0]
            except (ValueError,FetchError):continue
            if account==username:
                source_id=existing['id'];status='existing';reason='Akun sudah terdaftar; pilihan aktif/nonaktif dipertahankan.';break
        else:
            current=AutomationSettings.model_validate_json(conn.execute('SELECT data_json FROM automation_settings WHERE singleton=1').fetchone()[0])
            if context.snapshot is None:return 'held','Onboarding akun hanya pada discovery terjadwal.'
            used=conn.execute('SELECT count(*) FROM website_onboardings WHERE job_id=?',(context.job_id,)).fetchone()[0]
            if used>=min(current.max_new_sources_per_run,context.snapshot.max_new_sources_per_run) or conn.execute('SELECT count(*) FROM sources').fetchone()[0]>=30:
                status='limited';reason='Batas sumber baru atau total sumber tercapai.';source_id=None
            elif conn.execute('SELECT 1 FROM website_onboardings WHERE job_id=? AND canonical_key=?',(context.job_id,'ig:'+username)).fetchone():
                status='held';reason='Penghapusan akun pada job ini dipertahankan.';source_id=None
            else:
                stamp=utc_now()
                source_id=conn.execute("INSERT INTO sources(name,kind,url,adapter,config_json,created_at,updated_at) VALUES (?,'instagram',?,'instagram_provider',?,?,?)",('@'+username,url,encode({'scope':'public_competition_account'}),stamp,stamp)).lastrowid
                conn.execute('INSERT INTO website_onboardings(job_id,source_id,canonical_key,created_at) VALUES (?,?,?,?)',(context.job_id,source_id,'ig:'+username,stamp))
                status='active';reason='Akun publik lolos klasifikasi; dipantau mulai job berikutnya.'
        conn.execute('UPDATE instagram_candidates SET status=?,reason=?,source_id=?,profile_json=?,checked_at=? WHERE username=?',
            (status,reason,source_id,encode(profile),utc_now(),username))
    return status,reason


def consider(context,url,origin):
    username,url=candidate(context,url,origin)
    # Do not purchase profile validation when subscription is explicitly disabled by quota 0.
    if context.snapshot and context.snapshot.max_new_sources_per_run==0:
        return record(context,username,'limited','Batas sumber baru diatur 0.')
    try:
        profile,status,reason=verify(context,username)
    except (providers.ProviderUnavailable,DiscoveryBlocked):
        return record(context,username,'held','Provider Instagram/izin/kuota belum siap; profil belum diperiksa.')
    except ValueError:
        return record(context,username,'held','Profil gagal diambil; tidak mencoba postingan.')
    if status!='approved':return record(context,username,status,reason,profile)
    return onboard(context,username,url,profile)


def discover_links(context,page):
    urls=[]
    for node in BeautifulSoup(page.body,'html.parser').select('a[href]'):
        try:
            _,url=profile_url(node['href'])
        except (ValueError,TypeError,FetchError):continue
        if url not in urls:urls.append(url)
        if len(urls)>=3:break
    for url in urls:consider(context,url,page.url)


def collect(queue,job_id,token,source):
    context=ExtractionContext(queue,job_id,token,source)
    username,url=candidate(context,source['source_url'],source['source_url'])
    profile,status,reason=verify(context,username)
    record(context,username,status,reason,profile,source['source_id'])
    if status!='approved':raise ValueError(reason)
    limit=context.config.instagram_posts_limit
    def sanitize(rows):
        allowed=('url','ownerUsername','caption','displayUrl','images','childPosts','error')
        cleaned=[]
        for row in rows:
            if not isinstance(row,dict):continue
            value={key:row[key] for key in allowed if key in row}
            value['childPosts']=[{'displayUrl':child.get('displayUrl')} for child in (row.get('childPosts') or [])[:20] if isinstance(child,dict)] if isinstance(row.get('childPosts',[]),list) else []
            cleaned.append(value)
        return cleaned
    posts=apify_run(context,'posts:'+username,'apify~instagram-scraper',{'directUrls':[url],'resultsType':'posts','resultsLimit':limit},limit,sanitize)
    batch=Batch()
    for post in posts:
        batch.inspected+=1
        if post.get('error') or not isinstance(post.get('ownerUsername'),str) or post['ownerUsername'].lower()!=username:
            batch.errors.append('Postingan gagal atau pemilik tidak sesuai akun.');continue
        post_url=post.get('url','')
        try:
            public_url(post_url,frozenset({'instagram.com','www.instagram.com'}))
            if not re.fullmatch(r'/(?:p|reel)/[\w-]+/?',urlsplit(post_url).path):raise ValueError('URL bukan postingan.')
        except (ValueError,TypeError,FetchError):
            batch.errors.append('URL postingan provider tidak valid.');continue
        caption=post.get('caption') or ''
        if not isinstance(caption,str):batch.errors.append('Caption tidak valid.');continue
        raw=caption[:16000];ocr_used=False
        images=([post.get('displayUrl')]+(post.get('images') if isinstance(post.get('images'),list) else [])+[child.get('displayUrl') for child in post['childPosts']])
        for image in list(dict.fromkeys(image for image in images if isinstance(image,str)))[:5]:
            if not context.config.ocr_enabled:break
            key=hashlib.sha256(image.encode()).hexdigest()
            if not context.reserve(key,'ocr',post_url):continue
            try:
                queue.reserve_scheduled_page(job_id,token,source)
                text=providers.ocr_image(image,context.config);raw=(raw+'\n'+text)[:16000];ocr_used=ocr_used or bool(text)
                context.finish(key,'ocr','succeeded')
            except (FetchError,ValueError):
                context.finish(key,'ocr','failed');batch.errors.append('Poster gagal dibaca; caption tetap digunakan.')
        title=next((line for line in raw.splitlines() if re.search(r'hackathon|business (?:case|plan)|\bBCC\b|\bBPC\b',line,re.I)),raw.splitlines()[0] if raw else '')
        item=from_text(title,raw,post_url)
        from .source_links import attach_caption
        item=attach_caption(item)
        if item:
            if ocr_used:item.data.warnings.append('[Perlu review ekstraksi] Fakta poster Instagram perlu dicocokkan dengan gambar.')
            else:item.data.warnings.append('Informasi caption Instagram; poster belum dibaca.')
            item.field_values['_instagram']={'username':username,'profile':profile,'ocr':ocr_used}
            batch.items.append(item)
    return batch
