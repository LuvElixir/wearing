from study import ROOT, svg, render, outlined
from pathlib import Path
import re

BLUE='#4562DC'
INK='#29334B'
CREAM='#FFF2DC'

# Each portrait is a new native SVG drawing. 256-unit artboards.
AVATARS={
'a':f'''
<path fill="{BLUE}" d="M59 166C37 174 25 195 25 217C25 231 41 237 66 239C104 243 151 243 190 238C215 235 231 226 231 211C231 189 219 173 199 165L59 166Z"/>
<path fill="{INK}" d="M124 25C166 23 204 43 207 84L210 121C212 152 194 172 164 177L102 179C61 180 40 163 39 135L37 98C35 58 70 28 124 25Z"/>
<path fill="{CREAM}" d="M124 33C165 31 197 49 199 85L202 121C204 147 189 165 162 169L102 171C67 172 48 158 47 134L45 98C43 64 74 36 124 33Z"/>
<path fill="{BLUE}" d="M48 168C49 157 57 153 66 157L119 180L105 205C101 213 93 215 87 211L52 188C45 183 44 176 48 168Z"/>
<path fill="#92ACF4" d="M187 163C194 158 203 162 204 170L207 185C208 191 204 195 198 195L175 194L168 182Z"/>
<path fill="{INK}" d="M159 177L136 209C132 215 122 215 118 209L103 182L113 184L126 205L149 177Z"/>
<path fill="{INK}" d="M102 102C98 102 96 106 96 112V121C96 127 98 131 102 131C106 131 108 127 108 121V112C108 106 106 102 102 102ZM159 99C155 99 153 103 153 109V118C153 124 155 128 159 128C163 128 165 124 165 118V109C165 103 163 99 159 99Z"/>
''',
'b':f'''
<path fill="{BLUE}" d="M91 150C58 150 27 171 23 205C21 223 42 235 78 240C117 245 158 242 181 235C210 226 221 206 211 183C201 162 174 149 150 146Z"/>
<path fill="{INK}" d="M55 74C59 40 91 22 131 24C173 26 204 49 203 86L200 119C199 152 173 169 133 169C91 169 59 151 56 121L55 74Z"/>
<path fill="{CREAM}" d="M63 75C67 46 94 30 130 32C168 34 196 54 195 86L192 119C191 147 169 161 133 161C96 161 67 146 64 120L63 75Z"/>
<path fill="{INK}" d="M124 101C120 100 117 104 116 110L115 117C114 123 116 127 120 128C124 129 127 125 128 119L129 112C130 106 128 102 124 101ZM175 108C171 107 168 111 167 116L166 123C165 129 167 133 171 134C175 135 178 131 179 125L180 118C181 112 179 109 175 108Z"/>
<path fill="#92ACF4" d="M72 157C63 152 55 157 57 168L64 186C65 191 70 194 76 191L113 174Z"/>
<path fill="#92ACF4" d="M151 169L128 199L146 199C153 199 160 195 164 189L174 174Z"/>
<path fill="{INK}" d="M188 225C204 218 218 201 224 185C230 169 226 154 215 149C204 145 196 151 192 162C188 158 183 159 180 163C174 173 178 179 184 187L168 209Z"/>
<path fill="{CREAM}" d="M190 182C185 175 183 172 186 168C189 164 194 172 197 171C202 169 201 155 210 156C220 157 222 168 217 182C212 197 202 209 190 215L180 207C190 197 195 188 190 182Z"/>
<path fill="#92ACF4" d="M173 201C180 199 195 208 197 215C198 220 193 224 186 227L176 231L158 215Z"/>
''',
'c':f'''
<path fill="{BLUE}" d="M26 174C22 145 38 119 65 115C91 112 172 114 195 128C217 141 233 173 231 199C229 221 213 233 184 237C151 242 99 241 69 235C40 229 25 207 26 174Z"/>
<path fill="{CREAM}" d="M58 99C51 77 62 53 84 41C105 29 129 26 150 31C183 38 204 61 203 92C202 124 177 145 145 151C106 157 70 142 58 115Z"/>
<path fill="{INK}" d="M104 94C100 94 98 98 98 104V111C98 117 100 121 104 121C108 121 110 117 110 111V104C110 98 108 94 104 94ZM158 87C154 87 152 91 152 97V104C152 110 154 114 158 114C162 114 164 110 164 104V97C164 91 162 87 158 87Z"/>
<path fill="#92ACF4" d="M52 132C71 139 87 150 102 160L114 182C117 187 114 192 108 191L80 183C65 179 54 165 50 149C48 142 48 136 52 132Z"/>
<path fill="{INK}" d="M163 152L147 181C145 185 143 187 139 187C135 187 132 185 130 181L112 156L125 158L139 177L152 153Z"/>
<path fill="#92ACF4" d="M191 143C196 145 202 150 205 157L183 173C176 178 168 177 167 172L165 157Z"/>
'''
}

def wordmark(key):
    name,weight,case,spacing={'a':('fredoka',530,'Wearing',-0.5),'b':('grandstander',530,'Wearing',-0.7),'c':('fraunces',580,'Wearing',-0.8)}[key]
    data,bbox=outlined(name,case,weight,80,spacing)
    # Optical, per-word space is controlled before outlines. One quiet cobalt dot
    # is not added: the mascot carries the colour; the name remains one silhouette.
    x0,y0,x1,y1=bbox
    return svg(f'<g fill="{INK}" transform="translate({-x0+2:.2f} {-y0+2:.2f})">{data}</g>',round(x1-x0+4,2),round(y1-y0+4,2),'Wearing wordmark'),(x1-x0+4,y1-y0+4)

def contents(source):return re.sub(r'^.*?</title>|</svg>$','',source)

def board():
    body='<rect width="1320" height="850" fill="#FAFAF8"/>'
    body+='<text x="56" y="56" font-family="sans-serif" font-size="14" fill="#737780">WEARING / PORTRAIT &amp; WORDMARK STUDY</text>'
    names=['01  /  Soft companion','02  /  A little hello','03  /  Quiet character']
    for i,key in enumerate('abc'):
        x=40+i*426
        avatar=svg(AVATARS[key],256,256,'Wearing portrait')
        render(f'{key}-avatar-v1.svg',avatar)
        wm,(ww,wh)=wordmark(key);render(f'{key}-wordmark-v1.svg',wm)
        body+=f'<text x="{x+16}" y="108" font-family="sans-serif" font-size="14" fill="#737780">{names[i]}</text>'
        body+=f'<g transform="translate({x+82} 143)">{AVATARS[key]}</g>'
        factor=298/ww
        body+=f'<g transform="translate({x+57} 435) scale({factor})">{contents(wm)}</g>'
        body+=f'<path d="M{x+16} 563H{x+396}" stroke="#E0E3E9"/>'
        body+=f'<text x="{x+16}" y="600" font-family="sans-serif" font-size="12" fill="#737780">REAL SIZES / 64 · 32 · 24 · 16 PX</text>'
        for j,s in enumerate([64,32,24,16]):
            body+=f'<g transform="translate({x+24+j*100} {660-s/2}) scale({s/256})">{AVATARS[key]}</g>'
        body+=f'<rect x="{x+16}" y="722" width="380" height="78" rx="16" fill="#F0F2F9"/>'
        body+=f'<g transform="translate({x+32} 741) scale({40/256})">{AVATARS[key]}</g>'
        body+=f'<g transform="translate({x+89} 748) scale({122/ww})">{contents(wm)}</g>'
    render('concepts-v1.svg',svg(body,1320,850))

if __name__=='__main__':board()
