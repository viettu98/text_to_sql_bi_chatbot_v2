# -*- coding: utf-8 -*-
"""
Demo script: chạy các câu hỏi "bẫy" để minh họa Self-Correction và Context Retrieval.
Dùng để quay video demo — in từng bước rõ ràng ra console.

Chạy: python demo_trap_questions.py
"""
import sys
import io
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from graph.agent import run_agent

# ── ANSI colors cho console ────────────────────────────────────────────────
BOLD  = "\033[1m"
GREEN = "\033[92m"
YELLOW= "\033[93m"
RED   = "\033[91m"
CYAN  = "\033[96m"
RESET = "\033[0m"
LINE  = "─" * 70

def header(title: str):
    print(f"\n{BOLD}{CYAN}{'═'*70}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'═'*70}{RESET}\n")

def section(title: str):
    print(f"\n{BOLD}{YELLOW}{LINE}{RESET}")
    print(f"{BOLD}{YELLOW}  {title}{RESET}")
    print(f"{BOLD}{YELLOW}{LINE}{RESET}")

def ok(msg: str):
    print(f"{GREEN}✅ {msg}{RESET}")

def warn(msg: str):
    print(f"{YELLOW}⚠️  {msg}{RESET}")

def err(msg: str):
    print(f"{RED}❌ {msg}{RESET}")


# ── Câu hỏi demo ──────────────────────────────────────────────────────────
DEMO_CASES = [
    {
        "id": "Q1",
        "label": "Bẫy 1 — Thuật ngữ nghiệp vụ không khớp tên cột",
        "question": "Doanh thu thuần từ khách VIP tháng này là bao nhiêu?",
        "trap_explained": (
            "'Doanh thu thuần' ≠ tên cột nào trong DB\n"
            "  'Khách VIP' ≠ tên cột (phải là segment='VIP')\n"
            "  'Tháng này' cần SQL động theo ngày hiện tại"
        ),
        "expect_retry": False,
    },
    {
        "id": "Q2",
        "label": "Bẫy 2 — Nhập nhằng nghiệp vụ: tặng quà hay quà tặng?",
        "question": "Tổng doanh thu từ chương trình khuyến mãi tặng quà là bao nhiêu?",
        "trap_explained": (
            "'Tặng quà' có thể nhầm giữa:\n"
            "  (a) promotiontype=2 (Gift Promo — chương trình tặng kèm)\n"
            "  (b) is_gift=1 (sản phẩm quà tặng — không có doanh thu)\n"
            "  Agent phải dùng đúng (a) và loại trừ (b)"
        ),
        "expect_retry": False,
    },
    {
        "id": "Q3",
        "label": "Bẫy 3 — Câu hỏi đa chiều: KM + Kênh + Thời gian",
        "question": "So sánh hiệu quả khuyến mãi giữa kênh online và offline trong năm nay?",
        "trap_explained": (
            "Cần JOIN 3 bảng: sales_orders + promotions\n"
            "  'Hiệu quả' = so sánh AOV có KM vs không có KM\n"
            "  'Năm nay' cần date filter động\n"
            "  Phân tách theo kênh outputtype"
        ),
        "expect_retry": False,
    },
    {
        "id": "Q4",
        "label": "Bẫy 4 — Dùng tên cột sai (self-correction demo)",
        "question": "Tính discount rate trung bình theo từng ngành hàng",
        "trap_explained": (
            "'discount rate' không phải tên cột — LLM có thể tự đặt tên sai\n"
            "  Phải tính: total_discount / gross_revenue * 100\n"
            "  Cần NULLIF để tránh chia 0\n"
            "  Kỳ vọng: LLM gặp lỗi lần 1, tự sửa thành công"
        ),
        "expect_retry": True,
    },
    {
        "id": "Q5",
        "label": "Bẫy 5 — Câu hỏi tăng trưởng phức tạp",
        "question": "Top 3 ngành hàng có tăng trưởng doanh thu MoM cao nhất?",
        "trap_explained": (
            "MoM growth cần Window Function LAG()\n"
            "  Phải GROUP BY tháng + ngành hàng\n"
            "  Lấy top 3 theo % tăng trưởng (không phải tổng doanh thu)"
        ),
        "expect_retry": False,
    },
]


def run_demo(case: dict):
    header(f"[{case['id']}] {case['label']}")

    print(f"{BOLD}Câu hỏi:{RESET} {case['question']}\n")
    print(f"{BOLD}Phân tích bẫy:{RESET}")
    for line in case["trap_explained"].split("\n"):
        print(f"  {line}")

    if case.get("expect_retry"):
        warn("Kỳ vọng: Agent sẽ gặp lỗi và tự sửa (self-correction)")
    print()

    t0 = time.time()
    result = run_agent(case["question"])
    elapsed = time.time() - t0

    # ── Context Retrieval ──────────────────────────────────────────────
    section("Node 1: Context Retrieval")
    terms = result.get("retrieved_terms", [])
    if terms:
        ok(f"Retrieve được {len(terms)} thuật ngữ nghiệp vụ:")
        for t in terms:
            print(f"    [{t['id']:20s}] {t['term']}  (sim={t['similarity_score']})")
    else:
        warn("Không retrieve được thuật ngữ nào")

    # ── SQL Generated ──────────────────────────────────────────────────
    section("Node 2: SQL Generator")
    sql = result.get("sql_query", "")
    if sql:
        ok("SQL được generate:")
        for line in sql.split("\n"):
            print(f"    {line}")
    else:
        err("Không generate được SQL")

    # ── Execution & Retry ──────────────────────────────────────────────
    retry = result.get("retry_count", 0)
    section(f"Node 3: SQL Executor  |  Node 4: Self-Corrector (retry={retry})")

    if retry > 0:
        warn(f"SQL lỗi {retry} lần — Agent đã tự sửa thành công!")
    else:
        ok("SQL chạy thành công ngay lần đầu")

    err_msg = result.get("error_message")
    if err_msg:
        err(f"Lỗi cuối cùng (sau {retry} lần retry): {err_msg}")

    sql_result = result.get("sql_result", "")
    if sql_result:
        lines = sql_result.strip().split("\n")
        preview = lines[:6]
        print()
        for ln in preview:
            print(f"    {ln}")
        if len(lines) > 6:
            print(f"    ... ({len(lines)-6} dòng nữa)")
    else:
        warn("Kết quả rỗng hoặc có lỗi")

    # ── Insight ────────────────────────────────────────────────────────
    section("Node 5: Insight Generator")
    insight = result.get("final_answer", "")
    if insight:
        ok("Insight:")
        for line in insight.strip().split("\n")[:12]:
            print(f"    {line}")
        if len(insight.split("\n")) > 12:
            print("    ...")
    else:
        warn("Không có insight")

    # ── Summary ────────────────────────────────────────────────────────
    print(f"\n{BOLD}Thời gian:{RESET} {elapsed:.1f}s  |  "
          f"{BOLD}Retry:{RESET} {retry}  |  "
          f"{BOLD}Glossary hits:{RESET} {len(terms)}")
    print()


if __name__ == "__main__":
    print(f"\n{BOLD}{'='*70}")
    print("  DEMO: LangGraph Data Analyst Agent — Câu hỏi bẫy")
    print(f"{'='*70}{RESET}")
    print(f"Tổng: {len(DEMO_CASES)} câu hỏi\n")

    # Cho phép chạy 1 câu cụ thể: python demo_trap_questions.py Q3
    target = sys.argv[1].upper() if len(sys.argv) > 1 else None

    for case in DEMO_CASES:
        if target and case["id"] != target:
            continue
        run_demo(case)
        if not target:
            input(f"\n{CYAN}[Enter để tiếp tục câu tiếp theo...]{RESET}\n")

    print(f"\n{BOLD}{GREEN}Demo hoàn tất.{RESET}")
