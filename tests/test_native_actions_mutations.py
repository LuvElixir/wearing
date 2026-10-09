"""Synthetic phone receipts only. No EventKit or provider calls."""
from datetime import timedelta
import copy
import pytest

from test_native_actions import env, PHONE, SECRET, SESSION, POLICY, request, claim, finish
from wearing.native_actions import NativeActions, NativeActionError


def enable(book):
    policy = {**POLICY, 'calendar_edit': True, 'reminder_edit': True}
    book.configure('daily', PHONE, SECRET, 1, True, policy)
    book.connect('daily', PHONE, SECRET, 2, SESSION,
                 ['calendar.read', 'reminders.read', 'calendar.update', 'calendar.delete', 'reminders.update', 'reminders.delete'])


def read(book, kind='calendar', *, recurring=False, mutable=True):
    params = {'calendar_ids': ['cal'], 'start': '2026-10-08T00:00:00Z', 'end': '2026-10-09T00:00:00Z'} if kind == 'calendar' else {'calendar_ids': ['rem']}
    r = request(book, kind + '.read', params, 'read-one')
    item = {'id': 'original-system-id', 'calendar_id': 'cal' if kind == 'calendar' else 'rem', 'title': 'Synthetic original', 'notes': 'Keep these notes', 'all_day': False if kind == 'calendar' else None,
            'snapshot': {'revision': 'e' * 64, 'recurring': recurring, 'occurrence_start': '2026-10-08T01:00:00Z' if kind == 'calendar' else None, 'mutable': mutable}}
    item.update({'start': '2026-10-08T01:00:00Z', 'end': '2026-10-08T02:00:00Z'} if kind == 'calendar' else {'due': '2026-10-09T01:00:00Z', 'completed': False})
    claim(book, r)
    response = finish(book, r, data={'items': [item], 'returned': 1, 'has_more': False, 'text_may_be_truncated': True})
    return response, item


@pytest.mark.parametrize('method', ['calendar.update', 'calendar.delete', 'reminders.update', 'reminders.delete'])
def test_mutation_uses_verified_read_reference_claim_and_exact_receipt(env, method):
    book, _, _ = env; enable(book)
    source, original = read(book, method.split('.')[0])
    ref = source['references'][0]['record_ref']
    params = {'record_ref': ref}
    if method.endswith('.update'): params['patch'] = {'title': 'New title'}
    r = request(book, method, params)
    assert r['command']['params']['target'] == original
    assert r['command']['params']['calendar_id'] == original['calendar_id']
    result = {'record_ref': ref, 'before_revision': 'e'*64, 'operation': method,
              'absent': method.endswith('.delete'), 'record': None if method.endswith('.delete') else {k:('New title' if k == 'title' else v) for k,v in original.items() if k != 'snapshot'}}
    with pytest.raises(NativeActionError): finish(book, r, data=result)
    claim(book, r)
    assert finish(book, r, data=result)['state'] == 'succeeded'
    assert request(book, method, params)['result']['data'] == result
    with pytest.raises(NativeActionError): request(book, method, params, 'different-key')


def test_read_only_policy_never_inherits_existing_create_permission(env):
    book, _, _ = env
    source, _ = read(book)
    with pytest.raises(NativeActionError): request(book, 'calendar.delete', {'record_ref': source['references'][0]['record_ref']})


@pytest.mark.parametrize('attack', ['id', 'calendar', 'snapshot', 'leading_zero', 'index', 'wrong_kind', 'source_run', 'policy', 'owner', 'expired'])
def test_forged_or_stale_references_fail_closed(env, attack):
    book, stamp, task = env; enable(book)
    source, _ = read(book); ref = source['references'][0]['record_ref']; method = 'calendar.delete'
    params = {'record_ref': ref}
    if attack == 'id': params['id'] = 'arbitrary-system-id'
    if attack == 'calendar': params['calendar_id'] = 'outside'
    if attack == 'snapshot': params['target'] = {}
    if attack == 'leading_zero': params['record_ref'] = ref[:-1] + '00'
    if attack == 'index': params['record_ref'] = ref[:-1] + '1'
    if attack == 'wrong_kind': method = 'reminders.delete'
    if attack == 'source_run': book.store.update(task['id'], run_id='different-run')
    if attack == 'policy':
        book.configure('daily', PHONE, SECRET, 2, True, {**POLICY, 'calendar_edit': True})
        book.connect('daily', PHONE, SECRET, 3, SESSION, ['calendar.delete'])
    if attack == 'owner':
        with book.store.connection() as db: book.store.bind_task_principal(db, task['id'], 'a'*64)
    if attack == 'expired':
        stamp[0] += timedelta(minutes=11)
        book.connect('daily', PHONE, SECRET, 2, 'd'*32, ['calendar.delete'])
    with pytest.raises(NativeActionError): request(book, method, params)


def test_old_phone_read_without_snapshot_is_readable_but_cannot_authorize_write(env):
    book, _, _ = env; enable(book)
    r = request(book, 'reminders.read', {'calendar_ids':['rem']}, 'old-phone-read')
    claim(book, r)
    response = finish(book, r, data={'items':[{'id':'old','calendar_id':'rem','title':'Old','notes':'','all_day':None,'due':None,'completed':False}], 'returned':1,'has_more':False,'text_may_be_truncated':True})
    assert response['references'] == []
    with pytest.raises(NativeActionError): request(book, 'reminders.delete', {'record_ref': r['id']+':0'})


def test_recurring_reminder_has_no_mutable_reference_and_date_patch_is_rejected(env):
    book, _, _ = env; enable(book)
    source, _ = read(book, 'reminders', recurring=True, mutable=False)
    assert not source['references']
    with pytest.raises(NativeActionError): request(book, 'reminders.delete', {'record_ref':source['id']+':0'})
    with pytest.raises(NativeActionError): request(book, 'reminders.update', {'record_ref':source['id']+':0','patch':{'due':'2026-10-09T12:00:00Z'}})


def test_disconnect_expiry_and_restart_never_replay_admitted_delete(env):
    book, stamp, _ = env; enable(book)
    source, _ = read(book); params={'record_ref':source['references'][0]['record_ref']}
    r=request(book,'calendar.delete',params);claim(book,r)
    book.disconnect('daily',PHONE,SECRET,SESSION)
    restarted=NativeActions(book.store,book.clock)
    assert restarted.get('daily',r['id'])['state']=='unknown'
    assert request(restarted,'calendar.delete',params)['state']=='unknown'
    assert finish(restarted,r,status='unknown',code='interrupted')['state']=='unknown'
    restarted.review('daily',PHONE,SECRET,r['id'])
    restarted.connect('daily',PHONE,SECRET,2,'d'*32,['calendar.delete'])
    with pytest.raises(NativeActionError): request(restarted,'calendar.delete',params,'new-key')


def test_mutation_rejects_unrelated_or_invented_completion_receipt(env):
    book, _, _ = env; enable(book)
    source, original=read(book,'reminders');ref=source['references'][0]['record_ref']
    r=request(book,'reminders.update',{'record_ref':ref,'patch':{'completed':True}});claim(book,r)
    record={k:v for k,v in original.items() if k!='snapshot'}|{'completed':True}
    result={'record_ref':ref,'before_revision':'e'*64,'operation':'reminders.update','record':record,'absent':False}
    for altered in [dict(result,before_revision='f'*64),dict(result,record={**record,'id':'other'}),dict(result,record={**record,'completed':1}),dict(result,record={**record,'notes':'lost notes'}),dict(result,absent=True)]:
        with pytest.raises(NativeActionError): finish(book,r,data=altered)
    assert finish(book,r,data=copy.deepcopy(result))['state']=='succeeded'
