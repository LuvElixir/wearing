"""Mechanical exports from the next approved generated PNG icon master.

No vector candidate is used as an application icon. The source must be supplied
explicitly as app-icon-p-bear-master.png; absent input fails before any asset is written.
Android color uses the same unchanged raster with safe-zone padding; its monochrome
layer is a separate, explicitly simplified P-and-bear-head vector.
"""
from pathlib import Path
import base64
import hashlib
import json
import shutil
import math
import xml.etree.ElementTree as ET
import cairosvg
from PIL import Image

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
MASTER = ROOT / 'app-icon-p-bear-master.png'
MONO_MASTER = ROOT / 'app-icon-monochrome-master.svg'


def require_selected_master():
    selection = json.loads((ROOT / 'icon-selection.json').read_text())
    if selection.get('status') != 'selected' or selection.get('approved_for_release') is not True:
        raise ValueError('App icon remains a candidate. No icon export or release build is authorized by the selection manifest.')
    if selection.get('master') != MASTER.name:
        raise ValueError('The selected icon master and export source do not match.')


def raster_svg(path, title):
    encoded = base64.b64encode(path.read_bytes()).decode('ascii')
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024"><title>' + title + '</title><image width="1024" height="1024" href="data:image/png;base64,' + encoded + '"/></svg>\n'


def export_icons():
    require_selected_master()
    if not MASTER.is_file():
        raise FileNotFoundError('The revised generated app-icon-p-bear-master.png is not yet approved/present; no icon assets were written.')
    with Image.open(MASTER) as image:
        image.load()
        if image.width != image.height:
            raise ValueError('The approved app icon master must be square; no automatic cropping.')
        rgba = image.convert('RGBA')
        if rgba.getchannel('A').getextrema() != (255, 255):
            raise ValueError('The approved square app icon must be opaque; review its background before exporting.')
        icon = rgba.convert('RGB')
        icon.resize((1024, 1024), Image.Resampling.LANCZOS).save(ROOT / 'app-icon.png')
        for size in (16, 32, 48, 64, 128, 256, 512):
            icon.resize((size, size), Image.Resampling.LANCZOS).save(ROOT / f'icon-{size}.png')
    (ROOT / 'app-icon.svg').write_text(raster_svg(ROOT / 'app-icon.png', 'Pajio P and pajama bear app icon — embedded raster, not vector artwork'))
    # Preserve the complete generated composition, including its background.
    # Padding is mechanical; no fur/letter cutout or pixel redraw is performed.
    foreground = Image.new('RGB', (1024, 1024), '#202630')
    foreground.paste(icon.resize((608, 608), Image.Resampling.LANCZOS), (208, 208))
    foreground.save(ROOT / 'adaptive-foreground.png')
    (ROOT / 'adaptive-foreground.svg').write_text(raster_svg(ROOT / 'adaptive-foreground.png', 'Pajio adaptive foreground — padded generated raster'))
    ET.register_namespace('', 'http://www.w3.org/2000/svg')
    mono = ET.fromstring(MONO_MASTER.read_text())
    shapes = ET.tostring(mono.find('{http://www.w3.org/2000/svg}g'), encoding='unicode')
    mono_svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024"><title>Pajio P and bear head — monochrome vector</title><g transform="translate(147.2 147.2) scale(2.85)">' + shapes + '</g></svg>'
    (ROOT / 'adaptive-monochrome.svg').write_text(mono_svg + '\n')
    cairosvg.svg2png(bytestring=mono_svg.encode(), write_to=str(ROOT / 'adaptive-monochrome.png'), output_width=1024, output_height=1024)
    alpha = Image.open(ROOT / 'adaptive-monochrome.png').convert('RGBA').getchannel('A')
    mask = alpha.load()
    max_radius = max(math.hypot(x + .5 - 512, y + .5 - 512) for y in range(1024) for x in range(1024) if mask[x, y])
    safe_radius = 1024 * 33 / 108
    if max_radius > safe_radius:
        raise ValueError('Monochrome shape exceeds the Android adaptive safe circle.')
    mobile = REPO / 'clients/mobile/assets'
    shutil.copyfile(ROOT / 'app-icon.png', mobile / 'icon.png')
    shutil.copyfile(ROOT / 'icon-48.png', mobile / 'favicon.png')
    shutil.copyfile(ROOT / 'adaptive-foreground.png', mobile / 'android-icon-foreground.png')
    shutil.copyfile(ROOT / 'adaptive-monochrome.png', mobile / 'android-icon-monochrome.png')
    manifest = {'master': MASTER.name, 'master_sha256': hashlib.sha256(MASTER.read_bytes()).hexdigest(),
                'method': 'Pillow Lanczos resizing, no cropping or character redraw',
                'app_icon_svg': 'Embedded PNG wrapper, not a vector recreation',
                'android_adaptive': {'foreground': 'Full generated image scaled to 608px, centered on opaque graphite 1024px canvas',
                                     'monochrome_master': MONO_MASTER.name, 'monochrome_max_radius_px': round(max_radius, 3),
                                     'safe_circle_radius_px': round(safe_radius, 3)},
                'sha256': {str(path.relative_to(REPO)): hashlib.sha256(path.read_bytes()).hexdigest() for path in
                           [MASTER, MONO_MASTER, ROOT/'app-icon.png', ROOT/'app-icon.svg', ROOT/'adaptive-foreground.png', ROOT/'adaptive-foreground.svg',
                            ROOT/'adaptive-monochrome.png', ROOT/'adaptive-monochrome.svg', *[ROOT/f'icon-{size}.png' for size in (16,32,48,64,128,256,512)],
                            *[mobile/name for name in ('icon.png','favicon.png','android-icon-foreground.png','android-icon-monochrome.png')]]}}
    (ROOT / 'icon-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    export_icons()
