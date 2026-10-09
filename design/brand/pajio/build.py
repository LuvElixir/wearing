"""Reproducible Pajio lettering/symbol exports and approved PNG icon resizing.

Run with cairosvg and pillow. --wordmark-only skips the pending application icon.
"""
from pathlib import Path
from copy import deepcopy
import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
import cairosvg
from build_icons import export_icons, require_selected_master, MASTER as ICON_MASTER

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
NS = 'http://www.w3.org/2000/svg'
ET.register_namespace('', NS)
WORDMARK_MASTER = ROOT / 'wordmark-custom-v2.svg'
star = 'M12 2C12.8 8.8 14.6 11.2 20 12C14.6 12.8 12.8 15.2 12 22C11.2 15.2 9.4 12.8 4 12C9.4 11.2 11.2 8.8 12 2Z'


def svg(inner, viewbox, title='Pajio'):
    return f'<svg xmlns="{NS}" viewBox="{viewbox}"><title>{title}</title>{inner}</svg>'


def write(name, source, size):
    (ROOT / f'{name}.svg').write_text(source)
    cairosvg.svg2png(bytestring=source.encode(), write_to=str(ROOT / f'{name}.png'), output_width=size)


def export_wordmark():
    source = ET.fromstring(WORDMARK_MASTER.read_text())
    group = source.find(f'{{{NS}}}g')
    if group is None or len(list(group)) != 5 or source.find(f'.//{{{NS}}}text') is not None:
        raise ValueError('Expected five original filled path glyphs; no font/text fallback.')
    viewbox = source.attrib['viewBox']
    x0, y0, width, height = map(float, viewbox.split())
    for suffix, ink in [('', '#202228'), ('-white', '#F0F2F5'), ('-black', '#000000')]:
        glyphs = deepcopy(group)
        glyphs.set('fill', ink)
        body = ET.tostring(glyphs, encoding='unicode')
        write('wordmark'+suffix, svg(body, viewbox, 'Pajio — original geometric lettering'), 1000)
        # Keep the approved single-star geometry and existing color variants.
        write('symbol'+suffix, svg(f'<path fill="{ink}" d="{star}"/>', '0 0 24 24'), 512)
        shifted = f'<g transform="translate({height+12-x0:g} {-y0:g})">{body}</g>'
        symbol = f'<g transform="translate(0 3) scale({(height-6)/24:.5f})"><path fill="{ink}" d="{star}"/></g>'
        write('signature'+suffix, svg(symbol+shifted, f'0 0 {width+height+12:g} {height:g}', 'Pajio — star and original lettering'), 1200)
    manifest = {
        'brand': 'Pajio', 'typeface': 'Original Pajio geometric lettering; no font dependency',
        'wordmark_master': WORDMARK_MASTER.name, 'wordmark_master_sha256': hashlib.sha256(WORDMARK_MASTER.read_bytes()).hexdigest(),
        'wordmark_viewBox': viewbox, 'wordmark_glyphs': ['P', 'a', 'j', 'i', 'o'],
        'wordmark_construction': 'Five individually drawn filled SVG paths; even-odd counters',
        'historical_font_license': 'OFL-Nunito.txt retained for archived work only; not used by current lettering',
        'symbol': 'Existing approved single four-point star; separate from app-icon selection',
        'app_icon': {'selection': 'icon-selection.json', 'state': 'pending redesign; existing icon exports are candidates and must not be released'},
        'character': '../../character/pajama-bear-20261007/selected-character-base.png',
        'outfits': '../../../clients/mobile/assets/bear/',
        'scope': 'Digital identity and mobile assets; protocol and storage identifiers preserved',
    }
    (ROOT / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print(f'Exported original Pajio lettering and single-star symbol to {ROOT}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wordmark-only', action='store_true')
    args = parser.parse_args()
    if not args.wordmark_only:
        require_selected_master()
    export_wordmark()
    if not args.wordmark_only:
        export_icons()
