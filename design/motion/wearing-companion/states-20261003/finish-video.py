"""Normalize the generated clips onto the shared web resting pose, locally.

No inpainting: background matting matches the approved cream/cobalt palette;
short endpoint blends protect decoded swaps from generation/codec drift.
"""
import subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
for name in sys.argv[1:]:
    source=ROOT/'output'/f'{name}-source.mp4'
    graph="""[0:v]scale=720:720,fps=24,trim=end_frame=120,setpts=PTS-STARTPTS,format=rgba,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='if(lt(min(min(r(X,Y),g(X,Y)),b(X,Y)),170),255,clip((max(max(r(X,Y),g(X,Y)),b(X,Y))-min(min(r(X,Y),g(X,Y)),b(X,Y))-9)*255/8,0,255))'[fg];
color=c=0xfafafa:s=720x720:r=24:d=5[bg];
[bg][fg]overlay=shortest=1:format=auto,format=gbrp[clean];
[1:v]scale=720:720,fps=24,format=gbrp[anchor];
[clean][anchor]blend=all_expr='A*clip(min((N-1)/8,(120-N)/8),0,1)+B*(1-clip(min((N-1)/8,(120-N)/8),0,1))':shortest=1,format=yuv420p[v]"""
    subprocess.run(['ffmpeg','-v','error','-i',str(source),'-loop','1','-framerate','24','-i',str(ROOT/'anchor.png'),'-filter_complex',graph,'-map','[v]','-t','5','-an','-c:v','libx264','-preset','slow','-crf','18','-movflags','+faststart','-y',str(ROOT/'output'/f'{name}-720.mp4')],check=True)
    subprocess.run(['ffmpeg','-v','error','-i',str(ROOT/'output'/f'{name}-720.mp4'),'-vf','fps=2,scale=240:240,tile=5x2','-frames:v','1','-y',str(ROOT/'output'/f'{name}-final-review.png')],check=True)
    print(name,'finished 720×720 / 120 frames / silent',flush=True)
