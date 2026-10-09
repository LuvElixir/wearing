"""Independent onboarding integration checks; synthetic stores and model transport only."""
import json

import httpx

from wearing.app import create_app
from wearing.config import Settings
from wearing.hermes import HermesClient
from wearing.onboarding import ProfileValues, SaveOnboarding
from wearing.service import ACTIVE
from test_goals import GoalWire
from test_identity_export_documents import unpack


A, B = 'a' * 64, 'b' * 64


def choice(revision=0, request_key='independent-profile-001', **values):
    return SaveOnboarding(revision=revision, request_key=request_key, status='completed',
                          step=5, values=ProfileValues(**values))


async def test_actual_task_start_uses_latest_confirmed_owner_profile_without_leaking(tmp_path):
    settings = Settings(tmp_path, hermes_key='synthetic')
    wire = GoalWire()
    client = HermesClient(settings, httpx.MockTransport(wire))
    app = create_app(settings, hermes=client, engine_autostart=False)
    store, book, service = app.state.store, app.state.onboarding, app.state.service
    try:
        book.save('daily', choice(roles=['student'], reply_tone='warm'), owner_scope=A)
        book.save('daily', choice(roles=['business'], reply_tone='direct'), owner_scope=B)
        # A queued turn must resolve its own latest confirmed settings at admission.
        task = store.accept_message('synthetic A', 'daily', 'independent-message-A', ACTIVE, owner_scope=A)[0]
        book.save('daily', choice(1, 'independent-profile-002', roles=['caregiver'], reply_detail='brief'), owner_scope=A)
        await service.start(task['id'])
        instructions = wire.runs[-1]['instructions']
        assert '照顾家庭' in instructions and '简短结论' in instructions
        assert '在校学习' not in instructions and '经营事业' not in instructions and '温和表达' not in instructions
        store.update(task['id'], status='completed_unverified')
        task_b = store.accept_message('synthetic B', 'daily', 'independent-message-B', ACTIVE, owner_scope=B)[0]
        await service.start(task_b['id'])
        assert '经营事业' in wire.runs[-1]['instructions'] and '直接表达' in wire.runs[-1]['instructions']
        assert '照顾家庭' not in wire.runs[-1]['instructions']
        store.update(task_b['id'], status='completed_unverified')
        # A legacy unowned turn cannot borrow either authenticated profile.
        legacy = store.create_message('synthetic legacy')
        await service.start(legacy['id'])
        assert '用户已确认的初始偏好' not in wire.runs[-1]['instructions']
    finally:
        await client.close()


async def test_profile_context_derives_identity_and_owner_from_storage_not_task_fields(tmp_path):
    app = create_app(Settings(tmp_path), engine_autostart=False)
    store, book = app.state.store, app.state.onboarding
    other = store.save_identity('Synthetic second context')['id']
    try:
        book.save('daily', choice(roles=['student']), owner_scope=A)
        book.save(other, choice(roles=['caregiver']), owner_scope=B)
        task = store.accept_message('bound', 'daily', 'independent-bound-message', ACTIVE, owner_scope=A)[0]
        assert '在校学习' in book.context({**task, 'identity_id': other, 'owner_scope': B})
        assert '照顾家庭' not in book.context({**task, 'identity_id': other, 'owner_scope': B})
        assert book.context({'id': 'nonexistent', 'identity_id': 'daily', 'owner_scope': A}) == ''
    finally:
        await app.state.service.hermes.close()


async def test_export_is_owner_bound_and_never_includes_retry_journal(tmp_path):
    app = create_app(Settings(tmp_path), engine_autostart=False)
    book, exports = app.state.onboarding, app.state.identity_exports
    try:
        book.save('daily', choice(roles=['student']), owner_scope=A)
        book.save('daily', choice(roles=['business']), owner_scope=B)
        with book.store.connection() as db:
            db.execute("UPDATE onboarding_requests SET receipt=? WHERE owner_scope=?", ('INTERNAL-ONBOARDING-JOURNAL-SECRET', A))
        a, _, a_files = unpack(exports, key='independent-export-a', owner_scope=A)
        b, _, _ = unpack(exports, key='independent-export-b', owner_scope=B)
        assert a['onboarding_profile'][0]['values']['roles'] == ['student']
        assert b['onboarding_profile'][0]['values']['roles'] == ['business']
        assert b'INTERNAL-ONBOARDING-JOURNAL-SECRET' not in b'\n'.join(a_files.values())
        assert 'independent-profile-001' not in json.dumps(a)
    finally:
        await app.state.service.hermes.close()
