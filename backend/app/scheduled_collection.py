"""Per-source logical page budget for scheduled free website collectors."""
from urllib.parse import urlsplit

from .collectors.http import FetchError, PublicClient


class ScheduledPageClient:
    def __init__(self, url, limit, delegate=None, *, reserve=None):
        host = urlsplit(url).hostname
        if not host:
            raise ValueError('URL sumber tidak valid.')
        hosts = frozenset({host,host[4:] if host.startswith('www.') else 'www.'+host})
        self.delegate = delegate if delegate is not None else PublicClient(hosts)
        self.limit = limit
        self.used = 0
        self.reserve = reserve
        self.pages = []

    def get(self, url):
        if self.used >= self.limit:
            raise FetchError('Batas halaman otomatisasi untuk sumber ini tercapai; halaman berikutnya dilewati.')
        self.used = self.reserve() if self.reserve else self.used+1
        page = self.delegate.get(url)
        self.pages.append(page)
        return page
