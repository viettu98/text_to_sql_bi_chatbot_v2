# -*- coding: utf-8 -*-
"""
Compile và run LangGraph Data Analyst Agent.

Graph flow:
  START
    → context_retrieval          (quét glossary — nguồn sự thật nghiệp vụ)
    → question_validator         (dùng glossary context để kiểm tra câu hỏi)
    ↓ (conditional)
    ├─ [out_of_scope]  → out_of_scope → END
    └─ [ok]            → sql_generator
                         → sql_executor
                         ↓ (conditional)
                         ├─ [success]       → insight_generator → END
                         ├─ [error+retry]   → self_corrector → sql_generator (loop)
                         └─ [error+noretry] → error_response → END
"""
import os
import logging
import uuid
from pathlib import Path
from dotenv import load_dotenv

from langgraph.graph import StateGraph, START, END

# Load .env trước khi đọc bất kỳ env var nào
load_dotenv(Path(__file__).parent.parent / ".env")

from graph.state import AgentState
from graph.nodes import (
    question_validator,
    context_retrieval,
    sql_generator,
    sql_executor,
    self_corrector,
    insight_generator,
    error_response,
)
from graph.edges import route_after_executor


def _route_after_validator(state: AgentState) -> str:
    if state.get("validation_error"):
        return "out_of_scope"
    return "sql_generator"


def _out_of_scope(state: AgentState) -> AgentState:
    return {**state, "final_answer": state["validation_error"]}

log = logging.getLogger(__name__)

# ── Langfuse (optional) — v4 API ──────────────────────────────────────────
_LANGFUSE_ENABLED = bool(os.getenv("LANGFUSE_SECRET_KEY"))
_lf_client = None
if _LANGFUSE_ENABLED:
    try:
        from langfuse import Langfuse
        _lf_client = Langfuse(
            secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
            host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
        )
        log.info("[Langfuse] Connected to %s", os.getenv("LANGFUSE_HOST"))
    except Exception as e:
        log.warning("[Langfuse] Init failed: %s", e)
        _lf_client = None


def _build_graph() -> StateGraph:
    g = StateGraph(AgentState)

    g.add_node("question_validator", question_validator)
    g.add_node("out_of_scope",       _out_of_scope)
    g.add_node("context_retrieval",  context_retrieval)
    g.add_node("sql_generator",      sql_generator)
    g.add_node("sql_executor",       sql_executor)
    g.add_node("self_corrector",     self_corrector)
    g.add_node("insight_generator",  insight_generator)
    g.add_node("error_response",     error_response)

    g.add_edge(START,                "context_retrieval")
    g.add_edge("context_retrieval",  "question_validator")
    g.add_conditional_edges(
        "question_validator",
        _route_after_validator,
        {"out_of_scope": "out_of_scope", "sql_generator": "sql_generator"},
    )
    g.add_edge("out_of_scope",       END)
    g.add_edge("sql_generator",      "sql_executor")

    g.add_conditional_edges(
        "sql_executor",
        route_after_executor,
        {
            "insight_generator": "insight_generator",
            "self_corrector":    "self_corrector",
            "error_response":    "error_response",
        },
    )

    g.add_edge("self_corrector",    "sql_generator")
    g.add_edge("insight_generator", END)
    g.add_edge("error_response",    END)

    return g.compile()


# Singleton — compile 1 lần khi import
_graph = _build_graph()


def run_agent(question: str) -> AgentState:
    """
    Entry point chính. Nhận câu hỏi, trả về AgentState đầy đủ.
    """
    initial_state: AgentState = {
        "question":          question,
        "validation_error":  None,
        "retrieved_context": "",
        "retrieved_terms":   [],
        "sql_query":         "",
        "sql_result":        None,
        "sql_columns":       None,
        "error_message":     None,
        "retry_count":       0,
        "final_answer":      "",
        "trace_id":          None,
    }

    trace_id = None

    if _lf_client:
        try:
            from langfuse.langchain import CallbackHandler
            handler = CallbackHandler()

            with _lf_client.start_as_current_observation(
                as_type="span",
                name="data-analyst-agent",
                input={"question": question},
            ) as obs:
                trace_id = _lf_client.get_current_trace_id()
                final_state = _graph.invoke(
                    initial_state,
                    config={"callbacks": [handler]},
                )
                obs.update(output={"answer": final_state.get("final_answer", "")[:300]})

            _lf_client.flush()
            log.info("[Langfuse] trace_id=%s", trace_id)
        except Exception as e:
            log.warning("[Langfuse] Tracing failed: %s", e)
            # Fallback: chạy graph không có tracing
            final_state = _graph.invoke(initial_state)
    else:
        final_state = _graph.invoke(initial_state)

    return {**final_state, "trace_id": trace_id}
