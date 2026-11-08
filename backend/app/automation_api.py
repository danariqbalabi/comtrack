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
    def provider(flag, credential, *, discovery=False):
        configured = flag and bool(credential.get_secret_value())
        allowed = configured and settings.allow_paid_providers and (not discovery or config.brave_cost_per_request_usd is not None)
        return {'configured':configured, 'automation_allowed':allowed}
    heartbeat = schedule['last_tick_at']
    fresh = bool(heartbeat and (datetime.now(timezone.utc)-datetime.fromisoformat(heartbeat)).total_seconds() <= max(30,config.scheduler_poll_seconds*3))
    return {**snapshot, 'runtime':{
        'stage':8, 'scheduler_available':True, 'scheduler_online':fresh, 'running':settings.enabled and fresh,
        'state':('waiting_scheduler' if not fresh else schedule['last_status']) if settings.enabled else 'disabled',
        'limits_enforced':True, 'enforced_limits':['max_sources_per_run','max_new_sources_per_run','max_pages_per_source','max_images_per_post','provider_daily_request_limit','provider_daily_budget_usd'],
        'next_run_at':schedule['next_run_at'], 'last_tick_at':heartbeat,
        'last_enqueued_at':schedule['last_enqueued_at'], 'last_job_id':schedule['last_job_id'],
        'message':'Scheduler memantau website/RSS dan dapat mencari kandidat lewat discovery jika preferensi, provider, izin biaya dan kuota siap. Artikel website yang lolos kualifikasi menjadi pantauan dalam batas sumber baru. AI lokal/OCR opsional membantu artikel yang belum lengkap. Instagram hanya untuk profil publik yang lolos klasifikasi bio. Pencarian manual memakai alur sebelumnya.',
        'providers':{
            'discovery':provider(config.discovery_provider_enabled, config.brave_api_key,discovery=True),
            'instagram':provider(config.instagram_provider_enabled, config.apify_token),
            'ocr':{'configured':config.ocr_enabled and shutil.which(config.tesseract_command) is not None},
            'ai':{'configured':config.ai_enabled and bool(config.ai_model),'provider':'ollama_local'},
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
