from pathlib import Path
from io import BytesIO
from xml.sax.saxutils import escape
import re
import uharfbuzz as hb
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.boundsPen import BoundsPen
import cairosvg

ROOT = Path(__file__).parent

def outlined(name, text='Wearing', weight=650, size=60, tracking=-0.8):
    path = next((ROOT / 'fonts').glob(name+'-*.ttf'))
    font = TTFont(path)
    if 'fvar' in font:
        axes = {a.axisTag:a for a in font['fvar'].axes}
        requested = {'wght':weight, 'opsz':48, 'SOFT':100, 'WONK':1}
        font = instantiateVariableFont(font, {k:max(axes[k].minValue,min(axes[k].maxValue,v)) for k,v in requested.items() if k in axes}, inplace=False)
    buf = BytesIO(); font.save(buf)
    face = hb.Face(buf.getvalue()); hfont = hb.Font(face)
    upem = font['head'].unitsPerEm
    hfont.scale = (upem, upem)
    buffer = hb.Buffer(); buffer.add_str(text); buffer.guess_segment_properties()
    hb.shape(hfont, buffer, {'kern':True})
    glyphset = font.getGlyphSet(); order = font.getGlyphOrder()
    x=0; paths=[]; boxes=[]
    for info,pos in zip(buffer.glyph_infos,buffer.glyph_positions):
        glyph=glyphset[order[info.codepoint]]
        matrix=(size/upem,0,0,-size/upem,x+pos.x_offset*size/upem,-pos.y_offset*size/upem)
        pen=SVGPathPen(glyphset); glyph.draw(TransformPen(pen,matrix))
        data=re.sub(r'-?\d+\.\d+',lambda m:str(round(float(m.group()),2)),pen.getCommands())
        paths.append(f'<path d="{data}"/>')
        bounds=BoundsPen(glyphset); glyph.draw(TransformPen(bounds,matrix))
        if bounds.bounds:boxes.append(bounds.bounds)
        x+=pos.x_advance*size/upem+tracking
    bbox=(min(b[0] for b in boxes),min(b[1] for b in boxes),max(b[2] for b in boxes),max(b[3] for b in boxes))
    return ''.join(paths),bbox

def svg(body,w,h,title='Wearing design study'):
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}"><title>{title}</title>{body}</svg>'

def render(name,source):
    (ROOT/name).write_text(source)
    cairosvg.svg2png(bytestring=source.encode(),write_to=str(ROOT/name.replace('.svg','.png')))

if __name__=='__main__':
    names='figtree dmsans plusjakartasans nunito quicksand outfit sora urbanist rubik comfortaa balsamiqsans fredoka baloo2 lilitaone sniglet righteous grandstander fraunces dmserifdisplay literata lora biorhyme averiaseriflibre chivo'.split()
    body='<rect width="1440" height="1600" fill="#faf9f6"/>'
    for idx,name in enumerate(names):
        x=36+(idx%3)*475;y=40+(idx//3)*195
        body+=f'<text x="{x}" y="{y}" font-family="sans-serif" font-size="13" fill="#707785">{idx+1:02} / {escape(name)}</text>'
        for text,dy in [('Wearing',68),('wearing',132)]:
            paths,bbox=outlined(name,text)
            body+=f'<g transform="translate({x} {y+dy})" fill="#262d43">{paths}</g>'
    render('type-study.svg',svg(body,1440,1600))
