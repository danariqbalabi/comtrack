from fastapi import Request
from starlette.responses import JSONResponse
from .config import get_settings


async def protect_writes(request: Request, call_next):
    if request.url.path.startswith('/api/') and request.method not in ('GET', 'HEAD', 'OPTIONS'):
        allowed = {origin.strip() for origin in get_settings().api_allowed_origins.split(',')}
        origin = request.headers.get('origin')
        if request.headers.get('x-lomba-radar') != '1' or (origin and origin not in allowed):
            return JSONResponse({'detail': 'Permintaan harus berasal dari aplikasi Lomba Radar.'}, status_code=403)
    return await call_next(request)
