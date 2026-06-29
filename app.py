# -*- coding: utf-8 -*-
"""
Streamlit UI — LangGraph Data Analyst Agent
Hiển thị từng bước: Context Retrieval → SQL → Executor → (Retry) → Insight
"""
import sys
import os
import pandas as pd
import streamlit as st
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from graph.agent import run_agent

# ── Page config ────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="BI Chatbot — LangGraph Agent",
    page_icon="📊",
    layout="wide",
)

st.title("📊 Data Analyst Agent")
st.caption("LangGraph · Business Glossary · Self-Correction")

# ── Chat history ───────────────────────────────────────────────────────────
if "history" not in st.session_state:
    st.session_state.history = []

for msg in st.session_state.history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ── Input ──────────────────────────────────────────────────────────────────
question = st.chat_input("Hỏi dữ liệu kinh doanh... (VD: Doanh thu thuần tháng này theo ngành hàng?)")

if question:
    with st.chat_message("user"):
        st.markdown(question)
    st.session_state.history.append({"role": "user", "content": question})

    with st.chat_message("assistant"):
        with st.spinner("Đang xử lý..."):
            result = run_agent(question)

        # ── Hiển thị kết quả theo tabs ─────────────────────────────────
        tab_insight, tab_sql, tab_context, tab_debug = st.tabs([
            "💡 Insight", "🗄️ SQL & Data", "📚 Glossary Context", "🔧 Debug"
        ])

        with tab_insight:
            final = result.get("final_answer", "")
            if final:
                st.markdown(final)
            else:
                st.warning("Không có insight.")

        with tab_sql:
            sql = result.get("sql_query", "")
            if sql:
                st.subheader("SQL Query")
                st.code(sql, language="sql")

            sql_result = result.get("sql_result")
            if sql_result:
                st.subheader("Kết quả")
                try:
                    from io import StringIO
                    df = pd.read_csv(StringIO(sql_result), sep=r"\s{2,}", engine="python")
                    st.dataframe(df, use_container_width=True)
                except Exception:
                    st.text(sql_result)
            elif result.get("error_message"):
                st.error(f"Lỗi SQL: {result['error_message']}")

        with tab_context:
            terms = result.get("retrieved_terms", [])
            if terms:
                st.subheader(f"Đã retrieve {len(terms)} thuật ngữ nghiệp vụ")
                for t in terms:
                    with st.expander(f"[{t['id']}] {t['term']}  —  similarity: {t['similarity_score']}"):
                        if t.get("sql_formula"):
                            st.code(t["sql_formula"], language="sql")
                        elif t.get("sql_filter"):
                            st.code(t["sql_filter"], language="sql")
                        if t.get("sql_note"):
                            st.caption(t["sql_note"])
            else:
                st.info("Không retrieve được thuật ngữ nào.")

        with tab_debug:
            retry = result.get("retry_count", 0)
            err   = result.get("error_message")
            tid   = result.get("trace_id")

            col1, col2, col3 = st.columns(3)
            col1.metric("Số lần retry", retry,
                        delta="lần" if retry > 0 else None,
                        delta_color="inverse" if retry > 0 else "off")
            col2.metric("Glossary hits", len(result.get("retrieved_terms", [])))
            col3.metric("Langfuse trace", "✅" if tid else "❌")

            if retry > 0:
                st.warning(f"⚠️ Agent đã tự sửa lỗi {retry} lần.")
            if err:
                st.error(f"Lỗi cuối cùng: {err}")
            if tid:
                langfuse_host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com").rstrip("/")
                st.link_button("🔍 Xem trace trên Langfuse", f"{langfuse_host}/trace/{tid}")
                st.caption(f"Trace ID: `{tid}`")

        st.session_state.history.append({
            "role": "assistant",
            "content": result.get("final_answer", "Không có kết quả."),
        })

# ── Sidebar ────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Cấu hình")
    st.caption(f"LLM: `{os.getenv('LLM_MODEL', 'MWG')}`")
    st.caption(f"DB: `database/sales.db`")
    st.caption(f"Vector DB: `chroma_db/`")
    langfuse_on = bool(os.getenv("LANGFUSE_SECRET_KEY"))
    st.caption(f"Langfuse: {'✅ ON' if langfuse_on else '❌ OFF (set key in .env)'}")

    st.divider()
    st.subheader("💬 Câu hỏi mẫu")
    samples = [
        "Doanh thu thuần tháng này theo ngành hàng?",
        "Khách VIP mua sản phẩm thuộc ngành nào nhiều nhất?",
        "Hiệu quả khuyến mãi: đơn có KM vs không có KM?",
        "Top 5 chương trình khuyến mãi có doanh thu cao nhất?",
        "So sánh AOV kênh online và offline theo tháng?",
    ]
    for s in samples:
        st.markdown(f"- _{s}_")

    st.divider()
    if st.button("🗑️ Xóa lịch sử"):
        st.session_state.history = []
        st.rerun()

# lệnh chạy: streamlit run app.py
