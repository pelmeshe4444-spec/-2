import logging
import re

from sqlalchemy.engine import make_url

from backend.api import create_api
from config import Config
from database.session import Database


config = Config.load()
logging.basicConfig(level=config.log_level, format='%(asctime)s %(levelname)s %(name)s %(message)s')
logging.getLogger('aiogram.event').setLevel(logging.WARNING)
if make_url(config.db_url).drivername != 'postgresql+asyncpg':
    raise RuntimeError('Render requires PostgreSQL in DATABASE_URL.')
if not config.mini_app_url or not re.fullmatch(r'[A-Za-z0-9_-]{24,256}', config.webhook_secret):
    raise RuntimeError('Configure MINI_APP_URL and TELEGRAM_WEBHOOK_SECRET.')
if len(config.scheduler_secret) < 24 or config.scheduler_secret == config.webhook_secret:
    raise RuntimeError('Configure a separate SCHEDULER_SECRET.')

app = create_api(config, Database(config.db_url))
