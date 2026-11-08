"""Retain explicit registration/official/document anchors as evidence; never follow them."""
import hashlib
import re
from dataclasses import replace
from urllib.parse import urljoin,urlsplit
from bs4 import BeautifulSoup
from .collectors.http import public_url,FetchError


def attach(item,page):
    if item is None or 'html' not in page.content_type.lower():return item
    soup=BeautifulSoup(page.body,'html.parser')
    body=soup.select_one('article, .entry-content, .post-body, main')
    if body is None:return item
    matches={key:[] for key in ('registration_url','official_url','guidebook_url')}
    for node in body.select('a[href]')[:200]:
        label=node.get_text(' ',strip=True)
        field='registration_url' if re.fullmatch(r'(?:daftar(?: sekarang| di sini)?|pendaftaran|registrasi|register(?: now)?|registration)',label,re.I) else 'guidebook_url' if re.search(r'\b(?:guidebook|buku panduan|panduan lomba)\b',label,re.I) else 'official_url' if re.fullmatch(r'(?:website resmi|official website)',label,re.I) else None
        if not field:continue
        url=urljoin(page.url,node['href'])
        try:public_url(url,frozenset({urlsplit(url).hostname}))
        except (ValueError,FetchError):continue
        if urlsplit(url).path.rstrip('/')=='':continue
        if url not in matches[field]:matches[field].append(url)
    data=item.data.model_copy(deep=True);fields=dict(item.field_values);raw=item.raw_text
    for field,urls in matches.items():
        if len(urls)==1 and getattr(data,field) is None:
            setattr(data,field,urls[0]);fields[field]=urls[0];raw+='\n'+field+': '+urls[0]
        elif len(urls)>1:
            data.warnings.append('[Perlu review ekstraksi] Beberapa tautan '+field+' berbeda pada artikel.')
    return replace(item,data=data,field_values=fields,raw_text=raw,content_hash=hashlib.sha256(raw.encode()).hexdigest())


def attach_caption(item):
    if item is None or item.data.registration_url:return item
    urls=[];lines=item.raw_text.splitlines()
    for index,line in enumerate(lines):
        if not re.search(r'\b(?:daftar|pendaftaran|registrasi|register|registration)\b',' '.join(lines[max(0,index-1):index+1]),re.I):continue
        for url in re.findall(r'https?://[^\s<>]+',line):
            try:public_url(url,frozenset({urlsplit(url).hostname}))
            except (ValueError,FetchError):continue
            if urlsplit(url).path.rstrip('/') and url not in urls:urls.append(url)
    if len(urls)!=1:return item
    data=item.data.model_copy(update={'registration_url':urls[0]})
    return replace(item,data=data,field_values={**item.field_values,'registration_url':urls[0]})
