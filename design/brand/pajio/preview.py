"""Loopback-only brand board, with no repository directory browsing."""
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlsplit
import mimetypes

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        route = urlsplit(self.path).path
        name = route.rsplit('/', 1)[-1]
        if self.headers.get('Host') not in ('127.0.0.1:8877', 'localhost:8877'):
            self.send_error(403); return
        if route == '/':
            file = ROOT / 'index.html'
        elif route == '/selected-character-base.png':
            file = REPO / 'design/character/pajama-bear-20261007/selected-character-base.png'
        elif route == '/bear/' + name and name in {p.name for p in (REPO/'clients/mobile/assets/bear').glob('*.png')}:
            file = REPO / 'clients/mobile/assets/bear' / name
        elif route == '/' + name and (ROOT/name).suffix in ('.svg', '.png', '.md', '.json', '.txt') and (ROOT/name).is_file():
            file = ROOT / name
        else:
            self.send_error(404); return
        data = file.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', mimetypes.guess_type(file.name)[0] or 'application/octet-stream')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers(); self.wfile.write(data)

HTTPServer(('127.0.0.1', 8877), Handler).serve_forever()
