import logging
import secrets
from time import monotonic

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse

from backend.auth import Identity


log = logging.getLogger(__name__)
COOKIE = 'attendance_desktop'


class DesktopAccess:
    def __init__(self, owner_id: int, port: int):
        self.host = f'127.0.0.1:{port}'
        self.origin = f'http://{self.host}'
        self.identity = Identity(owner_id, None, 'Владелец')
        self._launch_key = secrets.token_urlsafe(32)
        self._expires = monotonic() + 120
        self._session = secrets.token_urlsafe(32)
        self._authenticated = False

    @property
    def launch_url(self):
        return f'{self.origin}/desktop/open/{self._launch_key}'

    def is_local(self, request: Request) -> bool:
        return (request.client is not None and request.client.host == '127.0.0.1'
                and request.headers.get('host') == self.host)

    def authenticate(self, request: Request) -> Identity | None:
        supplied = request.cookies.get(COOKIE, '').encode()
        if self.is_local(request) and secrets.compare_digest(supplied, self._session.encode()):
            if request.method not in ('GET', 'HEAD') and request.headers.get('origin') != self.origin:
                raise HTTPException(403, 'Действие доступно только из открытой локальной панели.')
            if not self._authenticated:
                self._authenticated = True
                log.info('Owner dashboard session authenticated')
            return self.identity
        return None

    async def open(self, request: Request, key: str):
        if (not self.is_local(request) or not self._launch_key or monotonic() > self._expires
                or not secrets.compare_digest(key.encode(), self._launch_key.encode())):
            raise HTTPException(404, 'Ссылка входа истекла. Запустите локальную панель снова.')
        self._launch_key = ''
        response = RedirectResponse('/', status_code=303, headers={'Cache-Control': 'no-store'})
        response.set_cookie(COOKIE, self._session, path='/api', httponly=True, samesite='strict')
        log.info('Local browser session opened')
        return response
