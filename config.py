import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram.utils.token import TokenValidationError, validate_token
from dotenv import load_dotenv
from sqlalchemy.engine import make_url


ROOT = Path(__file__).resolve().parent
DEFAULT_DB = 'sqlite+aiosqlite:///data/attendance.sqlite3'


def database_url() -> str:
    load_dotenv(ROOT / '.env')
    url = make_url(os.getenv('DATABASE_URL', DEFAULT_DB))
    if url.drivername in ('postgres', 'postgresql'):
        url = url.set(drivername='postgresql+asyncpg')
    if url.drivername == 'postgresql+asyncpg' and 'sslmode' in url.query:
        ssl_mode = url.query['sslmode']
        url = url.difference_update_query(['sslmode']).update_query_dict({'ssl': ssl_mode})
    if url.drivername == 'sqlite+aiosqlite':
        if not url.database or url.database == ':memory:':
            raise ValueError('Укажите путь к файлу SQLite в DATABASE_URL.')
        path = ROOT / url.database
        path.parent.mkdir(parents=True, exist_ok=True)
        url = url.set(database=path.as_posix())
    return url.render_as_string(hide_password=False)


@dataclass(frozen=True)
class Config:
    token: str = field(repr=False)
    owner_id: int
    zone: ZoneInfo
    db_url: str = field(repr=False)
    log_level: int = logging.INFO
    mini_app_url: str = ''
    init_data_ttl: int = 3600
    webhook_secret: str = field(default='', repr=False)
    scheduler_secret: str = field(default='', repr=False)
    updates_mode: str = 'polling'
    webhook_url: str = ''

    @property
    def frontend_origin(self):
        url = urlsplit(self.mini_app_url)
        return f'{url.scheme}://{url.netloc}' if url.netloc else ''

    @classmethod
    def load(cls) -> 'Config':
        load_dotenv(ROOT / '.env')
        token = os.getenv('BOT_TOKEN', '').strip()
        try:
            validate_token(token)
        except TokenValidationError:
            raise ValueError('Укажите токен от BotFather в BOT_TOKEN.') from None
        try:
            owner_id = int(os.getenv('OWNER_ID', ''))
            if not 0 < owner_id < 2**52:
                raise ValueError
        except ValueError:
            raise ValueError('Укажите числовой Telegram ID владельца в OWNER_ID.') from None
        try:
            zone = ZoneInfo(os.getenv('TIMEZONE', 'Asia/Tashkent'))
        except ZoneInfoNotFoundError:
            raise ValueError('Укажите часовой пояс IANA в TIMEZONE.') from None
        level = getattr(logging, os.getenv('LOG_LEVEL', 'INFO').upper(), None)
        if not isinstance(level, int):
            raise ValueError('Укажите уровень журналирования в LOG_LEVEL.')
        app_url = os.getenv('MINI_APP_URL', '').strip()
        if app_url:
            parsed = urlsplit(app_url)
            if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                    or parsed.query or parsed.fragment):
                raise ValueError('В MINI_APP_URL укажите публичный HTTPS-адрес приложения.')
        try:
            ttl = int(os.getenv('INIT_DATA_TTL', '3600'))
            if not 60 <= ttl <= 86400:
                raise ValueError
        except ValueError:
            raise ValueError('Укажите срок действия INIT_DATA_TTL от 60 до 86400 секунд.') from None
        mode = os.getenv('TELEGRAM_UPDATES_MODE', 'polling').strip()
        if mode not in {'polling', 'webhook'}:
            raise ValueError('TELEGRAM_UPDATES_MODE должен быть polling или webhook.')
        webhook_url = os.getenv('RENDER_EXTERNAL_URL', '').rstrip('/') + '/api/telegram/webhook' if mode == 'webhook' else ''
        secret = os.getenv('TELEGRAM_WEBHOOK_SECRET', '')
        if mode == 'webhook' and (not secret or urlsplit(webhook_url).scheme != 'https' or not urlsplit(webhook_url).hostname):
            raise ValueError('Для webhook настройте TELEGRAM_WEBHOOK_SECRET и RENDER_EXTERNAL_URL.')
        return cls(token, owner_id, zone, database_url(), level, app_url, ttl,
                   secret, os.getenv('SCHEDULER_SECRET', ''), mode, webhook_url)
