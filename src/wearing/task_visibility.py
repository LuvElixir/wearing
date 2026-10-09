"""Task-derived reads share one rule; identity-owned life/memory is unchanged."""
import re


def owner(value):
    if value == 'local' or isinstance(value, str) and re.fullmatch(r'[a-f0-9]{64}', value):
        return value
    raise ValueError('账户关联尚未通过验证，请重新登录。')


def request_owner(request, *, local_devices=True):
    from fastapi import HTTPException
    cloud = not local_devices or bool(request.scope.get('pajio.cloud_worker'))
    if not cloud:
        return 'local'
    value = request.scope.get('pajio.storage_scope')
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{64}', value):
        raise HTTPException(401, '账户关联尚未通过验证，请重新登录。')
    return value


def predicate(task_expression, parameter=':task_owner'):
    """Only fixed program SQL expressions/parameter names, never user text."""
    if not re.fullmatch(r'[a-z_]+\.[a-z_]+', task_expression) or not re.fullmatch(r':[a-z_]+', parameter):
        raise ValueError('Invalid task visibility expression')
    # No principal means explicitly legacy shared. Null caller is useful for
    # an unowned internal task: it can read only other unowned task content.
    return f'NOT EXISTS (SELECT 1 FROM task_principals tv WHERE tv.task_id={task_expression} AND tv.owner_scope IS NOT {parameter})'


def ids(db, identity, owner_scope):
    return {row[0] for row in db.execute(
        f'SELECT t.id FROM tasks t WHERE t.identity_id=:identity AND {predicate("t.id")}',
        {'identity': identity, 'task_owner': owner_scope})}


def visible(db, identity, task_id, owner_scope):
    return bool(db.execute(
        f'SELECT 1 FROM tasks t WHERE t.id=:task AND t.identity_id=:identity AND {predicate("t.id")}',
        {'task': task_id, 'identity': identity, 'task_owner': owner_scope}).fetchone())


INTERNAL = object()


def source_predicate(kind, expression):
    if kind not in {'goal', 'schedule'} or not re.fullmatch(r'[a-z_]+\.[a-z_]+', expression):
        raise ValueError('Invalid background visibility expression')
    return f"NOT EXISTS (SELECT 1 FROM background_principals bp WHERE bp.kind='{kind}' AND bp.source_id={expression} AND bp.owner_scope IS NOT :task_owner)"


def active_owner(db, identity):
    from .background_principals import active_task, task_owner
    from .service import ACTIVE
    task = active_task(db, identity, ACTIVE)
    return task_owner(db, task, identity) if task else None
