"""Run against the isolated PostgreSQL container used by GitHub Actions."""
import argparse
import hmac
import json
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ORIGIN = 'http://127.0.0.1:14183/api/v1'
TEST_TOKEN = '123456:ci-smoke-placeholder'
CLASS_NAME = 'QA Docker Class'
FULL_NAME = 'Абдуллаев Мухаммад Али Абдуллаевич ибн Хасан Каримов Отабеков Ибрагимов Шарифов Азизов Джамшедов'
EDITED_NAME = FULL_NAME + ' Oʻtkir'


def request(path, uid=None, *, method='GET', body=None, status=200):
    headers = {'Content-Type': 'application/json'}
    if uid is not None:
        fields = {'auth_date': str(int(time.time())), 'user': json.dumps({'id': uid, 'first_name': 'QA'})}
        payload = '\n'.join(f'{name}={fields[name]}' for name in sorted(fields))
        secret = hmac.digest(b'WebAppData', TEST_TOKEN.encode(), 'sha256')
        fields['hash'] = hmac.digest(secret, payload.encode(), 'sha256').hex()
        headers['Authorization'] = 'tma ' + urlencode(fields)
    query = Request(ORIGIN + path, method=method, headers=headers,
                    data=json.dumps(body).encode() if body is not None else None)
    try:
        with urlopen(query, timeout=8) as response:
            assert response.status == status, (path, response.status, status)
            return json.load(response)
    except HTTPError as error:
        assert error.code == status, (path, error.code, status)


def create_sample():
    owner = request('/me', 101)
    assert owner['roles'] == ['OWNER'] and not owner['sqlite']
    request('/me', 502)
    request('/admin/dashboard', status=401)
    request('/admin/dashboard', 502, status=403)
    school = request('/classes', 101, method='POST', body={'name': CLASS_NAME}, status=201)
    base = f'/classes/{school["id"]}'
    request(base + '/students', 101, method='POST', body={'full_name': FULL_NAME})
    [pupil] = request(base + '/students', 101)
    assert pupil['full_name'] == FULL_NAME
    assert request(f'/students/{pupil["id"]}', 101, method='PATCH', body={'full_name': EDITED_NAME})['full_name'] == EDITED_NAME
    request(f'{base}/attendance/{pupil["id"]}?day={owner["today"]}', 101, method='PUT', body={'status': 1, 'version': ''})
    pending = request('/join-requests', 502, method='POST', body={'class_id': school['id']}, status=201)
    approval = f'/admin/join-requests/{pending["id"]}/approve'
    request(approval, 502, method='POST', status=403)
    request(approval, 101, method='POST')
    request('/me', 503)
    grant = '/admin/users/503/roles'
    request(grant, 101, method='PATCH', body={'class_id': school['id'], 'operation': 'manager_add'})
    report = {'class_id': school['id'], 'request_id': 'e' * 32}
    assert request('/reports/send-now', 503, method='POST', body=report) == {'sent': 0, 'total': 0, 'pending': 0}
    request(grant, 101, method='PATCH', body={'class_id': school['id'], 'operation': 'report_send_off'})
    request('/reports/send-now', 503, method='POST', body=report, status=403)


def verify_sample():
    health = request('/admin/system-health', 101)
    assert health['database'] == {'state': 'ok', 'engine': 'postgresql'}
    dashboard = request('/admin/dashboard', 101)
    assert dashboard['students'] == 1 and dashboard['attendance'][1] == 1
    [school] = [item for item in request('/classes', 101) if item['active']]
    assert school['name'] == CLASS_NAME
    [student] = request(f'/classes/{school["id"]}/students', 101)
    assert student['full_name'] == EDITED_NAME
    member = request('/me', 502)
    assert member['roles'] == ['CLASS_MEMBER'] and member['member']['id'] == school['id']
    request(f'/classes/{school["id"]}/attendance', 502, status=403)
    print('PostgreSQL admin data, membership and access checks passed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--verify-only', action='store_true')
    if not parser.parse_args().verify_only:
        create_sample()
    verify_sample()
