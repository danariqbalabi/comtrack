from fastapi import Request
from starlette.responses import JSONResponse
from .config import get_settings
import base64
import binascii
import secrets


async def protect_writes(request: Request, call_next):
    settings = get_settings()
    password = settings.access_password.get_secret_value()
    if settings.access_username or password:
        authenticated = False
        try:
            scheme, encoded = request.headers.get('authorization', '').split(' ', 1)
            if scheme.lower() == 'basic' and len(encoded) < 4096:
                username, supplied = base64.b64decode(encoded, validate=True).decode('utf-8').split(':', 1)
                authenticated = secrets.compare_digest(username.encode(), settings.access_username.encode()) & secrets.compare_digest(supplied.encode(), password.encode())
        except (ValueError, UnicodeError, binascii.Error):
            pass
        if not authenticated:
            return JSONResponse({'detail': 'Akses pribadi memerlukan login.'}, status_code=401,
                                headers={'WWW-Authenticate': 'Basic realm="Lomba Radar", charset="UTF-8"', 'Cache-Control': 'no-store'})
    if request.url.path.startswith('/api/') and request.method not in ('GET', 'HEAD', 'OPTIONS'):
        allowed = {origin.strip() for origin in get_settings().api_allowed_origins.split(',')}
        origin = request.headers.get('origin')
        if request.headers.get('x-lomba-radar') != '1' or (origin and origin not in allowed):
            return JSONResponse({'detail': 'Permintaan harus berasal dari aplikasi Lomba Radar.'}, status_code=403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; manifest-src 'self'; worker-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    if request.url.path.startswith('/api/') or request.url.path in ('/', '/index.html', '/sw.js'):
        response.headers['Cache-Control'] = 'no-store'
    return response
