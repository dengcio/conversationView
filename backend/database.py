import sqlite3
import json
from typing import List, Optional, Tuple


DB_PATH = "conversations.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            title         TEXT DEFAULT '未命名对话',
            source        TEXT DEFAULT 'generic',
            message_count INTEGER DEFAULT 0,
            is_analyzed   INTEGER DEFAULT 0,
            created_at    TEXT DEFAULT (datetime('now','localtime')),
            updated_at    TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            seq_order       INTEGER NOT NULL,
            role            TEXT NOT NULL,
            content         TEXT NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, seq_order)
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS analysis_chunks (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            chunk_index     INTEGER NOT NULL,
            title           TEXT,
            summary         TEXT,
            start_msg_id    INTEGER,
            end_msg_id      INTEGER,
            keywords        TEXT DEFAULT '[]',
            value_score     INTEGER DEFAULT 0,
            tags            TEXT DEFAULT '[]',
            created_at      TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_chunks_conv ON analysis_chunks(conversation_id)
    """)
    conn.commit()
    conn.close()


# ---- Conversations CRUD ----

def create_conversation(title: str, source: str) -> int:
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO conversations (title, source) VALUES (?, ?)",
        (title, source)
    )
    conn.commit()
    conv_id = cursor.lastrowid
    conn.close()
    return conv_id


def get_all_conversations() -> List[dict]:
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM conversations ORDER BY updated_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_conversation(conv_id: int) -> Optional[dict]:
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM conversations WHERE id = ?", (conv_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def update_conversation(conv_id: int, title: str = None, is_analyzed: bool = None) -> None:
    conn = get_conn()
    cursor = conn.cursor()
    if title is not None:
        cursor.execute(
            "UPDATE conversations SET title = ?, updated_at = datetime('now','localtime') WHERE id = ?",
            (title, conv_id)
        )
    if is_analyzed is not None:
        cursor.execute(
            "UPDATE conversations SET is_analyzed = ?, updated_at = datetime('now','localtime') WHERE id = ?",
            (1 if is_analyzed else 0, conv_id)
        )
    conn.commit()
    conn.close()


def delete_conversation(conv_id: int) -> None:
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
    conn.commit()
    conn.close()


# ---- Messages CRUD ----

def insert_messages(conv_id: int, messages: List[Tuple[int, str, str]]) -> None:
    conn = get_conn()
    cursor = conn.cursor()
    cursor.executemany(
        "INSERT INTO messages (conversation_id, seq_order, role, content) VALUES (?, ?, ?, ?)",
        [(conv_id, seq, role, content) for seq, role, content in messages]
    )
    cursor.execute(
        "UPDATE conversations SET message_count = (SELECT COUNT(*) FROM messages WHERE conversation_id = ?), updated_at = datetime('now','localtime') WHERE id = ?",
        (conv_id, conv_id)
    )
    conn.commit()
    conn.close()


def get_messages(conv_id: int) -> List[dict]:
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM messages WHERE conversation_id = ? ORDER BY seq_order ASC",
        (conv_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_message_count(conv_id: int) -> int:
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM messages WHERE conversation_id = ?", (conv_id,))
    count = cursor.fetchone()[0]
    conn.close()
    return count


# ---- Analysis Chunks CRUD ----

def save_analysis_chunks(conv_id: int, chunks: List[dict]) -> None:
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM analysis_chunks WHERE conversation_id = ?", (conv_id,))
    for c in chunks:
        cursor.execute(
            """INSERT INTO analysis_chunks
               (conversation_id, chunk_index, title, summary, start_msg_id, end_msg_id, keywords, value_score, tags)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                conv_id,
                c["chunk_index"],
                c.get("title"),
                c.get("summary"),
                c.get("start_msg_id"),
                c.get("end_msg_id"),
                json.dumps(c.get("keywords", []), ensure_ascii=False),
                c.get("value_score", 0),
                json.dumps(c.get("tags", []), ensure_ascii=False),
            )
        )
    conn.commit()
    conn.close()


def get_analysis_chunks(conv_id: int) -> List[dict]:
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM analysis_chunks WHERE conversation_id = ? ORDER BY chunk_index ASC",
        (conv_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    results = []
    for row in rows:
        d = dict(row)
        d["keywords"] = json.loads(d.get("keywords", "[]"))
        d["tags"] = json.loads(d.get("tags", "[]"))
        results.append(d)
    return results


# ---- Combined query ----

def get_conversation_full(conv_id: int) -> Optional[dict]:
    conv = get_conversation(conv_id)
    if conv is None:
        return None
    conv["messages"] = get_messages(conv_id)
    conv["analysis"] = get_analysis_chunks(conv_id)
    conv["is_analyzed"] = bool(conv.get("is_analyzed"))
    return conv
