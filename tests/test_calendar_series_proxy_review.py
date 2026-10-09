"""The real product MCP dispatch must reach the shared calendar series book."""
import pytest
from pydantic import ValidationError
from wearing.calendar_series import SeriesError
from wearing.life import LifeBook
from wearing.life_proxy import TOOLS, dispatch
from wearing.store import Store


def test_calendar_series_product_tool_persists_and_checks_identity(tmp_path):
    life = LifeBook(Store(tmp_path / 'fixture.sqlite3'))
    assert [t.name for t in TOOLS].count('calendar_series') == 1
    command = {'action': 'create', 'request_key': 'fixture', 'draft': {
        'template': {'title': 'synthetic event', 'timezone': 'Asia/Shanghai', 'all_day': True,
                     'start_local': '2026-10-08', 'end_local': '2026-10-09'},
        'rule': {'frequency': 'daily', 'count': 2}}}
    result = dispatch(life, 'daily', 'calendar_series', command)
    assert dispatch(LifeBook(Store(life.store.path)), 'daily', 'calendar_series', command) == result
    other = life.store.save_identity('synthetic other')['id']
    with pytest.raises(SeriesError) as denied:
        dispatch(life, other, 'calendar_series', {'action': 'get', 'series_id': result['id']})
    assert denied.value.status == 404
    with pytest.raises(ValidationError):
        dispatch(life, other, 'calendar_series', {'action': 'get', 'series_id': result['id'], 'identity': 'daily'})
    rows = dispatch(life, 'daily', 'calendar_series', {'action': 'query', 'start': '2026-10-08', 'end': '2026-10-10', 'timezone': 'Asia/Shanghai'})
    assert len(rows['items']) == 2
