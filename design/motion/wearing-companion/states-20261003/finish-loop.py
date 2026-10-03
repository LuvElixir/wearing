"""Local video finishing: match material colors through exposure ramps, close the loop.

Uses approved source videos only; no generation or character retouching. Run with
bundled Python (numpy/Pillow). Sources and the original anchor stay untouched.
"""
import json, subprocess
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'output'/'loops-v4'; OUT.mkdir(exist_ok=True)
WEB=ROOT.parents[3]/'src/wearing/web'
NAMES=['idle','attention','listening','thinking','waiting','working']
def decode(path):
    b=subprocess.check_output(['ffmpeg','-v','error','-i',str(path),'-vf','scale=720:720','-f','rawvideo','-pix_fmt','rgb24','-'])
    return np.frombuffer(b,np.uint8).reshape(-1,720,720,3)
def samples(a):
    a=a.astype(np.float32); r,g,b=np.moveaxis(a,-1,0)
    y=np.arange(720)[:,None]
    head=(r-b>22)&(r>155)&(g>130)&(y<300)
    coat=(b-r>65)&(r<100)&(y>220)&(y<490)
    return np.percentile(a[head],65,axis=0),np.percentile(a[coat],65,axis=0)
ref=np.asarray(Image.open(ROOT/'anchor.png').convert('RGB').resize((720,720)))
target_head,target_coat=samples(ref)
report={}
for name in NAMES:
    src=ROOT/'output'/f'{name}{"-corrected" if name in ["idle","attention"] else ""}-source.mp4'
    raw=decode(src)[:120]
    # The generator changes exposure at both ends. Calibrate each frame's warm
    # head and blue fabric separately with continuous per-channel tone curves.
    # This preserves texture and shading; it does not repaint or move features.
    frames=[]
    for f in raw:
        head,coat=samples(f)
        lut=np.stack([np.interp(np.arange(256),[0,coat[c],head[c],255],[0,target_coat[c],target_head[c],255]) for c in range(3)],axis=1)
        rgb=f.astype(np.float32); lo=rgb.min(axis=2); chroma=rgb.max(axis=2)-lo
        alpha=np.where(lo<170,1,np.clip((chroma-9)/8,0,1))[...,None]
        graded=np.stack([lut[f[...,c],c] for c in range(3)],axis=-1)
        frames.append(graded*alpha+250*(1-alpha))
    frames=np.array(frames,np.float32)
    overlap=4
    weight=(1-np.cos(np.pi*(np.arange(overlap)+1)/overlap))/2
    frames[-overlap:]=frames[-overlap:]*(1-weight[:,None,None,None])+frames[0]*weight[:,None,None,None]
    loop=np.rint(frames).clip(0,255).astype(np.uint8)
    out=OUT/f'{name}.mp4'
    p=subprocess.Popen(['ffmpeg','-v','error','-f','rawvideo','-pixel_format','rgb24','-video_size','720x720','-framerate','24','-i','-',
      '-vf','scale=out_color_matrix=bt709:out_range=tv,format=yuv420p','-an','-c:v','libx264','-preset','slow','-crf','18',
      '-color_range','tv','-colorspace','bt709','-color_trc','bt709','-color_primaries','bt709','-movflags','+faststart','-y',str(out)],stdin=subprocess.PIPE)
    p.communicate(loop.tobytes()); assert p.returncode==0
    final=decode(out); means=np.array([samples(f)[0] for f in final])
    report[name]={'frames':len(final),'duration':len(final)/24,'bytes':out.stat().st_size,
      'head_p65_rgb_range':np.ptp(means,axis=0).round(2).tolist(),
      'head_seam_rgb_delta':np.abs(means[-1]-means[0]).round(2).tolist(),
      'seam_full_frame_mae':round(float(np.abs(final[-1].astype(float)-final[0]).mean()),3),
      'head_p65_first':means[0].round(2).tolist(), 'head_p65_middle':means[len(final)//2].round(2).tolist()}
    sheet=Image.new('RGB',(1440,240),'#fafafa'); draw=ImageDraw.Draw(sheet)
    for j,i in enumerate([0,1,8,len(final)//2,len(final)-2,len(final)-1]):
        sheet.paste(Image.fromarray(final[i]).resize((240,240)),(j*240,0));draw.text((j*240+8,6),f'{name} / {i}',fill='#333333')
    sheet.save(OUT/f'{name}-review.png')
    (WEB/'motion'/f'{name}.mp4').write_bytes(out.read_bytes())
    if name=='idle':
        Image.fromarray(final[0]).save(WEB/'character-poster.png')
    print(name,json.dumps(report[name]),flush=True)
(OUT/'QA.json').write_text(json.dumps(report,indent=2)+'\n')
