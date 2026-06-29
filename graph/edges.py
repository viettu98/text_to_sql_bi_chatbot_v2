# -*- coding: utf-8 -*-
"""
Conditional routing logic cho LangGraph.
Quyết định node tiếp theo sau sql_executor.
"""
from graph.state import AgentState

MAX_RETRY = 2


def route_after_executor(state: AgentState) -> str:
    """
    Sau sql_executor:
    - Không lỗi          → "insight_generator"
    - Lỗi + còn retry   → "self_corrector"
    - Lỗi + hết retry   → "error_response"
    """
    has_error   = bool(state.get("error_message"))
    retry_count = state.get("retry_count", 0)

    if not has_error:
        return "insight_generator"
    if retry_count < MAX_RETRY:
        return "self_corrector"
    return "error_response"
