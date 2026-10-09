"""Foreground-only iPhone commands inside the existing tenant/identity task DB.

The phone is an authenticated executor, not another Agent. Claim is admission,
not success. Admitted writes are never replayed after disconnect or uncertainty.
"""
import hashlib
import hmac
import json
import math
import re
import uuid
from datetime import datetime, timedelta, timezone

from .cloud.commands import (Scope, DeviceCommand, TaskAuthority, ResourceGrant,
                             ConnectionAuthority, LeaseAuthority, authorize_command)
from .native_actions_contract import NativePolicy, NativeOutcome, WRITES, EDITS, Snapshot, parameters, date

ACTIVE = {"starting", "running", "waiting_for_approval"}
OPEN = {"queued", "executing"}


class NativeActionError(ValueError):
    def __init__(self, message, status=409):
        self.status = status
        super().__init__(message)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class NativeActions:
    def __init__(self, store, clock=None, require_task_owner=False):
        self.store = store
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        with store.connection() as db:
            db.executescript("""
              CREATE TABLE IF NOT EXISTS native_devices (
                identity TEXT NOT NULL, installation TEXT NOT NULL, secret_hash TEXT NOT NULL,
                name TEXT NOT NULL, revision INTEGER NOT NULL, enabled INTEGER NOT NULL,
                policy TEXT NOT NULL, connection TEXT, expires TEXT, capabilities TEXT NOT NULL,
                epoch INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(identity,installation));
              CREATE TABLE IF NOT EXISTS native_commands (
                id TEXT PRIMARY KEY, identity TEXT NOT NULL, installation TEXT NOT NULL,
                task_id TEXT NOT NULL, run_id TEXT NOT NULL, request_key TEXT NOT NULL,
                fingerprint TEXT NOT NULL, command TEXT NOT NULL, state TEXT NOT NULL,
                created TEXT NOT NULL, expires TEXT NOT NULL, claimed TEXT, result TEXT,
                result_hash TEXT, reviewed INTEGER NOT NULL DEFAULT 0,
                UNIQUE(identity,task_id,installation,request_key));
            """)
            if "owner_scope" not in {r[1] for r in db.execute("PRAGMA table_info(native_devices)")}:
                db.execute("ALTER TABLE native_devices ADD COLUMN owner_scope TEXT NOT NULL DEFAULT 'local'")
            if require_task_owner:
                db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('native.require_owner.v1','true')")
            self.require_task_owner = bool(db.execute("SELECT 1 FROM settings WHERE key='native.require_owner.v1' AND value='true'").fetchone())
            # Store is already tenant-isolated; this unguessable namespace makes a
            # copied command fail even when two stores both contain identity=daily.
            db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('native.server.v1',?)", (uuid.uuid4().hex,))
            self.server_id = db.execute("SELECT value FROM settings WHERE key='native.server.v1'").fetchone()[0]

    @staticmethod
    def credentials(installation, secret):
        if not isinstance(installation, str) or not re.fullmatch(r"[a-f0-9]{32}", installation) or not isinstance(secret, str) or not re.fullmatch(r"[a-f0-9]{64}", secret):
            raise NativeActionError("手机凭据不完整，请重新打开本机能力设置。", 401)

    def _device(self, db, identity, installation, secret=None, owner_scope=None):
        row = db.execute("SELECT * FROM native_devices WHERE identity=? AND installation=?", (identity, installation)).fetchone()
        if not row or (owner_scope is not None and row["owner_scope"] != owner_scope):
            raise NativeActionError("这台手机尚未在当前账户中开启能力。", 404)
        if secret is not None:
            self.credentials(installation, secret)
            if not hmac.compare_digest(row["secret_hash"], digest(secret)):
                raise NativeActionError("手机凭据已失效，请重新连接。", 401)
        return dict(row)

    def _invalidate(self, db, identity, installation):
        db.execute("""UPDATE native_commands SET state=CASE WHEN state='executing' AND json_extract(command,'$.method') IN ('calendar.create','reminders.create','calendar.update','calendar.delete','reminders.update','reminders.delete') THEN 'unknown' ELSE 'cancelled' END
            WHERE identity=? AND installation=? AND state IN ('queued','executing')""", (identity, installation))

    def _expire(self, db):
        now = self.clock().isoformat()
        db.execute("""UPDATE native_commands SET state=CASE WHEN state='executing' AND json_extract(command,'$.method') IN ('calendar.create','reminders.create','calendar.update','calendar.delete','reminders.update','reminders.delete') THEN 'unknown' ELSE 'expired' END
            WHERE state IN ('queued','executing') AND (expires<=? OR NOT EXISTS (
              SELECT 1 FROM tasks t WHERE t.id=native_commands.task_id AND t.run_id=native_commands.run_id
              AND t.identity_id=native_commands.identity AND t.status IN ('starting','running','waiting_for_approval')))
            """, (now,))

    def _public_device(self, row):
        policy = NativePolicy.model_validate_json(row["policy"])
        online = bool(row["enabled"] and row["connection"] and row["expires"] and row["expires"] > self.clock().isoformat())
        return {"server_id": self.server_id, "identity_id": row["identity"], "installation_id": row["installation"],
                "name": row["name"], "revision": row["revision"], "enabled": bool(row["enabled"]), "policy": policy.model_dump(),
                "online": online, "capabilities": json.loads(row["capabilities"]) if online else [],
                "availability": "foreground_only", "requires_phone_confirmation": sorted(WRITES)}

    def task_owner(self, identity, db=None):
        if db is None:
            with self.store.connection() as connection:
                return self.task_owner(identity, connection)
        rows = db.execute("SELECT t.id,p.owner_scope FROM tasks t LEFT JOIN task_principals p ON p.task_id=t.id WHERE t.identity_id=? AND t.status IN ('starting','running','waiting_for_approval')", (identity,)).fetchall()
        if len(rows) != 1:
            raise NativeActionError("当前任务尚未绑定运行，不能使用手机能力。")
        owner = rows[0]["owner_scope"]
        if owner is None:
            # Legacy commitments have no provable creator. A foreground phone
            # or local compatibility default must never silently adopt them.
            for table in ("goal_steps", "schedule_occurrences"):
                if (db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
                        and db.execute(f"SELECT 1 FROM {table} WHERE task_id=?", (rows[0]["id"],)).fetchone()):
                    raise NativeActionError("这项旧委托没有可核对的创建账户，不能使用手机能力。请由本人重新建立委托；重试或重新连接不会补授权限。")
        if self.require_task_owner and (not isinstance(owner, str) or not re.fullmatch(r"[a-f0-9]{64}", owner)):
            raise NativeActionError("这次任务尚未核对提交账户，请从当前账户重新发起对话。")
        return owner or "local"

    def devices(self, identity, owner_scope="local"):
        self.store.identity(identity)
        with self.store.connection() as db:
            return [self._public_device(dict(r)) for r in db.execute("SELECT * FROM native_devices WHERE identity=? AND owner_scope=? ORDER BY name,installation", (identity, owner_scope))]

    def configure(self, identity, installation, secret, revision, enabled, policy, name="我的 iPhone", owner_scope="local"):
        self.store.identity(identity)
        if owner_scope != "local" and (not isinstance(owner_scope, str) or not re.fullmatch(r"[a-f0-9]{64}", owner_scope)):
            raise NativeActionError("手机账户授权无效。", 401)
        if self.require_task_owner and owner_scope == "local":
            raise NativeActionError("手机账户授权尚未通过验证。", 401)
        self.credentials(installation, secret)
        policy = NativePolicy.model_validate(policy)
        if type(revision) is not int or revision < 0 or type(enabled) is not bool or not isinstance(name, str) or not 1 <= len(name.strip()) <= 60:
            raise NativeActionError("手机设置不完整。", 422)
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM native_devices WHERE identity=? AND installation=?", (identity, installation)).fetchone()
            if row:
                current = self._device(db, identity, installation, secret, owner_scope)
                if current["revision"] != revision:
                    raise NativeActionError("手机设置已改变，请重新读取后保存。")
                self._invalidate(db, identity, installation)
                db.execute("UPDATE native_devices SET name=?,revision=revision+1,enabled=?,policy=?,connection=NULL,expires=NULL,capabilities='[]' WHERE identity=? AND installation=?",
                           (name.strip(), int(enabled), encoded(policy.model_dump()), identity, installation))
            else:
                if revision != 0:
                    raise NativeActionError("手机设置已改变，请重新读取后保存。")
                db.execute("INSERT INTO native_devices(identity,installation,secret_hash,name,revision,enabled,policy,connection,expires,capabilities,epoch,owner_scope) VALUES(?,?,?,?,1,?,?,NULL,NULL,'[]',0,?)",
                           (identity, installation, digest(secret), name.strip(), int(enabled), encoded(policy.model_dump()), owner_scope))
            return self._public_device(self._device(db, identity, installation, secret))

    def connect(self, identity, installation, secret, revision, connection, capabilities, owner_scope="local"):
        if not isinstance(connection, str) or not re.fullmatch(r"[a-f0-9]{32}", connection):
            raise NativeActionError("手机前台会话无效。", 422)
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._device(db, identity, installation, secret, owner_scope)
            if not row["enabled"] or row["revision"] != revision:
                raise NativeActionError("本机能力已停用或设置改变，请重新读取。")
            allowed = NativePolicy.model_validate_json(row["policy"]).methods()
            if not isinstance(capabilities, list) or len(capabilities) != len(set(capabilities)) or not set(capabilities) <= allowed:
                raise NativeActionError("手机权限与所选范围不一致。", 422)
            # A new foreground epoch cancels old work. Retrying the same connect
            # nonce is idempotent, but cannot resurrect an expired epoch.
            if row["connection"] == connection and row["expires"] <= self.clock().isoformat():
                raise NativeActionError("前台会话已到期，请重新连接。")
            if row["connection"] != connection or json.loads(row["capabilities"]) != capabilities:
                self._invalidate(db, identity, installation)
            expires = (self.clock() + timedelta(seconds=60)).isoformat()
            db.execute("UPDATE native_devices SET connection=?,expires=?,capabilities=? WHERE identity=? AND installation=?",
                       (connection, expires, encoded(capabilities), identity, installation))
            return {"connection_id": connection, "expires_at": expires, **self._public_device(self._device(db, identity, installation, secret))}

    def _live(self, row, connection):
        if not row["enabled"] or row["connection"] != connection or not row["expires"] or row["expires"] <= self.clock().isoformat():
            raise NativeActionError("手机已离开前台或连接到期，本次请求没有获准继续。")

    def disconnect(self, identity, installation, secret, connection, owner_scope="local"):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._device(db, identity, installation, secret, owner_scope)
            if row["connection"] == connection:
                self._invalidate(db, identity, installation)
                db.execute("UPDATE native_devices SET connection=NULL,expires=NULL,capabilities='[]' WHERE identity=? AND installation=?", (identity, installation))
            return {"disconnected": True}

    def poll(self, identity, installation, secret, connection, owner_scope="local"):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._device(db, identity, installation, secret, owner_scope)
            self._live(row, connection)
            self._expire(db)
            db.execute("UPDATE native_devices SET expires=? WHERE identity=? AND installation=?", ((self.clock() + timedelta(seconds=60)).isoformat(), identity, installation))
            rows = db.execute("SELECT * FROM native_commands WHERE identity=? AND installation=? AND state='queued' ORDER BY created LIMIT 1", (identity, installation)).fetchall()
            return {"items": [self._public_command(dict(r), db) for r in rows]}

    def _public_command(self, row, db=None):
        result = {"id": row["id"], "identity_id": row["identity"], "installation_id": row["installation"],
                  "task_id": row["task_id"], "run_id": row["run_id"], "command": json.loads(row["command"]),
                  "state": row["state"], "fingerprint": row["fingerprint"], "result": json.loads(row["result"]) if row["result"] else None,
                  "reviewed": bool(row["reviewed"]), "content_is_untrusted": True}
        if result['state'] == 'succeeded' and result['command']['method'] in {'calendar.read', 'reminders.read'}:
            result['references'] = [{'record_ref': row['id'] + ':' + str(index), 'index': index}
                for index, item in enumerate(result['result']['data']['items']) if item.get('snapshot', {}).get('mutable')]
        if db:
            task = db.execute("SELECT title FROM tasks WHERE id=?", (row["task_id"],)).fetchone()
            result["task_title"] = task[0] if task else "当前任务"
        return result

    def request(self, identity, installation, method, params, request_key):
        if not isinstance(request_key, str) or not 1 <= len(request_key) <= 120:
            raise NativeActionError("请为手机请求保留唯一的重试标记。", 422)
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._expire(db)
            tasks = db.execute("SELECT * FROM tasks WHERE identity_id=? AND status IN ('starting','running','waiting_for_approval')", (identity,)).fetchall()
            if len(tasks) != 1 or not tasks[0]["run_id"]:
                raise NativeActionError("当前任务尚未绑定运行，不能向手机派发动作。")
            task = tasks[0]
            owner_scope = self.task_owner(identity, db)
            self._device(db, identity, installation, owner_scope=owner_scope)
            fp = digest(encoded({"method": method, "params": params}))
            saved = db.execute("SELECT * FROM native_commands WHERE identity=? AND task_id=? AND installation=? AND request_key=?", (identity, task["id"], installation, request_key)).fetchone()
            if saved:
                if saved["fingerprint"] != fp or saved["run_id"] != task["run_id"]:
                    raise NativeActionError("相同手机请求标记对应不同内容，已阻止重复操作。")
                return self._public_command(dict(saved), db)
            row = self._device(db, identity, installation, owner_scope=owner_scope)
            self._live(row, row["connection"])
            try:
                validated = parameters(method, params, NativePolicy.model_validate_json(row["policy"]))
            except ValueError as error:
                raise NativeActionError("所需手机能力或列表未获授权，或参数超过范围。请先查看 native_devices。", 422) from error
            if method in EDITS:
                validated = self._resolve_reference(db, identity, installation, task, row, method, validated)
            if method not in json.loads(row["capabilities"]):
                raise NativeActionError("手机的这项系统权限暂不可用，请在手机设置中检查。")
            if db.execute("SELECT 1 FROM native_commands WHERE identity=? AND installation=? AND (state IN ('queued','executing') OR (state='unknown' AND reviewed=0))", (identity, installation)).fetchone():
                raise NativeActionError("这台手机还有一次请求待处理或结果待核对，不能重复发起。")
            now = self.clock()
            expires = min(now + timedelta(seconds=55), datetime.fromisoformat(row["expires"]))
            if (expires - now).total_seconds() < 10:
                raise NativeActionError("请保持 Pajio 在手机前台，等待连接刷新后再试。")
            epoch = row["epoch"] + 1
            command = DeviceCommand(protocol_version="1", command_id="native_" + uuid.uuid4().hex,
                scope=Scope(tenant_id=self.server_id, identity_id=identity), task_id=task["id"], resource_id=installation,
                connector_id=installation, connection_id=row["connection"], pairing_generation=1,
                policy_revision=row["revision"], lease_epoch=epoch, method=method, params=validated, created_at=now, expires_at=expires)
            db.execute("UPDATE native_devices SET epoch=? WHERE identity=? AND installation=?", (epoch, identity, installation))
            db.execute("INSERT INTO native_commands VALUES(?,?,?,?,?,?,?,?, 'queued',?,?,NULL,NULL,NULL,0)",
                       (command.command_id, identity, installation, task["id"], task["run_id"], request_key, fp, command.model_dump_json(), now.isoformat(), expires.isoformat()))
            return self._public_command(dict(db.execute("SELECT * FROM native_commands WHERE id=?", (command.command_id,)).fetchone()), db)

    def _resolve_reference(self, db, identity, installation, task, device, method, params):
        source_id, index = params['record_ref'].split(':')
        if str(int(index)) != index:
            raise NativeActionError('记录引用格式不正确。', 422)
        source = db.execute('SELECT * FROM native_commands WHERE id=? AND identity=? AND installation=? AND task_id=? AND run_id=? AND state=\'succeeded\'',
                            (source_id, identity, installation, task['id'], task['run_id'])).fetchone()
        if not source or self.clock() - date(source['created']) > timedelta(minutes=10):
            raise NativeActionError('请先在当前任务读取这条系统记录，再引用它修改或删除。', 422)
        original = json.loads(source['command'])
        if original['method'] != method.split('.')[0] + '.read' or original['policy_revision'] != device['revision']:
            raise NativeActionError('记录引用的类型或授权已变化，请重新读取。', 422)
        items = json.loads(source['result'])['data']['items']
        if int(index) >= len(items): raise NativeActionError('记录引用不存在。', 422)
        target = items[int(index)]
        snapshot = target.get('snapshot', {})
        if not snapshot.get('mutable') or (method.startswith('reminders.') and snapshot.get('recurring')):
            raise NativeActionError('这条记录不能安全地单次修改，请在系统应用处理。', 422)
        policy = NativePolicy.model_validate_json(device['policy'])
        lists = policy.calendars if method.startswith('calendar.') else policy.reminders
        if not any(c.id == target['calendar_id'] and c.writable for c in lists):
            raise NativeActionError('记录列表未获写入授权。', 422)
        if db.execute("SELECT 1 FROM native_commands WHERE identity=? AND installation=? AND json_extract(command,'$.params.record_ref')=?", (identity, installation, params['record_ref'])).fetchone():
            raise NativeActionError('这个读取版本已经用于一次操作。请核对原回执；需要新操作时先重新读取。')
        patch = params.get('patch', {})
        if method == 'calendar.update':
            start, end = patch.get('start', target['start']), patch.get('end', target['end'])
            if not 0 < (date(end) - date(start)).total_seconds() <= 31 * 86400:
                raise NativeActionError('修改后的日程起止时间无效。', 422)
            if target['all_day'] and ({'start', 'end'} & patch.keys()):
                raise NativeActionError('全天日程的日期修改请在系统日历中处理。', 422)
        return {**params, 'calendar_id': target['calendar_id'], 'target': target}

    def _record(self, db, identity, command_id):
        row = db.execute("SELECT * FROM native_commands WHERE id=? AND identity=?", (command_id, identity)).fetchone()
        if not row:
            raise NativeActionError("当前身份没有这项手机请求。", 404)
        return dict(row)

    def get(self, identity, command_id, owner_scope="local"):
        with self.store.connection() as db:
            self._expire(db)
            row = self._record(db, identity, command_id)
            self._device(db, identity, row["installation"], owner_scope=owner_scope)
            return self._public_command(row, db)

    def cancel_dispatch(self, identity, command_id):
        """Internal MCP cancellation: revoke unclaimed work, never claim rollback."""
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._record(db, identity, command_id)
            db.execute("UPDATE native_commands SET state=CASE WHEN state='executing' AND json_extract(command,'$.method') IN ('calendar.create','reminders.create','calendar.update','calendar.delete','reminders.update','reminders.delete') THEN 'unknown' ELSE 'cancelled' END WHERE id=? AND identity=? AND state IN ('queued','executing')", (command_id, identity))

    def history(self, identity, installation, secret, owner_scope="local"):
        with self.store.connection() as db:
            self._device(db, identity, installation, secret, owner_scope)
            self._expire(db)
            return {"items": [self._public_command(dict(row), db) for row in db.execute("SELECT * FROM native_commands WHERE identity=? AND installation=? ORDER BY created DESC LIMIT 30", (identity, installation))]}

    def claim(self, identity, installation, secret, connection, command_id, fingerprint, approve, owner_scope="local"):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._expire(db)
            device = self._device(db, identity, installation, secret, owner_scope)
            self._live(device, connection)
            row = self._record(db, identity, command_id)
            command = DeviceCommand.model_validate_json(row["command"])
            if row["installation"] != installation or row["fingerprint"] != fingerprint or command.connection_id != connection:
                raise NativeActionError("手机请求与当前确认不匹配。")
            if row["state"] != "queued":
                raise NativeActionError("请求已经处理或到期；不会再次执行。")
            if type(approve) is not bool:
                raise NativeActionError("请在手机上确认本次动作。", 422)
            if not approve:
                db.execute("UPDATE native_commands SET state='cancelled' WHERE id=?", (command_id,))
                return self._public_command(self._record(db, identity, command_id), db)
            scope = Scope(tenant_id=self.server_id, identity_id=identity)
            policy = NativePolicy.model_validate_json(device["policy"])
            try:
                authorize_command(command, task=TaskAuthority(scope=scope, task_id=row["task_id"]),
                    grant=ResourceGrant(scope=scope, resource_id=installation, connector_id=installation, pairing_generation=1, policy_revision=device["revision"], methods=policy.methods()),
                    connection=ConnectionAuthority(tenant_id=self.server_id, connector_id=installation, connection_id=connection, pairing_generation=1, capabilities=frozenset(json.loads(device["capabilities"])), expires_at=device["expires"]),
                    lease=LeaseAuthority(scope=scope, resource_id=installation, task_id=row["task_id"], connection_id=connection, epoch=device["epoch"], expires_at=command.expires_at), now=self.clock())
            except PermissionError as error:
                raise NativeActionError("手机授权已改变，请重新核对本次请求。") from error
            db.execute("UPDATE native_commands SET state='executing',claimed=? WHERE id=?", (self.clock().isoformat(), command_id))
            return self._public_command(self._record(db, identity, command_id), db)

    def finish(self, identity, installation, secret, connection, command_id, fingerprint, outcome, owner_scope="local"):
        result = NativeOutcome.model_validate(outcome).model_dump()
        payload = encoded(result)
        if len(payload.encode()) > 128 * 1024:
            raise NativeActionError("手机回执超过大小限制。", 413)
        if result["status"] != "succeeded" and result["data"]:
            raise NativeActionError("未完成的请求不能提交资料内容。", 422)
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._expire(db)
            device = self._device(db, identity, installation, secret, owner_scope)
            row = self._record(db, identity, command_id)
            command = DeviceCommand.model_validate_json(row["command"])
            if row["installation"] != installation or row["fingerprint"] != fingerprint or command.connection_id != connection:
                raise NativeActionError("手机回执与原请求不匹配。")
            if row["result_hash"]:
                if row["result_hash"] != digest(payload):
                    raise NativeActionError("这次请求已有不同回执，不能覆盖。")
                return self._public_command(row, db)
            # A write already admitted by this exact phone epoch may finish
            # after leaving foreground. Preserve only its original scoped receipt.
            write = command.method in WRITES
            if not row["claimed"] or row["state"] not in ({"executing", "unknown"} if write else {"executing"}):
                raise NativeActionError("请求未获执行许可或已结束，回执不被采纳。")
            if not write:
                self._live(device, connection)
                if device["revision"] != command.policy_revision or command.method not in json.loads(device["capabilities"]):
                    raise NativeActionError("读取权限已变化，本次内容不会保存。")
            self._validate_result(command, result)
            state = result["status"]
            db.execute("UPDATE native_commands SET state=?,result=?,result_hash=? WHERE id=?", (state, payload, digest(payload), command_id))
            return self._public_command(self._record(db, identity, command_id), db)

    @staticmethod
    def _validate_result(command, result):
        if result["status"] != "succeeded":
            return
        if result["code"] != "ok":
            raise NativeActionError("完成回执缺少核对结果。", 422)
        data, p, method = result["data"], command.params, command.method
        valid = False
        if method == "location.read":
            valid = (set(data) == {"latitude", "longitude", "accuracy", "timestamp"}
                     and all(type(data.get(k)) in (int, float) and math.isfinite(data[k]) for k in ("latitude", "longitude", "accuracy"))
                     and abs(data["latitude"]) <= 90 and abs(data["longitude"]) <= 180 and data["accuracy"] >= 0)
            if valid:
                try:
                    valid = abs((date(data["timestamp"]) - command.created_at).total_seconds()) <= 180
                except (ValueError, TypeError):
                    valid = False
        elif method in EDITS:
            target, patch = p['target'], p.get('patch', {})
            valid = (set(data) == {'record_ref', 'before_revision', 'operation', 'record', 'absent'}
                     and data['record_ref'] == p['record_ref'] and data['before_revision'] == target['snapshot']['revision']
                     and data['operation'] == method)
            if valid and method.endswith('.delete'):
                valid = data['absent'] is True and data['record'] is None
            elif valid:
                record = data['record']; expected = {k:v for k,v in target.items() if k != 'snapshot'} | patch
                valid = isinstance(record, dict) and set(record) == set(expected) and data['absent'] is False
                if valid:
                    for key, value in expected.items():
                        if key == 'id':
                            valid = isinstance(record[key], str) and 0 < len(record[key]) <= 240 and (method.startswith('calendar.') or record[key] == value)
                        elif key in {'start', 'end', 'due'} and value is not None:
                            try: valid = date(record[key]) == date(value)
                            except (ValueError, TypeError): valid = False
                        else: valid = type(record[key]) is type(value) and record[key] == value
                        if not valid: break
        elif method in WRITES:
            common = {"id", "calendar_id", "title", "notes", "all_day", "marker"}
            fields = common | ({"start", "end"} if method == "calendar.create" else {"due", "completed"})
            valid = (set(data) == fields and isinstance(data["id"], str) and 0 < len(data["id"]) <= 240
                     and data["calendar_id"] == p["calendar_id"] and data["title"] == p["title"] and data["notes"] == p["notes"]
                     and (data["all_day"] is p["all_day"] or (method == "reminders.create" and p["all_day"] is False and data["all_day"] is None))
                     and data["marker"] == "pajio://native/" + command.command_id)
            if valid:
                try:
                    if method == "calendar.create":
                        valid = date(data["start"]) == date(p["start"]) and date(data["end"]) == date(p["end"])
                    else:
                        valid = data["completed"] is False and ((data["due"] is None and p["due"] is None) or (p["due"] is not None and date(data["due"]) == date(p["due"])))
                except (ValueError, TypeError):
                    valid = False
        else:
            items = data.get("items")
            valid = (set(data) == {"items", "has_more", "returned", "text_may_be_truncated"}
                     and isinstance(items, list) and len(items) <= p["limit"] and type(data["returned"]) is int and data["returned"] == len(items)
                     and type(data["has_more"]) is bool and type(data["text_may_be_truncated"]) is bool)
            allowed = {"id", "calendar_id", "title", "notes", "all_day"} | ({"start", "end"} if method == "calendar.read" else {"due", "completed"})
            if valid:
                valid = all(isinstance(r, dict) and set(r) in (allowed, allowed | {'snapshot'}) and isinstance(r.get("id"), str) and 0 < len(r["id"]) <= 240
                            and r.get("calendar_id") in p["calendar_ids"] and isinstance(r.get("title"), str) and len(r["title"]) <= 300
                            and isinstance(r.get("notes"), str) and len(r["notes"]) <= 1000
                            and (type(r.get("all_day")) is bool or (method == "reminders.read" and r.get("all_day") is None)) for r in items)
            if valid:
                for r in items:
                    if 'snapshot' not in r: continue  # Old App reads remain readable but cannot authorize edits.
                    try:
                        snapshot = Snapshot.model_validate(r['snapshot'])
                        if method == 'calendar.read':
                            if date(snapshot.occurrence_start) != date(r['start']): raise ValueError('instance mismatch')
                        elif snapshot.occurrence_start is not None or (snapshot.mutable and snapshot.recurring):
                            raise ValueError('ambiguous reminder series')
                    except (ValueError, TypeError): valid = False; break
            if valid:
                try:
                    if method == "calendar.read":
                        valid = all(date(r["start"]) < date(r["end"]) and date(r["start"]) <= date(p["end"]) and date(r["end"]) >= date(p["start"]) for r in items)
                    else:
                        valid = all(type(r["completed"]) is bool and (p["completed"] or not r["completed"])
                                    and (r["due"] is None or date(r["due"]) is not None) for r in items)
                except (ValueError, TypeError):
                    valid = False
        if not valid:
            raise NativeActionError("手机回读与本次请求不一致，未记录为完成。", 422)

    def review(self, identity, installation, secret, command_id, owner_scope="local"):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._device(db, identity, installation, secret, owner_scope)
            row = self._record(db, identity, command_id)
            if row["installation"] != installation or row["state"] != "unknown":
                raise NativeActionError("只有结果不明的手机请求需要手动核对。")
            db.execute("UPDATE native_commands SET reviewed=1 WHERE id=?", (command_id,))
            return self._public_command(self._record(db, identity, command_id), db)
