"""Install the bounded UI revision. No changes to runtime, dialogue or motion."""
from pathlib import Path
import shutil
from study import ROOT,svg,render
from refine import V2,custom_wordmark

web=ROOT.parents[2]/'src/wearing/web'
mark=svg(V2['b'],256,256,'Wearing · 我在')
wm,(ww,wh)=custom_wordmark('a')
render('wearing-avatar.svg',mark)
render('wearing-wordmark.svg',wm)
shutil.copy2(ROOT/'wearing-avatar.svg',web/'mark.svg')
shutil.copy2(ROOT/'wearing-wordmark.svg',web/'wordmark.svg')
shutil.copy2(ROOT/'fonts/fredoka-OFL.txt',web/'fonts/Fredoka-OFL.txt')

index=(web/'index.html').read_text()
old='<a class="wordmark" href="#conversation-main" aria-label="回到对话">Wearing<span>.</span></a>'
new='<a class="wordmark" href="#conversation-main" aria-label="Wearing · 回到对话"><img src="/assets/wordmark.svg?v=1" width="132" height="35" alt="Wearing"></a>'
assert old in index
index=index.replace(old,new).replace('/assets/mark.svg?v=6','/assets/mark.svg?v=7').replace('/assets/style.css?v=4','/assets/style.css?v=5').replace('/assets/app.js?v=6','/assets/app.js?v=7')
(web/'index.html').write_text(index)
app=(web/'app.js').read_text().replace('/assets/mark.svg?v=6','/assets/mark.svg?v=7')
(web/'app.js').write_text(app)
css=(web/'style.css').read_text()
old='.wordmark{font-family:WearingWordmark,var(--font);font-weight:700;font-size:30px;letter-spacing:-.9px;color:var(--ink);text-decoration:none}.wordmark span{color:var(--blue)}'
new='.wordmark{display:inline-flex;align-items:center;flex-shrink:0;color:var(--ink);text-decoration:none;line-height:1}.wordmark img{display:block;width:132px;height:auto}'
assert old in css
css=css.replace(old,new).replace('.wordmark{font-size:25px}', '.wordmark img{width:112px}')
css=css.replace('@font-face{font-family:WearingWordmark;src:url("/assets/fonts/manrope.ttf") format("truetype");font-weight:700;font-display:swap}', '')
(web/'style.css').write_text(css)
