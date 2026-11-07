"""Monitor one proven article, without following page links or discovering a homepage."""
from .public import Batch, parse_html, client_for

ADAPTER = 'discovered_article'


def collect(source, client=None):
    client = client or client_for(source['source_url'])
    item = parse_html(client.get(source['source_url']))
    if item is None:
        raise ValueError('Artikel pantauan tidak lagi memuat lomba yang didukung; bukti lama dipertahankan.')
    return Batch([item], inspected=1)
