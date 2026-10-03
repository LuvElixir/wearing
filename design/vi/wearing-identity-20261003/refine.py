from study import ROOT, svg, render, outlined
from concepts import BLUE, INK, CREAM, contents, wordmark
import re
from fontTools.svgLib.path import parse_path
from fontTools.pens.svgPathPen import SVGPathPen
import pathops

BLUE='#4264DF'
DEEP='#2C449A'
LIGHT='#A7BEFF'
CREAM='#F8ECD8'
INK='#29313C'

# Final-path construction: soft head, ink eyes, shirt, rolled cuff.
# The loose sketches are interpretation references; every shape below is editable.
V2={
'a':f'''
<path fill="{BLUE}" d="M50 146C33 157 28 178 19 200L8 230H244L229 190C221 165 216 144 195 141Z"/>
<path fill="{DEEP}" d="M164 157C179 148 192 144 207 148C205 165 190 180 179 192L164 223L137 192Z"/>
<path fill="{CREAM}" d="M37 82C39 65 57 50 89 38C119 27 153 18 179 20C201 21 212 31 219 49C227 69 234 93 234 111C234 130 220 143 195 155C169 168 136 177 108 174C83 172 67 161 59 146C50 129 34 103 37 82Z"/>
<path fill="{BLUE}" d="M51 144C73 135 100 138 116 147C113 154 107 166 106 180C89 180 82 174 73 174C62 174 54 183 40 182C24 180 20 161 33 151C38 148 44 146 51 144Z"/>
<path fill="{CREAM}" d="M119 188C114 173 112 160 119 148C126 136 142 133 155 138C172 144 177 156 174 173C173 182 168 194 161 200Z"/>
<path fill="{LIGHT}" d="M106 169C119 161 141 167 162 180C177 189 186 202 182 213C180 220 174 226 166 230H141L101 201C92 189 93 177 106 169Z"/>
<path fill="{BLUE}" d="M94 190C113 186 129 196 146 209C155 216 162 224 164 230H41C48 213 68 195 94 190Z"/>
<path fill="{INK}" d="M124 100C120 101 119 105 121 110L123 116C125 121 128 124 132 123C136 122 137 118 135 113L133 107C131 102 128 99 124 100ZM183 80C179 81 178 85 180 90L182 96C184 101 187 104 191 103C195 102 196 98 194 93L192 87C190 82 187 79 183 80Z"/>
''',
'b':f'''
<path fill="{DEEP}" d="M32 230L50 191C57 174 68 158 86 153L173 145C194 152 204 170 212 190L229 230Z"/>
<path fill="{BLUE}" d="M38 226L56 193C63 177 73 164 89 159L173 151C190 158 199 174 207 192L221 226Z"/>
<path fill="{DEEP}" d="M30 87C25 62 45 45 75 34C104 23 145 13 166 18C184 22 196 41 204 68C212 91 218 114 207 132C194 150 165 161 133 168C96 176 65 170 52 151C43 137 34 108 30 87Z"/>
<path fill="{CREAM}" d="M34 87C29 65 48 49 77 38C106 27 145 17 165 22C181 26 192 44 200 69C208 92 213 113 203 129C191 146 163 157 132 164C98 172 68 167 55 149C47 135 38 107 34 87Z"/>
<path fill="{DEEP}" d="M77 160C92 154 116 156 133 163L157 195L140 218C125 213 127 199 115 194C103 188 92 192 81 186C70 180 67 165 77 160Z"/>
<path fill="{BLUE}" d="M77 164C91 158 114 161 129 166L142 186C142 192 137 197 132 194C121 179 114 185 104 184L84 181C75 179 71 167 77 164Z"/>
<path fill="{DEEP}" d="M183 206C206 188 224 164 230 141L209 116C185 128 177 151 161 168Z"/>
<path fill="{BLUE}" d="M184 200C203 184 218 165 224 143L209 122C190 134 181 153 167 169Z"/>
<path fill="{DEEP}" d="M199 116C198 96 211 74 226 74C242 74 250 90 247 105C244 120 234 134 225 144C211 142 199 129 199 116Z"/>
<path fill="{CREAM}" d="M203 116C202 99 213 78 226 78C239 78 246 91 243 104C240 118 231 131 224 139C213 136 203 126 203 116Z"/>
<path fill="{DEEP}" d="M198 111C201 129 212 141 230 143C232 154 226 166 219 171C207 179 187 166 179 151C171 136 181 116 198 111Z"/>
<path fill="{LIGHT}" d="M194 116C199 133 211 145 226 147C226 156 222 163 217 167C208 173 191 161 183 149C177 137 184 122 194 116Z"/>
<path fill="{INK}" d="M108 94C104 95 103 99 105 104L107 110C109 115 112 118 116 117C120 116 121 112 119 107L117 101C115 96 112 93 108 94ZM163 77C159 78 158 82 160 87L162 93C164 98 167 101 171 100C175 99 176 95 174 90L172 84C170 79 167 76 163 77Z"/>
''',
'c':f'''
<path fill="{BLUE}" d="M52 133C31 136 22 153 27 173L8 229H248L230 181C238 160 227 142 207 139Z"/>
<path fill="{DEEP}" d="M55 169C70 180 86 183 96 175C103 169 108 169 117 186L125 216L141 182C148 171 159 171 166 181C177 194 201 185 220 170L209 151L65 151Z"/>
<path fill="{CREAM}" d="M46 53C49 29 66 19 94 20C127 20 171 24 199 33C219 39 224 52 222 76L218 132C217 151 206 162 184 166L132 174C111 177 77 164 54 153C44 148 39 140 39 127Z"/>
<path fill="{LIGHT}" d="M53 153C89 165 107 177 128 207C147 181 166 168 200 163L185 177C161 187 141 204 130 224L119 209C104 188 76 172 53 153Z"/>
<path fill="{BLUE}" d="M51 151C64 166 86 172 99 185C89 185 86 197 71 194C53 191 35 181 30 174C24 164 29 143 42 143Z"/>
<path fill="{BLUE}" d="M206 152C192 170 165 176 153 190C163 188 165 199 179 198C198 197 220 184 226 174C232 163 225 146 217 146Z"/>
<path fill="{INK}" d="M97 86C93 86 91 90 91 95L90 103C90 108 92 112 96 112C100 112 102 109 102 104L103 95C103 90 101 86 97 86ZM165 93C161 93 159 97 159 102L158 110C158 115 160 119 164 119C168 119 170 116 170 111L171 102C171 97 169 93 165 93Z"/>
'''
}

def custom_wordmark(key):
    name,weight,spacing={'a':('fredoka',530,-0.45),'b':('grandstander',530,-0.7),'c':('fraunces',580,-0.8)}[key]
    data,bbox=outlined(name,'Wearing',weight,80,spacing)
    x0,y0,x1,y1=bbox
    if key=='a':
        # Cuff-like terminal on the g. Boolean outline, no masks or raster.
        last=re.findall(r'<path d="(.*?)"',data)[-1]
        glyph=pathops.Path(); parse_path(last,glyph.getPen())
        cutter=pathops.Path(); p=cutter.getPen()
        p.moveTo((250,2));p.lineTo((276,2));p.lineTo((281,25));p.lineTo((250,25));p.closePath()
        tail=pathops.op(glyph,cutter,pathops.PathOp.INTERSECTION)
        pen=SVGPathPen(None);tail.draw(pen)
        d=re.sub(r'-?\d+\.\d+',lambda m:str(round(float(m.group()),2)),pen.getCommands())
        data+=f'<path fill="{BLUE}" d="{d}"/>'
    source=svg(f'<g fill="{INK}" transform="translate({-x0+2:.2f} {-y0+2:.2f})">{data}</g>',round(x1-x0+4,2),round(y1-y0+4,2),'Wearing')
    return source,(x1-x0+4,y1-y0+4)

def create():
    body='<rect width="1320" height="870" fill="#FAFAF8"/>'
    body+='<text x="48" y="56" font-family="sans-serif" font-size="14" fill="#737780">WEARING / A LITTLE MORE YOU</text>'
    names=['01 / Curious companion','02 / A little hello','03 / Quiet company']
    for i,key in enumerate('abc'):
        x=32+i*428
        avatar=svg(V2[key],256,256,'Wearing portrait')
        render(f'{key}-avatar-v2.svg',avatar)
        wm,(ww,wh)=custom_wordmark(key);render(f'{key}-wordmark-v2.svg',wm)
        body+=f'<text x="{x+16}" y="112" font-family="sans-serif" font-size="14" fill="#737780">{names[i]}</text>'
        body+=f'<g transform="translate({x+67} 154) scale(1.1)">{V2[key]}</g>'
        factor=304/ww
        body+=f'<g transform="translate({x+53} 461) scale({factor})">{contents(wm)}</g>'
        body+=f'<path d="M{x+16} 595H{x+396}" stroke="#E0E3E9"/>'
        body+=f'<text x="{x+16}" y="625" font-family="sans-serif" font-size="12" fill="#737780">64 / 32 / 24 / 16 PX</text>'
        for j,s in enumerate([64,32,24,16]):
            body+=f'<g transform="translate({x+24+j*100} {688-s/2}) scale({s/256})">{V2[key]}</g>'
        body+=f'<rect x="{x+16}" y="746" width="380" height="78" rx="16" fill="#F0F2F9"/>'
        body+=f'<g transform="translate({x+32} 765) scale({40/256})">{V2[key]}</g>'
        body+=f'<g transform="translate({x+89} 772) scale({122/ww})">{contents(wm)}</g>'
    render('concepts-v2.svg',svg(body,1320,870))

if __name__=='__main__': create()
