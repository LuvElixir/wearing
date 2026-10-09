"""Room to finish tasks without changing stopped goals or inventing monetary limits."""
import httpx
import pytest
from wearing.app import NewGoal, create_app
from wearing.config import Settings
from wearing.goals import GoalBook, GoalError, DEFAULT_GOAL_STEPS, MAX_GOAL_STEPS
from wearing.hermes import HermesClient
from wearing.store import Store
from pydantic import ValidationError
from test_goals import GoalWire, report


def test_generous_default_and_continuation_beyond_old_ten_round_limit(tmp_path,monkeypatch):
    book=GoalBook(Store(tmp_path/'test.sqlite3'))
    goal=book.create('daily','核对研究资料','只用测试资料','形成可核对的报告')
    assert goal['max_steps']==DEFAULT_GOAL_STEPS==100 and goal['status']=='paused'
    book.control(goal['id'],1,'resume')
    monkeypatch.setattr('wearing.goals.after',lambda seconds:'2000-01-01T00:00:00+00:00')
    for index in range(12):
        task=book.claim(goal['id']); assert task
        book.store.update(task['id'],status='completed_unverified',output=report(summary=f'核对了第 {index+1} 项新资料',decision='continue'))
        book.reconcile()
    current=book.get(goal['id'])
    assert current['status']=='active' and current['used_steps']==12
    reopened=GoalBook(Store(book.store.path)); assert reopened.get(goal['id'])['max_steps']==100


def test_extensions_remain_explicit_and_stop_at_the_shared_maximum(tmp_path):
    book=GoalBook(Store(tmp_path/'test.sqlite3'))
    goal=book.create('daily','研究资料','只用测试资料','有依据',900)
    with pytest.raises(GoalError):book.control(goal['id'],1,'pause',add_steps=100)
    expanded=book.control(goal['id'],1,'resume',add_steps=100)
    assert expanded['max_steps']==MAX_GOAL_STEPS==1000
    with pytest.raises(GoalError):book.control(goal['id'],2,'resume',add_steps=1)
    assert book.get(goal['id'])['revision']==2
    paused=book.control(goal['id'],2,'pause')
    assert paused['status']=='paused' and paused['max_steps']==1000


@pytest.mark.parametrize('value',[0,1001,True,-1,1.5,'100'])
def test_invalid_capacity_is_rejected_at_both_boundaries(tmp_path,value):
    book=GoalBook(Store(tmp_path/'test.sqlite3'))
    with pytest.raises(GoalError):book.create('daily','研究资料','只用测试资料','有依据',value)
    with pytest.raises(ValidationError):NewGoal(objective='研究资料',boundaries='只用测试资料',success_criteria='有依据',max_steps=value)


async def test_api_default_policy_and_large_goal_are_persisted_without_starting(tmp_path):
    settings=Settings(tmp_path,hermes_key='test-key');hermes=HermesClient(settings,httpx.MockTransport(GoalWire()))
    app=create_app(settings,hermes)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as c:
        boot=(await c.get('/api/bootstrap')).json()
        assert boot['goal_policy']=={'default_steps':100,'max_steps':1000,'extension_steps':100}
        c.headers['X-Wearing-Token']=boot['token']
        body={'objective':'验证资料','boundaries':'只使用测试资料','success_criteria':'有核对依据'}
        default=(await c.post('/api/goals',json=body)).json()
        assert default['max_steps']==100 and default['status']=='paused'
        large=await c.post('/api/goals',json={**body,'max_steps':1000})
        assert large.status_code==201 and large.json()['max_steps']==1000
        assert (await c.post('/api/goals',json={**body,'max_steps':1001})).status_code==422
        assert app.state.store.list()==[]
    await hermes.close()
