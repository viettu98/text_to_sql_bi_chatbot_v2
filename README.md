# Best Practices: Thiết kế Schema và Prompt để giảm Hallucination trong Text-to-SQL

> **Team Resource Wiki** — BHX Data Analyst Agent  
> Dành cho: Data Engineer, Data Analyst, AI/ML Engineer  

---

## Mục lục

1. [Vì sao Text-to-SQL hay bị Hallucination?](#1-vì-sao-text-to-sql-hay-bị-hallucination)
2. [Best Practices: Thiết kế Schema](#2-best-practices-thiết-kế-schema)
3. [Best Practices: Viết Business Glossary](#3-best-practices-viết-business-glossary)
4. [Best Practices: Thiết kế Prompt](#4-best-practices-thiết-kế-prompt)
5. [Best Practices: Self-Correction Loop](#5-best-practices-self-correction-loop)
6. [Checklist trước khi deploy](#6-checklist-trước-khi-deploy)
7. [Ví dụ thực tế: Câu hỏi bẫy và cách Agent xử lý](#7-ví-dụ-thực-tế-câu-hỏi-bẫy-và-cách-agent-xử-lý)

---

## 1. Vì sao Text-to-SQL hay bị Hallucination?

LLM sinh SQL sai vì 3 nguyên nhân chính:

### 1.1 Không biết schema chính xác
LLM đoán tên cột, tên bảng không tồn tại.
```sql
-- Hallucination: cột "revenue" không tồn tại
SELECT SUM(revenue) FROM sales_orders   -- ❌

-- Đúng: phải dùng net_revenue
SELECT SUM(net_revenue) FROM sales_orders  -- ✅
```

### 1.2 Không hiểu định nghĩa nghiệp vụ
"Doanh thu thuần" có thể hiểu khác nhau tùy công ty. LLM dùng định nghĩa chung chung thay vì định nghĩa riêng của team.
```sql
-- LLM tự hiểu "doanh thu thuần" = gross revenue
SELECT SUM(gross_revenue) FROM sales_orders   -- ❌

-- Đúng theo định nghĩa BHX: đã trừ discount, loại quà tặng
SELECT SUM(net_revenue) FROM sales_orders WHERE is_gift = 0  -- ✅
```

### 1.3 Không biết các quy tắc nghiệp vụ ẩn
Ví dụ: đơn `is_gift = 1` không được tính vào doanh thu, `outputtype` phân biệt kênh bán hàng, v.v.

---

## 2. Best Practices: Thiết kế Schema

### ✅ Đặt tên cột rõ ràng, tự giải thích

| ❌ Tên mơ hồ | ✅ Tên rõ ràng |
|---|---|
| `rev` | `net_revenue` |
| `dt` | `outputdate` |
| `type` | `outputtype` |
| `flag` | `is_gift` |
| `val` | `discountvalue` |

### ✅ Tách biệt gross và net

Đừng chỉ có một cột `revenue`. Luôn có đủ 3 cột:
```sql
gross_revenue  INT  -- trước chiết khấu
total_discount INT  -- tổng giảm giá
net_revenue    INT  -- = gross - discount (doanh thu thực)
```
LLM sẽ dễ hiểu hơn và có thể kiểm tra tính nhất quán: `net = gross - discount`.

### ✅ Dùng boolean rõ ràng thay vì magic number

```sql
-- ❌ LLM không biết 1 nghĩa là gì
is_gift INT

-- ✅ Thêm comment trong Glossary, hoặc dùng TEXT nếu có nhiều giá trị
is_gift INT  -- 0=bán thật, 1=quà tặng kèm KM
```

### ✅ Format ngày nhất quán ISO 8601

```sql
-- ❌ DD/MM/YYYY gây lỗi date function trong SQLite
outputdate TEXT  -- '15/06/2025'

-- ✅ YYYY-MM-DD, SQLite xử lý tốt với strftime()
outputdate TEXT  -- '2025-06-15'
```

### ✅ Đặt tên FK theo pattern nhất quán

```sql
-- Pattern: <table_singular>_id
customer_id  -- FK → customers.customer_id
product_id   -- FK → products.product_id
promotionid  -- ❌ Không nhất quán (thiếu underscore)
promotion_id -- ✅ Nhất quán
```

### ✅ Tránh viết tắt trong tên category/segment

```sql
-- ❌ LLM không biết 'F' là gì
gender TEXT  -- 'M', 'F'

-- Nếu giữ thì PHẢI khai báo rõ trong Glossary/Prompt:
-- 'M' = Nam (Male), 'F' = Nữ (Female)
```

---

## 3. Best Practices: Viết Business Glossary

### ✅ Cấu trúc entry chuẩn

Mỗi entry trong `business_glossary.yaml` cần có đủ 4 phần:

```yaml
- id: DTT                          # ID ngắn để reference
  term: "Doanh thu thuần"          # Tên chính xác
  aliases:                         # Các tên khác user có thể dùng
    - "net revenue"
    - "DTT"
    - "doanh thu sau chiết khấu"
  definition: >                    # Định nghĩa bằng ngôn ngữ tự nhiên
    Tổng doanh thu thực tế sau khi đã trừ toàn bộ chiết khấu.
  sql_formula: "SUM(so.net_revenue)"  # SQL chính xác
  sql_note: "Luôn thêm WHERE is_gift = 0"  # Lưu ý quan trọng
  example_questions:               # Dùng để test retrieval
    - "Doanh thu thuần tháng này?"
```

### ✅ Aliases phải bao phủ cách user thực sự nói

User không nói như developer. Hãy hỏi business team:
- "Khi hỏi về doanh thu, anh/chị dùng từ gì?" → thêm vào aliases
- Bao gồm cả: tiếng Anh, viết tắt, không dấu, sai chính tả phổ biến

```yaml
aliases:
  - "doanh thu"
  - "revenue"
  - "DTT"
  - "doanh thu thuan"   # không dấu
  - "dt thuan"          # viết tắt
```

### ✅ sql_note phải nêu các "bẫy" quan trọng

```yaml
sql_note: >
  QUAN TRỌNG: Luôn thêm WHERE is_gift = 0 khi tính DTT.
  Không dùng gross_revenue. Không dùng cột 'revenue' (không tồn tại).
```

### ✅ Tổ chức theo nhóm nghiệp vụ, không phải theo bảng

```
Nhóm theo BẢNG (❌ khó maintain):
  sales_orders_metrics, customers_filters, ...

Nhóm theo NGHIỆP VỤ (✅):
  Doanh thu (DTT, DTG, Chiết khấu, AOV, ...)
  Khách hàng (VIP, New, Normal, Tần suất, ...)
  Khuyến mãi (Discount Promo, Gift Promo, ...)
  Thời gian (Tháng này, Quý, YTD, ...)
```

---

## 4. Best Practices: Thiết kế Prompt

### ✅ Cấu trúc prompt SQL Generator chuẩn

```
[ROLE]       Bạn là SQL expert, chỉ viết SQL, không giải thích
[SCHEMA]     Đầy đủ tên bảng, cột, kiểu dữ liệu, FK
[CONTEXT]    Business Glossary terms được retrieve (RAG)
[DATE]       Ngày hôm nay (dynamic)
[RULES]      Các ràng buộc cứng (is_gift=0, dùng net_revenue, v.v.)
[QUESTION]   Câu hỏi của user
[OUTPUT]     "SQL Query:" — anchor để LLM biết trả về gì
```

### ✅ Rules phải là ràng buộc cứng, không phải gợi ý

```
# ❌ Gợi ý — LLM có thể bỏ qua
"Nên dùng net_revenue thay vì gross_revenue"

# ✅ Ràng buộc cứng
"LUÔN dùng net_revenue. KHÔNG BAO GIỜ dùng gross_revenue hoặc revenue."
```

### ✅ Cung cấp date context động

```python
today = datetime.now().strftime("%Y-%m-%d")
prompt += f"\nNgày hôm nay: {today}"
```

Nếu không có date context, LLM sẽ tự bịa ngày (hallucination).

### ✅ Hướng dẫn output format rõ ràng

```
# ❌ Mơ hồ
"Viết SQL query"

# ✅ Rõ ràng
"Chỉ trả về SQL query thuần túy.
Không thêm giải thích, không dùng markdown code block.
Nếu cần nhiều query, chỉ giữ lại query cuối cùng hoàn chỉnh nhất."
```

### ✅ Với Self-Corrector: cung cấp đủ context để sửa

```python
# Prompt self-correction phải có:
# 1. Schema (để LLM không đoán cột)
# 2. Câu SQL đã sai
# 3. Thông báo lỗi chính xác
# 4. Câu hỏi gốc (để không lạc đề)
prompt = f"""
Schema: {DB_SCHEMA}
Câu hỏi gốc: {question}
SQL bị lỗi: {failed_sql}
Lỗi: {error_message}
SQL đã sửa:
"""
```

### ✅ Temperature = 0 cho SQL generation

```python
llm = ChatOpenAI(temperature=0)  # Deterministic, ít hallucination hơn
```

Temperature > 0 tăng "sáng tạo" nhưng cũng tăng hallucination trong SQL.

---

## 5. Best Practices: Self-Correction Loop

### ✅ Giới hạn retry hợp lý

```python
MAX_RETRY = 2  # Đủ để sửa lỗi syntax/tên cột
               # Nếu > 2, thường do câu hỏi quá phức tạp hoặc schema sai
```

### ✅ Log đầy đủ để debug

Mỗi lần retry cần log:
- SQL cũ bị lỗi
- Error message chính xác
- SQL mới sau khi sửa
- Thời gian mỗi lần retry

### ✅ Phân loại lỗi để xử lý đúng cách

| Loại lỗi | Ví dụ | Cách xử lý |
|---|---|---|
| **Syntax error** | `near "FORM": syntax error` | Self-correct — LLM sửa được |
| **Tên cột sai** | `no such column: revenue` | Self-correct + cung cấp schema |
| **Tên bảng sai** | `no such table: sale` | Self-correct + cung cấp schema |
| **Logic sai** | Kết quả rỗng dù data có | Cần human review |
| **Câu hỏi ngoài scope** | Hỏi về data không có | Trả lời thân thiện, không retry |

### ✅ Phân biệt "SQL lỗi" và "Kết quả rỗng"

```python
# Kết quả rỗng KHÔNG phải lỗi — không retry
if not rows:
    return {"sql_result": "", "error_message": None}  # ✅

# Chỉ retry khi có exception thực sự
except Exception as e:
    return {"error_message": str(e)}  # → trigger self_corrector
```

---

## 6. Checklist trước khi deploy

### Schema
- [ ] Tất cả cột có tên tự giải thích (không viết tắt)
- [ ] Date format nhất quán YYYY-MM-DD
- [ ] Có cột net_revenue riêng (không chỉ gross)
- [ ] Boolean flag có comment giải thích (is_gift, v.v.)
- [ ] FK đặt tên nhất quán theo pattern

### Business Glossary
- [ ] Đủ aliases cho mỗi term (tiếng Anh + viếng Việt + viết tắt)
- [ ] sql_note nêu rõ các "bẫy" (cột nào không dùng, filter nào bắt buộc)
- [ ] Có ít nhất 3 example_questions per term để test retrieval
- [ ] Đã test semantic search với các câu hỏi thực tế

### Prompt
- [ ] Schema trong prompt luôn đồng bộ với schema thực tế
- [ ] Có date context động
- [ ] Rules viết dưới dạng ràng buộc cứng (LUÔN/KHÔNG BAO GIỜ)
- [ ] Temperature = 0

### Self-Correction
- [ ] MAX_RETRY được set (khuyến nghị: 2)
- [ ] Error message đầy đủ được truyền vào prompt sửa
- [ ] Kết quả rỗng không trigger retry
- [ ] Log retry_count ra UI/Langfuse

### Testing
- [ ] Test ít nhất 5 câu hỏi "bình thường"
- [ ] Test ít nhất 3 câu hỏi "bẫy" (dùng thuật ngữ nghiệp vụ không khớp tên cột)
- [ ] Test câu hỏi có date (tháng này, năm ngoái, v.v.)
- [ ] Test câu hỏi multi-table JOIN
- [ ] Test câu hỏi về promotion analytics

---

## 7. Ví dụ thực tế: Câu hỏi bẫy và cách Agent xử lý

### Bẫy 1: Dùng thuật ngữ nghiệp vụ không khớp tên cột

**Câu hỏi:** *"Doanh thu thuần từ khách VIP tháng này là bao nhiêu?"*

**Vấn đề:**
- "Doanh thu thuần" ≠ tên cột nào trong DB (`net_revenue` mới đúng)
- "Khách VIP" ≠ tên cột (`segment = 'VIP'` mới đúng)
- "Tháng này" cần SQL động theo ngày hiện tại

**Cách Agent xử lý:**
1. Node 1 retrieve: `[DTT] → SUM(net_revenue)`, `[KH_VIP] → segment='VIP'`, `[THANG_NAY] → strftime(...)`
2. Node 2 sinh SQL đúng nhờ context từ Glossary:
```sql
SELECT SUM(so.net_revenue)
FROM sales_orders so
JOIN customers c ON so.customer_id = c.customer_id
WHERE c.segment = 'VIP'
  AND strftime('%Y-%m', so.outputdate) = strftime('%Y-%m', 'now')
  AND so.is_gift = 0
```

---

### Bẫy 2: Câu hỏi dùng từ sai logic

**Câu hỏi:** *"Tổng revenue của chương trình khuyến mãi tặng quà?"*

**Vấn đề:**
- "revenue" không phải tên cột (phải là `net_revenue`)
- "tặng quà" có thể nhầm sang `is_gift = 1` (quà tặng kèm) thay vì `promotiontype = 2` (chương trình Gift Promo)

**Cách Agent xử lý:**
1. Node 1 retrieve: `[KM_QUATANG] → promotiontype=2`, `[DON_QUATANG] → is_gift=1`
2. LLM hiểu context → sinh SQL đúng:
```sql
SELECT pm.promotionname, SUM(so.net_revenue) AS tong_doanh_thu
FROM sales_orders so
JOIN promotions pm ON so.promotionid = pm.promotionid
WHERE pm.promotiontype = 2
  AND so.is_gift = 0   -- loại trừ chính sản phẩm quà tặng
GROUP BY pm.promotionname
ORDER BY tong_doanh_thu DESC
```

---

### Bẫy 3: SQL lỗi — Self-Correction demo

**Câu hỏi:** *"So sánh tỷ lệ chiết khấu giữa các ngành hàng?"*

**Lần 1 — SQL sai** (LLM viết cột không đúng):
```sql
SELECT category, AVG(discount_rate) FROM sales_orders  -- ❌ cột không tồn tại
```
*Error: `no such column: discount_rate`*

**Self-Corrector nhận error → viết lại:**
```sql
SELECT p.category,
       ROUND(SUM(so.total_discount) * 100.0 / NULLIF(SUM(so.gross_revenue), 0), 2) AS ty_le_chiet_khau_pct
FROM sales_orders so
JOIN products p ON so.product_id = p.product_id
WHERE so.is_gift = 0
GROUP BY p.category
ORDER BY ty_le_chiet_khau_pct DESC
```
*✅ Thành công sau 1 lần retry*

---

*Tài liệu này được duy trì bởi team Data BHX. Cập nhật khi thêm bảng mới hoặc thay đổi business logic.*
