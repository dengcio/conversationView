import re
from typing import List, Tuple


def parse_conversation(raw_text: str, source: str) -> List[Tuple[int, str, str]]:
    if not raw_text or not raw_text.strip():
        return []

    if source == "chatgpt":
        return _parse_with_prefixes(raw_text, {
            "You": "user",
            "ChatGPT": "assistant",
        })
    elif source == "claude":
        return _parse_with_prefixes(raw_text, {
            "Human": "user",
            "Assistant": "assistant",
            "Claude": "assistant",
        })
    elif source == "deepseek":
        return _parse_with_prefixes(raw_text, {
            "User": "user",
            "DeepSeek": "assistant",
            "DS": "assistant",
            "Assistant": "assistant",
        })
    elif source == "gemini":
        return _parse_with_prefixes(raw_text, {
            "User": "user",
            "Gemini": "assistant",
            "Assistant": "assistant",
            "Model": "assistant",
        })
    else:  # generic
        return _parse_generic(raw_text)


def _parse_with_prefixes(raw_text: str, prefix_map: dict) -> List[Tuple[int, str, str]]:
    pattern = re.compile(
        r'^(' + '|'.join(re.escape(k) for k in prefix_map.keys()) + r')\s*[：:]\s*(.+)',
        re.UNICODE
    )

    lines = raw_text.strip().split('\n')
    result = []
    seq = 0
    current_role = None
    current_lines = []
    prev_line_blank = True  # treat start-of-text as message boundary

    for line in lines:
        stripped = line.strip()
        m = pattern.match(stripped)

        # Only split on prefix match at message boundary (preceded by blank line or start)
        if m and prev_line_blank:
            if current_role is not None and current_lines:
                seq += 1
                result.append((seq, current_role, '\n'.join(current_lines).strip()))
            current_role = prefix_map[m.group(1)]
            current_lines = [m.group(2)]
            prev_line_blank = False
        else:
            if not stripped:
                prev_line_blank = True
            else:
                prev_line_blank = False
            if stripped or current_lines:
                if current_role is not None:
                    current_lines.append(line)

    if current_role is not None and current_lines:
        seq += 1
        result.append((seq, current_role, '\n'.join(current_lines).strip()))

    return result


def _parse_generic(raw_text: str) -> List[Tuple[int, str, str]]:
    generic_prefixes = [
        (re.compile(r'^(👤\s*用户|👤)\s*[：:]\s*(.+)', re.UNICODE), "user"),
        (re.compile(r'^(🤖\s*助手|🤖)\s*[：:]\s*(.+)', re.UNICODE), "assistant"),
        (re.compile(r'^(用户|User)\s*[：:]\s*(.+)', re.UNICODE), "user"),
        (re.compile(r'^(助手|AI|Assistant|Bot)\s*[：:]\s*(.+)', re.UNICODE), "assistant"),
    ]

    lines = raw_text.strip().split('\n')
    result = []
    seq = 0
    current_role = None
    current_lines = []

    for line in lines:
        stripped = line.strip()
        matched = False
        for pattern, role in generic_prefixes:
            m = pattern.match(stripped)
            if m:
                if current_role is not None and current_lines:
                    seq += 1
                    result.append((seq, current_role, '\n'.join(current_lines).strip()))
                current_role = role
                current_lines = [m.group(2)]
                matched = True
                break

        if not matched:
            if stripped:
                if current_role is not None:
                    current_lines.append(line)
                else:
                    if current_lines:
                        current_lines.append(line)
                    else:
                        current_lines = [line]
            elif current_lines:
                current_lines.append(line)

    if current_role is not None and current_lines:
        seq += 1
        result.append((seq, current_role, '\n'.join(current_lines).strip()))

    if not result:
        result = _fallback_parse(raw_text)

    return result


def _fallback_parse(raw_text: str) -> List[Tuple[int, str, str]]:
    """Last-resort parsing when no prefix/role markers found.

    Tries to detect roles from content patterns before falling back to alternating.
    """
    blocks = re.split(r'\n\n+|---+', raw_text.strip())
    blocks = [b.strip() for b in blocks if b.strip()]
    if not blocks:
        return []

    # Try to detect roles from common patterns in content
    result = []
    consecutive_user = 0
    consecutive_assistant = 0

    for i, block in enumerate(blocks):
        # Heuristic: blocks starting with common user patterns are likely user
        first_line = block.split('\n')[0].strip().lower()
        is_user_pattern = any(
            first_line.startswith(p) for p in (
                'user:', 'human:', 'you:', 'i ', "i'm", 'my ', 'can ', 'what ',
                'how ', 'why ', 'when ', 'where ', 'who ', 'is ', 'are ',
                'please', 'tell me', 'show me', 'write', 'create', 'help',
                'thanks', 'thank', 'hi', 'hello', 'hey',
            )
        )
        # Blocks starting with code/output markers are likely assistant
        is_assistant_pattern = any(
            first_line.startswith(p) for p in (
                'assistant:', 'model:', 'gemini:', 'ai:', 'bot:',
                '```', 'here', 'sure', 'certainly', 'the ', 'this ',
            )
        )

        if is_user_pattern and not is_assistant_pattern:
            role = "user"
            consecutive_user += 1
            consecutive_assistant = 0
        elif is_assistant_pattern and not is_user_pattern:
            role = "assistant"
            consecutive_assistant += 1
            consecutive_user = 0
        elif consecutive_user >= 2:
            # If we've had multiple users in a row, force assistant
            role = "assistant"
            consecutive_assistant += 1
            consecutive_user = 0
        elif consecutive_assistant >= 2:
            # If we've had multiple assistants in a row, force user
            role = "user"
            consecutive_user += 1
            consecutive_assistant = 0
        else:
            # Fall back to alternating
            role = "user" if i % 2 == 0 else "assistant"
            if role == "user":
                consecutive_user += 1
                consecutive_assistant = 0
            else:
                consecutive_assistant += 1
                consecutive_user = 0

        result.append((i + 1, role, block))

    return result
