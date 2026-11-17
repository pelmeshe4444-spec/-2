import asyncio
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from httpx import ASGITransport, AsyncClient

from backend.api import create_api
from backend.auth import InvalidInitData, TelegramAuth
from config import Config
from services.attendance import AttendanceService
from services.directory import Directory
from conftest import MANAGER, MONDAY, OWNER, RECIPIENT, VISITOR
from test_reports import Sender


TOKEN = '123456:local-test'


def telegram_data(user, stamp=None):
    fields = {'auth_date': str(int(time.time()) if stamp is None else stamp),
              'user': json.dumps({'id': user, 'first_name': f'Tест {user}'}, ensure_ascii=False, separators=(',', ':')),
              'signature': 'additional_signed_field'}
    value = '\n'.join(f'{name}={fields[name]}' for name in sorted(fields))
    key = hmac.digest(b'WebAppData', TOKEN.encode(), 'sha256')
    return urlencode({**fields, 'hash': hmac.digest(key, value.encode(), 'sha256').hex()})


def auth(user):
    return {'Authorization': 'tma ' + telegram_data(user)}


def test_telegram_signatures_expiry_duplicates_and_tampering():
    validator = TelegramAuth(TOKEN, 120)
    valid = telegram_data(OWNER, 1000)
    verified = validator.validate(valid, now=1100)
    assert verified.telegram_id == OWNER
    for invalid, now in ((valid, 1121), (valid, 969), (valid + '&auth_date=1000', 1000),
                         (valid.replace('%3A101', '%3A102'), 1000), ('x' * 8193, 1000)):
        with pytest.raises(InvalidInitData):
            validator.validate(invalid, now=now)


@pytest.fixture
async def client(app, monkeypatch):
    monkeypatch.setattr(AttendanceService, 'today', lambda self: MONDAY)
    monkeypatch.setattr(Directory, 'today', lambda self: MONDAY)
    config = Config(TOKEN, OWNER, app.attendance.zone, str(app.db.engine.url))
    sender = Sender()
    api = create_api(config, app.db, sender=sender)
    async with AsyncClient(transport=ASGITransport(app=api), base_url='https://attendance.test') as client:
        yield client, sender


async def test_access_is_server_side_and_block_takes_effect_immediately(client, schools):
    http, _ = client
    a, b = schools
    assert (await http.get('/api/me')).status_code == 401
    assert (await http.get('/api/me', headers=auth(VISITOR))).json()['roles'] == ['USER']
    assert (await http.post('/api/classes', headers=auth(MANAGER), json={'name': '12-А'})).status_code == 403
    for body in ({'class_id': a.id, 'operation': 'manager_add'}, {'class_id': b.id, 'operation': 'recipient_add'}):
        assert (await http.post(f'/api/users/{MANAGER}/access', headers=auth(OWNER), json=body)).status_code == 200
    assert set((await http.get('/api/me', headers=auth(MANAGER))).json()['roles']) == {'MANAGER', 'REPORT_RECIPIENT'}
    assert (await http.get(f'/api/classes/{a.id}/attendance', headers=auth(MANAGER))).status_code == 200
    assert (await http.get(f'/api/classes/{b.id}/attendance', headers=auth(MANAGER))).status_code == 403
    assert (await http.get(f'/api/classes/{b.id}/report', headers=auth(MANAGER))).status_code == 200
    assert (await http.get(f'/api/classes/{a.id}/report', headers=auth(MANAGER))).status_code == 403
    assert (await http.patch(f'/api/users/{MANAGER}', headers=auth(OWNER), json={'blocked': True})).status_code == 200
    assert (await http.get(f'/api/classes/{a.id}/attendance', headers=auth(MANAGER))).status_code == 403
    assert (await http.get('/api/me', headers=auth(MANAGER))).json()['user']['blocked']
    assert (await http.patch(f'/api/users/{MANAGER}', headers=auth(OWNER), json={'blocked': False})).status_code == 200
    assert (await http.get(f'/api/classes/{a.id}/attendance', headers=auth(MANAGER))).status_code == 200


async def test_students_bulk_preview_archive_restore_and_concurrent_marks(client, schools):
    http, _ = client
    a, _ = schools
    headers = auth(OWNER)
    students = f'/api/classes/{a.id}/students'
    body = {'names': 'Иванов Иван\nСидорова Мария\nИванов Иван', 'bulk': True}
    preview = await http.post(students, headers=headers, json={**body, 'preview': True})
    assert len(preview.json()['added']) == 2 and len(preview.json()['duplicates']) == 1
    assert (await http.get(students, headers=headers)).json() == []
    assert (await http.post(students, headers=headers, json=body)).status_code == 200
    base = f'/api/classes/{a.id}/attendance'
    data = (await http.get(base, headers=headers)).json()
    assert data['counts'] == [2, 0, 0, 0, 0]
    first = data['entries'][0]
    path = f'{base}/{first["id"]}?day={MONDAY}'
    responses = await asyncio.gather(*(http.put(path, headers=headers, json={'status': 3, 'version': '', 'reason': reason})
                                       for reason in ('Причина один', 'Причина два')))
    assert sorted(item.status_code for item in responses) == [200, 409]
    assert (await http.post(f'{base}/mark-all?day={MONDAY}', headers=headers)).json()['changed'] == 1
    data = (await http.get(base, headers=headers)).json()
    assert data['counts'] == [0, 1, 0, 1, 0] and data['entries'][0]['author']
    assert (await http.delete(f'/api/students/{first["id"]}', headers=headers)).status_code == 200
    detail = (await http.get(f'/api/students/{first["id"]}', headers=headers)).json()
    assert detail['history'][0]['status'] == 3 and not detail['active']
    assert (await http.post(f'/api/students/{first["id"]}/restore', headers=headers)).json()['active']
    assert (await http.get(base, headers=headers)).json()['counts'] == [0, 1, 0, 1, 0]


async def test_schedule_reports_and_export(client, schools):
    http, sender = client
    a, _ = schools
    owner = auth(OWNER)
    base = f'/api/classes/{a.id}'
    await http.post(f'/api/users/{RECIPIENT}/access', headers=owner, json={'class_id': a.id, 'operation': 'recipient_add'})
    good = {'time': '08:30', 'timezone': 'Asia/Tashkent', 'weekdays': [0, 2], 'enabled': True, 'reminder_one': '08:15'}
    assert (await http.put(f'{base}/schedule', headers=owner, json={**good, 'timezone': 'other'})).status_code == 400
    assert (await http.put(f'{base}/schedule', headers=owner, json=good)).json()['enabled']
    idempotency = {'request_id': 'a' * 32}
    assert (await http.post(f'{base}/send', headers=owner, json=idempotency)).json()['sent'] == 1
    assert (await http.post(f'{base}/send', headers=owner, json=idempotency)).json()['sent'] == 1
    assert len([message for _, message, _ in sender.messages if 'ОТЧЁТ О ПОСЕЩАЕМОСТИ' in message]) == 1
    report = (await http.get(f'{base}/report', headers=auth(RECIPIENT))).json()
    assert report['dates'] == [MONDAY.isoformat()] and 'ОТЧЁТ О ПОСЕЩАЕМОСТИ' in report['parts'][0]
    assert (await http.delete(f'{base}/schedule', headers=owner)).json()['deleted']
    assert (await http.get(f'{base}/deliveries', headers=owner)).json()['items'][0]['status'] == 'sent'
    export = f'{base}/export?start={MONDAY}&end={MONDAY}'
    assert (await http.get(export, headers=auth(RECIPIENT))).status_code == 403
    ticket = (await http.get(f'{export}&ticket=true', headers=owner)).json()
    assert (await http.get(ticket['path'])).content.startswith(b'PK')


async def test_limit_and_backend_no_data_without_signature(client):
    http, _ = client
    for _ in range(180):
        assert (await http.get('/api/me', headers=auth(VISITOR))).status_code == 200
    assert (await http.get('/api/me', headers=auth(VISITOR))).status_code == 429
    assert (await http.get('/api/classes', headers={'X-Telegram-ID': str(OWNER)})).status_code == 401
