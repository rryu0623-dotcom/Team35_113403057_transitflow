# IM2002 — Database Design Document

**學生姓名 (Student Name)**: 王仲毅  
**學校 (University)**: 中央大學 (National Central University)

---

## Section 1 — Entity-Relationship Diagram

以下為 TransitFlow 系統的核心實體關聯圖（ERD）：

![TransitFlow ERD](https://i.im.ge/QM5lF4m/mermaid-diagram-2026-06-04-224004.png)

* **實體與屬性規劃 (Entities & Attributes)**：本系統架構圍繞核心關聯式模型展開，捨棄了獨立且冗餘的 `Tickets` 資料表，將車票票務與交易歷史整合至具備高審計價值的事件資料表 `national_rail_bookings`（國家鐵路訂單）與 `metro_travel_history`（捷運乘車紀錄）中。
    * `registered_users`（註冊使用者）：以 UUID (`user_id`) 作為主鍵，防止使用者 ID 列舉與爬蟲攻擊，並包含 `full_name`, `email` (Unique), `phone`, `date_of_birth` 等核心欄位。
    * `user_credentials`（使用者憑證）：採用共享主鍵模式（Shared Primary Key），其 `user_id` 既是主鍵亦是外鍵，緊密編織 1:1 的帳戶安全關係，內含安全雜湊後的 `password_hash` 與加密鹽值 `password_salt`。
    * `national_rail_bookings` 與 `metro_travel_history`：作為核心交易實體，包含 `booking_id`/`trip_id` (PK)、`user_id` (FK) 以及 `schedule_id`。並針對座位分配、票種類型、乘車狀態與金額進行全面追蹤（如：`coach`, `seat_id`, `fare_class`, `amount_usd`, `status`）。
    * `metro_stations` 與 `national_rail_stations`：定義路網中的物理站點，分別以權威機構定義的自然業務鍵（Natural Business Key，如 `MS01`, `NR01`）為主鍵。
    * `metro_schedules` 與 `national_rail_schedules`：定義班次時刻主表，包含路線、方向、起訖站與營運時間區間等。
    * `metro_schedule_stops` 與 `national_rail_schedule_stops`：作為標準的結合表（Junction Tables），用以拆解時刻表與站點間的多對多關聯，並記錄高度依賴該複合主鍵的屬性如 `stop_order`（停靠順序）與 `travel_time_from_origin_min`（自始發站發車之累計時間）。
* **關聯性與基數 (Cardinality & Relationships)**：在實體關聯圖中，所有主要實體間的線條皆明確標註了基數限制以符合真實業務邏輯：
    * `registered_users` 與 `user_credentials` 呈現 **1:1** 的強相依認證關係。
    * `registered_users` 與 `national_rail_bookings` / `metro_travel_history` 呈現 **1:N** 關係（一名使用者可擁有零至多筆交易歷史，且刪除使用者時採用 `ON DELETE RESTRICT` 策略以留存財務審計軌跡）。
    * `national_rail_schedules` / `metro_schedules` 與其對應的 `schedule_stops` 呈現 **1:N** 關係，而 `stations` 與 `schedule_stops` 亦呈現 **1:N** 關係，藉此將時刻表與站點的多對多（M:N）基數優雅降維解耦。
    * `national_rail_seat_layouts`、`national_rail_coaches` 與 `national_rail_seats` 依序向下呈現 **1:N** 的層級包含關係，確保每一張實體座位皆精確錨定於具體的列車車廂與班次佈局中。

---

## Section 2 — Normalisation Justification

* **正規化決策 (3NF Design Decision)**：本資料庫設計嚴格遵循第三正規化（3NF）以消除任何部分相依（Partial Dependency）與遞移相依（Transitive Dependency）。最顯著的實踐在於「時刻表停靠站點」的拆分。在原始需求中，一個班次班表（Schedule）沿途會停靠多個車站，若將這些站點直接以非第一正規化（1NF）的陣列（Array）或 JSONB 格式強行塞入 `metro_schedules` 或 `national_rail_schedules` 資料表中，不僅會違反 1NF 的原子性（Atomicity）原則，更會在更新沿途站點的特定資訊（如：某站的累計行車時間變更）時引發嚴重的更新異常（Update Anomaly）。
    
    為此，我們建立了解耦多對多關係的結合表 `metro_schedule_stops` 與 `national_rail_schedule_stops`。以 `national_rail_schedule_stops` 為例，其主鍵為複合主鍵 `(schedule_id, station_id)`。沿途停靠的非鍵值屬性 `stop_order` 與 `travel_time_from_origin_min`完全且直接相依於該複合主鍵，資料表中不存在任何非主鍵欄位對主鍵的部分相依，亦不存在遞移相依，完全達成了 3NF 的學術與實務標準，確保了資料的嚴密一致性。

* **反正規化權衡 (De-normalisation Trade-off)**：在高併發與講求資料完整性的生產環境下，我們在交易歷史表層級執行了策略性的反正規化設計，具體體現在 `national_rail_bookings` 以及 `metro_travel_history` 資料表中的 `origin_station_name`（出發站名稱）與 `destination_station_name`（到達站名稱）欄位。
    
    在完全正規化的理論模型中，這些名稱完全可以透過外鍵 `origin_station_id` 遞迴 JOIN 回車站主表來即時查詢。然而，這種設計會帶來兩大維運災難：第一，當大批使用者在前端高頻率查詢個人乘車歷史紀錄時，大規模的跨表 JOIN 會耗費大量 CPU 與 I/O 資源；第二，更致命的是**快照冗餘（Snapshot Redundancy）**的需求。在現實鐵道業務中，車站名稱可能會因為行政區劃變更、企業冠名或路網重組而被修改甚至遭到軟刪除。若完全依賴即時 JOIN，一旦車站更名，使用者過去十年前的歷史訂單收據上的文字將會隨之改變，這在財務審計與法律合規上是絕對不允許的錯誤。因此，我們刻意違反正規化，在購票當下將車站名稱以文字快照形式寫入訂單表中，將歷史紀錄查詢的時間複雜度降低至單列讀取（O(1)），同時完美鎖定了交易當下的歷史事實。

* **密碼雜湊與安全 (Password Hashing)**：本系統在認證層級完全摒棄了不具備抗碰撞性（Collision Resistance）且易受 GPU 暴力破解與彩虹表攻擊的 MD5 或 SHA-1 演算法，全面採用現代高強度的 **Argon2id** 密碼雜湊演算法（於 `_hash_password_argon2` 函數中實現）。
    
    Argon2id 是密碼雜湊大賽（PHC）的冠軍演算法，本系統將運算參數配置為：時間成本因子（Time Cost）= 3、記憶體硬度（Memory Cost）= 65,536 KB、並行因子（Parallelism）= 4。Argon2id 的核心優勢在於其同時具備**記憶體硬度（Memory-Hardness）**與時間硬度。它要求每次雜湊運算皆必須佔用大量記憶體記憶體，這使得攻擊者無法利用高度並行的 GPU 叢集或專屬特殊應用積體電路（ASIC）晶片來進行低成本的硬體加速破解。
    
    此外，系統在用戶註冊時，會透過密碼學安全虛擬隨機數生成器（CSPRNG）為每個帳戶獨立生成 128-bit 的唯一十六進位鹽值（Stored in `password_salt`）。Salt 的引入徹底破壞了預先計算的彩虹表（Rainbow Tables）之有效性。即便兩位使用者設定了完全相同的明文密碼（例如 `password123`），在與各自獨立的 Salt 融合並經由 Argon2id 進行密碼雜湊拉伸（Key Stretching）後，於 `user_credentials` 中產生的 `password_hash` 亦會徹底流向完全不同的高維空間，從根本上杜絕了憑證填補（Credential Stuffing）與字典攻擊。

---

## Section 3 — Graph Database Design Rationale

* **圖形資料庫結構設計 (Graph Schema Architecture)**：針對複雜的鐵道路網拓撲、跨路網轉乘以及延誤漣漪分析（Delay Ripple Analysis），系統引入了 Neo4j 圖形資料庫。其結構設計如下：
    * **節點標籤 (Node Labels)**：設計了兩個獨立的頂點實體：`(:MetroStation)`（捷運車站節點）與 `(:NationalRailStation)`（國家鐵路車站節點）。
    * **關聯類型 (Relationship Types)**：
        * `[:METRO_LINK]`：連接相鄰的 `(:MetroStation)`，代表捷運軌道區間。
        * `[:RAIL_LINK]`：連接相鄰的 `(:NationalRailStation)`，代表台鐵/國鐵軌道區間。
        * `[:INTERCHANGE_TO]`：跨越路網邊界的核心關聯，專門用來連接位於同一座綜合轉運站內的 `(:MetroStation)` 與 `(:NationalRailStation)`，模型化實體世界中的站內步行轉乘通道。
    * **屬性配置 (Properties)**：節點配置有 `id` 與 `name`。邊（Relationships）則配置了關鍵的權重屬性：`line`（所屬營運線別）、`travel_time_min`（兩站間實體行車或轉乘所需時間），以及優化成本路徑專用的 `cost_standard` 與 `cost_first` 欄位。

* **關聯式 vs. 圖形資料庫之演算法優勢 (Algorithmic Advantage)**：在面對 TransitFlow 的核心業務場景（如：尋找 A 站到 B 站的最短時間路徑，或分析某站事故引發的延誤漣漪）時，傳統關聯式資料庫（PostgreSQL）遭遇了嚴重的結構性瓶頸。
    
    在 PostgreSQL 中，要計算不固定跳數（Hops）的站點路徑，必須撰寫極度複雜的遞迴公用資料表表達式（Recursive CTEs）。每一次路徑向下延伸，資料庫引擎都必須對鄰接表執行一次代價高昂的 B-Tree 索引掃描與全表 JOIN。隨著路網直徑（Diameter）與層級增加，中間暫存結果集會呈現指數級暴增，導致記憶體耗盡與 CPU 鎖定。
    
    相對地，Neo4j 圖形資料庫原生具備 **免索引相鄰（Index-free Adjacency, IFA）** 的特性。在 Neo4j 中，每個車站節點在磁碟與記憶體中都直接儲存了指向其相鄰邊（`METRO_LINK`, `RAIL_LINK`, `INTERCHANGE_TO`）的實體記憶體指標（Pointers）。路徑遍歷（Graph Traversal）實質上退化為極其高效的指標解參照（Pointer Dereferencing）操作，時間複雜度與圖形的全局大小無關，僅與遍歷的路徑長度成正比。
    
    搭配 Neo4j 內建並經過底層優化的 **Dijkstra 演算法函式庫** (`apoc.algo.dijkstra`)，系統能夠直接將 `travel_time_min` 或 `cost_standard` 作為邊權重，在毫秒級別內返回全局最佳解，這在關聯式資料庫中是完全無法企及的效能優勢。

* **關鍵查詢類型與圖形錨定 (Core Query Types & Layout)**：本系統之 Cypher 實作精確支援以下多種複雜拓撲查詢：
    1.  **最快路徑查詢 (Fastest Route)**：呼叫 `apoc.algo.dijkstra`，傳入 `METRO_LINK|RAIL_LINK` 關聯，並指定權重欄位 `travel_time_min`。演算法會自動沿著 physical pointers 快速收斂，排除盲目遍歷，精準算出兩站間總用時最短的完美乘車方案。
    2.  **跨路網轉乘查詢 (Cross-Network Interchange Path)**：透過 Cypher 語法匹配包含 `INTERCHANGE_TO` 的複合路徑。例如當起點為捷運站而終點為國鐵站時，圖形引擎會自動尋找具備 `[:INTERCHANGE_TO]` 的轉運樞紐節點（如台北車站或板橋車站），將跨系統的行車時間與站內步行時間（預設 5.0 分鐘）完美加權累加，解決了跨路網轉乘規劃的痛點。
    3.  **替代路徑查詢與事故繞道 (Alternative Routing)**：當特定車站發生延誤或關閉時，Cypher 可利用過濾條件 `WHERE NONE(node IN nodes(path) WHERE node.id = $avoid_station_id)`。由於 IFA 的特性，圖形引擎能在走訪時直接「剪枝（Pruning）」掉該受災節點的所有關聯指標，瞬間完成繞道重新運算。

* **節點身分識別 (Node Identity Justification)**：在本系統的圖形架構中，節點的唯一身分識別明確選用 `id` 屬性（其值對應至關聯式資料庫中的自然業務鍵，例如 `"MS03"` 或 `"NR12"`），而非依賴 Neo4j 內部的元素識別碼（Internal ID）。
    
    選用自然業務鍵作為圖形 Node Identity 的原因在於**穩定性與架構解耦**。Neo4j 的內部 ID 是由圖形引擎自行分配的動態整數，當資料庫進行備份還原、移轉、或大規模節點刪除重建時，內部 ID 極有可能發生重組與改變。若將外部系統或 API 參照與內部 ID 進行強綁定，將會導致災難性的懸空指標（Dangling Pointers）。採用穩定不變、由交通主管機關統一編碼的自然業務鍵 `id`，不僅能確保圖形重構時的身分一致性，更能讓 PostgreSQL 的關聯式外鍵與 Neo4j 的頂點 ID 達成一對一的無縫映射（Mapping Lookup），極大地簡化了雙資料庫同步與混合查詢的架構複雜度。

---

## Section 4 — Vector / RAG Design

* **語意搜尋的應用場景 (Semantic Search Use Case)**：TransitFlow 的客服知識庫面臨大量的非結構化自然語言提問（例如處理使用者的退票政策諮詢、班次誤點規範以及特殊颱風氣象因應措施）。
    
    傳統關聯式資料庫的全文檢索（Full-Text Search）或關鍵字比對（Keyword Matching），在面對自然語言的豐富多樣性時會完全失效。舉例而言，當使用者驚慌地在 Chat UI 輸入：「**颱風天火車停駛了，我要怎麼拿回我的錢？**」時，官方的規章政策文件裡，標準措辭可能是：「*當面臨不可抗力之天災與極端氣候因素導致列車停班時，旅客得憑票證辦理全額免手續費退充*」。由於「颱風天」對不上「極端氣候」，「拿回我的錢」對不上「退充」，傳統關鍵字搜尋會因為**關鍵字錯配（Keyword Mismatch）**而返回空結果。
    
    透過 RAG（檢索增強生成）設計，系統將政策文本切割分塊並轉化為高維稠密向量（Dense Vectors），能深入捕捉文字背後的「語意特徵（Semantic Features）」。在向量嵌入空間（Embedding Space）中，「颱風」與「天災」、「拿錢」與「退款」會因為概念高度相似而被拉近，使系統能精準識別使用者意圖並提取正確的規章條款。

* **餘弦相似度與文本分塊策略 (Chunking & Cosine Similarity)**：
    * **餘弦相似度 (Cosine Similarity)**：在 pgvector 向量資料庫中，我們明確選擇餘弦相似度（利用 `<=>` 餘弦距離算子，在 SQL 中以 `1 - (embedding <=> %s::vector)` 計算相似度分數）作為比對度量標準，而非歐氏距離（Euclidean Distance）。
        
        歐氏距離極易受到文本絕對長度（Magnitude）的干擾——長篇大論的政策文檔會因為包含較多單字而導致向量絕對長度極大，從而在歐氏空間中被拉遠。相反地，餘弦相似度專注於計算兩個高維向量在空間中的**方向夾角**，其核心本質是將向量長度歸一化（Normalised），僅評估語意概念的投射方向。這完美契合了客服場景下「短查詢（User Query）比對長文本（Policy Document Chunks）」的業務物理特性。
    * **文本分塊策略 (Chunking Strategy)**：為防止單篇長文規章過度稀釋局部核心語意，系統採用了**固定步長重疊分塊策略（Fixed-size Overlapping Chunking）**。文檔以每 500 個 Token 為一個獨立 Chunks 進行切分，並配置 50 個 Token 的滑動重疊區間（Overlap）。重疊區間的設計至關重要，它能確保跨邊界語句的上下文（Context）語意連續性，防止關鍵政策條文因物理切斷而丟失前置條件。

* **RAG 完整檢索管線 (Complete Pipeline Workflow)**：系統建構了端到端的工業級檢索增強生成管線：
    1.  **向量化（Embedding Phase）**：當使用者輸入自然語言提問時，系統即時調用與後端資料庫完全相同的 Embedding 模型，將提問文字編碼為固定維度的高維向量。
    2.  **近似最近鄰搜尋（ANN Search Phase）**：將查詢向量送入 PostgreSQL，利用 `pgvector` 外掛程式，在 `policy_documents` 資料表上透過已經建立的 **HNSW（Hierarchical Navigable Small World）階層式導航小世界索引** (`idx_policy_docs_embedding`) 執行高速的近似最近鄰搜尋。HNSW 索引能繞過全表掃描，在對數時間複雜度下快速收斂，篩選出相似度大於設定閾值（`VECTOR_SIMILARITY_THRESHOLD`）且最相關的 Top-3 政策文檔區塊。
    3.  **提示詞注入（Prompt Injection Phase）**：檢索模組將這 3 個最相關的真實規章區塊作為「事實背景（Immutable Ground Truth）」，與原始用戶提問一同動態注入到預先設計好的 LLM 系統提示詞（System Prompt）範本中。
    4.  **事實 Grounded 生成（Generation Phase）**：提示詞嚴格限制大語言模型（LLM）：「*你只能依據 Context 提供的官方條款進行回答，若背景資訊未提及，請直接回答不知道，嚴禁憑空捏造。*」LLM 最終輸出精準、具備法律依據的回答，從根源上徹底消除了 LLM 的**模型幻覺（Hallucination）**，確保客運服務的準確與權威。

* **向量維度選擇與模型供應商切換之災難性後果 (Embedding Dimension & Provider Switch Impact)**：本系統的資料庫 Schema 在設計時，於 `policy_documents` 資料表的 `embedding` 欄位指定了明確的維度限制。在與 Ollama 後端（如 `nomic-embed-text` 模型）搭配時，設定為 `vector(768)`；若切換至高階的 Gemini 生態系（如 `gemini-embedding-001` 模型），則需設定為 `vector(3072)`。
    
    這裡隱含了一個重大的架構級約束：**一旦資料庫完成 Seeding（向量入庫與建置 HNSW 索引）後，開發團隊絕對不可在運作中途任意切換 LLM Provider。**
    
    若貿然將 Provider 從 Ollama（產出 768 維向量）切換至 Gemini（產出 3072 維向量），將會引發**向量維度不匹配（Dimension Mismatch）**的致命系統崩潰。底層的 pgvector 引擎與 HNSW 索引在數學上是嚴格綁定於固定維度的線性空間。當後端嘗試將一個新生成的 3072 維 Query 向量傳入 SQL 去與資料庫內現存的 768 維 Embedding 計算餘弦夾角時，資料庫會直接拋出低階核心錯誤（Core Dimension Mismatch Error），導致整個向量檢索管線瞬間癱瘓。要避免此災難，任何供應商的切換都必須伴隨著資料庫 Schema 的修改、刪除現有 HNSW 索引、清空所有歷史向量、並重新執行全局文本重新 Embedding 與重新 Seeding 的完整重構管線。

---

## Section 5 — AI Tool Usage Evidence

### Example 1: Initial Schema Generation & Security Implementation
* **Context**: 建立關聯式資料庫的基礎結構，並著重於現代安全標準與穩健的資料表管理。
* **Prompt**: 「schema.sql 幫我做資料表(多個，用argon2id)」
* **Outcome**: AI 成功產生了包含 21 個資料表的 `schema.sql` 檔案。它為 Argon2id 密碼雜湊實作了 `VARCHAR(255)` 欄位，以確保有足夠的儲存空間容納安全參數。此外，它還包含了針對訂單 ID 的多型關聯（Polymorphic References），以及 `DROP TABLE IF EXISTS ... CASCADE` 指令，確保未來重建資料表時不會發生外鍵衝突。

### Example 2: Refining Security Architecture via Entity Isolation
* **Context**: 透過將敏感的使用者憑證與一般個人資料隔離，改善資料庫安全架構，以符合最小權限原則（Least Privilege）。
* **Prompt**: 「使用者的密碼相關應該存在額外的表中」
* **Outcome**: AI 確認這項提議符合現代資安最佳實踐，並提供了更新後的 SQL 結構。它將使用者資料拆分為 1:1 關係的兩個表：存放非敏感資料（如姓名、Email）的 `registered_users`，以及獨立的憑證表。AI 解釋，這樣可以避免在執行一般個人資料查詢（如 `SELECT *`）時意外將密碼雜湊值也一併查出而增加洩漏風險。

### Example 3: Query Generation & Identifying Architectural Contradictions (Correction Case)
* **Context**: 根據專案要求檔案（`AI_SESSION_CONTEXT`、`transitflow-db-tutorial`）以及剛建立的 Schema 來撰寫關聯式查詢語法，並請 AI 協助偵錯。
* **Prompt**: 「根據repo裡的要求檔案（AI_SESSION_CONTEXT、README、TEAM_AI_WORKFLOW、transitflow-db-tutorial）和schema，寫出relational的query，如根據repo裡的要求檔案（AI_SESSION_CONTEXT、README、TEAM_AI_WORKFLOW、transitflow-db-tutorial）和schema，寫出relational的query，如果有什麼寫法上的問題跟我說果有什麼寫法上的問題跟我說」
* **Outcome**: AI 產生了要求的查詢程式碼，但同時指出了先前協助建立的 Schema 設計中存在嚴重矛盾。AI 點出目前的 Schema 使用了高度正規化的關聯表（`metro_schedule_stops`），這直接牴觸了教學文件與團隊決策紀錄中強烈建議使用的 JSONB 陣列（`stops_in_order`）作法。此外，AI 也抓到了一個錯誤：查詢邏輯中密碼原本故意存成明碼，而非寫入 `password_hash` 欄位，這促使了後續手動修正以匯入雜湊函式庫。

### Example 4: Evaluating Trade-offs: Normalization vs. JSONB
* **Context**: 根據 AI 先前的警告，進行最終的架構決策：是要堅持對停靠站使用嚴格的 3NF 正規化設計，還是改用反正規化的 JSONB 作法。
* **Prompt**: 「教學文件 (transitflow-db-tutorial.md Part 7.1) 指出： 強烈建議使用 JSONB 陣列來儲存停靠站 (stops_in_order) 以及行車時間，因為如果用正規化拆表，查詢「起站到迄站」時會需要寫很複雜的 Self-JOIN。另外在 AI_SESSION_CONTEXT 的 Team Decisions Log 也寫到：using jsonb_array_elements approach。我們採用了高度正規化的設計，建立了 metro_schedule_stops 與 national_rail_schedule_stops。這導致我們在寫 query_metro_schedules 時，必須將 stops 表自己 JOIN 兩次（一次找起站、一次找迄站，並比較 stop_order），效能與可讀性都會比使用 JSONB 差。你建議哪一個?要放棄正規化使用JSONB 陣列來儲存停靠站 (stops_in_order) 以及行車時間還是用我們原本寫的?」
* **Outcome**: AI 強烈建議在這種特定場景下放棄目前的嚴格正規化設計。它解釋，若使用高度正規化的關聯表，在進行基本的路線查詢時會需要寫極度複雜且耗費資源的 Self-JOIN，導致嚴重的效能瓶頸。AI 建議改用 JSONB 陣列，並強調 PostgreSQL 的 GIN 索引功能允許快速查詢停靠站而無需複雜的 JOIN，這不僅符合效能需求，也與既有的團隊共識一致。

---

## Section 6 — Reflection & Trade-offs

在設計這個交通網路資料庫時，我們在資料庫的效能、資訊安全和資料完整性之間做了不少拉鋸與取捨。以下整理了兩個最核心的設計決定，以及如果這個系統要實際推向真實生產（Production）環境時，我們在刪除機制上必須做的重大調整。

### 1. 具體的設計決策與權衡 (Design Decisions & Reasoning)

* **決策一：主鍵選擇（用 UUID 取代自動遞增整數 SERIAL）**
    * **決策與原因：** 在設計 `registered_users` 和核心訂單表時，我們決定用 UUID 當作 Primary Key，而不是用傳統的 `SERIAL` 流水號。因為這是一個包含個資和票務金流的系統，如果使用者的 ID 或訂單 ID 是 1001、1002 這樣規律遞增，有心人士只要在 API 網址裡隨便改個數字，就能輕易猜到其他人的 ID 並把資料爬走（也就是常見的 IDOR 漏洞）。
    * **Trade-off（權衡）：** 這個決定的缺點就是犧牲了儲存空間（UUID 要佔 16 Bytes）跟寫入效能。因為 UUID 是隨機的，會造成資料庫底層 B-Tree 索引的碎片化（Index Fragmentation），讓資料塞進去時的開銷變大。但在安全第一的前提下，我們認為稍微犧牲一點效能來換取防範枚舉攻擊的安全性，是非常值得的。

* **決策二：正規化決策（堅持 3NF 結合表 vs 陣列/JSONB）**
    * **決策與原因：** 在設計時刻表與停靠站點的關係時，雖然有些教學文件建議可以用 JSONB 陣列直接把站點塞進時刻表主表裡（查詢起來比較直覺），但我們最後還是決定嚴格遵守第三正規化（3NF）。我們選擇建立獨立的結合表 `metro_schedule_stops`，把 `schedule_id` 和 `station_id` 拆成複合主鍵，並將停靠順序（`stop_order`）等非鍵值屬性完全相依於該複合主鍵。
    * **Trade-off（權衡）：** 雖然改用 JSONB 可以少掉很多 JOIN，但如果沿途某個車站的資訊有變動，JSONB 很容易在更新時引發異常。我們選擇 3NF 的好處是能確保資料的原子性（Atomicity）與強烈的一致性，完全消除部分相依與遞移相依。代價就是當我們在寫查詢路線的 SQL 時，必須自己做痛苦的 Self-JOIN（起站跟迄站各 JOIN 一次去比對順序），導致查詢語法變得比較複雜且耗費效能。但為了確保交通資料的精準不卡 bug，我們選擇了嚴格正規化的架構。

### 2. 生產環境的差異化考量 (Production Difference)

* **從開發環境的「硬刪除」走向生產環境的「軟刪除」 (Soft Deletion vs. Hard Deletion)**
    * 在目前的開發與寫作業階段，如果資料弄錯了或測試帳號不要了，我們通常就直接下 `DELETE FROM` 或是把整張表 `DROP ... CASCADE` 掉重來，也就是所謂的實體刪除（Hard Deletion）。但如果這個系統真的要上線營運，這種硬幹的做法絕對會造成災難。
    * **具體的架構改變：** 實際上線到 Production 環境時，我們必須在所有核心表單（像是使用者、車站、訂單表）全面導入**軟刪除 (Soft Deletion)** 機制，也就是在 Schema 中加上 `deleted_at TIMESTAMPTZ NULL` 欄位，並把所有 API 的查詢預設加上 `WHERE deleted_at IS NULL`。
    * **原因探討：** 因為客運系統牽扯到複雜的財務查帳和乘車紀錄保留法規。如果一個使用者要求刪除帳號，我們直接下 `DELETE` 把他物理抹除，一定會因為外鍵約束（Foreign Key Constraints）卡住，或者導致他名下的歷史訂單變成孤兒資料（Orphaned Records）甚至引發連帶刪除，這樣到時候財務部門對帳一定會對不起來。改用軟刪除的話，使用者端看起來帳號已經「不見了」，但後台依然留著完整的交易事實，才能符合未來法規備查、財務稽核和商業智能（BI）分析的需求。
