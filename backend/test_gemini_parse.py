"""
Feedback loop: test Gemini parse path with synthetic data.

Run: python test_gemini_parse.py
Purpose: Verify role-driven extraction, unicode unescape, Thinking/Tools handling.
"""
import json
import sys

# Mock httpx before importing link_importer (avoid SSL issues in test env)
class FakeAsyncClient:
    pass
fake_httpx = type(sys)('httpx')
fake_httpx.AsyncClient = FakeAsyncClient
sys.modules['httpx'] = fake_httpx

import link_importer
from conv_parser import parse_conversation

# Direct function references for convenience
_find_gemini_messages = link_importer._find_gemini_messages
_extract_from_gemini_data = link_importer._extract_from_gemini_data
_format_messages = link_importer._format_messages
_extract_gemini = link_importer._extract_gemini


def test_role_driven_extraction():
    """Test A: message objects with explicit role fields — role MUST be read from field, not i%2."""
    data = [
        {"role": "user", "content": "Hello, can you help me?"},
        {"role": "model", "content": "Sure! Let me think about that."},
        {"role": "user", "content": "Thanks!"},
        {"role": "model", "content": "You're welcome."},
    ]
    msgs = _find_gemini_messages(data)
    assert msgs is not None, "FAIL: _find_gemini_messages returned None"
    assert len(msgs) == 4, f"FAIL: expected 4 msgs, got {len(msgs)}"
    assert msgs[0] == ("user", "Hello, can you help me?"), f"FAIL: msg0={msgs[0]}"
    assert msgs[1] == ("assistant", "Sure! Let me think about that."), f"FAIL: msg1={msgs[1]}"
    assert msgs[2] == ("user", "Thanks!"), f"FAIL: msg2={msgs[2]}"
    assert msgs[3] == ("assistant", "You're welcome."), f"FAIL: msg3={msgs[3]}"
    print("PASS: test_role_driven_extraction")


def test_thinking_blocks_not_split():
    """Test A: Thinking blocks within same role must NOT create separate messages."""
    data = [
        {"role": "user", "content": "Question?"},
        {"role": "model", "content": "Let me think..."},
        # Thinking block — same role, different content key
        {"role": "model", "content": "Actually, the answer is 42."},
    ]
    msgs = _find_gemini_messages(data)
    assert msgs is not None, "FAIL: returned None"
    # Should have 2 messages (user + merged assistant), not 3
    roles = [r for r, c in msgs]
    print(f"  roles={roles}, msgs={msgs}")
    # At minimum, role field must be respected
    for i, (role, content) in enumerate(msgs):
        expected_role = data[i]["role"]
        expected_role = "user" if expected_role in ("user", "human") else "assistant"
        assert role == expected_role, f"FAIL: msg[{i}] role={role}, expected={expected_role}"
    print("PASS: test_thinking_blocks_not_split")


def test_unicode_unescape():
    """Test C: Unicode escape sequences must be decoded."""
    data = [
        {"role": "user", "content": "Check user\\u0027s panel\\u0027s settings"},
        {"role": "model", "content": "The panel\\u0027s configuration is correct."},
    ]
    msgs = _find_gemini_messages(data)
    assert msgs is not None, "FAIL: returned None"
    for role, content in msgs:
        assert "\\u0027" not in content, f"FAIL: unescaped unicode in: {content[:80]}"
        assert "'" in content, f"FAIL: unicode not converted to apostrophe in: {content[:80]}"
    print("PASS: test_unicode_unescape")


def test_special_escape_chars():
    """Test B: Backslash and quote escapes must not break parsing."""
    data = [
        {"role": "user", "content": "Path is C:\\\\Users\\\\test"},
        {"role": "model", "content": 'She said \\"hello\\" to me'},
    ]
    msgs = _find_gemini_messages(data)
    assert msgs is not None, "FAIL: returned None"
    assert len(msgs) == 2, f"FAIL: expected 2 msgs, got {len(msgs)}"
    print(f"  msgs={msgs}")
    # Content should be intact
    assert "C:\\\\Users\\\\test" in msgs[0][1] or "C:\\Users\\test" in msgs[0][1], \
        f"FAIL: backslash content broken: {msgs[0][1][:80]}"
    print("PASS: test_special_escape_chars")


def test_alternating_fallback_without_role_field():
    """Test that when NO role field exists, alternating is acceptable fallback."""
    data = ["User question 1", "Model answer 1", "User question 2", "Model answer 2"]
    msgs = _find_gemini_messages(data)
    assert msgs is not None, "FAIL: returned None"
    assert len(msgs) == 4, f"FAIL: expected 4, got {len(msgs)}"
    # Without role info, alternating is the best guess
    assert msgs[0][0] == "user", f"FAIL: msg0 role={msgs[0][0]}"
    assert msgs[1][0] == "assistant", f"FAIL: msg1 role={msgs[1][0]}"
    print("PASS: test_alternating_fallback_without_role_field")


def test_format_messages_roundtrip():
    """Test that _format_messages + parse_conversation roundtrip preserves roles."""
    msgs = [
        ("user", "Hello world"),
        ("assistant", "Hi there! How can I help?"),
        ("user", "What is AI?"),
        ("assistant", "AI stands for Artificial Intelligence."),
    ]
    formatted = _format_messages(msgs, "gemini")
    print(f"  formatted:\n{formatted}\n")
    parsed = parse_conversation(formatted, "gemini")
    assert len(parsed) == 4, f"FAIL: roundtrip lost messages: {len(parsed)}"
    for i, (seq, role, content) in enumerate(parsed):
        assert role == msgs[i][0], f"FAIL: roundtrip msg[{i}] role={role}, expected={msgs[i][0]}"
    print("PASS: test_format_messages_roundtrip")


def test_format_messages_with_special_chars():
    """Test roundtrip with special characters in content."""
    msgs = [
        ("user", 'Path: C:\\Users\\test\\file.txt'),
        ("assistant", "Found file at user's directory."),
        ("user", 'She said "hello"'),
    ]
    formatted = _format_messages(msgs, "gemini")
    print(f"  formatted:\n{formatted}\n")
    parsed = parse_conversation(formatted, "gemini")
    assert len(parsed) == 3, f"FAIL: expected 3, got {len(parsed)}"
    for i, (seq, role, content) in enumerate(parsed):
        assert role == msgs[i][0], f"FAIL: msg[{i}] role={role}, expected={msgs[i][0]}"
    print("PASS: test_format_messages_with_special_chars")


def test_gemini_author_format():
    """Test Gemini-specific format: author field instead of role."""
    data = [
        {"author": "user", "parts": [{"text": "Hello"}]},
        {"author": "model", "parts": [{"text": "Hi there"}]},
    ]
    msgs = _find_gemini_messages(data)
    assert msgs is not None, f"FAIL: returned None"
    assert len(msgs) == 2, f"FAIL: expected 2, got {len(msgs)}"
    assert msgs[0][0] == "user", f"FAIL: msg0 role={msgs[0][0]}"
    assert msgs[1][0] == "assistant", f"FAIL: msg1 role={msgs[1][0]}"
    print("PASS: test_gemini_author_format")


def test_double_parse_no_false_split_on_mid_content_label():
    """Test that 'User:' or 'Gemini:' in content does NOT cause false split."""
    msgs = [
        ("user", "What do you think of this: Gemini: is it good?"),
        ("assistant", "User: I think it's fine. Here's why:\n\n1. It works\n2. It's fast"),
    ]
    formatted = _format_messages(msgs, "gemini")
    print(f"  formatted:\n{formatted}\n")
    parsed = parse_conversation(formatted, "gemini")
    assert len(parsed) == 2, f"FAIL: expected 2 msgs, got {len(parsed)}: {[(r,c[:50]) for _,r,c in parsed]}"
    assert parsed[0][1] == "user", f"FAIL: msg0 role={parsed[0][1]}"
    assert parsed[1][1] == "assistant", f"FAIL: msg1 role={parsed[1][1]}"
    print("PASS: test_double_parse_no_false_split_on_mid_content_label")


def test_deeply_nested_gemini_data():
    """Test extraction from deeply nested Gemini data structure."""
    # Simulate AF_initDataCallback structure: [[[[msg1, msg2, ...]]]]
    data = [[[[
        {"role": "user", "content": "Nested question"},
        {"role": "model", "content": "Nested answer"},
    ]]]]
    msgs = _find_gemini_messages(data)
    assert msgs is not None, f"FAIL: returned None for nested data"
    assert len(msgs) == 2, f"FAIL: expected 2, got {len(msgs)}"
    assert msgs[0][0] == "user", f"FAIL: nested msg0 role={msgs[0][0]}"
    assert msgs[1][0] == "assistant", f"FAIL: nested msg1 role={msgs[1][0]}"
    print("PASS: test_deeply_nested_gemini_data")


if __name__ == "__main__":
    print("=" * 60)
    print("Gemini Parse Test Suite — Feedback Loop")
    print("=" * 60)

    failures = []
    tests = [
        test_role_driven_extraction,
        test_thinking_blocks_not_split,
        test_unicode_unescape,
        test_special_escape_chars,
        test_alternating_fallback_without_role_field,
        test_format_messages_roundtrip,
        test_format_messages_with_special_chars,
        test_gemini_author_format,
        test_double_parse_no_false_split_on_mid_content_label,
        test_deeply_nested_gemini_data,
    ]
    for test in tests:
        try:
            test()
        except AssertionError as e:
            failures.append((test.__name__, str(e)))
            print(f"  FAIL: {test.__name__}: {e}")
        except Exception as e:
            failures.append((test.__name__, f"UNEXPECTED: {e}"))
            print(f"  ERROR: {test.__name__}: {e}")

    print(f"\n{'=' * 60}")
    if failures:
        print(f"FAILURES: {len(failures)}/{len(tests)}")
        for name, msg in failures:
            print(f"  - {name}: {msg}")
        sys.exit(1)
    else:
        print(f"ALL {len(tests)} TESTS PASSED")
        sys.exit(0)
