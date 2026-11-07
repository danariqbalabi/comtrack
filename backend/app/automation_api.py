"""Automation controls and local configuration readiness; no remote validation or fetch."""
import shutil

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from .automation import AutomationStore, AutomationUpdate
from .config import get_settings
from .repository import VersionConflictError

router = APIRouter(prefix='/api/automation', tags=['automation'])


def store_for(request: Request):
    return AutomationStore(request.app.state.database)


def present(snapshot):
    config = get_settings()
    settings = snapshot['settings']
    def provider(flag, credential):
        configured = flag and bool(credential.get_secret_value())
        return {'configured':configured, 'automation_allowed':configured and settings.allow_paid_providers}
    return {**snapshot, 'runtime':{
        'stage':1, 'scheduler_available':False, 'running':False,
        'state':'pending_scheduler' if settings.enabled else 'disabled',
        'limits_enforced':False,
        'message':'Konfigurasi tersimpan. Scheduler dan penerapan batas otomatisasi belum tersedia; pencarian manual tetap memakai alur lama.',
        'providers':{
            'discovery':provider(config.discovery_provider_enabled, config.brave_api_key),
            'instagram':provider(config.instagram_provider_enabled, config.apify_token),
            'ocr':{'configured':config.ocr_enabled and shutil.which(config.tesseract_command) is not None},
            'ai':{'configured':False},
        },
    }}


@router.get('')
def get_automation(response: Response, store: AutomationStore = Depends(store_for)):
    response.headers['Cache-Control'] = 'no-store'
    return present(store.get())


@router.put('')
def save_automation(body: AutomationUpdate, response: Response, store: AutomationStore = Depends(store_for)):
    response.headers['Cache-Control'] = 'no-store'
    try:
        return present(store.save(body.settings, expected_version=body.expected_version))
    except VersionConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
