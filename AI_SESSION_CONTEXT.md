# AI Session Context — TransitFlow

**How to use this file:**
At the start of every AI coding session, paste the full contents of this file as your first message to your AI assistant. This gives the AI the context it needs to produce code that fits your codebase and is consistent with your teammates' work.

**Who maintains this file:**
Whoever makes a schema change or architectural decision updates this file in the same commit. Treat it like a team contract.

---

## Project Overview

TransitFlow is a Python-based AI chat assistant for a fictional transit operator. It queries three databases — PostgreSQL (relational + vector), Neo4j (graph) — and uses an LLM to answer user questions. Our task as students is to design the database schema and implement the query functions in `databases/relational/queries.py` and `databases/graph/queries.py`.

## Tech Stack

- Language: Python 3.11+
- Relational DB: PostgreSQL via `psycopg2` with `RealDictCursor`
- Graph DB: Neo4j via the `neo4j` Python driver
- Vector search: `pgvector` extension (already implemented — do not modify)
- Web UI: Gradio
- LLM: Google Gemini or local Ollama (configured via `.env`)

## Coding Conventions

- **Naming:** `snake_case` for all Python names and SQL identifiers
- **Docstrings:** All functions must have a docstring with `Args:` and `Returns:` sections
- **Return types:** Use type hints. Read-only functions return `list[dict]` or `Optional[dict]`
- **Empty results:** Return `[]` or `None` (as documented), never raise an exception for "not found"
- **SQL:** Use `%s` placeholders for all user inputs — never string-format into SQL
- **Relational pattern:** Use `_connect()` helper + `psycopg2.extras.RealDictCursor`:
  ```python
  with _connect() as conn:
      with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
          cur.execute("SELECT ...", (param,))
          return [dict(row) for row in cur.fetchall()]
  ```
- **Graph pattern:** Use `_driver()` helper + session:
  ```python
  with _driver() as driver:
      with driver.session() as session:
          result = session.run("MATCH ...", station_id=station_id)
          return [dict(record) for record in result]
  ```

## Agreed Relational Schema

<!-- ============================================================
  FILL THIS IN after your team completes the schema design workshop.
  Paste your final CREATE TABLE statements here.
  ============================================================ -->

```sql
-- ============================================================
--  TransitFlow PostgreSQL Schema
--  Seed data is loaded separately by: python skeleton/seed_postgres.py
--
--  DELETE STRATEGY: This database uses a Soft Delete strategy (via deleted_at TIMESTAMPTZ columns)
--  for audit trails, historical reference, and to prevent breaking cascade joins on transactional data.
--
--  TWO ROLES:
--    1. Relational  → dual-network transit data you design below
--    2. Vector      → policy documents for RAG (provided — do not modify)
-- ============================================================

-- ============================================================
--  STUDENT TASK — Design and create your relational tables here
--
--  Start from the mock data in train-mock-data/:
--    metro_stations.json, national_rail_stations.json
--    metro_schedules.json, national_rail_schedules.json
--    national_rail_seat_layouts.json
--    registered_users.json
--    bookings.json, metro_travel_history.json
--    payments.json, feedback.json
--
--  Think about:
--    - What tables do you need?
--    - What columns and data types?
--    - Which fields are primary keys? Which are foreign keys?
--    - What constraints make sense?
--
--  Apply your schema with:
--    docker-compose down -v && docker-compose up -d
-- ============================================================

-- Option 2: PostgreSQL native ENUM (fast, enforced at type level)
CREATE TYPE booking_status AS ENUM ('confirmed', 'completed', 'cancelled');
CREATE TYPE travel_status AS ENUM ('completed', 'cancelled');
CREATE TYPE payment_status AS ENUM ('paid', 'refunded');
CREATE TYPE transit_direction AS ENUM ('northbound', 'southbound', 'eastbound', 'westbound');
CREATE TYPE rail_service_type AS ENUM ('normal', 'express');
CREATE TYPE fare_class AS ENUM ('standard', 'first');
CREATE TYPE rail_ticket_type AS ENUM ('single', 'return');
CREATE TYPE metro_ticket_type AS ENUM ('single', 'day_pass');
CREATE TYPE pass_type AS ENUM ('SINGLE', 'DAY_PASS', 'MONTHLY');
CREATE TYPE payment_method AS ENUM ('credit_card', 'debit_card', 'ewallet');




-- 1. Metro stations table
CREATE TABLE metro_stations (
    station_id                   VARCHAR(10)  PRIMARY KEY, -- PK Design Decision: A natural business key (e.g. MS01) is chosen because station identifiers are stable, globally unique, and defined by the transit authority.
    name                         VARCHAR(100) NOT NULL,
    is_interchange_metro         BOOLEAN      NOT NULL,
    is_interchange_national_rail BOOLEAN      NOT NULL,
    deleted_at                   TIMESTAMPTZ  DEFAULT NULL,
    is_active                    BOOLEAN      NOT NULL DEFAULT TRUE
);

-- 2. Metro station lines
CREATE TABLE metro_station_lines (
    station_id VARCHAR(10) REFERENCES metro_stations(station_id) ON DELETE CASCADE,
    line       VARCHAR(10) NOT NULL,
    PRIMARY KEY (station_id, line)
);

-- 3. Metro adjacent stations and travel time
CREATE TABLE metro_station_adjacents (
    station_id          VARCHAR(10) REFERENCES metro_stations(station_id) ON DELETE CASCADE,
    adjacent_station_id VARCHAR(10) REFERENCES metro_stations(station_id) ON DELETE CASCADE,
    line                VARCHAR(10) NOT NULL,
    travel_time_min     INTEGER     NOT NULL,
    PRIMARY KEY (station_id, adjacent_station_id, line)
);

-- 4. National rail stations table
CREATE TABLE national_rail_stations (
    station_id                   VARCHAR(10)  PRIMARY KEY, -- PK Design Decision: A natural business key (e.g. NR01) is chosen because rail station identifiers are stable, globally unique, and defined by the transit authority.
    name                         VARCHAR(100) NOT NULL,
    is_interchange_national_rail BOOLEAN      NOT NULL,
    is_interchange_metro         BOOLEAN      NOT NULL,
    deleted_at                   TIMESTAMPTZ  DEFAULT NULL,
    is_active                    BOOLEAN      NOT NULL DEFAULT TRUE
);

-- 5. National rail station lines
CREATE TABLE national_rail_station_lines (
    station_id VARCHAR(10) REFERENCES national_rail_stations(station_id) ON DELETE CASCADE,
    line       VARCHAR(10) NOT NULL,
    PRIMARY KEY (station_id, line)
);

-- 6. National rail adjacent stations and travel time
CREATE TABLE national_rail_station_adjacents (
    station_id          VARCHAR(10) REFERENCES national_rail_stations(station_id) ON DELETE CASCADE,
    adjacent_station_id VARCHAR(10) REFERENCES national_rail_stations(station_id) ON DELETE CASCADE,
    line                VARCHAR(10) NOT NULL,
    travel_time_min     INTEGER     NOT NULL,
    PRIMARY KEY (station_id, adjacent_station_id, line)
);

-- 6.5 Interchange stations table
CREATE TABLE station_interchanges (
    metro_station_id         VARCHAR(10) REFERENCES metro_stations(station_id) ON DELETE CASCADE,
    national_rail_station_id VARCHAR(10) REFERENCES national_rail_stations(station_id) ON DELETE CASCADE,
    transfer_time_min        INTEGER     NOT NULL DEFAULT 5,
    PRIMARY KEY (metro_station_id, national_rail_station_id)
);

-- 7. Metro schedule table
CREATE TABLE metro_schedules (
    schedule_id                 VARCHAR(20)  PRIMARY KEY, -- PK Design Decision: Business identifier (e.g., MS_SCH01) is chosen as primary key for readability and stable referencing.
    line                        VARCHAR(10)  NOT NULL,
    direction                   transit_direction  NOT NULL,
    origin_station_id           VARCHAR(10)  REFERENCES metro_stations(station_id) ON DELETE RESTRICT,
    destination_station_id      VARCHAR(10)  REFERENCES metro_stations(station_id) ON DELETE RESTRICT,
    first_train_time            TIME         NOT NULL,
    last_train_time             TIME         NOT NULL,
    base_fare_usd               NUMERIC(5,2) NOT NULL,
    per_stop_rate_usd           NUMERIC(5,2) NOT NULL,
    frequency_min               INTEGER      NOT NULL,
    operates_on                 JSONB        NOT NULL,
    deleted_at                  TIMESTAMPTZ  DEFAULT NULL,
    is_active                   BOOLEAN      NOT NULL DEFAULT TRUE
);

CREATE TABLE national_rail_schedules (
    schedule_id                 VARCHAR(20) PRIMARY KEY, -- PK Design Decision: Business identifier (e.g., NR_SCH01) is chosen as primary key for readability and stable referencing.
    line                        VARCHAR(10) NOT NULL,
    service_type                rail_service_type NOT NULL, 
    direction                   transit_direction NOT NULL,
    origin_station_id           VARCHAR(10) REFERENCES national_rail_stations(station_id) ON DELETE RESTRICT,
    destination_station_id      VARCHAR(10) REFERENCES national_rail_stations(station_id) ON DELETE RESTRICT,
    passed_through_stations     JSONB NOT NULL DEFAULT '[]'::jsonb,
    first_train_time            TIME        NOT NULL,
    last_train_time             TIME        NOT NULL,
    frequency_min               INTEGER     NOT NULL,
    operates_on                 JSONB NOT NULL,
    deleted_at                  TIMESTAMPTZ DEFAULT NULL,
    is_active                   BOOLEAN     NOT NULL DEFAULT TRUE
);

-- ============================================================
--  STUDENT TASK — Normalized Schedule Stops Junction Tables
-- ============================================================

-- Junction table for Metro schedule stops
CREATE TABLE metro_schedule_stops (
    schedule_id                 VARCHAR(20)  REFERENCES metro_schedules(schedule_id) ON DELETE CASCADE,
    station_id                  VARCHAR(10)  REFERENCES metro_stations(station_id) ON DELETE CASCADE,
    stop_order                  INTEGER      NOT NULL,
    travel_time_from_origin_min INTEGER      NOT NULL,
    PRIMARY KEY (schedule_id, station_id)
);

-- Junction table for National Rail schedule stops
CREATE TABLE national_rail_schedule_stops (
    schedule_id                 VARCHAR(20)  REFERENCES national_rail_schedules(schedule_id) ON DELETE CASCADE,
    station_id                  VARCHAR(10)  REFERENCES national_rail_stations(station_id) ON DELETE CASCADE,
    stop_order                  INTEGER      NOT NULL,
    travel_time_from_origin_min INTEGER      NOT NULL,
    PRIMARY KEY (schedule_id, station_id)
);

-- 11. National rail fare classes
CREATE TABLE national_rail_schedule_fares (
    schedule_id       VARCHAR(20)  REFERENCES national_rail_schedules(schedule_id) ON DELETE CASCADE,
    fare_class        fare_class  NOT NULL, 
    base_fare_usd     NUMERIC(5,2) NOT NULL,
    per_stop_rate_usd NUMERIC(5,2) NOT NULL,
    PRIMARY KEY (schedule_id, fare_class)
);

-- 14. National rail seat layouts table
CREATE TABLE national_rail_seat_layouts (
    layout_id   VARCHAR(10) PRIMARY KEY,
    schedule_id VARCHAR(20) REFERENCES national_rail_schedules(schedule_id) ON DELETE CASCADE
);

-- 15. National rail coaches
CREATE TABLE national_rail_coaches (
    layout_id  VARCHAR(10) REFERENCES national_rail_seat_layouts(layout_id) ON DELETE CASCADE,
    coach      VARCHAR(2)  NOT NULL, 
    fare_class fare_class NOT NULL,
    PRIMARY KEY (layout_id, coach)
);

-- 16. National rail seats
CREATE TABLE national_rail_seats (
    layout_id   VARCHAR(10) NOT NULL,
    coach       VARCHAR(2)  NOT NULL,
    seat_id     VARCHAR(10) NOT NULL,
    row         INTEGER     NOT NULL,
    seat_column VARCHAR(2)  NOT NULL, 
    PRIMARY KEY (layout_id, coach, seat_id),
    FOREIGN KEY (layout_id, coach) REFERENCES national_rail_coaches(layout_id, coach) ON DELETE CASCADE
);

-- 17. Registered users table
CREATE TABLE registered_users (
    user_id       UUID         PRIMARY KEY, -- PK Design Decision: UUID is used to ensure global uniqueness and prevent user ID enumeration/scraping attacks.
    full_name     VARCHAR(100), 
    email         VARCHAR(100) UNIQUE, 
    phone         VARCHAR(20),  
    date_of_birth DATE,         
    registered_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    deleted_at    TIMESTAMPTZ  DEFAULT NULL, 
    is_active     BOOLEAN      NOT NULL DEFAULT TRUE
);

CREATE TABLE user_credentials (
    user_id             UUID         PRIMARY KEY REFERENCES registered_users(user_id) ON DELETE CASCADE, -- PK Design Decision: Shared primary key pattern (UUID) matching the registered_users table for efficient 1-to-1 relationship mapping.
    password_hash       VARCHAR(255) NOT NULL, 
    password_salt       VARCHAR(64)  NOT NULL, -- CSPRNG generated salt for password
    secret_question     VARCHAR(250) NOT NULL,
    secret_answer_hash  VARCHAR(255) NOT NULL, 
    secret_answer_salt  VARCHAR(64)  NOT NULL, -- CSPRNG generated salt for secret answer
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    deleted_at          TIMESTAMPTZ  DEFAULT NULL 
);

-- 18. National rail bookings (note: removed strong FK to schedules, use application-maintained reference; snapshot station names; larger amount precision)
CREATE TABLE national_rail_bookings (
    booking_id             VARCHAR(15)  PRIMARY KEY, -- PK Design Decision: Business identifier (e.g. BK-XXXXXX) is used for external tracking and user convenience.
    user_id                UUID         REFERENCES registered_users(user_id) ON DELETE RESTRICT, -- avoid hard-deleting users causing orders to disappear
    schedule_id            VARCHAR(20), -- note: decoupled strong FK, allows old schedules to be deleted
    origin_station_id      VARCHAR(10), 
    origin_station_name    VARCHAR(100) NOT NULL, -- note: snapshot redundancy to prevent mismatches if station is deleted/renamed
    destination_station_id VARCHAR(10), 
    destination_station_name VARCHAR(100) NOT NULL, -- note: snapshot redundancy
    travel_date            DATE         NOT NULL,
    departure_time         TIME         NOT NULL,
    ticket_type            rail_ticket_type  NOT NULL,
    fare_class             fare_class  NOT NULL,
    coach                  VARCHAR(2)   NOT NULL,
    seat_id                VARCHAR(10)  NOT NULL,
    stops_travelled        INTEGER      NOT NULL,
    amount_usd             NUMERIC(10,2) NOT NULL, -- note: increased amount precision to prevent overflow
    status                 booking_status  NOT NULL,
    booked_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at             TIMESTAMPTZ  NOT NULL DEFAULT NOW(), -- Mutable State Track requirement
    travelled_at           TIMESTAMPTZ,
    deleted_at             TIMESTAMPTZ  DEFAULT NULL 
);

CREATE TABLE metro_passes (
    pass_id     VARCHAR(15)  PRIMARY KEY, -- PK Design Decision: Business identifier (e.g. MP-XXXXXX) is used for external visibility and pass tracking.
    user_id     UUID         REFERENCES registered_users(user_id) ON DELETE CASCADE,
    pass_type   pass_type  NOT NULL,
    expires_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- 19. Metro travel history (note: decoupled schedule FK; snapshot station names; larger amount precision)
CREATE TABLE metro_travel_history (
    trip_id                VARCHAR(15)  PRIMARY KEY, -- PK Design Decision: Business identifier (e.g. MT-XXXXXX) is used for external visibility.
    user_id                UUID         REFERENCES registered_users(user_id) ON DELETE RESTRICT,
    schedule_id            VARCHAR(20), -- note: decoupled strong FK
    origin_station_id      VARCHAR(10), 
    origin_station_name    VARCHAR(100) NOT NULL, -- note: snapshot redundancy
    destination_station_id VARCHAR(10), 
    destination_station_name VARCHAR(100) NOT NULL, -- note: snapshot redundancy
    travel_date            DATE         NOT NULL,
    ticket_type            metro_ticket_type  NOT NULL,
    pass_id_ref            VARCHAR(15)  REFERENCES metro_passes(pass_id) ON DELETE SET NULL, -- note: changed to reference independent pass table
    stops_travelled        INTEGER,
    amount_usd             NUMERIC(10,2) NOT NULL, -- note: increased amount precision
    status                 travel_status  NOT NULL,
    purchased_at           TIMESTAMPTZ,
    travelled_at           TIMESTAMPTZ,
    updated_at             TIMESTAMPTZ  NOT NULL DEFAULT NOW(), -- Mutable State Track requirement
    deleted_at             TIMESTAMPTZ  DEFAULT NULL 
);

-- 20. Payments
CREATE TABLE payments (
    payment_id          VARCHAR(15)  PRIMARY KEY, -- PK Design Decision: Business identifier (e.g. PM-XXXXXX) is used for payment tracing.
    national_booking_id VARCHAR(15)  REFERENCES national_rail_bookings(booking_id) ON DELETE SET NULL,
    metro_trip_id       VARCHAR(15)  REFERENCES metro_travel_history(trip_id) ON DELETE SET NULL,
    metro_pass_id       VARCHAR(15)  REFERENCES metro_passes(pass_id) ON DELETE SET NULL, -- Allow paying for metro passes
    amount_usd          NUMERIC(10,2) NOT NULL, 
    method              payment_method  NOT NULL,
    status              payment_status  NOT NULL,
    paid_at             TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(), -- Mutable State Track requirement
    deleted_at          TIMESTAMPTZ  DEFAULT NULL, 
    CONSTRAINT check_polymorphic_payment CHECK (
        num_nonnulls(national_booking_id, metro_trip_id, metro_pass_id) = 1
    )
);

-- 21. Feedback
CREATE TABLE feedback (
    feedback_id         VARCHAR(15)  PRIMARY KEY, -- PK Design Decision: Business identifier (e.g. FB-XXXXXX) is used for support tickets/feedback tracing.
    national_booking_id VARCHAR(15)  REFERENCES national_rail_bookings(booking_id) ON DELETE SET NULL,
    metro_trip_id       VARCHAR(15)  REFERENCES metro_travel_history(trip_id) ON DELETE SET NULL,
    user_id             UUID         REFERENCES registered_users(user_id) ON DELETE CASCADE,
    rating              INTEGER      NOT NULL CHECK (rating >= 1 AND rating <= 5),
    comment             TEXT,
    submitted_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    deleted_at          TIMESTAMPTZ  DEFAULT NULL, 
    CONSTRAINT check_polymorphic_feedback CHECK (
        num_nonnulls(national_booking_id, metro_trip_id) = 1
    )
);


-- ============================================================
--                     Performance index section
-- ============================================================

-- Optimize user history/order queries (most frequent network I/O queries)
CREATE INDEX idx_nr_bookings_user_date ON national_rail_bookings (user_id, travel_date) WHERE deleted_at IS NULL;
CREATE INDEX idx_metro_history_user_date ON metro_travel_history (user_id, travel_date) WHERE deleted_at IS NULL;

-- Optimize frontend daily schedule search by line and service type
CREATE INDEX idx_metro_sched_search ON metro_schedules (line, is_active);
CREATE INDEX idx_nr_sched_search ON national_rail_schedules (line, service_type, is_active);

-- Optimize stops lookup inside schedules
CREATE INDEX idx_metro_sched_stops ON metro_schedule_stops (station_id, stop_order);
CREATE INDEX idx_metro_sched_operates ON metro_schedules USING GIN (operates_on);
CREATE INDEX idx_nr_sched_stops ON national_rail_schedule_stops (station_id, stop_order);
CREATE INDEX idx_nr_sched_operates ON national_rail_schedules USING GIN (operates_on);

-- Partial indexes: reduce polymorphic join index size and improve cache hit rate
CREATE INDEX idx_payments_booking_uid ON payments (national_booking_id) WHERE national_booking_id IS NOT NULL;
CREATE INDEX idx_payments_metro_uid ON payments (metro_trip_id) WHERE metro_trip_id IS NOT NULL;
CREATE INDEX idx_feedback_booking_uid ON feedback (national_booking_id) WHERE national_booking_id IS NOT NULL;
CREATE INDEX idx_feedback_metro_uid ON feedback (metro_trip_id) WHERE metro_trip_id IS NOT NULL;

-- Optimize backend interchange/pathfinding algorithms (core join columns for Dijkstra/A* search)
CREATE INDEX idx_metro_adj_lookup ON metro_station_adjacents (station_id, adjacent_station_id);
CREATE INDEX idx_nr_adj_lookup ON national_rail_station_adjacents (station_id, adjacent_station_id);
-- ============================================================
--  VECTOR SCHEMA  (RAG / Help Desk) — do not modify
-- ============================================================

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS policy_documents (
    id          SERIAL       PRIMARY KEY,
    title       VARCHAR(200) NOT NULL,
    category    VARCHAR(50)  NOT NULL,  -- 'refund', 'booking', 'conduct'
    content     TEXT         NOT NULL,
    -- 768-dim  → Ollama nomic-embed-text (default)
    -- 3072-dim → Gemini gemini-embedding-001
    -- If you switch LLM_PROVIDER to gemini, change to vector(3072) and reset the database.
    embedding   vector(768),
    source_file VARCHAR(200),
    created_at  TIMESTAMPTZ  DEFAULT NOW()
);

-- Index for fast cosine similarity search
CREATE INDEX IF NOT EXISTS idx_policy_docs_embedding ON policy_documents USING hnsw (embedding vector_cosine_ops);
```

## Agreed Graph Schema

<!-- ============================================================
  FILL THIS IN after your team agrees on Neo4j node labels and
  relationship types.
  ============================================================ -->

```
Node labels:
- MetroStation: Represents a station in the city metro network.
- NationalRailStation: Represents a station in the national rail network.

Relationship types:
- METRO_LINK: Connects two adjacent MetroStation nodes on a specific line.
- RAIL_LINK: Connects two adjacent NationalRailStation nodes on a specific line.
- INTERCHANGE_TO: Bi-directional link connecting a MetroStation and a NationalRailStation at physical transfer hubs.

Key properties:
- Nodes (MetroStation, NationalRailStation):
  - id: VARCHAR (e.g. "MS01", "NR01") - unique business identifier of the station.
  - name: VARCHAR (e.g. "Central Station") - station name.
  - lines: LIST of strings (e.g. ["Red", "Blue"]) - lines running through the station.
- Relationships (METRO_LINK, RAIL_LINK):
  - line: String (e.g. "Red") - the transit line name.
  - travel_time_min: Integer - travel duration between the two adjacent stations.
  - cost_standard: Float - standard fare cost in USD (e.g. 0.30 for metro, 1.50 for rail).
  - cost_first: Float - first-class fare cost in USD (e.g. 0.30 for metro, 2.50 for rail).
```


## Function Signatures We Are Implementing

These are fixed contracts. AI-generated code must match these signatures exactly.

### Relational (`databases/relational/queries.py`)

```python
# Read-only
def query_national_rail_availability(origin_id: str, destination_id: str, travel_date: Optional[str] = None) -> list[dict]: ...
def query_national_rail_fare(schedule_id: str, fare_class: str, stops_travelled: int) -> Optional[dict]: ...
def query_metro_schedules(origin_id: str, destination_id: str) -> list[dict]: ...
def query_metro_fare(schedule_id: str, stops_travelled: int) -> Optional[dict]: ...
def query_available_seats(schedule_id: str, travel_date: str, fare_class: str) -> list[dict]: ...
def query_user_profile(user_email: str) -> Optional[dict]: ...
def query_user_bookings(user_email: str) -> dict: ...  # returns {"national_rail": [...], "metro": [...]}
def query_payment_info(booking_id: str) -> Optional[dict]: ...

# Write operations
def execute_booking(user_id, schedule_id, origin_station_id, destination_station_id, travel_date, fare_class, seat_id, ticket_type="single") -> tuple[bool, dict | str]: ...
def execute_cancellation(booking_id: str, user_id: str) -> tuple[bool, dict | str]: ...

# Auth
def register_user(email, first_name, surname, year_of_birth, password, secret_question, secret_answer) -> tuple[bool, str]: ...
def login_user(email: str, password: str) -> Optional[dict]: ...
def get_user_secret_question(email: str) -> Optional[str]: ...
def verify_secret_answer(email: str, answer: str) -> bool: ...
def update_password(email: str, new_password: str) -> bool: ...
```

### Graph (`databases/graph/queries.py`)

```python
def query_shortest_route(origin_id: str, destination_id: str, network: str = "auto") -> dict: ...
def query_cheapest_route(origin_id: str, destination_id: str, network: str = "auto", fare_class: str = "standard") -> dict: ...
def query_alternative_routes(origin_id, destination_id, avoid_station_id, network="auto", max_routes=3) -> list[list[dict]]: ...
def query_interchange_path(origin_id: str, destination_id: str) -> dict: ...
def query_delay_ripple(delayed_station_id: str, hops: int = 2) -> list[dict]: ...
def query_station_connections(station_id: str) -> list[dict]: ...
```

## Team Decisions Log

<!-- Add entries as you make decisions. Format: "Decision: X. Why: Y." -->

- [x] Schema design: Normalized schedule stops into `metro_schedule_stops` and `national_rail_schedule_stops` junction tables; separated credentials into `user_credentials` table with Argon2id + CSPRNG salts and salt rotation; added `updated_at` columns for state tracking; simplified polymorphic checks using PostgreSQL `num_nonnulls()`.
- [x] Graph schema: Node labels `MetroStation` and `NationalRailStation`; relationships `METRO_LINK` and `RAIL_LINK` with standard/first-class fare costs, and `INTERCHANGE_TO` for cross-network transfer links; pathfinding via APOC Dijkstra using relationship edge weights.
- [x] Metro schedule stop ordering: using `jsonb_array_elements` approach — easier to debug than containment operators

## Prompts That Worked

<!-- Share prompts that produced good output so teammates can reuse them. -->

### Schema design prompt that worked:
```
TODO — add a prompt here after your schema design workshop
```

### Query implementation prompt that worked:
```
你現在是 TransitFlow 專案的資料庫開發專家。
請幫我實作以下 Python 函數。在撰寫程式碼時，請你「嚴格」遵守以下所有專案規則，若違反任何一條將會導致系統崩潰：

【核心規則】
1. 嚴格遵守 Schema：只能使用我下方提供的資料表、節點(Node)、關係(Relationship)與欄位名稱，**絕對不可以憑空捏造**任何欄位或表名。
2. 防範注入攻擊：
   - 若為 SQL (PostgreSQL)：所有的變數綁定「必須」使用 `%s` 佔位符（例如 `WHERE id = %s`），「嚴禁」使用 f-string 拼接查詢變數。
   - 若為 Cypher (Neo4j)：所有的變數綁定「必須」使用 `$param` 語法（例如 `WHERE s.station_id = $station_id`）。
3. 函數簽名與回傳型態：
   - 函數名稱、參數名稱、預設值與 Type Hints (例如 `-> list[dict]`) 必須與 Stub 完全一致。
   - 查詢不到結果時，若回傳型態為 `list` 則回傳 `[]`；若為 `Optional` 則回傳 `None`，不要拋出 Exception。
4. 連線管理規範：
   - PostgreSQL 唯讀查詢：使用 `with get_db_connection() as conn:` 搭配 `with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:`。
   - PostgreSQL 寫入操作 (execute_*)：必須包含 `try...except` 區塊，並明確呼叫 `conn.commit()` 與 `conn.rollback()` 保證交易原子性 (Transaction ACID)。
   - Neo4j 查詢：使用 `with _driver() as driver:` 搭配 `with driver.session() as session:`，回傳結果請轉換為 dict。
5. 軟刪除 (Soft Delete)：若查詢的資料表含有 `deleted_at` 或 `is_active` 欄位，請務必在 WHERE 條件中過濾（例如 `deleted_at IS NULL` 或 `is_active = TRUE`）。
```
---
