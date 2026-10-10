"""Real EXECUTE-only role; never run without disposable PostgreSQL QA config."""
import importlib.util
from pathlib import Path
import time
import uuid

import pytest
from sqlalchemy import create_engine, insert, select, text
from sqlalchemy.exc import DBAPIError

from test_control_postgres import pg
from wearing.cloud.control import states

spec=importlib.util.spec_from_file_location('state_cleanup',Path(__file__).parents[1]/'deploy/control/cleanup-expired-states.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def test_cleanup_cannot_read_change_tables_or_other_functions(pg):
    if 'cleanup' not in pg:pytest.skip('requires disposable dedicated cleanup role')
    engine=create_engine(pg['cleanup'],hide_parameters=True)
    try:
        for sql in ('SELECT * FROM wearing_control.wearing_oidc_states',
                    'DELETE FROM wearing_control.wearing_users',
                    "SELECT wearing_control.invitation_check('x','y')",
                    'SET ROLE wearing_web','SET ROLE wearing_operator','SET ROLE wearing_registration','SET ROLE inv_owner'):
            with pytest.raises(DBAPIError),engine.begin() as db:db.execute(text(sql))
        for key in ('app','operator','registration','migration'):
            with pytest.raises(ValueError):module.cleanup(pg[key])
    finally:engine.dispose()


def test_cleanup_is_bounded_and_preserves_unexpired_states(pg):
    if 'cleanup' not in pg:pytest.skip('requires disposable dedicated cleanup role')
    prefix=uuid.uuid4().hex
    values=[{'id_hash':prefix+format(i,'032x'),'value':'synthetic','expires':0} for i in range(5003)]
    future={'id_hash':uuid.uuid4().hex*2,'value':'synthetic-future','expires':int(time.time())+600}
    with pg['operator_store'].transaction() as db:db.execute(insert(states),values+[future])
    assert module.cleanup(pg['cleanup'])==5000
    with pg['operator_store'].transaction() as db:
        assert len(db.scalars(select(states.c.id_hash).where(states.c.id_hash.in_([v['id_hash'] for v in values]))).all())>=3
        assert db.scalar(select(states.c.value).where(states.c.id_hash==future['id_hash']))=='synthetic-future'
    assert module.cleanup(pg['cleanup'])>=3
