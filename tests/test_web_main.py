from types import SimpleNamespace

import pytest

import web_main


@pytest.mark.parametrize(('env_port', 'args', 'host', 'port'), [
    (None, [], '127.0.0.1', 8000),
    ('12183', [], '0.0.0.0', 12183),
    ('12183', ['--host', '127.0.0.1', '--port', '12184'], '127.0.0.1', 12184),
])
def test_web_main_binds_to_configured_port(monkeypatch, env_port, args, host, port):
    if env_port is None:
        monkeypatch.delenv('PORT', raising=False)
    else:
        monkeypatch.setenv('PORT', env_port)
    events = []
    fake_config = SimpleNamespace(db_url='sqlite-test')
    monkeypatch.setattr(web_main.Config, 'load', lambda: fake_config)
    monkeypatch.setattr(web_main, 'migrate', lambda url: events.append(('migrate', url)))
    monkeypatch.setattr(web_main, 'Database', lambda url: url)
    monkeypatch.setattr(web_main, 'create_api', lambda config, url: 'api')
    monkeypatch.setattr(web_main.uvicorn, 'run', lambda app, **kw: events.append(('serve', app, kw['host'], kw['port'])))
    web_main.main(args)
    assert events == [('migrate', 'sqlite-test'), ('serve', 'api', host, port)]
