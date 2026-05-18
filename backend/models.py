from pydantic import BaseModel, Field
from typing import List, Optional


# ---------- Request models ----------

class ImportRequest(BaseModel):
    raw_text: str
    source: str = "generic"  # chatgpt | claude | deepseek | generic
    title: Optional[str] = None


class LinkImportRequest(BaseModel):
    url: str
    title: Optional[str] = None


class AnalyzeRequest(BaseModel):
    chunk_mode: str = "auto"  # auto | manual


# ---------- Response models ----------

class MessageResponse(BaseModel):
    id: int
    seq_order: int
    role: str
    content: str


class AnalysisChunkResponse(BaseModel):
    id: int
    chunk_index: int
    title: Optional[str]
    summary: Optional[str]
    start_msg_id: Optional[int]
    end_msg_id: Optional[int]
    keywords: List[str] = []
    value_score: int
    tags: List[str] = []
    created_at: str


class ConversationListItem(BaseModel):
    id: int
    title: str
    source: str
    message_count: int
    is_analyzed: bool
    created_at: str


class ConversationDetail(BaseModel):
    id: int
    title: str
    source: str
    message_count: int
    is_analyzed: bool
    created_at: str
    messages: List[MessageResponse] = []
    analysis: Optional[List[AnalysisChunkResponse]] = []


class ImportResponse(BaseModel):
    conversation_id: int
    title: str
    message_count: int
    parsed_preview: List[MessageResponse]
