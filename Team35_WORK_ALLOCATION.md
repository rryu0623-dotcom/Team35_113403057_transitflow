# Work Allocation Report — [Team ID]

> **Instructions:** Complete this document as a team before or alongside your final submission.
> Submit one copy per team via EEClass. This document is shared with all markers.
> Be specific — vague entries ("we all helped") will prevent individual contribution adjustments from being applied in your favour.

---

## 1. Team Members

| Full Name | Student ID | GitHub Username | Email |
|-----------|-----------|----------------|-------|
| 王仲毅 | 113403057 | rryu0623-dotcom | rryu0623@gmail.com |
| 陳辰 | 113302056 | brianchen989 | brianchen989@gmail.com |
| 施駿朋 | 113403064 | aa379 | andybella9987@gmail.com |

---

## 2. Task Ownership

For each task, name the **primary owner** (the person most responsible for delivering it)
and any **supporting members** (who assisted but were not the lead). Leave the Notes column
for anything that deviates from the standard expectation (e.g., task was pair-programmed,
or reassigned mid-project).

### Code Repository

| Task | Primary Owner | Supporting Member(s) | Notes |
|------|--------------|---------------------|-------|
| **Task 1** — Relational schema design (`schema.sql`) | 施駿朋、陳辰 | 王仲毅 | |
| **Task 2a** — Core availability & fare queries (`query_national_rail_availability`, `query_metro_schedules`, `query_national_rail_fare`, `query_metro_fare`) | 王仲毅 | | |
| **Task 2b** — Seat & user queries (`query_available_seats`, `query_user_profile`, `query_user_bookings`, `query_payment_info`) | 王仲毅 | | |
| **Task 2c** — Write operations (`execute_booking`, `execute_cancellation`) | 王仲毅 | | |
| **Task 2d** — Authentication queries (`login_user`, `register_user`, `get_user_secret_question`, `verify_secret_answer`, `update_password`) | 王仲毅 | | |
| **Task 3** — PostgreSQL seeding (`seed_postgres.py`) | 陳辰 | | |
| **Task 4** — Neo4j graph design & seeding (`seed_neo4j.py`, `seed.cypher`) | 施駿朋 | | |
| **Task 5** — Neo4j query functions (`graph/queries.py`) | 施駿朋 | | |
| **Task 6** *(if attempted)* — Optional extension | | | |

### Design Document

| Section | Primary Author | Supporting Member(s) | Notes |
|---------|--------------|---------------------|-------|
| Section 1 — ER Diagram | 王仲毅 | | |
| Section 2 — Normalisation Justification | 王仲毅 | | |
| Section 3 — Graph Database Design Rationale | 王仲毅 | | |
| Section 4 — Vector / RAG Design | 王仲毅 | | |
| Section 5 — AI Tool Usage Evidence | | | |
| Section 6 — Reflection & Trade-offs | | | |
| Section 7 — Optional Extension *(if applicable)* | | | |

---

## 3. Estimated Contribution Percentages

Based on the task allocation above, what percentage of total team effort do you estimate each member contributed?
All members must sum to 100%.

| Member | Estimated % | Brief justification |
|--------|-----------|---------------------|
| 王仲毅 | 33% | 主要負責 PostgreSQL 核心查詢與寫入功能（Task 2a-2d）的開發，並撰寫設計文件的主體。 |
| 陳辰 | 34% | 主導關聯式資料庫的 Schema 設計與 Seeding 腳本撰寫（Task 1 & 3）以及測試我們的程式碼，並協助系統整合，對整體架構貢獻顯著。 |
| 施駿朋 | 33% | 負責整個 Neo4j 圖形資料庫的設計、資料導入與查詢函式開發（Task 4 & 5），並共同參與 Schema 設計以及修改組員測試出來有出錯的部分(程式碼) |
| **Total** | **100%** | |

---

## 4. Mid-Project Changes

If any tasks were reassigned or the original plan changed significantly, document it here.
If nothing changed, write "No changes."

No changes.

---

## 5. Team Declaration

We confirm that this work allocation accurately reflects how responsibilities were divided within our team.

| Name | Signature / Typed name | Date |
|------|----------------------|------|
| 王仲毅 | 王仲毅 | 2026/06/05 |
| 陳辰 | 陳辰 | 2026/06/05 |
| 施駿朋 | 施駿朋 | 2026/06/05 |
