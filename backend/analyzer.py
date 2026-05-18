import os
import json
import re
import httpx
from typing import List, Dict

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
if not DEEPSEEK_API_KEY:
    raise RuntimeError("未配置 DEEPSEEK_API_KEY 环境变量，请在 .env 文件中设置")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek-v4-flash"

SYSTEM_PROMPT = """你是一个专业的AI对话内容整理助手。你的任务是对用户提供的AI对话记录进行分析，识别其中的主题分块，并为每个分块生成简洁准确的总结。

## 分析步骤
1. 快速浏览全部对话，理解整体脉络
2. 按主题变化将对话切分为3-8个逻辑块
3. 为每个块生成标题、总结、关键词、评分和标签

## 分块原则
- 每个块应覆盖一段连贯的主题讨论（通常4-10轮对话）
- 主题切换处切分（如：从需求讨论切换到技术选型）
- 块与块之间可以有轻微重叠
- 如果对话很短（少于6轮），可以只分1-2块

## value_score 评分标准
- 5: 包含重要决策、核心方案、深度见解或可复用的代码/方法论
- 4: 有实质性的讨论内容，包含具体建议或分析
- 3: 一般性的知识问答或信息交流
- 2: 简单澄清、确认或寒暄
- 1: 纯闲聊或无效对话
- 注意：大多数有价值的对话块应该在3-5分之间

## 输出格式
你必须只输出一个 JSON 对象，不要有任何其他文字。JSON 格式如下：
{
  "overall_title": "整个对话的标题（15字以内，提取最核心的主题）",
  "chunks": [
    {
      "title": "分块标题（10字以内）",
      "summary": "分块总结（40-80字，提取核心信息和结论，让读者一眼看出内容价值）",
      "keywords": ["关键词1", "关键词2", "关键词3"],
      "value_score": 4,
      "tags": ["分类标签1", "分类标签2"]
    }
  ]
}

## 标签参考分类
- 需求分析、技术选型、架构设计、代码实现、调试修复
- 学习笔记、知识问答、方案对比、项目管理、创意构思
- 问题排查、最佳实践、工具推荐、配置部署"""


async def analyze_conversation(messages: List[dict]) -> dict:
    user_prompt = _build_user_prompt(messages)

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            DEEPSEEK_API_URL,
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": DEEPSEEK_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.3,
            },
        )

    if response.status_code == 401:
        raise RuntimeError("DeepSeek API Key 无效，请检查 DEEPSEEK_API_KEY 环境变量。")
    if response.status_code != 200:
        raise RuntimeError(f"DeepSeek API 返回错误 (HTTP {response.status_code}): {response.text[:200]}")

    data = response.json()
    content = data["choices"][0]["message"]["content"]
    parsed = _parse_analysis_response(content)
    return parsed


def _build_user_prompt(messages: List[dict]) -> str:
    lines = ["以下是一段AI对话记录，请按主题进行分块分析：", "", "---"]
    role_labels = {"user": "用户", "assistant": "助手", "system": "系统"}
    for msg in messages:
        label = role_labels.get(msg.get("role", "user"), msg.get("role", "user"))
        lines.append(f"[{label}] {msg['content']}")
    lines.extend(["", "---", "", "请按照要求的 JSON 格式输出分析结果。"])
    return "\n".join(lines)


def _parse_analysis_response(response_text: str) -> dict:
    # Strategy 1: Direct JSON parse
    try:
        return json.loads(response_text)
    except (json.JSONDecodeError, ValueError):
        pass

    # Strategy 2: Extract JSON from code blocks
    code_match = re.search(r'```(?:json)?\s*\n([\s\S]*?)\n```', response_text)
    if code_match:
        try:
            return json.loads(code_match.group(1))
        except (json.JSONDecodeError, ValueError):
            pass

    # Strategy 3: Extract first { to last }
    brace_match = re.search(r'\{[\s\S]*\}', response_text)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except (json.JSONDecodeError, ValueError):
            pass

    # Strategy 4: All failed
    raise ValueError(f"无法解析 DeepSeek 响应为 JSON。原始响应: {response_text[:200]}...")
