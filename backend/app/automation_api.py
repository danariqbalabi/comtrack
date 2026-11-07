"""Automation controls and local configuration readiness; no remote validation or fetch."""
import shutil
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from .automation import AutomationStore, AutomationUpdate
from .config import get_settings
from .repository import VersionConflictError

router = APIRouter(prefix='/api/automation', tags=['automation'])


def store_for(request: Request):
    return AutomationStore(request.app.state.database)


def present(snapshot, schedule):
    config = get_settings()
    settings = snapshot['settings']
    def provider(flag, credential):
        configured = flag and bool(credential.get_secret_value())
        return {'configured':configured, 'automation_allowed':False}
    heartbeat = schedule['last_tick_at']
    fresh = bool(heartbeat and (datetime.now(timezone.utc)-datetime.fromisoformat(heartbeat)).total_seconds() <= max(30,config.scheduler_poll_seconds*3))
    return {**snapshot, 'runtime':{
        'stage':2, 'scheduler_available':True, 'scheduler_online':fresh, 'running':settings.enabled and fresh,
        'state':('waiting_scheduler' if not fresh else schedule['last_status']) if settings.enabled else 'disabled',
        'limits_enforced':True, 'enforced_limits':['max_sources_per_run','max_pages_per_source'],
        'next_run_at':schedule['next_run_at'], 'last_tick_at':heartbeat,
        'last_enqueued_at':schedule['last_enqueued_at'], 'last_job_id':schedule['last_job_id'],
        'message':'Scheduler tahap 2 hanya menjadwalkan website/RSS terdaftar, dengan batas sumber dan halaman. Discovery, penambahan sumber, Instagram, OCR dan provider berbayar belum dijalankan otomatis. Pencarian manual memakai alur sebelumnya.',
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
    return present(store.get(),store.schedule())


@router.put('')
def save_automation(body: AutomationUpdate, response: Response, store: AutomationStore = Depends(store_for)):
    response.headers['Cache-Control'] = 'no-store'
    try:
        return present(store.save(body.settings, expected_version=body.expected_version),store.schedule())
    except VersionConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
