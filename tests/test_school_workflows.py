from urllib.parse import urlencode

from httpx import ASGITransport, AsyncClient

from backend.api import create_api
from config import Config
from conftest import MONDAY, OWNER, VISITOR
from database.session import Database
from test_mini_app_api import TOKEN, auth, client  # noqa: F401


async def test_join_request_review_and_member_permissions(client, schools):
    http, sender = client
    first, second = schools
    member, owner = auth(VISITOR), auth(OWNER)
    assert {item['id'] for item in (await http.get('/api/join-requests/me', headers=member)).json()['classes']} == {first.id, second.id}
    request = await http.post('/api/join-requests', headers=member, json={'class_id': second.id})
    assert request.status_code == 201 and request.json()['status'] == 'PENDING'
    path = f'/api/join-requests/{request.json()["id"]}'
    assert (await http.get('/api/join-requests?pending=true', headers=owner)).json()[0]['id'] == request.json()['id']
    assert any(chat == OWNER and 'Новая заявка' in text for chat, text, _ in sender.messages)
    assert (await http.patch(path, headers=member, json={'decision': 'APPROVED'})).status_code == 403
    assert (await http.patch(path, headers=owner, json={'decision': 'REJECTED'})).json()['status'] == 'REJECTED'

    request = await http.post('/api/join-requests', headers=member, json={'class_id': first.id})
    path = f'/api/join-requests/{request.json()["id"]}'
    assert (await http.patch(path, headers=owner, json={'decision': 'APPROVED'})).json()['status'] == 'APPROVED'
    profile = (await http.get('/api/me', headers=member)).json()
    assert profile['roles'] == ['CLASS_MEMBER'] and profile['member']['id'] == first.id
    assert (await http.get(f'/api/classes/{first.id}/timetable', headers=member)).status_code == 200
    assert (await http.get(f'/api/classes/{second.id}/timetable', headers=member)).status_code == 403
    assert (await http.post(f'/api/classes/{first.id}/attendance/mark-all?day={MONDAY}', headers=member)).status_code == 403
    assert (await http.post(f'/api/users/{VISITOR}/access', headers=member,
                            json={'class_id': first.id, 'operation': 'manager_add'})).status_code == 403


async def test_timetable_revision_dates_and_class_isolation(client, schools):
    http, _ = client
    first, second = schools
    owner = auth(OWNER)
    metadata = {'name': 'Математика', 'color': '#2277aa', 'icon': 'calculator'}
    subject = await http.post('/api/subjects', headers=owner, json=metadata)
    assert subject.status_code == 201
    subject_id = subject.json()['id']
    assert (await http.put(f'/api/subjects/{subject_id}', headers=owner,
                           json={**metadata, 'name': 'Алгебра'})).json()['name'] == 'Алгебра'
    replacement = (await http.post('/api/subjects', headers=owner,
                                   json={**metadata, 'name': 'Геометрия'})).json()['id']
    plan = {'name': 'Первая четверть', 'cycle': 'A', 'effective_from': '2026-09-01', 'revision': 0,
            'lessons': [{'weekday': 0, 'lesson_number': 1, 'subject_id': subject_id,
                         'start_time': '08:30', 'end_time': '09:15'}]}
    one = f'/api/classes/{first.id}/timetable'
    two = f'/api/classes/{second.id}/timetable'
    assert (await http.put(one, headers=owner, json=plan)).json()['revision'] == 1
    assert (await http.put(two, headers=owner, json=plan)).json()['revision'] == 1
    moved = {**plan['lessons'][0], 'weekday': 1, 'lesson_number': 2, 'start_time': '09:30', 'end_time': '10:15'}
    edit = {**plan, 'revision': 1, 'lessons': [moved]}
    assert (await http.put(one, headers=owner, json=edit)).json()['lessons'][0]['weekday'] == 1
    assert (await http.put(one, headers=owner, json=edit)).status_code == 409
    assert (await http.get(f'{two}?day={MONDAY}', headers=owner)).json()['days'][0]['lessons'][0]['subject_id'] == subject_id
    assert (await http.get(f'{one}?day={MONDAY}', headers=owner)).json()['days'][0]['lessons'] == []

    path = f'{one}/exceptions/2026-11-17'
    changed = await http.put(path, headers=owner, json={'action': 'replace', 'revision': 0,
                             'lessons': [{**moved, 'subject_id': replacement}]})
    assert changed.json()['lessons'][0]['subject_id'] == replacement
    closed = await http.put(path, headers=owner, json={'action': 'closed', 'revision': 1, 'lessons': []})
    assert closed.json()['action'] == 'closed' and closed.json()['lessons'] == []
    assert (await http.get(f'{one}?day=2026-11-17', headers=owner)).json()['days'][0]['action'] == 'closed'


async def test_all_attendance_statuses_are_exclusive_after_reopening_database(client, app, schools):
    http, _ = client
    first, _ = schools
    owner = auth(OWNER)
    base = f'/api/classes/{first.id}'
    assert (await http.post(f'{base}/students', headers=owner, json={'names': 'Тестов Алексей'})).status_code == 200
    [pupil] = (await http.get(f'{base}/students', headers=owner)).json()
    assert (await http.patch(f'/api/students/{pupil["id"]}', headers=owner,
                             json={'name': 'Тестов Антон'})).status_code == 200
    attendance = f'{base}/attendance'
    path = f'{attendance}/{pupil["id"]}?day={MONDAY}'
    version = ''
    for status in (1, 2, 3, 4, 0, 3):
        response = await http.put(path, headers=owner, json={'status': status, 'version': version,
                                  'reason': 'Проверка' if status in (2, 3, 4) else None})
        assert response.status_code == 200, response.text
        version = response.json()['version']
        data = (await http.get(f'{attendance}?day={MONDAY}', headers=owner)).json()
        assert data['counts'] == [int(value == status) for value in range(5)]

    await app.db.engine.dispose()
    url = app.db.engine.url.render_as_string(hide_password=False)
    reopened = Database(url)
    try:
        api = create_api(Config(TOKEN, OWNER, app.attendance.zone, url), reopened)
        async with AsyncClient(transport=ASGITransport(app=api), base_url='https://attendance.test') as fresh:
            query = urlencode({'start': MONDAY, 'end': MONDAY})
            stats = (await fresh.get(f'{base}/stats?{query}', headers=owner)).json()
            assert stats['counts'] == [0, 0, 0, 1, 0]
            [mark] = (await fresh.get(f'{attendance}?day={MONDAY}', headers=owner)).json()['entries']
            assert mark['status'] == 3 and mark['reason'] == 'Проверка'
    finally:
        await reopened.engine.dispose()
