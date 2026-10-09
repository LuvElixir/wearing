import asyncio
import json
from types import SimpleNamespace

from wearing.feishu_receiver import FeishuReceiver


class Input:
    def __init__(self):
        self.written = []
    def write(self, value):
        self.written.append(value)
    async def drain(self):
        pass


async def test_worker_event_is_acknowledged_only_after_product_acceptance():
    accepted = asyncio.Event()
    entered = asyncio.Event()
    statuses = []
    async def receive(row, event):
        entered.set()
        await accepted.wait()
    async def status(row, state):
        statuses.append(state)
    receiver = FeishuReceiver(receive, status)
    output = asyncio.StreamReader()
    process = SimpleNamespace(stdout=output, stdin=Input(), returncode=0)
    row = {"identity_id": "daily", "revision": "revision"}
    output.feed_data(b'{"kind":"connected"}\n')
    output.feed_data(b'{"kind":"message","event":{"header":{"event_id":"event-one"}}}\n')
    reading = asyncio.create_task(receiver._read(row, process))
    await asyncio.wait_for(entered.wait(), 1)
    assert process.stdin.written == []
    assert statuses == ["connected"]
    accepted.set()
    output.feed_eof()
    await reading
    assert json.loads(process.stdin.written[0]) == {"ack": "event-one"}


async def test_disable_stops_only_owned_child_and_cancels_its_reader():
    class Process:
        returncode = None
        terminated = False
        def terminate(self):
            self.terminated = True
            self.returncode = 0
        async def wait(self):
            return self.returncode
    async def idle():
        await asyncio.Future()
    receiver = FeishuReceiver(None, None)
    process = Process()
    task = asyncio.create_task(idle())
    receiver.children["daily"] = {"process": process, "reader": task, "revision": "r"}
    await receiver.stop("daily")
    assert process.terminated
    assert task.cancelled()
    assert not receiver.children


def test_installed_official_sdk_message_shape_matches_worker_contract():
    import lark_oapi as lark
    from lark_oapi.api.im.v1 import P2ImMessageReceiveV1
    payload = {"schema": "2.0", "header": {"event_id": "fixture-event", "app_id": "cli_fixture", "event_type": "im.message.receive_v1"},
               "event": {"sender": {"sender_type": "user", "sender_id": {"open_id": "ou_fixture"}},
                         "message": {"message_id": "om_fixture", "chat_type": "p2p", "message_type": "text", "content": '{"text":"hello"}', "create_time": "1791410000000"}}}
    decoded = json.loads(lark.JSON.marshal(P2ImMessageReceiveV1(payload)))
    assert decoded["header"]["app_id"] == "cli_fixture"
    assert decoded["event"]["sender"]["sender_id"]["open_id"] == "ou_fixture"
    assert decoded["event"]["message"]["chat_type"] == "p2p"
