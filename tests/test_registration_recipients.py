import asyncio
import logging
import os
from uuid import uuid4

from aiogram import Bot
from aiogram.methods import SetWebhook
from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import func, select

from backend.api import create_api
from config import Config
from conftest import OWNER
from database.models import ClassMembership, ReportRecipient, User, UserRole
from database.session import Database
from main import migrate, serve
from services.application import AttendanceApplication
from test_mini_app_api import TOKEN, auth
from test_telegram_flow import TelegramSession


@pytest.fixture
async def registration_app(app):
    url = os.getenv('ATTENDANCE_REGISTRATION_TEST_DATABASE_URL')
    if not url:
        yield app
        return
    await asyncio.to_thread(migrate, url)
    db = Database(url)
    core = AttendanceApplication(db, Config(TOKEN, OWNER, app.attendance.zone, url))
    await core.directory.register(OWNER, None, 'QA Owner')
    try:
        yield core
    finally:
        await db.engine.dispose()


@pytest.mark.parametrize('already_opened_app', [False, True])
async def test_start_to_recipient_without_class_membership(registration_app, already_opened_app, caplog):
    core = registration_app
    uid = 9_876_543_210 + uuid4().int % 1_000_000_000
    school = await core.directory.add_class(OWNER, 'QA registration ' + uuid4().hex[:8])
    config = Config(TOKEN, OWNER, core.attendance.zone, core.db.engine.url.render_as_string(hide_password=False),
                    mini_app_url='https://example.github.io/attendance/', webhook_secret='registration-test-secret')
    secret = {'X-Telegram-Bot-Api-Secret-Token': config.webhook_secret}
    candidate_path = f'/api/v1/admin/recipient-candidates?class_id={school.id}&q={uid}'
    assignment_path = f'/api/v1/users/{uid}/access'
    assignment = {'class_id': school.id, 'operation': 'recipient_add'}
    session = TelegramSession()
    caplog.set_level(logging.WARNING, logger='httpx')
    caplog.set_level(logging.INFO)
    async with Bot(TOKEN, session=session) as bot:
        async with AsyncClient(transport=ASGITransport(app=create_api(config, core.db, sender=bot)),
                               base_url='https://attendance.test') as http:
            assert (await http.post(assignment_path, headers=auth(OWNER), json=assignment)).status_code == 400
            if already_opened_app:
                assert not (await http.get('/api/v1/me', headers=auth(uid))).json()['user']['started']
            assert (await http.get(candidate_path, headers=auth(OWNER))).json()['total'] == 0
            update = {'update_id': 400, 'message': {'message_id': 400, 'date': 1800000000,
                      'text': '/start', 'entities': [{'type': 'bot_command', 'offset': 0, 'length': 6}],
                      'chat': {'id': uid, 'type': 'private'},
                      'from': {'id': uid, 'is_bot': False, 'first_name': 'PrivateNameSentinel', 'username': 'private_username'}}}
            webhook = '/api/telegram/webhook'
            assert (await http.post(webhook, json=update)).status_code == 403
            assert (await http.post(webhook, headers=secret, json=update)).json() == {'ok': True}
            assert session.panels[uid].reply_markup.inline_keyboard[0][0].web_app.url == config.mini_app_url
            first = (await http.get(candidate_path, headers=auth(OWNER))).json()['users']
            assert len(first) == 1 and first[0]['id'] == uid and first[0]['started']
            update['message']['from']['first_name'] = 'UpdatedPrivateName'
            assert (await http.post(webhook, headers=secret, json=update)).status_code == 200
            assert (await http.get(candidate_path, headers=auth(OWNER))).json()['users'][0]['name'] == 'UpdatedPrivateName'
            assert (await http.get(candidate_path, headers=auth(uid))).status_code == 403
            assert (await http.get(candidate_path)).status_code == 401
            assert (await http.post(assignment_path, headers=auth(uid), json=assignment)).status_code == 403
            for changed in (True, False):
                assert (await http.post(assignment_path, headers=auth(OWNER), json=assignment)).json()['changed'] is changed
            assert (await http.get(candidate_path, headers=auth(OWNER))).json()['total'] == 0
            team = (await http.get(f'/api/v1/classes/{school.id}/access', headers=auth(OWNER))).json()
            assert [item['user']['id'] for item in team['recipients']] == [uid]

    # A new connection verifies the committed PostgreSQL/SQLite state and numeric ID.
    check = Database(config.db_url)
    try:
        async with check.read() as db:
            assert await db.scalar(select(func.count(User.id)).where(User.telegram_id == uid)) == 1
            user = await db.scalar(select(User).where(User.telegram_id == uid))
            assert type(user.telegram_id) is int and user.telegram_id == uid and user.started_at
            assert user.full_name == 'UpdatedPrivateName'
            assert await db.get(ClassMembership, user.id) is None
            assert await db.get(ReportRecipient, (user.id, school.id))
            assert await db.get(UserRole, (user.id, 'REPORT_RECIPIENT'))
    finally:
        await check.engine.dispose()
    assert 'telegram_registration committed' in caplog.text
    assert 'telegram_webhook processed' in caplog.text
    assert 'recipient_assignment committed' in caplog.text
    for private in ('PrivateNameSentinel', 'UpdatedPrivateName', 'private_username', str(uid), TOKEN, config.webhook_secret):
        assert private not in caplog.text


async def test_candidates_search_and_blocked_accounts(app, schools):
    school, other = schools
    uid = 8_123_456_789
    await app.directory.register(uid, 'Parent_Example', 'Родитель без класса')
    await app.directory.access(OWNER, uid, other.id, 'recipient_add')
    users, _, total = await app.directory.recipient_candidates(OWNER, school.id, 0, '@parent_example')
    assert total == 1 and users[0].telegram_id == uid
    assert (await app.directory.recipient_candidates(OWNER, school.id, 0, 'parent%'))[2] == 0
    await app.directory.manage_user(OWNER, uid, blocked=True)
    assert (await app.directory.recipient_candidates(OWNER, school.id, 0, str(uid)))[2] == 0


async def test_webhook_startup_registers_without_dropping_updates(app):
    class WebhookSession(TelegramSession):
        calls = []

        async def make_request(self, bot, method, timeout=None):
            if isinstance(method, SetWebhook):
                self.calls.append(method)
                return True
            return await super().make_request(bot, method, timeout)

    config = Config(TOKEN, OWNER, app.attendance.zone, app.db.engine.url.render_as_string(hide_password=False),
                    updates_mode='webhook', webhook_url='https://attendance.test/api/telegram/webhook',
                    webhook_secret='startup-webhook-secret')
    session = WebhookSession()
    async with Bot(TOKEN, session=session) as bot:
        api = create_api(config, app.db, sender=bot)
        async with api.router.lifespan_context(api):
            [call] = session.calls
            assert call.url == config.webhook_url and call.secret_token == config.webhook_secret
            assert call.drop_pending_updates is False
            assert call.allowed_updates == ['message', 'callback_query']
    with pytest.raises(ValueError, match='web_main'):
        await serve(config)
