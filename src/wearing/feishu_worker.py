"""Isolated official Feishu WebSocket SDK loop. Private JSON pipes only.

The SDK owns a global event loop; isolating it avoids touching FastAPI's loop.
Credentials arrive through stdin, never argv, environment or log output.
"""
import json
import logging
import queue
import sys
import threading


def main():
    import lark_oapi as lark

    configuration = json.loads(sys.stdin.readline())
    logging.disable(logging.CRITICAL)
    acknowledgements = queue.Queue()

    def read_acknowledgements():
        for line in sys.stdin:
            acknowledgements.put(line)
        acknowledgements.put(None)

    threading.Thread(target=read_acknowledgements, daemon=True).start()

    def emit(value):
        print(json.dumps(value, ensure_ascii=False), flush=True)

    def receive(data):
        event = json.loads(lark.JSON.marshal(data))
        event_id = (event.get("header") or {}).get("event_id")
        emit({"kind": "message", "event": event})
        # Acknowledge the SDK event only after the product has durably accepted
        # or rejected it. A crash/timeout lets Feishu retry the same event id.
        acknowledgement = json.loads(acknowledgements.get(timeout=60))
        if acknowledgement.get("ack") != event_id:
            raise RuntimeError("Product acknowledgement does not match")

    handler = lark.EventDispatcherHandler.builder("", "", lark.LogLevel.ERROR).register_p2_im_message_receive_v1(receive).build()

    class Client(lark.ws.Client):
        async def _connect(self):
            # Pinned SDK 1.7.x has no initial-connection observer. Its reconnect
            # observers do not fire for the first connection, hence this narrow
            # wrapper around the inspected SDK handshake.
            await super()._connect()
            emit({"kind": "connected"})

    client = Client(configuration["app_id"], configuration["secret"], log_level=lark.LogLevel.ERROR, event_handler=handler)
    client.on_reconnecting = lambda: emit({"kind": "reconnecting"})
    client.start()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Upstream errors can contain credentials or endpoint tokens.
        print('{"kind":"failed"}', flush=True)
        sys.exit(1)
