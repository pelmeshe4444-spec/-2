import asyncio
import sqlite3

import pytest
from alembic import command
from alembic.config import Config

from config import ROOT
from conftest import MANAGER, MONDAY, OWNER, RECIPIENT, VISITOR
from main import migrate
from services.directory import parse_students
from services.permissions import UserError
from test_mini_app_api import auth, client  # noqa: F401
from test_reports import at


@pytest.mark.parametrize('name', [
    'Малика', 'Иванов Иван', 'Иванов Иван Иванович', 'Мухаммад Али Абдулла ибн Хасан',
    'Абдуллаев Мухаммад Али Абдуллаевич ибн Хасан Каримов',
    'Бир Икки Уч Тўрт Беш Олти Етти Саккиз Тўққиз Ўн',
    "Oʻtkir G‘ulom O'Connor-García", 'Анна-Мария д’Арк', 'A' * 255,
])
def test_student_full_name_ignores_word_count(name):
    assert parse_students('  ' + name.replace(' ', '   ') + '  ', False) == [name]


@pytest.mark.parametrize('text', ['A' * 256, 'Иван\nПётр'])
def test_invalid_single_name_is_rejected_without_truncation(text):
    with pytest.raises(UserError):
        parse_students(text, False)


def test_migration_keeps_student_identity_and_attendance(tmp_path):
    path = tmp_path / 'legacy.sqlite'
    url = f'sqlite+aiosqlite:///{path.as_posix()}'
    cfg = Config(str(ROOT / 'alembic.ini'))
    cfg.attributes['database_url'] = url
    command.upgrade(cfg, '0004')
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO classes (id, name, name_key, is_active) VALUES (3, 'QA', 'qa', 1)")
        db.execute("INSERT INTO users (id, telegram_id, created_at) VALUES (5, 101, '2026-11-16')")
        db.execute("INSERT INTO students (id, last_name, first_name, class_id, active_name_key, is_active, created_at, updated_at) "
                   "VALUES (7, 'Иванов', 'Иван', 3, 'иванов иван', 1, '2026-11-16', '2026-11-16')")
        db.execute("INSERT INTO enrollments (student_id, class_id, starts_on) VALUES (7, 3, '2026-11-16')")
        db.execute("INSERT INTO attendance (id, student_id, date, status, marked_by, updated_at) "
                   "VALUES (11, 7, '2026-11-16', 2, 5, '2026-11-16')")
    migrate(url)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT id, full_name, active_name_key FROM students').fetchall() == [(7, 'Иванов Иван', 'иванов иван')]
        assert db.execute('SELECT student_id FROM enrollments').fetchall() == [(7,)]
        assert db.execute('SELECT student_id, status FROM attendance').fetchall() == [(7, 2)]
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []


async def test_bulk_full_names_edit_search_and_duplicate(client, schools):
    http, _ = client
    path = f'/api/v1/classes/{schools[0].id}/students'
    names = ['Иванов Иван Иванович', 'Мухаммад Али Абдулла ибн Хасан', 'Абдуллаев Мухаммад Али Абдуллаевич ибн Хасан Каримов']
    bulk = {'names': '\n'.join(names), 'bulk': True}
    assert (await http.post(path, headers=auth(OWNER), json={**bulk, 'preview': True})).json()['added'] == names
    assert (await http.get(path, headers=auth(OWNER))).json() == []
    assert (await http.post(path, headers=auth(OWNER), json=bulk)).json()['added'] == names
    assert (await http.post(path, headers=auth(OWNER), json={'full_name': '  ' + names[0].upper()})).json()['added'] == []
    [student] = (await http.get(path, headers=auth(OWNER), params={'q': 'али   абдулла ИБН'})).json()
    assert student['full_name'] == names[1]
    revised = "Oʻtkir G‘ulom O'Connor-García"
    assert (await http.patch(f'/api/v1/students/{student["id"]}', headers=auth(OWNER),
                             json={'full_name': revised})).json()['full_name'] == revised
    [result] = (await http.get(path, headers=auth(OWNER), params={'q': 'garcía'})).json()
    assert result['id'] == student['id'] and result['name'] == revised


async def test_manager_send_is_scoped_and_idempotent_and_does_not_replace_scheduled(client, schools, app):
    http, sender = client
    first, second = schools
    for uid, role in ((MANAGER, 'manager_add'), (RECIPIENT, 'recipient_add')):
        await app.directory.access(OWNER, uid, first.id, role)
    await app.directory.access(OWNER, VISITOR, second.id, 'recipient_add')
    name = 'Абдуллаев Мухаммад Али Абдуллаевич ибн Хасан Каримов'
    await app.directory.add_students(OWNER, first.id, [name])
    _, pupils = await app.directory.students(OWNER, first.id)
    body = {'class_id': first.id, 'request_id': '1' * 32}
    path = '/api/v1/reports/send-now'
    assert (await http.post(path, json=body)).status_code == 401
    for uid in (VISITOR, RECIPIENT):
        assert (await http.post(path, headers=auth(uid), json=body)).status_code == 403
    assert (await http.post(path, headers=auth(MANAGER), json={**body, 'class_id': second.id})).status_code == 403
    assert (await http.post(path, headers=auth(MANAGER), json={**body, 'recipient_id': VISITOR})).status_code == 422
    responses = await asyncio.gather(*(http.post(path, headers=auth(MANAGER), json=body) for _ in range(2)))
    assert all(r.status_code == 200 and r.json()['total'] == 1 for r in responses)
    assert len(sender.messages) == 1 and name in sender.messages[0][1]
    await app.attendance.mark(OWNER, first.id, MONDAY, pupils[0].id, 1)
    assert (await http.post(path, headers=auth(MANAGER), json={**body, 'request_id': '2' * 32})).json()['sent'] == 1
    assert name not in sender.messages[1][1] and 'ПРИСУТСТВУЮТ: 1' in sender.messages[1][1]
    await app.reports.configure(OWNER, first.id, 'is_enabled', True)
    await app.reports.tick(sender, at(app, 9, 0))
    assert [chat for chat, _, _ in sender.messages] == [RECIPIENT] * 3
    base = f'/api/v1/classes/{first.id}'
    assert (await http.get(base + '/reports/last-manual', headers=auth(MANAGER))).json()['sent_at']
    history = (await http.get(base + '/deliveries', headers=auth(OWNER))).json()['items']
    assert {item['kind'] for item in history} == {'manual', 'scheduled'}
    assert all(item['initiated_by'] == MANAGER and item['sent_at'] and item['telegram_message_id']
               for item in history if item['kind'] == 'manual')
    await app.directory.access(OWNER, MANAGER, first.id, 'report_send_off')
    assert (await http.post(path, headers=auth(MANAGER), json={**body, 'request_id': '3' * 32})).status_code == 403


async def test_send_without_telegram_acknowledgement_is_uncertain(client, schools, app, monkeypatch):
    http, sender = client
    first, _ = schools
    await app.directory.access(OWNER, RECIPIENT, first.id, 'recipient_add')

    async def unconfirmed(*args, **kwargs):
        return None

    monkeypatch.setattr(sender, 'send_message', unconfirmed)
    body = {'class_id': first.id, 'request_id': '4' * 32}
    assert (await http.post('/api/v1/reports/send-now', headers=auth(OWNER), json=body)).json()['sent'] == 0
    [delivery] = (await http.get(f'/api/v1/classes/{first.id}/deliveries', headers=auth(OWNER))).json()['items']
    assert delivery['status'] == 'uncertain' and not delivery['telegram_message_id']
