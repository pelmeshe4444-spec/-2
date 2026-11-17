from datetime import UTC, datetime

from aiogram import Bot
from httpx import ASGITransport, AsyncClient

from backend.api import create_api
from config import Config
from conftest import MONDAY, OWNER
from services.reports import Reports
from test_mini_app_api import TOKEN, auth
from test_telegram_flow import TelegramSession


async def test_webhook_scheduler_and_pages_cors(app, schools, monkeypatch, caplog):
    first, _ = schools
    await app.directory.add_students(OWNER, first.id, [('Пробный', 'Ученик')])
    url = app.db.engine.url.render_as_string(hide_password=False)
    frontend = 'https://example.github.io'
    config = Config(TOKEN, OWNER, app.attendance.zone, url, mini_app_url=frontend + '/attendance/',
                    webhook_secret='webhook-test', scheduler_secret='scheduler-test')
    session = TelegramSession()
    send_tick = Reports.tick

    async def tick(self, bot):
        await send_tick(self, bot, datetime(2026, 11, 16, 4, 0, tzinfo=UTC))

    monkeypatch.setattr(Reports, 'tick', tick)
    async with Bot(TOKEN, session=session) as sender:
        api = create_api(config, app.db, sender=sender)
        async with AsyncClient(transport=ASGITransport(app=api), base_url='https://attendance.test') as http:
            preflight = {'Access-Control-Request-Method': 'GET', 'Access-Control-Request-Headers': 'authorization'}
            assert (await http.options('/api/v1/me', headers={**preflight, 'Origin': frontend})).headers['access-control-allow-origin'] == frontend
            assert (await http.options('/api/v1/me', headers={**preflight, 'Origin': 'https://other.test'})).status_code == 400
            webhook = '/api/telegram/webhook'
            secret = {'X-Telegram-Bot-Api-Secret-Token': config.webhook_secret}
            update = {'update_id': 1, 'message': {'message_id': 1, 'date': 1800000000, 'text': '/start',
                      'chat': {'id': OWNER, 'type': 'private'},
                      'from': {'id': OWNER, 'is_bot': False, 'first_name': 'Проверка'}}}
            assert (await http.post(webhook, json=update)).status_code == 403
            assert (await http.post(webhook, headers=secret, json={})).status_code == 400
            assert (await http.post(webhook, headers=secret, json=update)).json() == {'ok': True}
            assert session.panels[OWNER].reply_markup.inline_keyboard[0][0].web_app.url == config.mini_app_url

            async def fail(*args, **kwargs):
                raise RuntimeError('sensitive details belong in neither HTTP nor logs')

            with monkeypatch.context() as failure:
                failure.setattr(session, 'make_request', fail)
                assert (await http.post(webhook, headers=secret, json=update)).status_code == 503
            assert 'RuntimeError' in caplog.text and 'sensitive details' not in caplog.text

            owner = auth(OWNER)
            base = f'/api/classes/{first.id}'
            previous = session.panels[OWNER].text
            access = f'/api/users/{OWNER}/access'
            assert (await http.post(access, headers=owner, json={
                'class_id': first.id, 'operation': 'manager_add'})).status_code == 400
            assert (await http.post(access, headers=owner, json={
                'class_id': first.id, 'operation': 'recipient_add'})).json()['changed']
            assert session.panels[OWNER].text == previous
            scheduled = await http.put(f'{base}/schedule', headers=owner, json={
                'time': '08:30', 'timezone': 'Asia/Tashkent', 'weekdays': [0], 'enabled': True})
            assert scheduled.json()['enabled']
            path = '/api/internal/scheduler/run'
            assert (await http.post(path, headers={'Authorization': 'Bearer incorrect'})).status_code == 403
            for _ in range(2):
                assert (await http.post(path, headers={'Authorization': 'Bearer ' + config.scheduler_secret})).json() == {'ok': True}
            [delivery] = (await http.get(f'{base}/deliveries', headers=owner)).json()['items']
            assert delivery['kind'] == 'scheduled' and delivery['status'] == 'sent' and delivery['day'] == MONDAY.isoformat()
            assert 'Пробный Ученик' in session.panels[OWNER].text
            assert 'Не отмечены' in session.panels[OWNER].text
