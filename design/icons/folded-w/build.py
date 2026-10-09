"""Deterministic vector variants. Rendering/bundling uses logo-design and Tauri CLI."""
from pathlib import Path
import re
root = Path(__file__).resolve().parent
source = (root/'wearing-symbol.svg').read_text()
paths = '\n'.join(re.findall(r'<path[^>]*/>', source))
def svg(name, body):
    (root/name).write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" role="img"><title>Wearing</title>'+body+'</svg>\n')
svg('wearing-symbol-black.svg', paths.replace('#97A9F7','#1C2331').replace('#4562DC','#1C2331'))
svg('wearing-symbol-white.svg', paths.replace('#97A9F7','#FFFFFF').replace('#4562DC','#FFFFFF'))
svg('wearing-app.svg','<rect width="256" height="256" fill="#FFFFFF"/><g transform="translate(15.36 15.36) scale(.88)">'+paths+'</g>')
svg('wearing-desktop.svg','<rect x="20" y="20" width="216" height="216" rx="48" fill="#FFFFFF"/><g transform="translate(20.48 20.48) scale(.84)">'+paths+'</g>')
svg('wearing-adaptive.svg','<g transform="translate(28.16 28.16) scale(.78)">'+paths+'</g>')
svg('wearing-adaptive-mono.svg','<g transform="translate(28.16 28.16) scale(.78)">'+paths.replace('#97A9F7','#000000').replace('#4562DC','#000000')+'</g>')
