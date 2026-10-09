"""Bounded bookmark view over canonical life records, without remote fetching."""
import base64
import hashlib
import hmac
import json
import secrets
import time

from .life import LifeError


class BookmarkBook:
    def __init__(self, life):
        self.life = life
        self.secret = secrets.token_bytes(32)

    def _encode(self, data):
        body = base64.urlsafe_b64encode(json.dumps(data, separators=(',', ':')).encode()).decode().rstrip('=')
        return body + '.' + hmac.new(self.secret, body.encode(), hashlib.sha256).hexdigest()

    def page(self, identity, *, query='', archived=False, limit=30, cursor=None):
        self.life.store.identity(identity)
        if (not isinstance(query, str) or len(query) > 120 or any(ord(c) < 32 for c in query)
                or type(limit) is not int or not 1 <= limit <= 50 or type(archived) is not bool):
            raise LifeError('收藏筛选条件无效。', 422)
        query = query.strip()
        state = None
        if cursor is not None:
            try:
                if not isinstance(cursor, str) or len(cursor) > 2048:
                    raise ValueError()
                body, signature = cursor.split('.')
                if not hmac.compare_digest(signature, hmac.new(self.secret, body.encode(), hashlib.sha256).hexdigest()):
                    raise ValueError()
                state = json.loads(base64.urlsafe_b64decode(body + '=' * (-len(body) % 4)))
                if (set(state) != {'identity', 'query', 'archived', 'version', 'after', 'expires'}
                        or (state['identity'], state['query'], state['archived']) != (identity, query, archived)
                        or state['expires'] < time.time() or not isinstance(state['after'], list)
                        or len(state['after']) != 2 or not all(isinstance(v, str) for v in state['after'])):
                    raise ValueError()
            except (ValueError, TypeError, KeyError, UnicodeError) as error:
                raise LifeError('收藏分页已失效，请刷新列表。', 409) from error
        with self.life.store.connection() as db:
            db.execute('BEGIN')
            version = db.execute('SELECT COALESCE(MAX(sequence),0) FROM life_changes WHERE identity_id=?', (identity,)).fetchone()[0]
            if state and state['version'] != version:
                raise LifeError('记录已有变化，请刷新收藏后继续查看。', 409)
            state = state or dict(identity=identity, query=query, archived=archived, version=version, after=['', ''], expires=time.time()+900)
            # Literal search: %, _, and SQL-looking input have no special meaning.
            db.create_function('bookmark_match', 1, lambda value: query.casefold() in (value or '').casefold())
            rows = db.execute("""SELECT * FROM life_records WHERE identity_id=?
                AND json_extract(body,'$.kind')='note' AND json_type(body,'$.url')='text'
                AND (deleted_at IS NOT NULL)=?
                AND (bookmark_match(json_extract(body,'$.title')) OR bookmark_match(json_extract(body,'$.content')) OR bookmark_match(json_extract(body,'$.url')))
                AND (?='' OR created_at<? OR (created_at=? AND id>?))
                ORDER BY created_at DESC,id ASC LIMIT ?""",
                (identity, archived, state['after'][0], state['after'][0], state['after'][0], state['after'][1], limit+1)).fetchall()
        items = [self.life.unpack(row) for row in rows[:limit]]
        next_cursor = self._encode({**state, 'after': [items[-1]['created_at'], items[-1]['id']]}) if len(rows) > limit else None
        return dict(identity_id=identity, query=query, archived=archived, version=version, items=items, next_cursor=next_cursor)
