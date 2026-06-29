# -*- coding: utf-8 -*-
"""
Business Glossary Loader
Đọc file YAML và chuẩn bị dữ liệu để embed vào Vector DB.
"""

import yaml
from pathlib import Path

GLOSSARY_PATH = Path(__file__).parent / "business_glossary.yaml"


def load_glossary() -> list[dict]:
    """Trả về list các term entries từ YAML."""
    with open(GLOSSARY_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["terms"]


def get_documents_for_vectordb() -> list[dict]:
    """
    Chuẩn bị documents cho Vector DB.
    Mỗi document gồm:
      - page_content: text để embed (term + aliases + definition)
      - metadata: sql_formula, sql_filter, tables_involved, id
    """
    terms = load_glossary()
    docs = []
    for t in terms:
        # Nội dung để embed: gom term + aliases + definition thành 1 chuỗi
        aliases_str = ", ".join(t.get("aliases", []))
        content = (
            f"Thuật ngữ: {t['term']}\n"
            f"Tên khác: {aliases_str}\n"
            f"Định nghĩa: {t['definition']}\n"
            f"Ví dụ câu hỏi: {'; '.join(t.get('example_questions', []))}"
        )

        # Metadata để trả về kèm kết quả retrieve
        meta = {
            "id": t["id"],
            "term": t["term"],
            "category": t.get("category", ""),
            "sql_formula": t.get("sql_formula", ""),
            "sql_filter": t.get("sql_filter", ""),
            "sql_note": t.get("sql_note", ""),
            "tables_involved": ", ".join(t.get("tables_involved", [])),
        }
        docs.append({"page_content": content, "metadata": meta})
    return docs


def format_context_for_prompt(retrieved_docs: list) -> str:
    """
    Format các docs đã retrieve thành chuỗi context để đưa vào prompt LLM.
    """
    if not retrieved_docs:
        return ""

    lines = ["=== ĐỊNH NGHĨA NGHIỆP VỤ LIÊN QUAN ==="]
    for doc in retrieved_docs:
        meta = doc.metadata if hasattr(doc, "metadata") else doc.get("metadata", {})
        content = doc.page_content if hasattr(doc, "page_content") else doc.get("page_content", "")
        lines.append(f"\n[{meta.get('id', '')}] {meta.get('term', '')}")
        lines.append(f"  {content.split(chr(10))[2]}")  # chỉ lấy dòng định nghĩa
        if meta.get("sql_formula"):
            lines.append(f"  SQL: {meta['sql_formula']}")
        elif meta.get("sql_filter"):
            lines.append(f"  SQL Filter: {meta['sql_filter']}")
        if meta.get("sql_note"):
            lines.append(f"  Lưu ý: {meta['sql_note'][:120]}...")
    return "\n".join(lines)
