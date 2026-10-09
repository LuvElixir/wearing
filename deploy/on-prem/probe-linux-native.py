"""Exercise only the explicitly opened synthetic Linux native acceptance page.

Run as the dedicated desktop user. This local provisioning probe supplies its
own one-use decision; it is not an agent endpoint or a substitute for relay tests.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, '/opt/pajio-native')
from linux_computer import LinuxComputerBackend


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    options=parser.parse_args()
    output=options.output
    if output.is_symlink():raise ValueError('unsafe probe directory')
    output.mkdir(mode=0o700,parents=True,exist_ok=True)
    output.chmod(0o700)
    backend=LinuxComputerBackend()
    ready=backend.status()
    if not ready.get('ready'):raise ValueError(ready.get('error','desktop_not_ready'))
    windows=json.loads(backend.dispatch({'action':'list_windows'}))['windows']
    matches=[w for w in windows if w['window_title'].startswith('Pajio Desktop Native Probe') and 'firefox' in w['app'].lower()]
    if len(matches)!=1:raise ValueError('open_exact_synthetic_fixture_first')
    target={k:matches[0][k] for k in ('app','window_id','pid')}
    report={'ready':ready,'target':target,'checks':[]}

    def capture(name=None):
        frame=json.loads(backend.dispatch({'action':'capture',**target}))
        if not frame['window_title'].startswith('Pajio Desktop Native Probe'):
            raise ValueError('probe_window_changed')
        if name:
            image=base64.b64decode(frame['screenshot']['data'])
            path=output/(name+'.png');path.write_bytes(image);path.chmod(0o600)
            report[name]={'sha256':hashlib.sha256(image).hexdigest(),'width':frame['width'],'height':frame['height'],
                          'origin':frame['origin'],'elements':len(frame['elements'])}
        return frame

    def submit(**args):
        used=False
        def once(*_):
            nonlocal used
            if used:return 'deny'
            used=True;return 'once'
        backend.set_approval_callback(once)
        try:result=json.loads(backend.dispatch({'app':target['app'],**args}))
        finally:backend.set_approval_callback(None)
        if not result.get('ok'):raise ValueError('native_action_not_submitted')
        time.sleep(.3)

    initial=capture('initial')
    entries=[e for e in initial['elements'] if e['label']=='Test note' and e['role'] in {'entry','text'}]
    if len(entries)!=1:raise ValueError('synthetic_fixture_entry_not_available')
    note=entries[0]
    submit(action='set_value',element=note['index'],value='Pajio synthetic note')
    edited=capture()
    if 'Pajio synthetic note' not in edited['accessibility_text']:raise ValueError('editable_text_not_observed')
    report['checks'].append('editable_text_observed')
    # Fixture autofocus keeps the text field active; replace via real XTEST keys.
    submit(action='key',keys='ctrl+a')
    capture()
    submit(action='type',text='Pajio keyboard 42')
    typed=capture('typed')
    if 'Pajio keyboard 42' not in typed['accessibility_text']:raise ValueError('typed_text_not_observed')
    report['checks'].append('xtest_keyboard_observed')
    save=next(e for e in typed['elements'] if e['label']=='Save note' and 'button' in e['role'])
    submit(action='click',element=save['index'])
    clicked=capture()
    if 'Saved 1' not in clicked['accessibility_text']:raise ValueError('button_effect_not_observed')
    report['checks'].append('atspi_click_observed')
    submit(action='scroll',direction='down',amount=5)
    scrolled=capture('scrolled')
    if clicked['screenshot']['data']==scrolled['screenshot']['data']:raise ValueError('scroll_pixels_unchanged')
    initial_positions=[e.get('bounds') for e in clicked['elements'] if e['label']=='Scroll section 2']
    later_positions=[e.get('bounds') for e in scrolled['elements'] if e['label']=='Scroll section 2']
    if initial_positions==later_positions:raise ValueError('scroll_geometry_unchanged')
    report['checks'].append('scroll_pixels_and_accessibility_geometry_observed')
    report['ok']=True
    result=output/'report.json';result.write_text(json.dumps(report,indent=2));result.chmod(0o600)
    print(json.dumps(report))


if __name__=='__main__':main()
