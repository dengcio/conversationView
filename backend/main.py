"""
OpenClaw Conversation Viewer - Backend API
FastAPI application that interfaces with OpenClaw Gateway API
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import httpx
import sqlite3
import json
from datetime import datetime

app = FastAPI(title="Conversation Viewer API", version="1.0.0")

# CORS configuration for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# OpenClaw Gateway configuration
OPENCLAW_GATEWAY_URL = "http://127.0.0.1:28789"
OPENCLAW_GATEWAY_TOKEN = "qclaw_3c7790d3218d9501a8bdba76e44f6f1a021b57f4153c9dcf0dd26ca05580417"

# SQLite database setup
DB_PATH = "conversations.db"


def init_db():
    """Initialize SQLite database for storing user annotations"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_key TEXT NOT NULL,
            message_id TEXT,
            content TEXT NOT NULL,
            role TEXT NOT NULL,
            timestamp TEXT,
            tags TEXT,  -- JSON array
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bookmarks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_key TEXT NOT NULL,
            message_id TEXT,
            title TEXT,
            note TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


init_db()


# Pydantic models
class SessionResponse(BaseModel):
    sessionKey: str
    kind: Optional[str]
    lastActivity: Optional[str]
    messageCount: Optional[int]


class ConversationChunk(BaseModel):
    id: Optional[int] = None
    session_key: str
    message_id: Optional[str] = None
    content: str
    role: str
    timestamp: Optional[str] = None
    tags: List[str] = []
    notes: Optional[str] = None


class Bookmark(BaseModel):
    id: Optional[int] = None
    session_key: str
    message_id: Optional[str] = None
    title: str
    note: Optional[str] = None


@app.get("/")
async def root():
    return {"message": "Conversation Viewer API is running"}


@app.get("/api/sessions", response_model=List[SessionResponse])
async def list_sessions(
    kinds: Optional[List[str]] = None,
    active_minutes: Optional[int] = None,
    limit: int = 50,
    message_limit: int = 10
):
    """
    List all conversation sessions from OpenClaw
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{OPENCLAW_GATEWAY_URL}/api/tools/call",
                headers={
                    "Authorization": f"Bearer {OPENCLAW_GATEWAY_TOKEN}",
                    "Content-Type": "application/json"
                },
                json={
                    "tool": "sessions_list",
                    "parameters": {
                        "kinds": kinds,
                        "activeMinutes": active_minutes,
                        "limit": limit,
                        "messageLimit": message_limit
                    }
                },
                timeout=30.0
            )

            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail=response.text)

            result = response.json()
            return result.get("result", [])

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/sessions/{session_key}/history")
async def get_session_history(session_key: str, limit: int = 100, include_tools: bool = False):
    """
    Get conversation history for a specific session
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{OPENCLAW_GATEWAY_URL}/api/tools/call",
                headers={
                    "Authorization": f"Bearer {OPENCLAW_GATEWAY_TOKEN}",
                    "Content-Type": "application/json"
                },
                json={
                    "tool": "sessions_history",
                    "parameters": {
                        "sessionKey": session_key,
                        "limit": limit,
                        "includeTools": include_tools
                    }
                },
                timeout=30.0
            )

            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail=response.text)

            result = response.json()
            return result.get("result", {})

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/search")
async def search_conversations(query: str, limit: int = 20):
    """
    Search across conversation history using memory_search
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{OPENCLAW_GATEWAY_URL}/api/tools/call",
                headers={
                    "Authorization": f"Bearer {OPENCLAW_GATEWAY_TOKEN}",
                    "Content-Type": "application/json"
                },
                json={
                    "tool": "memory_search",
                    "parameters": {
                        "query": query,
                        "maxResults": limit,
                        "corpus": "memory"
                    }
                },
                timeout=30.0
            )

            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail=response.text)

            result = response.json()
            return result.get("result", {})

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Chunk management endpoints
@app.post("/api/chunks")
async def create_chunk(chunk: ConversationChunk):
    """
    Save a conversation chunk with tags and notes
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO chunks (session_key, message_id, content, role, timestamp, tags, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        chunk.session_key,
        chunk.message_id,
        chunk.content,
        chunk.role,
        chunk.timestamp,
        json.dumps(chunk.tags),
        chunk.notes
    ))
    conn.commit()
    chunk_id = cursor.lastrowid
    conn.close()
    return {"message": "Chunk saved", "chunk_id": chunk_id}


@app.get("/api/chunks")
async def get_chunks(session_key: Optional[str] = None, tag: Optional[str] = None):
    """
    Get all saved chunks, optionally filtered by session or tag
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    if session_key:
        cursor.execute("SELECT * FROM chunks WHERE session_key = ? ORDER BY created_at DESC", (session_key,))
    else:
        cursor.execute("SELECT * FROM chunks ORDER BY created_at DESC")

    rows = cursor.fetchall()
    conn.close()

    chunks = []
    for row in rows:
        tags = json.loads(row[6]) if row[6] else []
        if tag and tag not in tags:
            continue
        chunks.append({
            "id": row[0],
            "session_key": row[1],
            "message_id": row[2],
            "content": row[3],
            "role": row[4],
            "timestamp": row[5],
            "tags": tags,
            "notes": row[7],
            "created_at": row[8]
        })

    return chunks


@app.delete("/api/chunks/{chunk_id}")
async def delete_chunk(chunk_id: int):
    """
    Delete a chunk by ID
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM chunks WHERE id = ?", (chunk_id,))
    conn.commit()
    conn.close()
    return {"message": "Chunk deleted"}


# Bookmark management endpoints
@app.post("/api/bookmarks")
async def create_bookmark(bookmark: Bookmark):
    """
    Save a bookmark
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO bookmarks (session_key, message_id, title, note)
        VALUES (?, ?, ?, ?)
    """, (bookmark.session_key, bookmark.message_id, bookmark.title, bookmark.note))
    conn.commit()
    bookmark_id = cursor.lastrowid
    conn.close()
    return {"message": "Bookmark saved", "bookmark_id": bookmark_id}


@app.get("/api/bookmarks")
async def get_bookmarks(session_key: Optional[str] = None):
    """
    Get all bookmarks, optionally filtered by session
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    if session_key:
        cursor.execute("SELECT * FROM bookmarks WHERE session_key = ? ORDER BY created_at DESC", (session_key,))
    else:
        cursor.execute("SELECT * FROM bookmarks ORDER BY created_at DESC")

    rows = cursor.fetchall()
    conn.close()

    bookmarks = []
    for row in rows:
        bookmarks.append({
            "id": row[0],
            "session_key": row[1],
            "message_id": row[2],
            "title": row[3],
            "note": row[4],
            "created_at": row[5]
        })

    return bookmarks


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
