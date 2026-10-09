from concurrent.futures import ThreadPoolExecutor
import pytest
from wearing.goals import GoalBook, GoalError
from wearing.store import Store


def test_app_request_is_durable_scoped_and_does_not_resume(tmp_path):
    store=Store(tmp_path/'db.sqlite3');book=GoalBook(store)
    spec=dict(objective='整理资料',boundaries='只读取资料',success_criteria='收到有来源的总结',request_key='request-123456789')
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(lambda _:book.create('daily',**spec),range(4)))
    assert len({x['id'] for x in results})==1
    assert len(book.list('daily'))==1
    assert results[0]['status']=='paused'
    assert GoalBook(Store(tmp_path/'db.sqlite3')).create('daily',**spec)['id']==results[0]['id']
    with pytest.raises(GoalError):book.create('daily',**{**spec,'objective':'新资料'})
    assert len(book.list('daily'))==1

@pytest.mark.parametrize('key',['short','../1234567890123456','a'*121,4])
def test_invalid_app_keys_do_not_write(tmp_path,key):
    book=GoalBook(Store(tmp_path/'db.sqlite3'))
    with pytest.raises(GoalError):book.create('daily','整理资料','只读取资料','收到总结',request_key=key)
    assert book.list('daily')==[]
