"""Take the README screenshots from a demo database.

    python scripts/make_demo_db.py demo.db
    python scripts/screenshots.py demo.db

Starts the app on a local port with FINANCE_DB=<demo.db>, drives a headless
Chromium through the DevTools protocol (needs `websocket-client`) and writes
PNG files to docs/screenshots/.
"""
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

import websocket

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'docs', 'screenshots')
APP_PORT, CDP_PORT = 5055, 9333

CLICK = "document.querySelector({sel!r}).click()"

# name, path, width, height, [JS to run after load]
SHOTS = [
    ('dashboard', '/', 1440, 1000, []),
    ('input', '/input', 1440, 760, []),
    ('elenco', '/elenco', 1440, 820, []),
    ('monitor-monthly', '/monitor', 1440, 1000, ["document.querySelector('#heat-period [data-v=\"5\"]').click()"]),
    ('monitor-average', '/monitor', 1440, 560, ["document.querySelector('#heat-agg [data-v=\"media\"]').click()"]),
    ('monitor-change', '/monitor', 1440, 560, ["document.querySelector('#heat-agg [data-v=\"delta\"]').click()"]),
    ('charts-flow', '/grafici?periodo=all', 1440, 820, []),
    ('charts-composition', '/grafici?periodo=all', 1440, 820,
     ["document.querySelector('#flusso-view [data-v=\"sunburst\"]').click()"]),
    ('net-worth', '/patrimonio', 1440, 1050, []),
    ('planned', '/previste', 1440, 820, []),
    ('settings', '/impostazioni', 1440, 1000, []),
    ('mobile-dashboard', '/', 390, 1500, []),
]


class CDP:
    def __init__(self, port):
        for _ in range(60):
            try:
                tabs = json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/json'))
                break
            except Exception:
                time.sleep(0.5)
        page = next(t for t in tabs if t['type'] == 'page')
        self.ws = websocket.create_connection(page['webSocketDebuggerUrl'], max_size=None)
        self.n = 0

    def call(self, method, **params):
        self.n += 1
        self.ws.send(json.dumps({'id': self.n, 'method': method, 'params': params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get('id') == self.n:
                return msg.get('result', {})


def main(db):
    os.makedirs(OUT, exist_ok=True)
    env = dict(os.environ, FINANCE_DB=os.path.abspath(db))
    app = subprocess.Popen([sys.executable, '-c',
                            f"from app import create_app; create_app().run(port={APP_PORT})"],
                           cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    profile = tempfile.mkdtemp()
    browser = subprocess.Popen([shutil.which('chromium-browser') or shutil.which('chromium') or 'google-chrome',
                                '--headless=new', f'--remote-debugging-port={CDP_PORT}', '--no-sandbox',
                                '--hide-scrollbars', '--remote-allow-origins=*', f'--user-data-dir={profile}', 'about:blank'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(2.5)
        cdp = CDP(CDP_PORT)
        cdp.call('Page.enable')
        for name, path, w, h, actions in SHOTS:
            mobile = w < 600
            cdp.call('Emulation.setDeviceMetricsOverride', width=w, height=h, deviceScaleFactor=1.5 if not mobile else 2,
                     mobile=mobile)
            cdp.call('Page.navigate', url=f'http://127.0.0.1:{APP_PORT}{path}')
            time.sleep(4)                      # page + Plotly (CDN) + fonts
            for js in actions:
                cdp.call('Runtime.evaluate', expression=js)
                time.sleep(1.5)
            png = cdp.call('Page.captureScreenshot', format='png')['data']
            with open(os.path.join(OUT, f'{name}.png'), 'wb') as f:
                f.write(base64.b64decode(png))
            print('saved', name)
    finally:
        browser.terminate()
        app.terminate()
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'demo.db')
