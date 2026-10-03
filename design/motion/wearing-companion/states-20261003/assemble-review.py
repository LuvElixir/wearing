from pathlib import Path
import subprocess,json
root=Path(__file__).resolve().parent
clips=[('idle-corrected','待命'),('attention-corrected','叫一下'),('listening','听你说'),('thinking','想一想'),('working','我来动手'),('waiting','等你接手')]
font='/System/Library/Fonts/Supplemental/Arial Unicode.ttf'
args=['ffmpeg','-v','error']
for clip,label in clips:args+=['-i',str(root/'output'/f'{clip}-720.mp4')]
graph=[]
for n,(_,label) in enumerate(clips):
    graph.append(f"[{n}:v]scale=240:240,pad=240:320:0:16:color=0xfafafa,drawtext=fontfile='{font}':text='{label}':fontsize=18:fontcolor=0x344cc3:x=(w-tw)/2:y=267[v{n}]")
graph.append('[v0][v1][v2][v3][v4][v5]xstack=inputs=6:layout=0_0|240_0|480_0|0_320|240_320|480_320,pad=720:720:0:40:color=0xfafafa,format=yuv420p[v]')
subprocess.run(args+['-filter_complex',';'.join(graph),'-map','[v]','-t','5','-an','-c:v','libx264','-crf','18','-movflags','+faststart','-y',str(root/'output/states-overview-720.mp4')],check=True)
subprocess.run(['ffmpeg','-v','error','-ss','2.0','-i',str(root/'output/states-overview-720.mp4'),'-frames:v','1','-y',str(root/'output/states-overview.png')],check=True)
