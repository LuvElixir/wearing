from contextlib import contextmanager
import json
import pytest
from wearing.desktop_capture import capture_with_text


def test_retains_text_from_same_snapshot_without_second_native_request():
    class Backend:
        count=0
        def _fetch_or_refetch(self,*_,**__):
            self.count+=1
            return {'data':'Window\n[0] AXWindow "Test"\n  [1] AXStaticText = "clicked"\n  [2] AXTextField = "value"'}
    backend=Backend()
    @contextmanager
    def bound(**_):yield backend
    def dispatch(args,**_):
        backend._fetch_or_refetch('get_window_state',{},30)
        return json.dumps({'app':'Test','elements':[{'index':2,'label':'input'}]})
    text=lambda r:(r['data'].split('\n',1)[1],'Test')
    result=json.loads(capture_with_text({'action':'capture'},dispatch,bound,text,'test'))
    assert 'AXStaticText = "clicked"' in result['accessibility_text']
    assert 'AXTextField = "value"' in result['accessibility_text']
    assert backend.count==1 and '_fetch_or_refetch' not in vars(backend)
    assert result['elements']==[{'index':2,'label':'input'}]


def test_capture_exception_always_restores_driver_method():
    class Backend:pass
    backend=Backend();original=lambda *_:{};backend._fetch_or_refetch=original
    @contextmanager
    def bound(**_):yield backend
    def dispatch(*_,**__):raise RuntimeError('unavailable')
    with pytest.raises(RuntimeError):capture_with_text({'action':'capture'},dispatch,bound,lambda r:('',''),'test')
    assert backend._fetch_or_refetch is original
