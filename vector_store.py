# -*- coding: utf-8 -*-
"""
Vector Store: build và load ChromaDB từ Business Glossary.
- Lần đầu chạy: embed 32 terms và persist vào ./chroma_db/
- Các lần sau: load từ disk, không embed lại
"""
import os
import sys
from pathlib import Path

import chromadb
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

sys.path.insert(0, str(Path(__file__).parent))
from glossary import get_documents_for_vectordb

CHROMA_DIR = os.path.join(os.path.dirname(__file__), "chroma_db")
COLLECTION_NAME = "business_glossary"


def _get_embed_fn():
    # DefaultEmbeddingFunction dùng all-MiniLM-L6-v2 qua onnxruntime (không cần sentence_transformers)
    return DefaultEmbeddingFunction()


def build_vector_store(force_rebuild: bool = False) -> chromadb.Collection:
    """
    Build hoặc load ChromaDB collection từ Business Glossary.
    force_rebuild=True: xóa và build lại từ đầu.
    """
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    embed_fn = _get_embed_fn()

    existing = [c.name for c in client.list_collections()]

    if COLLECTION_NAME in existing and not force_rebuild:
        collection = client.get_collection(
            name=COLLECTION_NAME,
            embedding_function=embed_fn,
        )
        print(f"[VectorStore] Loaded '{COLLECTION_NAME}' ({collection.count()} docs)")
        return collection

    # Build mới
    if COLLECTION_NAME in existing:
        client.delete_collection(COLLECTION_NAME)

    collection = client.create_collection(
        name=COLLECTION_NAME,
        embedding_function=embed_fn,
        metadata={"hnsw:space": "cosine"},
    )

    docs = get_documents_for_vectordb()
    collection.add(
        documents=[d["page_content"] for d in docs],
        metadatas=[d["metadata"] for d in docs],
        ids=[d["metadata"]["id"] for d in docs],
    )
    print(f"[VectorStore] Built '{COLLECTION_NAME}' with {collection.count()} docs")
    return collection


def retrieve(question: str, top_k: int = 3) -> list[dict]:
    """
    Tìm kiếm các thuật ngữ nghiệp vụ liên quan đến câu hỏi.
    Trả về list dict: {term, sql_formula, sql_filter, sql_note, tables_involved, score}
    """
    collection = build_vector_store()
    results = collection.query(
        query_texts=[question],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )

    output = []
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        output.append({
            "term": meta.get("term", ""),
            "id": meta.get("id", ""),
            "category": meta.get("category", ""),
            "sql_formula": meta.get("sql_formula", ""),
            "sql_filter": meta.get("sql_filter", ""),
            "sql_note": meta.get("sql_note", ""),
            "tables_involved": meta.get("tables_involved", ""),
            "document": doc,
            "similarity_score": round(1 - dist, 3),  # cosine: distance→similarity
        })
    return output


def format_for_prompt(retrieved: list[dict]) -> str:
    """
    Format kết quả retrieve thành block context để đưa vào LLM prompt.
    """
    if not retrieved:
        return ""

    lines = ["=== ĐỊNH NGHĨA NGHIỆP VỤ LIÊN QUAN ==="]
    for r in retrieved:
        lines.append(f"\n[{r['id']}] {r['term']}  (score: {r['similarity_score']})")
        # Lấy dòng định nghĩa từ document
        for line in r["document"].split("\n"):
            if line.startswith("Định nghĩa:"):
                lines.append(f"  {line}")
                break
        if r["sql_formula"]:
            lines.append(f"  → SQL: {r['sql_formula']}")
        elif r["sql_filter"]:
            lines.append(f"  → SQL Filter: {r['sql_filter']}")
        if r["sql_note"]:
            note = r["sql_note"].strip().replace("\n", " ")[:150]
            lines.append(f"  → Lưu ý: {note}")
    return "\n".join(lines)


if __name__ == "__main__":
    # Test build & retrieve
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    build_vector_store(force_rebuild=True)

    test_questions = [
        "Doanh thu thuần tháng này theo ngành hàng?",
        "Khách VIP mua nhiều nhất ngành nào?",
        "Hiệu quả chương trình khuyến mãi giảm giá?",
        "So sánh kênh online vs offline",
    ]
    for q in test_questions:
        print(f"\nQ: {q}")
        hits = retrieve(q, top_k=3)
        for h in hits:
            print(f"  [{h['id']:20s}] {h['term']}  sim={h['similarity_score']}")
