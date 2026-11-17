import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from time import time
from urllib.parse import parse_qsl


class InvalidInitData(ValueError):
    pass


@dataclass(frozen=True)
class Identity:
    telegram_id: int
    username: str | None
    full_name: str


class TelegramAuth:
    def __init__(self, token, ttl):
        self.key = hmac.digest(b'WebAppData', token.encode(), 'sha256')
        self.ttl = ttl

    def validate(self, raw, *, now=None):
        if not raw or len(raw) > 8192:
            raise InvalidInitData
        try:
            pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True, errors='strict', max_num_fields=32)
            fields = dict(pairs)
            if len(fields) != len(pairs) or any(not re.fullmatch(r'[a-z_]+', name) or '\n' in value for name, value in pairs):
                raise InvalidInitData
            signature = fields.pop('hash')
            if not re.fullmatch(r'[a-f0-9]{64}', signature):
                raise InvalidInitData
            payload = '\n'.join(f'{key}={value}' for key, value in sorted(fields.items()))
            expected = hmac.new(self.key, payload.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                raise InvalidInitData
            age = (time() if now is None else now) - int(fields['auth_date'])
            if not -30 <= age <= self.ttl:
                raise InvalidInitData
            user = json.loads(fields['user'])
            telegram_id = user['id']
            names = [user.get('first_name', ''), user.get('last_name', '')]
            username = user.get('username')
            if (type(telegram_id) is not int or not 0 < telegram_id < 2**52 or user.get('is_bot')
                    or not all(isinstance(name, str) for name in names)
                    or (username is not None and not isinstance(username, str))):
                raise InvalidInitData
            return Identity(telegram_id, username, ' '.join(names).strip())
        except (KeyError, TypeError, ValueError, AttributeError):
            raise InvalidInitData from None
