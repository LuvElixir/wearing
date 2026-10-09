"""Exercise the installed public SDK, not a stub with renamed model fields."""
from mcp import types

from wearing.phone_proxy import extra_schemas, normalize_result, scoped_schema, stamp_observation


def test_phone_tool_schema_serializes_standard_wire_names():
    original = types.Tool.model_validate({"name": "mobile_type_keys", "inputSchema": {
        "type": "object", "properties": {"device": {"type": "string"}, "text": {"type": "string"}},
        "required": ["device", "text"]}})
    wire = scoped_schema(original).model_dump(mode="json", by_alias=True)
    assert wire["inputSchema"]["required"] == ["text", "resource_id"]
    assert "device" not in wire["inputSchema"]["properties"]
    assert "device" in original.model_dump(by_alias=True)["inputSchema"]["properties"]
    for schema in extra_schemas():
        assert "inputSchema" in schema.model_dump(by_alias=True)


def test_native_failure_stays_error_on_actual_mcp_wire():
    result = types.CallToolResult.model_validate({"content": [{"type": "text", "text":
        "Non-ASCII text is not supported on Android"}]})
    normalize_result(result)
    wire = result.model_dump(mode="json", by_alias=True)
    assert wire["isError"] is True
    assert "mobile_set_text" in wire["content"][0]["text"]
    stamp_observation(result, "mobile_take_screenshot", {"action_id": "fixture", "resource_id": "phone_fixture"})
    assert '"ok": false' in result.content[0].text
