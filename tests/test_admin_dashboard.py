from datetime import timedelta

from conftest import MANAGER, MONDAY, OWNER, RECIPIENT, VISITOR
from services.attendance import AttendanceService
from test_mini_app_api import auth, client  # noqa: F401


async def test_admin_dashboard_uses_owner_identity_and_live_database(client, schools):
    http, _ = client
    first, _ = schools
    owner, visitor = auth(OWNER), auth(VISITOR)
    for endpoint in ('dashboard', 'users', 'join-requests', 'audit-logs', 'system-health', 'announcements'):
        path = f'/api/v1/admin/{endpoint}'
        assert (await http.get(path)).status_code == 401
        assert (await http.get(path, headers={**visitor, 'X-Role': 'OWNER'})).status_code == 403
    assert (await http.post(f'/api/classes/{first.id}/students', headers=owner,
                            json={'names': 'Тестовый Ученик'})).status_code == 200
    [pupil] = (await http.get(f'/api/classes/{first.id}/students', headers=owner)).json()
    assert (await http.put(f'/api/classes/{first.id}/attendance/{pupil["id"]}?day={MONDAY}', headers=owner,
                           json={'status': 1, 'version': ''})).status_code == 200
    dashboard = (await http.get('/api/v1/admin/dashboard', headers=owner)).json()
    assert (dashboard['students'], dashboard['classes'], dashboard['attendance']) == (1, 2, [0, 1, 0, 0, 0])
    assert dashboard['trend'][-1]['day'] == str(MONDAY) and dashboard['recent_actions']
    health = (await http.get('/api/v1/admin/system-health', headers=owner)).json()
    assert health['backend'] == 'ok' and health['database'] == {'engine': 'sqlite', 'state': 'ok'}
    assert health['webhook']['state'] == 'not_configured' and health['last_scheduler_success'] is None
    assert not {'token', 'url', 'connection_string'} & health.keys()


async def test_delegated_correction_and_statistics_stay_in_one_class(client, schools, monkeypatch):
    http, _ = client
    first, second = schools
    owner, manager = auth(OWNER), auth(MANAGER)
    path = f'/api/v1/admin/users/{MANAGER}/roles'
    async def grant(operation):
        return await http.patch(path, headers=owner, json={'class_id': first.id, 'operation': operation})

    assert (await http.patch(path, headers=manager, json={'class_id': first.id, 'operation': 'manager_add'})).status_code == 403
    assert (await grant('owner_add')).status_code == 422
    assert (await grant('manager_add')).json()['changed']
    await http.post(f'/api/classes/{first.id}/students', headers=owner, json={'names': 'Тестовый Ученик'})
    [pupil] = (await http.get(f'/api/classes/{first.id}/students', headers=owner)).json()
    monkeypatch.setattr(AttendanceService, 'today', lambda self: MONDAY + timedelta(days=1))
    attendance = f'/api/classes/{first.id}/attendance/{pupil["id"]}?day={MONDAY}'
    assert (await http.put(attendance, headers=manager, json={'status': 1, 'version': ''})).status_code == 403
    assert (await grant('correction_on')).json()['changed']
    assert (await http.put(attendance, headers=manager, json={'status': 1, 'version': ''})).status_code == 200
    params = f'?start={MONDAY}&end={MONDAY}'
    assert (await http.get(f'/api/classes/{first.id}/stats{params}', headers=manager)).status_code == 403
    assert (await grant('statistics_on')).json()['changed']
    assert (await http.get(f'/api/classes/{first.id}/stats{params}', headers=manager)).json()['counts'] == [0, 1, 0, 0, 0]
    assert (await http.get(f'/api/classes/{second.id}/stats{params}', headers=manager)).status_code == 403
    assert (await http.get(f'/api/classes/{first.id}/export{params}', headers=manager)).status_code == 403
    assert (await grant('statistics_off')).json()['changed']
    assert (await http.get(f'/api/classes/{first.id}/stats{params}', headers=manager)).status_code == 403
    report = f'/api/classes/{first.id}/report?day={MONDAY}'
    assert (await http.get(report, headers=manager)).status_code == 403
    assert (await grant('report_view_on')).json()['changed']
    assert (await http.get(report, headers=manager)).status_code == 200
    profile = (await http.get('/api/me', headers=manager)).json()
    assert profile['roles'] == ['MANAGER'] and profile['reports'][0]['can_view_reports']
    events = (await http.get(f'/api/v1/admin/users/{MANAGER}/audit-logs', headers=owner)).json()['items']
    assert {'access.correction_on', 'access.statistics_on', 'access.statistics_off'} <= {row['action'] for row in events}


async def test_school_preferences_and_membership_workflows(client, schools):
    http, _ = client
    first, second = schools
    owner, visitor = auth(OWNER), auth(VISITOR)
    assert (await http.put('/api/settings', headers=owner, json={'school': 'Тест', 'timezone': 'unknown.example'})).status_code == 400
    settings = {'school': 'Школа тестов', 'system_name': 'Журнал', 'timezone': 'Asia/Tashkent',
                'school_days': [4, 0, 2], 'notify_schedule': True, 'lesson_start': '07:40', 'lesson_minutes': 50,
                'report_time': '09:45', 'dashboard_chart': False, 'statistics_days': 30, 'join_retry_days': 2}
    response = await http.put('/api/settings', headers=owner, json=settings)
    assert response.status_code == 200 and response.json()['school_days'] == [0, 2, 4]
    created = await http.post('/api/classes', headers=owner, json={'name': '10-Т'})
    assert created.status_code == 201
    path = f'/api/classes/{created.json()["id"]}'
    assert (await http.get(path + '/schedule', headers=owner)).json()['time'] == '09:45'
    assert (await http.get(path + '/timetable/editor', headers=owner)).json()['slots'][0]['end_time'] == '08:30'
    assert not (await http.delete(path, headers=owner)).json()['active']
    assert (await http.post(path + '/restore', headers=owner)).json()['active']
    assert not (await http.get('/api/v1/admin/dashboard', headers=owner)).json()['trend']

    requested = await http.post('/api/join-requests', headers=visitor, json={'class_id': first.id})
    accept = f'/api/v1/admin/join-requests/{requested.json()["id"]}/approve'
    assert (await http.post(accept, headers=visitor, json={'class_id': second.id})).status_code == 403
    assert (await http.post(accept, headers=owner, json={'class_id': second.id})).json()['class_id'] == second.id
    assert (await http.get('/api/join-requests/me', headers=visitor)).json()['notify_schedule']
    membership = f'/api/v1/admin/users/{VISITOR}/membership'
    assert (await http.put(membership, headers=owner, json={'class_id': first.id})).json()['class_id'] == first.id
    assert (await http.get('/api/me', headers=visitor)).json()['member']['id'] == first.id
    assert (await http.put(membership, headers=owner, json={'class_id': None})).status_code == 200
    assert (await http.get('/api/me', headers=visitor)).json()['roles'] == ['USER']
    requested = await http.post('/api/join-requests', headers=visitor, json={'class_id': first.id})
    assert (await http.post(f'/api/v1/admin/join-requests/{requested.json()["id"]}/reject', headers=owner)).json()['status'] == 'REJECTED'
    assert (await http.post('/api/join-requests', headers=visitor, json={'class_id': first.id})).status_code == 400


async def test_announcement_requires_current_confirmation_and_sends_only_once(client, schools):
    http, sender = client
    first, second = schools
    owner = auth(OWNER)
    await http.put(f'/api/v1/admin/users/{VISITOR}/membership', headers=owner, json={'class_id': first.id})
    await http.put(f'/api/v1/admin/users/{RECIPIENT}/membership', headers=owner, json={'class_id': second.id})
    base = '/api/v1/admin/announcements'
    body = {'class_ids': [first.id], 'message': 'Проверочное объявление'}
    preview = (await http.post(base + '/preview', headers=owner, json=body)).json()
    assert preview['recipients'] == 1
    payload = {**body, 'request_id': 'b' * 32, 'confirmation': preview['confirmation']}
    assert (await http.post(base, headers=owner, json={**payload, 'message': 'Другой текст'})).status_code == 409
    for _ in range(2):
        assert (await http.post(base, headers=owner, json=payload)).status_code == 202
    assert [chat for chat, text, _ in sender.messages if text == body['message']] == [VISITOR]
    [entry] = (await http.get(base, headers=owner)).json()
    assert entry['statuses'] == {'sent': 1}
