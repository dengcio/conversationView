"""
AI Conversation Import & Analysis Tool - Backend API v2.0
FastAPI application for importing AI conversations and DeepSeek-powered analysis.
"""

from dotenv import load_dotenv
load_dotenv()

from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uvicorn

from database import (
    init_db,
    create_conversation,
    get_all_conversations,
    get_conversation,
    get_conversation_full,
    update_conversation,
    delete_conversation,
    insert_messages,
    get_messages,
    get_analysis_chunks,
    save_analysis_chunks,
)
from conv_parser import parse_conversation
from link_importer import import_from_link
from analyzer import analyze_conversation
from models import (
    ImportRequest,
    ImportResponse,
    LinkImportRequest,
    AnalyzeRequest,
    ConversationListItem,
    ConversationDetail,
    MessageResponse,
    AnalysisChunkResponse,
)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield

app = FastAPI(title="AI对话导入与分析工具", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================
# Phase 1: Import + View
# ============================================

@app.post("/api/import", response_model=ImportResponse)
async def import_conversation(request: ImportRequest):
    parsed = parse_conversation(request.raw_text, request.source)
    if not parsed:
        raise HTTPException(
            status_code=422,
            detail="无法识别对话格式。请确认来源选择正确，或尝试手动添加角色标注。"
        )

    title = request.title or "未命名对话"
    conv_id = create_conversation(title, request.source)
    insert_messages(conv_id, parsed)

    messages = get_messages(conv_id)
    preview = messages[:5]
    conv = get_conversation(conv_id)

    return ImportResponse(
        conversation_id=conv_id,
        title=conv["title"],
        message_count=conv["message_count"],
        parsed_preview=[
            MessageResponse(id=m["id"], seq_order=m["seq_order"], role=m["role"], content=m["content"])
            for m in preview
        ]
    )


@app.post("/api/import-from-link", response_model=ImportResponse)
async def import_from_link_endpoint(request: LinkImportRequest):
    try:
        result = await import_from_link(request.url)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取链接内容失败: {str(e)}")

    parsed = parse_conversation(result["raw_text"], result["source"])
    if not parsed:
        raise HTTPException(
            status_code=422,
            detail="成功获取链接内容但无法识别对话格式。已保存原始文本，请尝试手动导入。"
        )

    title = request.title or result.get("title") or "未命名对话"
    conv_id = create_conversation(title, result["source"])
    insert_messages(conv_id, parsed)

    messages = get_messages(conv_id)
    preview = messages[:5]
    conv = get_conversation(conv_id)

    return ImportResponse(
        conversation_id=conv_id,
        title=conv["title"],
        message_count=conv["message_count"],
        parsed_preview=[
            MessageResponse(id=m["id"], seq_order=m["seq_order"], role=m["role"], content=m["content"])
            for m in preview
        ]
    )


@app.get("/api/conversations", response_model=list[ConversationListItem])
async def list_conversations():
    convs = get_all_conversations()
    return [
        ConversationListItem(
            id=c["id"],
            title=c["title"],
            source=c["source"],
            message_count=c["message_count"],
            is_analyzed=bool(c["is_analyzed"]),
            created_at=c["created_at"],
        )
        for c in convs
    ]


@app.get("/api/conversations/{conv_id}", response_model=ConversationDetail)
async def get_conversation_detail(conv_id: int):
    conv = get_conversation_full(conv_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="对话不存在")

    return ConversationDetail(
        id=conv["id"],
        title=conv["title"],
        source=conv["source"],
        message_count=conv["message_count"],
        is_analyzed=conv["is_analyzed"],
        created_at=conv["created_at"],
        messages=[
            MessageResponse(id=m["id"], seq_order=m["seq_order"], role=m["role"], content=m["content"])
            for m in conv.get("messages", [])
        ],
        analysis=[
            AnalysisChunkResponse(
                id=a["id"],
                chunk_index=a["chunk_index"],
                title=a.get("title"),
                summary=a.get("summary"),
                start_msg_id=a.get("start_msg_id"),
                end_msg_id=a.get("end_msg_id"),
                keywords=a.get("keywords", []),
                value_score=a.get("value_score", 0),
                tags=a.get("tags", []),
                created_at=a["created_at"],
            )
            for a in conv.get("analysis", [])
        ] if conv.get("analysis") else None,
    )


@app.delete("/api/conversations/{conv_id}")
async def delete_conversation_endpoint(conv_id: int):
    conv = get_conversation(conv_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="对话不存在")
    delete_conversation(conv_id)
    return {"message": "对话已删除", "conversation_id": conv_id}


# ============================================
# Phase 2: AI Analysis
# ============================================

@app.post("/api/conversations/{conv_id}/analyze")
async def analyze_conversation_endpoint(conv_id: int, request: AnalyzeRequest = None):
    conv = get_conversation(conv_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="对话不存在")

    messages = get_messages(conv_id)
    if not messages:
        raise HTTPException(status_code=400, detail="对话没有消息，无法分析")

    try:
        analysis_result = await analyze_conversation(messages)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"分析失败: {str(e)}")

    chunks = analysis_result.get("chunks", [])
    overall_title = analysis_result.get("overall_title")

    chunk_records = []
    for c in chunks:
        chunk_records.append({
            "chunk_index": len(chunk_records) + 1,
            "title": c.get("title", ""),
            "summary": c.get("summary", ""),
            "start_msg_id": None,
            "end_msg_id": None,
            "keywords": c.get("keywords", []),
            "value_score": c.get("value_score", 3),
            "tags": c.get("tags", []),
        })

    save_analysis_chunks(conv_id, chunk_records)
    update_conversation(conv_id, is_analyzed=True)

    if overall_title and conv["title"] == "未命名对话":
        update_conversation(conv_id, title=overall_title)

    return {
        "conversation_id": conv_id,
        "chunks": [
            {
                "chunk_index": c["chunk_index"],
                "title": c["title"],
                "summary": c["summary"],
                "keywords": c["keywords"],
                "value_score": c["value_score"],
                "tags": c["tags"],
                "message_range": {"start": c.get("start_msg_id"), "end": c.get("end_msg_id")},
            }
            for c in chunk_records
        ]
    }


@app.get("/api/conversations/{conv_id}/analysis")
async def get_analysis(conv_id: int):
    conv = get_conversation(conv_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="对话不存在")

    chunks = get_analysis_chunks(conv_id)
    return {
        "conversation_id": conv_id,
        "chunks": chunks,
    }


# Mount frontend at root — must be AFTER all API routes
frontend_dir = str(Path(__file__).resolve().parent.parent / "frontend")
app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
