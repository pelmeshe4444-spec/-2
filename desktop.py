import argparse
import asyncio
import logging
import socket
import webbrowser
from logging.handlers import RotatingFileHandler

import uvicorn

from backend.api import create_api
from backend.desktop import DesktopAccess
from config import ROOT, Config
from database.session import Database
from main import migrate


async def run(config, listener):
    port = listener.getsockname()[1]
    desktop = DesktopAccess(config.owner_id, port)
    app = create_api(config, Database(config.db_url), desktop=desktop)
    server = uvicorn.Server(uvicorn.Config(app, access_log=False, log_config=None, proxy_headers=False))
    running = asyncio.create_task(server.serve(sockets=[listener]))
    while not server.started and not running.done():
        await asyncio.sleep(0.1)
    if server.started:
        logging.info('Attendance is ready at %s', desktop.origin)
        opened = await asyncio.to_thread(webbrowser.open_new_tab, desktop.launch_url)
        if not opened:
            server.should_exit = True
            logging.error('Windows could not open the default browser.')
    await running


def main():
    parser = argparse.ArgumentParser(description='Запустить локальную панель Attendance и открыть браузер')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    logs = ROOT / 'data'
    logs.mkdir(exist_ok=True)
    handler = RotatingFileHandler(logs / 'attendance-desktop.log', maxBytes=1_000_000, backupCount=2, encoding='utf-8')
    logging.basicConfig(handlers=[handler], level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    try:
        config = Config.load()
        if not (ROOT / 'frontend' / 'dist' / 'index.html').is_file():
            raise ValueError('Сначала выполните npm.cmd --prefix frontend run build.')
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', args.port))
            listener.listen(socket.SOMAXCONN)
            migrate(config.db_url)
            asyncio.run(run(config, listener))
    except OSError as exc:
        logging.error('Не удалось запустить локальную панель (%s).', exc.errno)
        return 1
    except ValueError as exc:
        logging.error('%s', exc)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
