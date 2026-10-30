"""Associate only Trotter's invitation landing with the signed iPhone app."""
import os
import re
from urllib.parse import urlsplit

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get('/.well-known/apple-app-site-association', include_in_schema=False)
def apple_app_site_association():
    prefix = os.getenv('APPLE_APP_ID_PREFIX', '').strip() or os.getenv('APPLE_TEAM_ID', '').strip()
    bundle = os.getenv('APPLE_BUNDLE_ID', 'com.trotter.mobilev2').strip()
    if not re.fullmatch(r'[A-Z0-9]{10}', prefix) or not re.fullmatch(r'[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+', bundle):
        # Never advertise a placeholder app association. Do not let a CDN cache
        # the absence of a real signing identity during initial provisioning.
        return JSONResponse({'applinks': {'details': []}}, status_code=503, headers={'Cache-Control': 'no-store'})
    try:
        api = urlsplit(os.getenv('BACKEND_URL', '').strip())
    except ValueError:
        return JSONResponse({'applinks': {'details': []}}, status_code=503, headers={'Cache-Control': 'no-store'})
    base_path = api.path.rstrip('/')
    if api.query or api.fragment or api.username or api.password or '*' in base_path or '?' in base_path:
        return JSONResponse({'applinks': {'details': []}}, status_code=503, headers={'Cache-Control': 'no-store'})
    return JSONResponse({'applinks': {'details': [{
        'appIDs': [f'{prefix}.{bundle}'],
        'components': [{'/': f'{base_path}/planner/open', 'comment': 'Shared trip invitations; the token remains in the URL fragment.'}],
    }]}}, headers={'Cache-Control': 'public, max-age=3600', 'X-Content-Type-Options': 'nosniff'})
