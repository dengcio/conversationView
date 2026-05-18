import re
import json
import httpx
from typing import Optional


async def import_from_link(url: str) -> dict:
    """Import conversation from a shared link URL."""
    platform = _detect_platform(url)
    share_id = _extract_share_id(url)
    print(f"[link_importer] 导入链接: {url}, 平台: {platform}, share_id: {share_id}")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/html, */*",
    }

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        result = None

        if platform == "deepseek" and share_id:
            result = await _fetch_deepseek_api(client, share_id, headers)
        elif platform == "chatgpt" and share_id:
            result = await _fetch_chatgpt_api(client, share_id, headers)
        elif platform == "gemini" and share_id:
            result = await _fetch_gemini_api(client, share_id, headers)

        # Fallback: scrape HTML page
        if result is None:
            response = await client.get(url, headers=headers)
            if response.status_code != 200:
                raise ValueError(f"无法访问链接 (HTTP {response.status_code})，请确认链接可公开访问。")
            html = response.text
            print(f"[link_importer] 最终 URL: {str(response.url)}, 长度: {len(html)}")

            if platform == "chatgpt":
                result = _extract_chatgpt(html)
            elif platform == "claude":
                result = _extract_claude(html)
            elif platform == "deepseek":
                result = _extract_deepseek(html)
            elif platform == "gemini":
                result = _extract_gemini(html)
            else:
                result = _extract_generic(html)

    if result is None:
        print(f"[link_importer] 提取失败，平台={platform}")
        raise ValueError(
            "无法从此链接提取对话内容。链接可能需要登录才能访问，或者它不是有效的对话分享链接。"
        )

    print(f"[link_importer] 成功提取 {len(result['raw_text'])} 字符, 标题: {result.get('title', '')}")
    return {
        "title": result.get("title", "未命名对话"),
        "source": platform,
        "raw_text": result["raw_text"],
    }


def _extract_share_id(url: str) -> Optional[str]:
    """Extract share ID from known URL patterns."""
    # chat.deepseek.com/share/{id}
    m = re.search(r'/share/([a-zA-Z0-9_-]+)', url)
    if m:
        return m.group(1)
    # chatgpt.com/share/{id}
    m = re.search(r'/share/([a-zA-Z0-9_-]+)', url)
    if m:
        return m.group(1)
    # claude.ai/share/{id}
    m = re.search(r'/share/([a-zA-Z0-9_-]+)', url)
    if m:
        return m.group(1)
    return None


async def _fetch_deepseek_api(client: httpx.AsyncClient, share_id: str, headers: dict) -> Optional[dict]:
    """Fetch DeepSeek share content via the official API."""
    api_url = f"https://chat.deepseek.com/api/v0/share/content"
    try:
        print(f"[link_importer]   请求 API: {api_url}?share_id={share_id}")
        resp = await client.get(api_url, params={"share_id": share_id}, headers={
            **headers, "Accept": "application/json",
        })
        if resp.status_code != 200:
            print(f"[link_importer]   API 返回 {resp.status_code}")
            return None
        data = resp.json()
        biz_data = data.get("data", {}).get("biz_data", {})
        title = biz_data.get("title", "")
        messages = biz_data.get("messages", [])
        if not messages:
            print(f"[link_importer]   API 返回空消息")
            return None

        parsed = []
        for msg in messages:
            role = "user" if msg.get("role", "").upper() == "USER" else "assistant"
            content = msg.get("content", "")
            if content and str(content).strip():
                parsed.append((role, str(content)))

        if not parsed:
            print(f"[link_importer]   解析后无有效消息")
            return None

        raw_text = _format_messages(parsed, "deepseek")
        print(f"[link_importer]   成功提取 {len(parsed)} 条消息")
        return {"title": title, "raw_text": raw_text}
    except Exception as e:
        print(f"[link_importer]   API 请求失败: {e}")
        return None


async def _fetch_chatgpt_api(client: httpx.AsyncClient, share_id: str, headers: dict) -> Optional[dict]:
    """Try ChatGPT API endpoints to fetch share data."""
    api_urls = [
        f"https://chatgpt.com/backend-api/share/{share_id}",
        f"https://chatgpt.com/public-api/share/{share_id}",
        f"https://chatgpt.com/backend-api/me/sharing/{share_id}",
        f"https://chatgpt.com/api/share/{share_id}",
    ]
    for api_url in api_urls:
        try:
            print(f"[link_importer]   尝试 ChatGPT API: {api_url}")
            resp = await client.get(api_url, headers={
                **headers,
                "Accept": "application/json",
                "Origin": "https://chatgpt.com",
            })
            print(f"[link_importer]     状态={resp.status_code}, 前200字={resp.text[:200]}")
            if resp.status_code == 200:
                text = resp.text.strip()
                if text.startswith('{'):
                    try:
                        data = json.loads(text)
                        print(f"[link_importer]     JSON keys: {list(data.keys())}")
                        return _parse_chatgpt_api_response(data)
                    except json.JSONDecodeError:
                        pass
                # Also try extracting from the response if it's HTML
                result = _extract_chatgpt(text)
                if result:
                    return result
        except Exception as e:
            print(f"[link_importer]   ChatGPT API 失败: {e}")
    return None


async def _fetch_gemini_api(client: httpx.AsyncClient, share_id: str, headers: dict) -> Optional[dict]:
    """Fetch Gemini share content via API endpoints."""
    # Try API endpoints first
    api_urls = [
        f"https://gemini.google.com/_/share/{share_id}",
        f"https://gemini.google.com/api/share/{share_id}",
        f"https://generativelanguage.googleapis.com/v1beta/share/{share_id}",
    ]
    for api_url in api_urls:
        try:
            print(f"[link_importer]   尝试 Gemini API: {api_url}")
            resp = await client.get(api_url, headers={
                **headers, "Accept": "application/json",
            })
            print(f"[link_importer]     状态={resp.status_code}, 前200字={resp.text[:200]}")
            if resp.status_code == 200:
                text = resp.text.strip()
                if text.startswith('{'):
                    try:
                        data = json.loads(text)
                        print(f"[link_importer]     JSON keys: {list(data.keys())}")
                        # Try to extract messages from Gemini API response
                        msgs = _find_gemini_messages(data)
                        if msgs:
                            raw_text = _format_messages(msgs, "gemini")
                            title = data.get("title", data.get("name", ""))
                            return {"title": title, "raw_text": raw_text}
                    except json.JSONDecodeError:
                        pass
        except Exception as e:
            print(f"[link_importer]   Gemini API 失败: {e}")

    # Also try the share page with JS bundle analysis
    # Gemini sometimes embeds data as JSON in the page or in __DATA__ variables
    url = f"https://gemini.google.com/share/{share_id}"
    try:
        print(f"[link_importer]   请求 Gemini 页面: {url}")
        resp = await client.get(url, headers=headers)
        if resp.status_code == 200:
            html = resp.text
            print(f"[link_importer]   Gemini 页面长度: {len(html)}")
            # Search for any JS bundle URLs to find API endpoints
            js_urls = re.findall(r'(?:src|href)="([^"]*\.js[^"]*)"', html)
            print(f"[link_importer]   JS 文件: {len(js_urls)} 个")
            for js_url in js_urls[:5]:
                print(f"[link_importer]     {js_url}")
            # Try to find __DATA__ or similar patterns
            for pattern in [r'window\.__DATA__', r'window\.__INITIAL_STATE__', r'AF_initDataCallback']:
                if re.search(pattern, html):
                    print(f"[link_importer]   发现模式: {pattern}")
            return _extract_gemini(html)
        else:
            print(f"[link_importer]   Gemini 页面返回 {resp.status_code}")
    except Exception as e:
        print(f"[link_importer]   Gemini 页面请求失败: {e}")
    return None


def _parse_deepseek_api_response(data: dict) -> Optional[dict]:
    """Parse DeepSeek API response into messages."""
    msgs = (
        data.get("data", {}).get("biz_data", {}).get("chat_session", {}).get("messages")
        or data.get("data", {}).get("messages")
        or data.get("messages")
        or data.get("chat_session", {}).get("messages")
        or data.get("data", {}).get("chat_session")
    )
    if not msgs:
        # Try deeper nesting
        for key in data:
            if isinstance(data[key], dict):
                inner = _parse_deepseek_api_response(data[key])
                if inner:
                    return inner
        return None

    messages = []
    for msg in msgs:
        role = msg.get("role", "user")
        content = msg.get("content", "") or msg.get("text", "")
        if content and str(content).strip():
            messages.append((role, str(content)))

    if not messages:
        return None

    title = data.get("data", {}).get("biz_data", {}).get("chat_session", {}).get("title", "")
    title = title or data.get("title", "")
    raw_text = _format_messages(messages, "deepseek")
    return {"title": title, "raw_text": raw_text}


def _parse_chatgpt_api_response(data: dict) -> Optional[dict]:
    """Parse ChatGPT API response into messages."""
    mapping = data.get("mapping", {})
    if mapping:
        return _parse_chatgpt_mapping(data)
    messages = data.get("messages") or data.get("data", {}).get("messages")
    if messages:
        msgs = []
        for m in messages:
            role = m.get("author", {}).get("role", m.get("role", "user"))
            content = m.get("content", {}).get("parts", [m.get("content", "")])
            if isinstance(content, list):
                content = "\n".join(str(p) for p in content if p)
            if content and str(content).strip():
                msgs.append((role, str(content)))
        if msgs:
            return {"title": data.get("title", ""), "raw_text": _format_messages(msgs, "chatgpt")}
    return None


def _detect_platform(url: str) -> str:
    url_lower = url.lower()
    if "chatgpt.com" in url_lower or "chat.openai.com" in url_lower:
        return "chatgpt"
    if "claude.ai" in url_lower:
        return "claude"
    if "chat.deepseek.com" in url_lower or "platform.deepseek.com" in url_lower:
        return "deepseek"
    if "gemini.google.com" in url_lower:
        return "gemini"
    return "generic"


def _extract_chatgpt(html: str) -> Optional[dict]:
    # Strategy 0: React Router streaming — extract all streamController.enqueue() calls
    enqueue_calls = re.findall(
        r'window\.__reactRouterContext\.streamController\.enqueue\(("[\s\S]*?")\);',
        html
    )
    if enqueue_calls:
        print(f"[link_importer]   ChatGPT: 找到 {len(enqueue_calls)} 个 React Router stream enqueue")
        # Concatenate all streamed data
        full_stream = ""
        for call in enqueue_calls:
            try:
                decoded = json.loads(call)  # JSON string decode
                full_stream += decoded
            except json.JSONDecodeError:
                full_stream += call.strip('"')
        print(f"[link_importer]   Stream 总长度: {len(full_stream)}")

        result = _parse_react_router_stream(full_stream)
        if result:
            return result

    # Strategy 1: __NEXT_DATA__ JSON (older Next.js SSR data)
    match = re.search(
        r'<script\s+id="__NEXT_DATA__"[^>]*type="application/json"[^>]*>([\s\S]*?)</script>',
        html
    )
    if match:
        try:
            data = json.loads(match.group(1))
            props = data.get("props", {}).get("pageProps", {})
            chat_data = props.get("chatData") or props.get("serverResponse", {})
            print(f"[link_importer]   ChatGPT __NEXT_DATA__: chat_data keys={list(chat_data.keys())}")
            if "mapping" in chat_data:
                return _parse_chatgpt_mapping(chat_data)
            if "linearConversation" in chat_data:
                return _parse_chatgpt_linear(chat_data)
        except (json.JSONDecodeError, KeyError) as e:
            print(f"[link_importer]   ChatGPT __NEXT_DATA__ 失败: {e}")

    # Strategy 2: window.__DATA__
    match = re.search(r'window\.__DATA__\s*=\s*({[\s\S]*?});', html)
    if match:
        try:
            data = json.loads(match.group(1))
            print(f"[link_importer]   ChatGPT window.__DATA__: keys={list(data.keys())}")
            if "mapping" in data:
                return _parse_chatgpt_mapping(data)
        except (json.JSONDecodeError, KeyError) as e:
            print(f"[link_importer]   ChatGPT window.__DATA__ 失败: {e}")

    # Strategy 3: application/json script tags
    for sm in re.finditer(r'<script[^>]*type="application/json"[^>]*>([\s\S]*?)</script>', html):
        try:
            data = json.loads(sm.group(1))
            if isinstance(data, dict) and any(k in data for k in ("mapping","messages","conversation")):
                print(f"[link_importer]   ChatGPT JSON script found conversation data")
                return _parse_chatgpt_generic(data)
        except (json.JSONDecodeError, KeyError):
            continue

    # Strategy 4: Visible HTML extraction
    result = _extract_from_visible_html(html, "chatgpt")
    if result:
        return result

    print(f"[link_importer]   ChatGPT 所有策略失败")
    return None


def _parse_react_router_stream(stream: str) -> Optional[dict]:
    """Extract conversation messages from React Router turbo-stream using direct string matching."""
    messages = []
    title = ""

    # Extract title from meta section
    title_m = re.search(r'"pageTitle","([^"]+)"', stream)
    if title_m:
        title = title_m.group(1)
        print(f"[link_importer]   标题: {title}")

    # Strategy: Find all "parts",[...] patterns containing message text
    # Each message has: "content_type","text","parts",[...content...]
    # The parts array contains the message text

    # Find the linear_conversation to get message order
    lc_match = re.search(r'"linear_conversation",\[([^\]]+)\]', stream)
    msg_indices = []
    if lc_match:
        msg_indices = [int(x) for x in re.findall(r'\d+', lc_match.group(1))]
        print(f"[link_importer]   消息索引: {msg_indices}")

    # Find message entries: each is "N",{...manifest...} where N is an index
    # Each message manifest points to message data
    # The actual message objects are like: "message",{...} with content

    # Clean up React Router stream format:
    # 1. Remove line prefixes like "P374:"
    # 2. Find the main JSON array
    clean = re.sub(r'^[A-Za-z]?\d*:', '', stream, flags=re.MULTILINE)

    # Try to find and parse the main JSON array
    try:
        arr = json.loads(clean)
    except json.JSONDecodeError:
        # Try extracting just the first complete JSON array
        m = re.match(r'(\[[\s\S]*\])(?:[^\]]|$)', clean)
        if m:
            try:
                arr = json.loads(m.group(1))
            except json.JSONDecodeError:
                print(f"[link_importer]   JSON 解析仍然失败")
                arr = None
        else:
            arr = None

    if arr and isinstance(arr, list):
        all_strings = []
        _collect_strings(arr, all_strings)

        # Filter message-like content
        candidates = []
        for s in all_strings:
            if len(s) > 80 and not any(x in s.lower() for x in ['chatgpt.com', 'cdn.openai', 'gpt-5', 'data-build', '__reactRouter', 'streamController', '.js', '.css', '.png', '.jpg']):
                candidates.append(s)

        print(f"[link_importer]   候选消息: {len(candidates)}")
        for i, c in enumerate(candidates[:10]):
            print(f"[link_importer]     [{i}] {c[:120]}...")

        if candidates:
            # ChatGPT share conversations alternate: user, assistant, user, assistant...
            # Determine starting role by looking at author info in the stream
            roles = []
            _extract_roles_from_stream(stream, roles)
            start_role = roles[0] if roles else "user"
            print(f"[link_importer]   角色序列: {roles[:5]}..., 起始角色: {start_role}")

            for i, text in enumerate(candidates):
                role = "user" if i % 2 == 0 else "assistant"
                if start_role == "assistant":
                    role = "assistant" if i % 2 == 0 else "user"
                messages.append((role, text))
    else:
        print(f"[link_importer]   JSON 解析失败")
        # Direct regex: find all long quoted strings
        for m in re.finditer(r'"([^"]{100,})"', stream):
            text = m.group(1)
            if not any(x in text for x in ['chatgpt.com', 'cdn.openai', 'gpt-5', 'chunk-', '.js']):
                messages.append(("user", text))

    if messages:
        print(f"[link_importer]   提取到 {len(messages)} 条消息")
        raw_text = _format_messages(messages, "chatgpt")
        return {"title": title, "raw_text": raw_text}

    return None


def _collect_strings(obj, result):
    """Recursively collect all string values from a JSON structure."""
    if isinstance(obj, str):
        result.append(obj)
    elif isinstance(obj, list):
        for item in obj:
            _collect_strings(item, result)
    elif isinstance(obj, dict):
        for v in obj.values():
            _collect_strings(v, result)


def _extract_roles_from_stream(stream, roles):
    """Extract message roles from the stream."""
    # Find "author",{...} patterns and look for role info
    for m in re.finditer(r'"author",\{[^}]+\}', stream):
        author_block = m.group()
        if '"assistant"' in author_block or '"role":"assistant"' in author_block:
            roles.append("assistant")
        elif '"user"' in author_block or '"role":"user"' in author_block:
            roles.append("user")
        elif '"system"' in author_block or '"role":"system"' in author_block:
            roles.append("system")
        else:
            roles.append("assistant")  # default for ChatGPT shares


def _is_metadata(text):
    """Check if text looks like metadata/technical content, NOT conversation."""
    if len(text) < 30:
        return True
    # HTML/CSS/JS artifacts
    meta_patterns = [
        'AF_initDataCallback', 'function(', 'gstatic',
        'googletagmanager', 'google', 'viewport', 'width=device',
        'initial-scale', 'charset', 'stylesheet', 'text/css',
        'application/json', 'data-build', '__reactRouterContext',
        '__NEXT_DATA__', 'streamController', 'import{',
        'gemini.google.com', 'chatgpt.com', 'cdn.openai',
        'script nonce', 'style nonce', 'nonce=',
        '{', '}', 'import ', 'export ', 'return ', 'const ',
        '.png', '.jpg', '.svg', '.ico', '.js?', '.css?', '.js"', '.css"',
    ]
    for pat in meta_patterns:
        if pat.lower() in text.lower():
            return True
    # No spaces or very few spaces = not natural language
    space_ratio = text.count(' ') / max(len(text), 1)
    if space_ratio < 0.01:  # Less than 1% spaces
        return True
    # Base64-like: long runs without spaces, high uppercase ratio
    if len(text) > 100 and space_ratio < 0.02:
        return True
    # High ratio of non-letter characters
    alpha_count = sum(1 for c in text if c.isalpha() or c.isspace())
    if len(text) > 0 and alpha_count / len(text) < 0.4:
        return True
    # Starts with HTML/XML-like content
    if text.strip().startswith('<'):
        return True
    return False


def _is_conversation_content(text):
    """Check if text looks like conversation content (not metadata)."""
    return not _is_metadata(text)


def _parse_chatgpt_mapping(data: dict) -> dict:
    mapping = data.get("mapping", {})
    messages = []
    title = data.get("title", "")

    # mapping keys are node IDs, each with message data
    sorted_nodes = sorted(
        [v for v in mapping.values() if v.get("message")],
        key=lambda x: x.get("message", {}).get("create_time") or 0
    )

    for node in sorted_nodes:
        msg = node["message"]
        author = msg.get("author", {})
        role = author.get("role", "user")
        content_parts = msg.get("content", {}).get("parts", [])
        content = "\n".join(str(p) for p in content_parts if p and isinstance(p, str))

        if content.strip():
            if role == "assistant":
                role = "assistant"
            elif role == "user":
                role = "user"
            else:
                role = msg.get("role", role)

            messages.append((role, content))

    raw_text = _format_messages(messages, "chatgpt")
    return {"title": title, "raw_text": raw_text}


def _parse_chatgpt_linear(data: dict) -> dict:
    messages = []
    conversation = data.get("linearConversation", data.get("conversation", []))
    for msg in conversation:
        role = msg.get("speaker") or msg.get("author", {}).get("role", "user")
        if role == "assistant":
            role = "assistant"
        else:
            role = "user"
        content = msg.get("text", msg.get("content", ""))
        if isinstance(content, list):
            content = "\n".join(str(p) for p in content if p)
        if content and str(content).strip():
            messages.append((role, str(content)))

    raw_text = _format_messages(messages, "chatgpt")
    title = data.get("title", "")
    return {"title": title, "raw_text": raw_text}


def _parse_chatgpt_generic(data: dict) -> dict:
    messages = []
    # Try to find messages anywhere in the structure
    all_messages = []
    _find_messages_recursive(data, all_messages)
    if all_messages:
        raw_text = _format_messages(all_messages, "chatgpt")
        return {"title": data.get("title", ""), "raw_text": raw_text}
    return None


def _find_messages_recursive(obj, results, depth=0):
    if depth > 10:
        return
    if isinstance(obj, dict):
        if "author" in obj and ("content" in obj or "parts" in obj):
            author = obj["author"]
            role = author.get("role", "user") if isinstance(author, dict) else "user"
            if role == "assistant":
                role = "assistant"
            else:
                role = "user"
            content = obj.get("content", "")
            if isinstance(content, dict):
                parts = content.get("parts", [])
                content = "\n".join(str(p) for p in parts if p)
            if content and str(content).strip():
                results.append((role, str(content)))
        for v in obj.values():
            _find_messages_recursive(v, results, depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            _find_messages_recursive(item, results, depth + 1)


def _extract_claude(html: str) -> Optional[dict]:
    # Strategy 1: Look for JSON data in script tags
    for match in re.finditer(
        r'<script[^>]*type="application/json"[^>]*>([\s\S]*?)</script>',
        html
    ):
        try:
            data = json.loads(match.group(1))
            if "chat_messages" in data or "messages" in data:
                msgs = data.get("chat_messages") or data.get("messages", [])
                messages = []
                for msg in msgs:
                    role = "user" if msg.get("sender") == "human" else "assistant"
                    content = msg.get("text", msg.get("content", ""))
                    if content and str(content).strip():
                        messages.append((role, str(content)))
                if messages:
                    raw_text = _format_messages(messages, "claude")
                    return {"title": data.get("name", data.get("title", "")), "raw_text": raw_text}
        except (json.JSONDecodeError, KeyError):
            continue

    # Strategy 2: Extract from visible HTML
    result = _extract_from_visible_html(html, "claude")
    if result:
        return result

    return None


def _extract_deepseek(html: str) -> Optional[dict]:
    # Strategy 1: Look for JSON data
    for match in re.finditer(
        r'<script[^>]*type="application/json"[^>]*>([\s\S]*?)</script>',
        html
    ):
        try:
            data = json.loads(match.group(1))
            if "chat_session" in data or "messages" in data or "conversation" in data:
                msgs = data.get("messages") or data.get("chat_session", {}).get("messages") or data.get("conversation", [])
                messages = []
                for msg in msgs:
                    role = msg.get("role", "user")
                    content = msg.get("content", "")
                    if content and str(content).strip():
                        messages.append((role, str(content)))
                if messages:
                    raw_text = _format_messages(messages, "deepseek")
                    return {"title": data.get("title", data.get("name", "")), "raw_text": raw_text}
        except (json.JSONDecodeError, KeyError):
            continue

    # Strategy 2: Extract from visible HTML
    result = _extract_from_visible_html(html, "deepseek")
    if result:
        return result

    return None


def _is_valid_conversation_result(result: dict) -> bool:
    """Check if extracted result looks like real conversation, not JS artifacts."""
    if not result or not result.get("raw_text"):
        return False
    raw = result["raw_text"]
    # Must have at least some actual content
    if len(raw) < 100:
        return False
    # Check that formatted messages look like conversation
    msgs = raw.split("\n\n")
    real_msgs = 0
    for msg in msgs:
        if not msg.strip():
            continue
        # Skip metadata-looking messages
        if re.search(r'\.js\b|\.css\b|googleapis\.|gci_|\.push\(|function\s*\(', msg):
            continue
        # Must have a role label and some content
        if re.match(r'(User|Gemini|Assistant|Model):\s*\S', msg):
            content_part = msg.split(':', 1)[1].strip() if ':' in msg else ''
            if len(content_part) > 20:
                real_msgs += 1
    print(f"[link_importer]   Validation: {len(msgs)} formatted msgs, {real_msgs} real-looking")
    return real_msgs >= 2


def _extract_gemini_visible_text(html: str) -> Optional[dict]:
    """Extract conversation from Gemini share page by parsing visible text.

    Gemini renders conversation as visible text in the HTML (SSR).
    This extracts natural-language text segments and assembles them as messages.
    """
    # Remove script and style content
    clean = re.sub(r'<script[^>]*>[\s\S]*?</script>', '', html, flags=re.IGNORECASE)
    clean = re.sub(r'<style[^>]*>[\s\S]*?</style>', '', clean, flags=re.IGNORECASE)
    clean = re.sub(r'<noscript[^>]*>[\s\S]*?</noscript>', '', clean, flags=re.IGNORECASE)
    # Remove HTML comments
    clean = re.sub(r'<!--[\s\S]*?-->', '', clean)

    # Strip remaining HTML tags — use space not newline to keep text flowing
    text = re.sub(r'<[^>]+>', ' ', clean)

    # Decode common HTML entities
    import html as _html
    text = _html.unescape(text)

    # Normalize whitespace: collapse spaces, keep paragraph breaks
    text = re.sub(r'[ \t\r]+', ' ', text)
    text = re.sub(r'\n{2,}', '\n\n', text)
    text = re.sub(r' \n', '\n', text)
    text = re.sub(r'\n ', '\n', text)

    # Apply unicode unescape to the entire text first
    text = _unescape_content(text)

    # Find natural language segments DIRECTLY from HTML before stripping tags.
    # HTML tags act as natural boundaries between messages — the character class
    # excludes tag characters like < > / so segments auto-split at tag boundaries.
    raw_segments = re.findall(r'[\w\s一-鿿.,!?;:()\[\]{}\"\'\-_@#$%^&*+=]{80,}', clean)
    print(f"[link_importer]   Raw segments from HTML: {len(raw_segments)}")

    # Now strip any remaining inline tags from each segment
    segments = []
    for seg in raw_segments:
        seg = re.sub(r'<[^>]+>', ' ', seg)
        seg = re.sub(r'\s+', ' ', seg).strip()
        if seg:
            segments.append(seg)

    # Fallback: if regex approach yields too few, try newline-based splitting
    if len(segments) < 3:
        blocks = [b.strip() for b in text.split('\n\n') if b.strip()]
        segments = []
        for block in blocks:
            lines = [l.strip() for l in block.split('\n') if l.strip()]
            for line in lines:
                if len(line) >= 30:
                    segments.append(line)

    print(f"[link_importer]   Raw segments before filter: {len(raw_segments)}")

    # Filter: must be natural language, not UI boilerplate, reasonable length
    segments = []
    for seg in raw_segments:
        seg = seg.strip()
        if len(seg) < 30:
            continue
        if len(seg) > 10000:  # Too long = probably concatenated
            continue
        if _is_gemini_ui_boilerplate(seg):
            continue
        # Must have spaces (natural language), not just one long token
        if ' ' not in seg and '\n' not in seg:
            continue
        segments.append(seg)

    print(f"[link_importer]   After filter: {len(segments)} segments")

    if not segments:
        return None

    # Deduplicate: remove shorter substrings contained in longer ones
    deduped = []
    for s in segments:
        is_sub = False
        for other in segments:
            if s != other and s in other and len(s) < len(other):
                is_sub = True
                break
        if not is_sub:
            deduped.append(s)

    print(f"[link_importer]   After dedup: {len(deduped)} segments")

    # Build messages with alternating roles (Gemini always starts with user)
    messages = []
    for i, content in enumerate(deduped):
        role = "user" if i % 2 == 0 else "assistant"
        messages.append((role, content))

    if not messages:
        return None

    print(f"[link_importer]   Visible text messages: {len(messages)}")
    for i, (r, c) in enumerate(messages[:6]):
        print(f"[link_importer]     [{i}] {r}: {c[:150]}...")

    raw_text = _format_messages(messages, "gemini")
    return {"title": "", "raw_text": raw_text}


def _is_gemini_ui_boilerplate(text: str) -> bool:
    """Check if text looks like Gemini UI boilerplate, not conversation content."""
    boilerplate_patterns = [
        r'^©\s*\d{4}',  # Copyright
        r'^Privacy(\s|$)',  # Privacy link
        r'^Terms(\s|$)',  # Terms link
        r'^Gemini(\s|$)',  # Just "Gemini" label
        r'^Google(\s|$)',  # Just "Google" label
        r'^Sign\sin',  # Sign in
        r'^Help(\s|$)',  # Help link
        r'^Send\sfeedback',  # Feedback link
        r'^Report\sabuse',  # Report abuse
        r'^Dark\stheme',  # Theme toggle
        r'^Light\stheme',  # Theme toggle
        r'^Settings(\s|$)',  # Settings
        r'^Navigation',  # Navigation
        r'^Menu(\s|$)',  # Menu
        r'^Search(\s|$)',  # Search
        r'^Skip\sto',  # Skip to content
        r'^More(\s|$)',  # More button
        r'^Share(\s|$)',  # Share button
        r'^Export(\s|$)',  # Export button
        r'^Delete(\s|$)',  # Delete button
        r'^Copy(\s|$)',  # Copy button
        r'^Edit(\s|$)',  # Edit button
        r'^New\s(chat|conversation)',  # New chat
        r'^Chat\s\d+',  # Chat 1, Chat 2
        r'^Today(\s|$)',  # Date label
        r'^Yesterday(\s|$)',  # Date label
        r'^Previous\s\d+\sdays',  # Date range
        r'^\d+:\d+\s*(AM|PM)?$',  # Time label
        r'^Loading',  # Loading indicator
        r'^Error(\s|$)',  # Error
        r'^Retry(\s|$)',  # Retry
        r'^Cancel(\s|$)',  # Cancel
        r'^Submit(\s|$)',  # Submit
        r'^Enter\sa\sprompt',  # Input placeholder
        r'^Type\ssomething',  # Input placeholder
        r'^Ask\sGemini',  # Input placeholder
        r'^You\shave\sreached',  # Limit warning
        r'^Please\stry\sagain',  # Error message
        r'^Something\swent\swrong',  # Error message
        r'^\(function',  # JS code leaked
        r'^var\s',  # JS code leaked
        r'^function\s',  # JS code leaked
        r'^use\sstrict',  # JS code leaked
        r'\.js\s*$',  # JS filename
        r'googleapis\.',  # Google API reference
        r'gci_',  # Google component ID
    ]
    for pat in boilerplate_patterns:
        if re.search(pat, text, re.IGNORECASE):
            return True
    # High ratio of numbers/symbols
    alpha_ratio = sum(1 for c in text if c.isalpha() or c.isspace()) / max(len(text), 1)
    if alpha_ratio < 0.5:
        return True
    return False


def _try_extract_json_from_text(text: str) -> Optional[dict]:
    """Try to find and extract conversation data from text containing JSON fragments."""
    # Find all JSON array starts
    best_result = None
    for bracket_m in re.finditer(r'\[', text):
        depth = 0
        start = bracket_m.start()
        end = start
        for i in range(start, min(start + 1000000, len(text))):
            if text[i] == '[':
                depth += 1
            elif text[i] == ']':
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end <= start:
            continue
        json_str = text[start:end]
        if len(json_str) < 200:
            continue
        # Clean up JS quirks
        for attempt in range(2):
            try:
                data = json.loads(json_str)
                # Check if this looks like conversation data
                if isinstance(data, list) and len(data) > 0:
                    result = _extract_from_gemini_data(data)
                    if result:
                        print(f"[DEBUG-gemini]   try_extract: raw_text preview: {result['raw_text'][:200]}...")
                        if _is_valid_conversation_result(result):
                            return result
                        elif best_result is None:
                            best_result = result  # keep as fallback
                break
            except json.JSONDecodeError:
                if attempt == 0:
                    cleaned = re.sub(r'/\*[\s\S]*?\*/', '', json_str)
                    cleaned = re.sub(r'//[^\n]*', '', cleaned)
                    cleaned = re.sub(r',\s*([}\]])', r'\1', cleaned)
                    json_str = cleaned
    return None


def _extract_gemini(html: str) -> Optional[dict]:
    """Extract conversation from Gemini share page HTML.

    Gemini uses Google's AF_initDataCallback pattern to pass server data to client.
    The conversation data is embedded in these callbacks as JSON arrays.
    """
    # Strategy 1: AF_initDataCallback — Google's data injection pattern
    # Format: AF_initDataCallback({key: 'ds:0', data: [...]});
    #         AF_initDataCallback({key: 'ds:0', data: function() { return [...] }});

    # DEBUG: Show context around AF_initDataCallback occurrences
    for m in re.finditer(r'AF_initDataCallback', html):
        ctx = html[max(0, m.start()-50):m.end()+200]
        print(f"[DEBUG-gemini] AF_initDataCallback at {m.start()}: ...{ctx[:300]}...")

    # DEBUG: Search for data injection patterns
    for pat in [r'AF_initDataChunkQueue\.push', r'AF_initDataCallback\s*\(', r'window\.__DATA__', r'window\.__INITIAL_STATE__']:
        matches = list(re.finditer(pat, html))
        if matches:
            for m in matches[:3]:
                ctx = html[max(0, m.start()-30):m.end()+300]
                print(f"[DEBUG-gemini] Pattern '{pat}' at {m.start()}: ...{ctx[:400]}...")
        else:
            print(f"[DEBUG-gemini] Pattern '{pat}': NOT FOUND")

    # DEBUG: Show visible text content (strip HTML tags)
    visible_text = re.sub(r'<[^>]+>', ' ', html)
    visible_text = re.sub(r'\s+', ' ', visible_text).strip()
    # Find long natural language segments
    text_segments = re.findall(r'[\w\s一-鿿]{80,}', visible_text)
    print(f"[DEBUG-gemini] Visible text segments (>80 chars): {len(text_segments)}")
    for i, seg in enumerate(text_segments[:5]):
        print(f"[DEBUG-gemini]   seg[{i}]: {seg[:200]}...")

    # Step 1: Find all AF_initDataCallback blocks — try multiple regex variants
    cb_starts = []
    for pattern in [
        r'AF_initDataCallback\s*\(\s*\{',
        r'AF_initDataCallback\s*\(',
        r'AF_initDataChunkQueue\.push\s*\(',
    ]:
        for m in re.finditer(pattern, html):
            cb_starts.append((m.start(), m.end(), pattern))
    # Deduplicate by start position
    seen = set()
    unique = []
    for s, e, p in cb_starts:
        if s not in seen:
            seen.add(s)
            unique.append((s, e, p))
    cb_starts = unique
    print(f"[link_importer]   Gemini: found {len(cb_starts)} data blocks")
    for s, e, p in cb_starts:
        ctx = html[s:min(s+200, len(html))]
        print(f"[DEBUG-gemini]   block '{p}' at {s}: ...{ctx}...")

    for block_start, data_start, block_pattern in cb_starts:
        # Step 2: Find the data array using bracket counting from the data key
        # For AF_initDataChunkQueue.push([...]), search for the array directly
        if 'push' in block_pattern:
            data_key_match = re.search(r'push\s*\(', html[data_start-10:data_start+10])
            if data_key_match:
                arr_start = data_start + 1  # skip past the '(' after 'push'
            else:
                arr_start = data_start
        else:
            data_key_match = re.search(r'data\s*:\s*(?:function\s*\(\s*\)\s*\{?\s*return\s*)?', html[data_start:])
            if not data_key_match:
                continue
            arr_start = data_start + data_key_match.end()
        if arr_start >= len(html) or html[arr_start] not in '[{':
            continue

        # Step 3: Bracket counting to find the matching closing bracket
        depth = 0
        arr_end = arr_start
        for i in range(arr_start, min(arr_start + 500000, len(html))):
            if html[i] == '[':
                depth += 1
            elif html[i] == ']':
                depth -= 1
                if depth == 0:
                    arr_end = i + 1
                    break

        if arr_end <= arr_start:
            continue

        data_str = html[arr_start:arr_end]
        print(f"[link_importer]   Gemini AF_initDataCallback data_len={len(data_str)}")

        # Step 4: Try parsing as JSON, with JS-literal cleanup
        data = None
        for parse_attempt in range(2):
            try:
                data = json.loads(data_str)
                break
            except json.JSONDecodeError:
                if parse_attempt == 0:
                    # Clean up JS object literal quirks
                    cleaned = re.sub(r'/\*[\s\S]*?\*/', '', data_str)  # remove block comments
                    cleaned = re.sub(r'//[^\n]*', '', cleaned)  # remove line comments
                    cleaned = re.sub(r',\s*([}\]])', r'\1', cleaned)  # remove trailing commas
                    data_str = cleaned
                else:
                    continue

        if data is not None:
            print(f"[link_importer]   JSON parsed, type={type(data).__name__}")
            result = _extract_from_gemini_data(data)
            if result:
                return result
        else:
            print(f"[link_importer]   JSON parse failed, trying demjson3...")
            # Final attempt: try demjson3 for very loose JS parsing
            try:
                import demjson3
                data = demjson3.decode(data_str)
                result = _extract_from_gemini_data(data)
                if result:
                    return result
            except Exception:
                continue

    # Strategy 1.5: Search all <script> tags for conversation-like JSON data
    print(f"[link_importer]   Gemini Strategy 1.5: searching script tags for JSON")
    script_matches = list(re.finditer(r'<script[^>]*>([\s\S]*?)</script>', html))
    print(f"[link_importer]   Found {len(script_matches)} script tags")
    for si, sm in enumerate(script_matches):
        script_content = sm.group(1).strip()
        if len(script_content) < 500:
            continue
        # Try to find JSON objects/arrays that look like conversation data
        for json_pattern in [
            r'\{["\'](?:messages|conversation|chat|contents|parts|role)',
            r'\[["\'](?:user|model|human|assistant)',
            r'\[\[.+?\]\]',
        ]:
            if re.search(json_pattern, script_content, re.IGNORECASE):
                print(f"[link_importer]   Script tag {si}: len={len(script_content)}, found pattern: {json_pattern}")
                # Try to extract the JSON data
                result = _try_extract_json_from_text(script_content)
                if result:
                    print(f"[link_importer]   Script tag {si}: extraction succeeded!")
                    return result
                break

    # Strategy 2: Extract visible conversation text from HTML
    print(f"[link_importer]   Gemini Strategy 2: visible text extraction")
    result = _extract_gemini_visible_text(html)
    if result:
        return result

    # Strategy 2b: Visible HTML extraction (prefix-based)
    print(f"[link_importer]   Gemini Strategy 2b: visible HTML extraction")
    result = _extract_from_visible_html(html, "gemini")
    if result:
        return result

    # Strategy 3: Generic approach — extract conversation-like strings from HTML (last resort)
    print(f"[link_importer]   Gemini Strategy 3: generic string extraction")
    all_strings = re.findall(r'"([^"]{60,})"', html)
    candidates = []
    for s in all_strings:
        decoded = _unescape_content(s)
        if _is_metadata(decoded) or _is_gemini_suggestion(decoded):
            continue
        candidates.append(decoded)

    print(f"[link_importer]   Gemini candidate messages: {len(candidates)}")
    if candidates:
        messages = []
        roles = _extract_gemini_roles_from_strings(all_strings)
        for i, text in enumerate(candidates):
            if roles and i < len(roles):
                role = roles[i]
            else:
                role = "user" if i % 2 == 0 else "assistant"
            messages.append((role, text))
        if messages:
            return {"title": "", "raw_text": _format_messages(messages, "gemini")}

    return None


def _extract_from_gemini_data(data) -> Optional[dict]:
    """Extract conversation messages from Gemini data structures.

    Gemini embeds conversation in deeply nested arrays. The data structure is:
    [[["text1", "text2", ...], [...], ...], ...]
    or [[[msg_obj1, msg_obj2, ...], ...]]
    where msg_obj has keys like role, content, parts, text.
    """
    # Strategy A: Structured extraction — look for message objects with known keys
    msgs = _find_gemini_messages(data)
    if msgs:
        filtered = [(r, c) for r, c in msgs if not _is_gemini_suggestion(c)]
        if filtered:
            print(f"[link_importer]   Gemini structured extraction: {len(filtered)} messages (filtered {len(msgs) - len(filtered)} suggestions)")
            raw_text = _format_messages(filtered, "gemini")
            return {"title": "", "raw_text": raw_text}

    # Strategy B: String collection with metadata filtering
    all_strings = []
    _collect_strings(data, all_strings)

    title = ""
    candidates = []
    for s in all_strings:
        if len(s) > 80 and not _is_metadata(s) and not _is_gemini_suggestion(s):
            if not any(x in s.lower() for x in [
                'gemini.google.com', 'gstatic.com', 'googletagmanager',
                'function(', 'import ', 'export ', '.js', '.css',
                'AF_initDataCallback', 'window.', 'document.',
            ]):
                candidates.append(s)

    print(f"[link_importer]   Gemini candidate messages: {len(candidates)}")
    for i, c in enumerate(candidates[:8]):
        print(f"[link_importer]     [{i}] {c[:120]}...")

    if not candidates:
        return None

    messages = []
    roles = _extract_gemini_roles_from_strings(all_strings)

    for i, text in enumerate(candidates):
        if text.startswith('##') and ('Prompt' in text or 'System' in text):
            title = text.split('\n')[0].replace('## ', '')[:50]
            continue
        # Determine role: use detected roles if available, else fall back to alternating
        if roles and i < len(roles):
            role = roles[i]
        else:
            role = "user" if i % 2 == 0 else "assistant"
        messages.append((role, _unescape_content(text)))

    if messages:
        # Merge consecutive same-role messages
        merged = []
        for role, content in messages:
            if merged and merged[-1][0] == role:
                merged[-1] = (role, merged[-1][1] + "\n\n" + content)
            else:
                merged.append((role, content))
        raw_text = _format_messages(merged, "gemini")
        return {"title": title, "raw_text": raw_text}

    return None


def _extract_gemini_roles_from_strings(strings):
    """Try to find role indicators in Gemini data strings.

    Returns list of ('user'|'assistant') matching each string's detected role,
    or empty list if roles cannot be determined.
    """
    roles = []
    for s in strings:
        s_lower = s.lower()
        if s in ('user', 'human', 'model', 'assistant', 'gemini', 'bot'):
            roles.append('user' if s_lower in ('user', 'human') else 'assistant')
    return roles


def _unescape_content(text: str) -> str:
    """Decode JSON/JS escape sequences: \\uXXXX, \\n, \\t, \\\", \\\\, etc."""
    if not isinstance(text, str):
        return str(text)
    # Use JSON decode for full escape handling (handles \\uXXXX, \\n, \\\", etc.)
    try:
        return json.loads(f'"{text}"')
    except (json.JSONDecodeError, ValueError):
        pass
    # Fallback: regex-based unicode escape + common escapes
    result = text
    result = re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1), 16)), result)
    result = result.replace('\\n', '\n').replace('\\t', '\t')
    result = result.replace('\\"', '"').replace('\\\\', '\\').replace('\\/', '/')
    return result


def _find_gemini_messages(data, depth=0):
    """Recursively search for message arrays in Gemini data structures.

    Handles multiple Gemini message formats:
    1. [{"role": "user", "content": "..."}, {"role": "model", "content": "..."}]
    2. [{"author": "user", "parts": [{"text": "..."}]}, ...]
    3. [[[msg_obj1, msg_obj2, ...]]] — deeply nested
    """
    if depth > 10:
        return None
    if isinstance(data, list) and len(data) > 0:
        # Check if this list contains message-like objects
        msg_like_count = 0
        for item in data:
            if isinstance(item, dict) and any(k in item for k in ("content", "text", "parts", "role", "author")):
                msg_like_count += 1
        # If majority of items are message-like, parse them all
        if msg_like_count > 0 and msg_like_count >= len(data) * 0.5:
            messages = []
            for msg in data:
                if not isinstance(msg, dict):
                    continue
                role = msg.get("role", msg.get("author", ""))
                role_str = str(role).lower()
                if role_str in ("user", "human", "0"):
                    role = "user"
                elif role_str in ("system",):
                    role = "system"
                else:
                    role = "assistant"
                # Handle multiple content formats:
                # 1. {"content": "text"} or {"text": "text"}
                # 2. {"content": ["part1", "part2"]}
                # 3. {"parts": [{"text": "..."}, ...]} (Gemini format)
                # 4. {"content": {"parts": [{"text": "..."}]}}
                content = msg.get("content", msg.get("text", ""))
                if not content:
                    # Try parts directly on message (Gemini format)
                    parts = msg.get("parts", [])
                    if parts:
                        content = parts
                if isinstance(content, list):
                    parts = []
                    for p in content:
                        if isinstance(p, dict):
                            part_text = p.get("text", str(p))
                            parts.append(_unescape_content(part_text))
                        else:
                            parts.append(_unescape_content(str(p)))
                    content = "\n".join(parts)
                if content and str(content).strip():
                    messages.append((role, _unescape_content(str(content))))
            if messages:
                # Merge consecutive same-role messages (e.g., thinking + response)
                merged = []
                for role, content in messages:
                    if merged and merged[-1][0] == role:
                        merged[-1] = (role, merged[-1][1] + "\n\n" + content)
                    else:
                        merged.append((role, content))
                return merged
        # Also handle Gemini's nested string arrays: [[["user text", "model text", ...], ...]]
        # These are arrays of strings where even indices are user, odd are model
        all_strings_in_list = all(isinstance(item, str) for item in data)
        if all_strings_in_list and len(data) >= 2:
            messages = []
            for i, text in enumerate(data):
                if len(text) > 10 and not _is_gemini_suggestion(text):
                    role = "user" if i % 2 == 0 else "assistant"
                    messages.append((role, _unescape_content(text)))
            if messages:
                return messages
    if isinstance(data, dict):
        for v in data.values():
            result = _find_gemini_messages(v, depth + 1)
            if result:
                return result
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, (dict, list)):
                result = _find_gemini_messages(item, depth + 1)
                if result:
                    return result
    return None


def _is_gemini_suggestion(text: str) -> bool:
    """Check if text looks like a Gemini template/suggestion prompt, not actual conversation.

    Gemini share pages embed example/suggested prompts in the UI template.
    These are generic one-liners that start with action verbs like 'can', 'write', 'create', etc.
    """
    if not text or len(text) < 10:
        return False
    text_stripped = text.strip()
    # Gemini suggestions are typically short, single-sentence prompts
    suggestion_starters = [
        'can ', 'could ', 'write ', 'create ', 'make ', 'help ', 'list ',
        'give ', 'tell ', 'explain ', 'show ', 'find ', 'what ', 'how ',
        'brainstorm ', 'design ', 'suggest ', 'recommend ',
    ]
    text_lower = text_stripped.lower()
    # Suggestions are typically 1-2 sentences, < 300 chars, and start with a verb
    if len(text_stripped) < 300:
        for starter in suggestion_starters:
            if text_lower.startswith(starter):
                # Exclude genuine technical conversations — they're usually longer
                # and contain code, URLs, or multi-line content
                if '\n' not in text_stripped and 'http' not in text_lower:
                    return True
    return False


def _extract_generic(html: str) -> Optional[dict]:
    result = _extract_from_visible_html(html, "generic")
    return result


def _extract_from_visible_html(html: str, platform: str) -> Optional[dict]:
    known_prefixes = {
        "chatgpt": [(r"You(?:\s*said)?[：:]\s*(.+)", "user"), (r"ChatGPT[：:]\s*(.+)", "assistant")],
        "claude": [(r"Human[：:]\s*(.+)", "user"), (r"(?:Assistant|Claude)[：:]\s*(.+)", "assistant")],
        "deepseek": [(r"User[：:]\s*(.+)", "user"), (r"(?:DeepSeek|Assistant|DS)[：:]\s*(.+)", "assistant")],
        "gemini": [(r"User[：:]\s*(.+)", "user"), (r"(?:Gemini|Assistant|Model)[：:]\s*(.+)", "assistant")],
        "generic": [
            (r"(?:You|User|Human|用户)[：:]\s*(.+)", "user"),
            (r"(?:ChatGPT|Assistant|Claude|Bot|AI|助手|AI助手)[：:]\s*(.+)", "assistant"),
        ],
    }

    prefixes = known_prefixes.get(platform, known_prefixes["generic"])
    messages = []

    for prefix_re, role in prefixes:
        for m in re.finditer(prefix_re, html, re.IGNORECASE):
            content = m.group(1).strip()
            # Remove HTML tags
            content = re.sub(r'<[^>]+>', '', content)
            content = content.strip()
            if content and len(content) > 1:
                messages.append((role, content))

    if messages:
        messages.sort()
        raw_text = _format_messages(messages)
        return {"title": "", "raw_text": raw_text}

    return None


def _debug_json_structure(obj, depth=0, prefix=""):
    """Print the structure of a JSON object for debugging."""
    indent = "  " * depth
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                summary = f"{type(v).__name__}(len={len(v)})"
                print(f"[link_importer] {indent}{prefix}{k}: {summary}")
                if depth < 3:
                    _debug_json_structure(v, depth + 1, f"{k}.")
            else:
                val_str = str(v)[:100]
                print(f"[link_importer] {indent}{prefix}{k}: {val_str}")
    elif isinstance(obj, list) and len(obj) > 0:
        print(f"[link_importer] {indent}{prefix}[0]: {type(obj[0]).__name__}")
        if isinstance(obj[0], dict):
            _debug_json_structure(obj[0], depth + 1, f"[0].")


def _format_messages(messages: list, platform: str = "generic") -> str:
    lines = []
    role_labels = {
        "user": {"chatgpt": "You", "claude": "Human", "deepseek": "User", "gemini": "User", "generic": "用户"},
        "assistant": {"chatgpt": "ChatGPT", "claude": "Assistant", "deepseek": "DeepSeek", "gemini": "Gemini", "generic": "AI"},
    }
    for role, content in messages:
        label = role_labels.get(role, {}).get(platform, role_labels.get(role, {}).get("generic", role))
        lines.append(f"{label}: {content}")
    return "\n\n".join(lines)
