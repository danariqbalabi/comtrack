"""Bounded public HTTP reads with TLS verification, pinned DNS, and robots checks."""

import http.client
import ipaddress
import socket
import ssl
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

USER_AGENT = "LombaRadar/0.3"
MAX_BYTES = 2 * 1024 * 1024


class FetchError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, retry_after: float | None = None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


@dataclass(frozen=True)
class Page:
    url: str
    body: bytes
    content_type: str


def public_url(url: str, allowed_hosts: frozenset[str]) -> str:
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError
        if parsed.username or parsed.password or parsed.port not in (None, 80, 443):
            raise ValueError
        if parsed.hostname.lower() not in allowed_hosts:
            raise FetchError("Host di luar daftar sumber yang diizinkan.")
        # Local literals must be rejected even if accidentally added to a future allowlist.
        host = parsed.hostname.lower()
        if host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
            raise FetchError("Alamat internal tidak diizinkan.")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and not is_public(address):
            raise FetchError("Alamat internal tidak diizinkan.")
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))
    except ValueError:
        raise FetchError("URL sumber harus HTTP/HTTPS publik tanpa credential atau port khusus.") from None


def is_public(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    mapped = getattr(address, "ipv4_mapped", None)
    return address.is_global and (mapped is None or mapped.is_global)


class PublicClient:
    def __init__(self, allowed_hosts: frozenset[str], *, timeout: float = 15, max_bytes: int = MAX_BYTES):
        self.allowed_hosts = allowed_hosts
        self.timeout = timeout
        self.max_bytes = max_bytes
        self._robots: dict[str, RobotFileParser] = {}
        self._last_request: dict[str, float] = {}

    def _request(self, url: str, deadline: float) -> tuple[Page, int, dict[str, str]]:
        url = public_url(url, self.allowed_hosts)
        parsed = urlsplit(url)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            addresses = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
        except OSError:
            raise FetchError("DNS sumber tidak dapat dihubungi.") from None
        if not addresses or any(not is_public(ipaddress.ip_address(row[4][0])) for row in addresses):
            raise FetchError("DNS sumber mengarah ke alamat private/internal.")
        connection = http.client.HTTPConnection(parsed.hostname, port, timeout=self.timeout)
        try:
            # Connect to the validated numeric address, not a second DNS lookup of the hostname.
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise FetchError("Batas waktu pengambilan sumber habis.")
            connection.sock = socket.create_connection((addresses[0][4][0], port), timeout=min(self.timeout, remaining))
            if parsed.scheme == "https":
                connection.sock = ssl.create_default_context().wrap_socket(connection.sock, server_hostname=parsed.hostname)
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
            connection.request("GET", path, headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain;q=0.9", "Accept-Encoding": "identity"})
            response = connection.getresponse()
            headers = {key.lower(): value for key, value in response.getheaders()}
            if response.status in (301, 302, 303, 307, 308) or response.status >= 400:
                return Page(url, b"", headers.get("content-type", "")), response.status, headers
            if headers.get("content-encoding", "identity").lower() != "identity":
                raise FetchError("Kompresi respons sumber belum didukung; tidak diproses.")
            if int(headers.get("content-length", "0")) > self.max_bytes:
                raise FetchError("Konten sumber melebihi batas ukuran.")
            chunks = []; total = 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise FetchError("Batas waktu pengambilan sumber habis.")
                if connection.sock is not None:
                    connection.sock.settimeout(min(self.timeout, remaining))
                chunk = response.read(min(65536, self.max_bytes + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk); total += len(chunk)
                if total > self.max_bytes:
                    raise FetchError("Konten sumber melebihi batas ukuran.")
            return Page(url, b"".join(chunks), headers.get("content-type", "")), response.status, headers
        except (OSError, http.client.HTTPException, ValueError):
            raise FetchError("Koneksi/TLS sumber gagal atau respons tidak valid.") from None
        finally:
            connection.close()

    def _get(self, url: str, *, check_robots: bool, deadline: float, redirects: int = 3) -> Page:
        url = public_url(url, self.allowed_hosts)
        parsed = urlsplit(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if check_robots:
            self._respect_robots(url, origin, deadline)
        for attempt in range(2):
            try:
                page, status, headers = self._request(url, deadline)
                if status in (301, 302, 303, 307, 308):
                    if not redirects or not headers.get("location"):
                        raise FetchError("Redirect sumber berlebih atau tidak valid.")
                    target = public_url(urljoin(url, headers["location"]), self.allowed_hosts)
                    if parsed.scheme == "https" and urlsplit(target).scheme != "https":
                        raise FetchError("Redirect HTTPS ke HTTP ditolak.")
                    return self._get(target, check_robots=check_robots, deadline=deadline, redirects=redirects-1)
                if status >= 400:
                    retry = headers.get("retry-after")
                    # A long/date Retry-After is respected by stopping, never retrying early.
                    delay = float(retry) if retry and retry.isdigit() else None
                    if retry and delay is None:
                        delay = 999
                    raise FetchError(f"HTTP {status} dari sumber.", status=status, retry_after=delay)
                return page
            except FetchError as error:
                transient = error.status in (429, 500, 502, 503, 504) or str(error).startswith("Koneksi/TLS")
                delay = error.retry_after if error.retry_after is not None else 1
                if attempt or not transient or delay > 3 or time.monotonic() + delay >= deadline:
                    raise
                time.sleep(delay)
        raise FetchError("Pengambilan gagal.")

    def _respect_robots(self, url: str, origin: str, deadline: float) -> None:
        if origin not in self._robots:
            parser = RobotFileParser()
            try:
                page = self._get(origin + "/robots.txt", check_robots=False, deadline=deadline)
                if len(page.body) > 256000:
                    raise FetchError("robots.txt terlalu besar.")
                # HTML login/challenge pages must not masquerade as permission to crawl.
                if b"<html" in page.body[:1000].lower():
                    raise FetchError("robots.txt tidak valid.")
                parser.parse(page.body.decode("utf-8", "replace").splitlines())
            except FetchError as error:
                if error.status not in (404, 410):
                    raise FetchError("Akses robots.txt gagal; sumber tidak diambil.") from None
                parser.parse([])
            self._robots[origin] = parser
        parser = self._robots[origin]
        if not parser.can_fetch(USER_AGENT, url):
            raise FetchError("Pengambilan dilarang oleh robots.txt sumber.")
        delay = max(0.5, parser.crawl_delay(USER_AGENT) or parser.crawl_delay("*") or 0)
        delay = max(0, self._last_request.get(origin, 0) + delay - time.monotonic())
        if time.monotonic() + delay >= deadline:
            raise FetchError("Crawl-delay melebihi batas waktu; sumber dilewati.")
        time.sleep(delay)
        self._last_request[origin] = time.monotonic()

    def get(self, url: str) -> Page:
        return self._get(url, check_robots=True, deadline=time.monotonic() + 40)
