"""Acceptance for f6: gateway -> service timeouts in the chat path are not seconds-tight."""

import ast
import inspect


def test_chat_path_client_timeouts_allow_a_queued_generation():
    import api_gateway.app.main as gateway

    tree = ast.parse(inspect.getsource(gateway.chat_stream))
    timeouts = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "async_client":
            for kw in node.keywords:
                if kw.arg == "timeout" and isinstance(kw.value, ast.Constant):
                    timeouts.append(kw.value.value)
    assert timeouts, "expected explicit client timeouts in chat_stream"
    assert min(timeouts) >= 20, f"chat path timeouts {timeouts}: a queued generation needs more than seconds"
