from urllib.parse import urlsplit

from httpx import ASGITransport, AsyncClient

from backend.api import create_api
from backend.desktop import DesktopAccess
from config import Config
from conftest import OWNER


async def test_desktop_unlock_is_one_time_and_owner_cookie_is_local(app, schools):
    config = Config('123456:local-test', OWNER, app.attendance.zone, str(app.db.engine.url))
    desktop = DesktopAccess(OWNER, 8000)
    url = urlsplit(desktop.launch_url)
    api = create_api(config, app.db, desktop=desktop)
    transport = ASGITransport(app=api, client=('127.0.0.1', 50001))
    async with AsyncClient(transport=transport, base_url=desktop.origin) as client:
        assert (await client.get('/api/me')).status_code == 401
        assert (await client.get(url.path, headers={'Host': 'example.org'})).status_code == 403
        login = await client.get(url.path)
        assert login.status_code == 303 and 'HttpOnly' in login.headers['set-cookie']
        assert (await client.get(url.path)).status_code == 404
        assert (await client.get('/api/me')).json()['roles'] == ['OWNER']
        assert (await client.get('/api/classes')).status_code == 200
        assert (await client.put('/api/settings', json={'school': 'Школа'}, headers={'Origin': 'http://127.0.0.1:12345'})).status_code == 403
        assert (await client.put('/api/settings', json={'school': 'Школа'}, headers={'Origin': desktop.origin})).status_code == 200
