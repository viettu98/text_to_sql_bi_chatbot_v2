# -*- coding: utf-8 -*-
"""
5 Node functions cho LangGraph Data Analyst Agent.

Node 1: context_retrieval   — tìm định nghĩa nghiệp vụ từ Vector DB
Node 2: sql_generator       — generate SQL từ question + schema + context
Node 3: sql_executor        — chạy SQL trên SQLite
Node 4: self_corrector      — sửa SQL dựa trên error message
Node 5: insight_generator   — tóm tắt kết quả thành business insight
"""
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv

# ── Paths ──────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from graph.state import AgentState
from vector_store import retrieve, format_for_prompt

load_dotenv(ROOT / ".env")

# ── Config ─────────────────────────────────────────────────────────────────
DB_PATH = ROOT / "database" / "sales.db"
MAX_RETRY = 2

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "DEFAULT_LLM_BASE_URL")
LLM_MODEL    = os.getenv("LLM_MODEL", "DEFAULT_LLM_MODEL")
LLM_API_KEY  = os.getenv("LLM_API_KEY", "DEFAULT_LLM_API_KEY")

engine = create_engine(f"sqlite:///{DB_PATH}")

llm = ChatOpenAI(
    model=LLM_MODEL,
    base_url=LLM_BASE_URL,
    api_key=LLM_API_KEY,
    temperature=0,
)

# Langfuse được xử lý qua CallbackHandler trong agent.py — không cần code ở đây


# ── DB Schema (static, dùng trong prompt) ──────────────────────────────────
DB_SCHEMA = """
Tables trong SQLite database:

1. customers
   - customer_id    TEXT  (PK)
   - customer_name  TEXT
   - gender         TEXT  ('M' = Nam, 'F' = Nữ)
   - city           TEXT
   - segment        TEXT  ('VIP', 'NORMAL', 'NEW')

2. products
   - product_id    TEXT  (PK)
   - product_name  TEXT
   - category      TEXT  ('Gia_dung','Thuc_pham','Do_uong','Me_Be','Dien_tu','qua_tang')

3. promotions
   - promotionid        TEXT  (PK)
   - promotionname      TEXT
   - promotiontype      INT   (1=Discount Promo, 2=Gift Promo)
   - fromdate           TEXT  (YYYY-MM-DD)
   - todate             TEXT  (YYYY-MM-DD)
   - promotiongifttype  INT   (1=fixed amount off, 2=percentage off, 3=gift product)
   - discountvalue      INT   (số tiền VND nếu type=1, số % nếu type=2, 0 nếu type=3)
   - productid          TEXT  (FK → products.product_id)
   - categoryid         TEXT
   - quantity           INT   (số lượng tối thiểu để áp KM)
   - giftproductid      TEXT  (FK → products.product_id, chỉ có khi promotiongifttype=3)

4. sales_orders
   - sale_id        TEXT  (PK)
   - customer_id    TEXT  (FK → customers.customer_id)
   - product_id     TEXT  (FK → products.product_id)
   - quantity       INT
   - unit_price     INT
   - gross_revenue  INT   (= quantity × unit_price, trước chiết khấu)
   - total_discount INT   (tổng chiết khấu áp dụng)
   - net_revenue    INT   (= gross_revenue - total_discount, doanh thu thực)
   - is_gift        INT   (1 = sản phẩm quà tặng, không tính vào doanh thu)
   - promotionid    TEXT  (FK → promotions.promotionid, NULL nếu không có KM)
   - outputdate     TEXT  (YYYY-MM-DD)
   - outputtype     TEXT  ('online', 'offline')

QUAN TRỌNG:
- Khi tính doanh thu, LUÔN dùng net_revenue (không phải gross_revenue) và WHERE is_gift = 0
- Date format: YYYY-MM-DD (ISO), dùng strftime('%Y-%m', outputdate) để group theo tháng
- Dùng LEFT JOIN khi join với promotions (nhiều đơn không có KM)
"""


# ══════════════════════════════════════════════════════════════════════════
# NODE 2: Question Validator  (chạy SAU context_retrieval)
# ══════════════════════════════════════════════════════════════════════════
_VALIDATOR_PROMPT = """Bạn là người kiểm tra xem câu hỏi có thể trả lời từ dữ liệu hiện có không.

{schema}

--- Các khái niệm nghiệp vụ glossary tìm được liên quan đến câu hỏi ---
{retrieved_context}
--- Hết glossary context ---

Câu hỏi: "{question}"

Hãy kiểm tra: Câu hỏi có entity/khái niệm chính nào KHÔNG được khai báo trong schema hoặc glossary context trên không?

Ví dụ các trường hợp KHÔNG thể trả lời:
- Hỏi về "siêu thị", "cửa hàng", "chi nhánh" → schema không có bảng/cột nào về store/branch
- Hỏi về "lợi nhuận", "giá vốn", "chi phí" → schema không có cột cost/COGS
- Hỏi về "tồn kho", "nhập hàng" → không có bảng inventory
- Hỏi về "hoàn hàng", "đổi trả" → không có bảng returns
- Hỏi về thông tin cá nhân ngoài {{customer_name, gender, city, segment}}

Trả về JSON hợp lệ duy nhất, không giải thích thêm:
{{"answerable": true}} nếu có thể trả lời.
{{"answerable": false, "missing": ["khái niệm không có"], "reason": "lý do ngắn gọn tiếng Việt"}} nếu không thể.

JSON:"""


def question_validator(state: AgentState) -> AgentState:
    """
    Chạy SAU context_retrieval. Dùng cả schema + glossary đã retrieve để
    đánh giá câu hỏi có ánh xạ được vào dữ liệu không.
    Glossary là nguồn sự thật — thêm term mới vào glossary là validator tự hiểu.
    """
    import json
    question         = state["question"]
    retrieved_context = state.get("retrieved_context", "")

    # Nếu glossary không trả về gì → tăng ngưỡng cảnh báo
    context_note = retrieved_context if retrieved_context.strip() else "(Không tìm thấy khái niệm liên quan trong glossary)"

    prompt = _VALIDATOR_PROMPT.format(
        schema=DB_SCHEMA,
        retrieved_context=context_note,
        question=question,
    )
    response = llm.invoke(prompt)
    raw = response.content.strip()

    json_match = re.search(r'\{.*\}', raw, re.DOTALL)
    if not json_match:
        return {**state, "validation_error": None}  # fail-open: cho qua

    try:
        result = json.loads(json_match.group())
    except json.JSONDecodeError:
        return {**state, "validation_error": None}

    if not result.get("answerable", True):
        missing = ", ".join(result.get("missing", []))
        reason  = result.get("reason", "Câu hỏi chứa khái niệm không có trong dữ liệu.")
        error_msg = (
            f"Câu hỏi không thể trả lời từ dữ liệu hiện có.\n\n"
            f"**Khái niệm không tìm thấy:** {missing}\n\n"
            f"**Lý do:** {reason}\n\n"
            "Gợi ý: Hỏi về khách hàng, sản phẩm, đơn hàng, hoặc chương trình khuyến mãi."
        )
        return {**state, "validation_error": error_msg}

    return {**state, "validation_error": None}


# ══════════════════════════════════════════════════════════════════════════
# NODE 1: Context Retrieval
# ══════════════════════════════════════════════════════════════════════════
def context_retrieval(state: AgentState) -> AgentState:
    """
    Tìm kiếm các định nghĩa nghiệp vụ liên quan từ Vector DB (ChromaDB).
    Kết quả được format thành chuỗi context để đưa vào prompt SQL Generator.
    """
    question = state["question"]
    try:
        hits = retrieve(question, top_k=3)
        context_str = format_for_prompt(hits)
        return {
            **state,
            "retrieved_context": context_str,
            "retrieved_terms": hits,
        }
    except Exception as e:
        return {
            **state,
            "retrieved_context": "",
            "retrieved_terms": [],
        }


# ══════════════════════════════════════════════════════════════════════════
# NODE 2: SQL Generator
# ══════════════════════════════════════════════════════════════════════════
def sql_generator(state: AgentState) -> AgentState:
    """
    Dùng LLM để generate SQL query từ:
    - Câu hỏi của user
    - Database schema
    - Business context (retrieved từ Glossary)
    """
    question         = state["question"]
    context          = state.get("retrieved_context", "")
    retry_count      = state.get("retry_count", 0)
    today            = datetime.now().strftime("%Y-%m-%d")

    prompt = f"""Bạn là SQL expert chuyên phân tích dữ liệu bán lẻ.
Nhiệm vụ: Viết MỘT câu SQL query duy nhất cho câu hỏi bên dưới.
Chỉ trả về SQL query thuần túy, không giải thích, không markdown.

{DB_SCHEMA}

{context}

Ngày hôm nay: {today}

RULES:
1. Chỉ dùng các bảng và cột có trong schema trên.
2. Luôn dùng net_revenue (không phải revenue hay gross_revenue) khi tính doanh thu.
3. Luôn thêm WHERE is_gift = 0 khi tính doanh thu (trừ khi câu hỏi hỏi về quà tặng).
4. Dùng LEFT JOIN với bảng promotions.
5. Date format YYYY-MM-DD, group theo tháng dùng strftime('%Y-%m', outputdate).
6. Nếu câu hỏi hỏi "tháng này" → strftime('%Y-%m', outputdate) = strftime('%Y-%m', 'now').
7. Trả về cả tên đối tượng lẫn giá trị khi câu hỏi hỏi "cái gì / ai nhiều nhất".

Câu hỏi: {question}

SQL Query:"""

    response = llm.invoke(prompt)
    raw = response.content.strip()

    # Clean markdown code block nếu LLM trả về
    sql = re.sub(r"^```(?:sql)?\s*", "", raw, flags=re.IGNORECASE)
    sql = re.sub(r"\s*```$", "", sql).strip()

    return {**state, "sql_query": sql, "error_message": None}


# ══════════════════════════════════════════════════════════════════════════
# NODE 3: SQL Executor
# ══════════════════════════════════════════════════════════════════════════
def sql_executor(state: AgentState) -> AgentState:
    """
    Thực thi SQL query trên SQLite.
    - Thành công: lưu kết quả dưới dạng string + column list
    - Thất bại: lưu error_message để self_corrector xử lý
    """
    sql = state["sql_query"]
    try:
        with engine.connect() as conn:
            result = conn.execute(text(sql))
            rows = result.fetchall()
            columns = list(result.keys())

        if not rows:
            return {
                **state,
                "sql_result": "",
                "sql_columns": columns,
                "error_message": None,
            }

        df = pd.DataFrame(rows, columns=columns)

        # SUM/COUNT trên tập rỗng trả về 1 row toàn NULL → treat như empty
        if df.isnull().all().all():
            return {
                **state,
                "sql_result": "",
                "sql_columns": columns,
                "error_message": None,
            }

        result_str = df.to_string(index=False)
        return {
            **state,
            "sql_result": result_str,
            "sql_columns": columns,
            "error_message": None,
        }

    except Exception as e:
        return {
            **state,
            "sql_result": None,
            "sql_columns": None,
            "error_message": str(e),
        }


# ══════════════════════════════════════════════════════════════════════════
# NODE 4: Self-Corrector
# ══════════════════════════════════════════════════════════════════════════
def self_corrector(state: AgentState) -> AgentState:
    """
    Khi SQL thất bại, gửi error + SQL cũ vào LLM để tự sửa.
    Tăng retry_count sau mỗi lần.
    """
    sql_failed    = state["sql_query"]
    error_msg     = state["error_message"]
    question      = state["question"]
    context       = state.get("retrieved_context", "")
    retry_count   = state.get("retry_count", 0) + 1

    prompt = f"""Câu SQL bên dưới bị lỗi khi chạy trên SQLite. Hãy sửa lại.
Chỉ trả về SQL query đã sửa, không giải thích.

{DB_SCHEMA}

{context}

Câu hỏi gốc: {question}

SQL bị lỗi:
{sql_failed}

Thông báo lỗi:
{error_msg}

SQL đã sửa:"""

    response = llm.invoke(prompt)
    raw = response.content.strip()

    sql = re.sub(r"^```(?:sql)?\s*", "", raw, flags=re.IGNORECASE)
    sql = re.sub(r"\s*```$", "", sql).strip()

    return {
        **state,
        "sql_query": sql,
        "error_message": None,
        "retry_count": retry_count,
    }


# ══════════════════════════════════════════════════════════════════════════
# NODE 5: Insight Generator
# ══════════════════════════════════════════════════════════════════════════
def insight_generator(state: AgentState) -> AgentState:
    """
    Dùng LLM để tóm tắt kết quả SQL thành business insight ngắn gọn.
    """
    question   = state["question"]
    sql_result = state.get("sql_result", "")

    if not sql_result or not sql_result.strip():
        answer = "Không tìm thấy dữ liệu phù hợp với điều kiện này. Thử điều chỉnh khoảng thời gian hoặc tiêu chí lọc."
        return {**state, "final_answer": answer}

    prompt = f"""Bạn là chuyên gia phân tích dữ liệu bán lẻ với 10 năm kinh nghiệm.
Dựa vào dữ liệu SQL bên dưới, hãy trả lời ngắn gọn và súc tích bằng tiếng Việt.

QUAN TRỌNG: Chỉ nhận xét dựa trên số liệu thực tế trong bảng dữ liệu. KHÔNG được suy diễn nguyên nhân kỹ thuật (POS, ETL, pipeline) hay đưa ra giả thuyết ngoài dữ liệu.

Câu hỏi: {question}

Dữ liệu:
{sql_result}

Hãy trả về 3 phần (mỗi phần 2-4 câu gạch đầu dòng, tô đậm số liệu quan trọng):

**1. Tóm tắt:** Tóm tắt dữ liệu chính
**2. Insight:** Phát hiện quan trọng nhất
**3. Đề xuất:** Hành động cụ thể dựa trên số liệu

Trả lời tiếng Việt, ngắn gọn, chỉ giữ thông tin có giá trị."""

    response = llm.invoke(prompt)
    answer = response.content

    return {**state, "final_answer": answer}


# ══════════════════════════════════════════════════════════════════════════
# NODE: Error Response (khi hết retry)
# ══════════════════════════════════════════════════════════════════════════
def error_response(state: AgentState) -> AgentState:
    """Trả về thông báo lỗi thân thiện sau khi hết lượt retry."""
    err = state.get("error_message", "Unknown error")
    sql = state.get("sql_query", "")
    retries = state.get("retry_count", 0)

    answer = (
        f"Không thể thực thi truy vấn sau {retries} lần thử.\n\n"
        f"**Lỗi cuối:** `{err}`\n\n"
        f"**SQL cuối:**\n```sql\n{sql}\n```\n\n"
        "Gợi ý: Thử diễn đạt lại câu hỏi hoặc liên hệ team data để kiểm tra schema."
    )
    return {**state, "final_answer": answer}
