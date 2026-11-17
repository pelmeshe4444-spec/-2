import argparse
import os

import uvicorn

from backend.api import create_api
from config import Config
from database.session import Database
from main import migrate


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Attendance Mini App')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    config = Config.load()
    migrate(config.db_url)
    uvicorn.run(create_api(config, Database(config.db_url)), host=args.host, port=args.port, access_log=False,
                forwarded_allow_ips=os.getenv('FORWARDED_ALLOW_IPS', '127.0.0.1'))
