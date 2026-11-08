"""Local readiness report. No search, paid API, model generation, or configuration changes."""
import json
import shutil
import sqlite3
from backend.app.automation import AutomationStore
from backend.app.config import ROOT,get_settings
from backend.app.database import Database,MigrationError
from backend.app.repository import Repository


def inspect():
    config=get_settings();db=Database(config.resolved_database_path)
    report={'database':{'exists':db.path.exists()},'frontend_built':(ROOT/'frontend/dist/index.html').is_file(),
        'production_auth_configured':bool(config.access_username and len(config.access_password.get_secret_value())>=16),
        'providers':{'discovery_provider':config.discovery_provider,'tavily_configured':bool(config.discovery_provider_enabled and config.tavily_api_key.get_secret_value()),
            'brave_configured':bool(config.discovery_provider_enabled and config.brave_api_key.get_secret_value() and config.brave_cost_per_request_usd),
            'instagram_configured':bool(config.instagram_provider_enabled and config.apify_token.get_secret_value()),
            'ocr_configured':bool(config.ocr_enabled and shutil.which(config.tesseract_command)),
            'ai_configured':bool(config.ai_enabled and config.ai_model)},
        'provider_credentials_verified':False,'model_runtime_verified':False,'network_requests':0}
    if db.path.exists():
        try:
            report['database']['schema']=db.check()
            state=AutomationStore(db).get()
            report['automation']={'enabled':state['settings'].enabled,'paid_allowed':state['settings'].allow_paid_providers,
                'daily_requests':state['settings'].provider_daily_request_limit,'daily_usd':str(state['settings'].provider_daily_budget_usd),
                'tavily_free_enabled':state['settings'].tavily_free_enabled,'tavily_daily_limit':state['settings'].tavily_daily_credit_limit,'tavily_monthly_limit':state['settings'].tavily_monthly_credit_limit,
                'schedule':AutomationStore(db).schedule()}
            with db.connection() as conn:
                report['database']['foreign_key_errors']=len(conn.execute('PRAGMA foreign_key_check').fetchall())
                report['database']['integrity']=conn.execute('PRAGMA quick_check').fetchone()[0]
                report['database']['sources']=conn.execute('SELECT count(*) FROM sources').fetchone()[0]
                report['database']['competitions']=conn.execute('SELECT count(*) FROM competitions').fetchone()[0]
        except (MigrationError,OSError,ValueError,sqlite3.Error):
            report['database']['error']='Database perlu migrasi/perbaikan; jalankan perintah migrate setelah backup.'
    return report


def main():
    print(json.dumps(inspect(),indent=2,ensure_ascii=True))


if __name__=='__main__':main()
