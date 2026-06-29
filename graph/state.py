# -*- coding: utf-8 -*-
"""
AgentState: trạng thái dùng xuyên suốt LangGraph.
Mỗi node đọc và ghi vào state này.
"""
from typing import Optional
from typing_extensions import TypedDict


class AgentState(TypedDict):
    # Input
    question: str

    # Node 1 — Context Retrieval
    retrieved_context: str          # formatted string đưa vào prompt
    retrieved_terms: list[dict]     # raw list để log Langfuse

    # Node 2 — SQL Generator
    sql_query: str

    # Node 3 — SQL Executor
    sql_result: Optional[str]       # DataFrame.to_string() nếu thành công
    sql_columns: Optional[list]     # tên cột để render bảng trên UI
    error_message: Optional[str]    # message lỗi nếu thất bại

    # Node 0 — Question Validator
    validation_error: Optional[str] # None nếu câu hỏi hợp lệ, string lỗi nếu không

    # Self-Correction loop
    retry_count: int                # số lần đã retry (tối đa MAX_RETRY)

    # Node 5 — Insight Generator
    final_answer: str

    # Langfuse tracing (optional — None nếu không config)
    trace_id: Optional[str]
