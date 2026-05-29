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
DROP TYPE IF EXISTS booking_status CASCADE;
DROP TYPE IF EXISTS travel_status CASCADE;
DROP TYPE IF EXISTS payment_status CASCADE;
DROP TYPE IF EXISTS transit_direction CASCADE;
DROP TYPE IF EXISTS rail_service_type CASCADE;
DROP TYPE IF EXISTS fare_class CASCADE;
DROP TYPE IF EXISTS rail_ticket_type CASCADE;
DROP TYPE IF EXISTS metro_ticket_type CASCADE;
DROP TYPE IF EXISTS pass_type CASCADE;
DROP TYPE IF EXISTS payment_method CASCADE;

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
    station_id                   VARCHAR(10)  PRIMARY KEY,
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
    station_id                   VARCHAR(10)  PRIMARY KEY,
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
    schedule_id            VARCHAR(20)  PRIMARY KEY,
    line                   VARCHAR(10)  NOT NULL,
    direction              transit_direction  NOT NULL,
    origin_station_id      VARCHAR(10)  REFERENCES metro_stations(station_id),
    destination_station_id VARCHAR(10)  REFERENCES metro_stations(station_id),
    first_train_time       TIME         NOT NULL,
    last_train_time        TIME         NOT NULL,
    base_fare_usd          NUMERIC(5,2) NOT NULL,
    per_stop_rate_usd      NUMERIC(5,2) NOT NULL,
    frequency_min          INTEGER      NOT NULL,
    deleted_at             TIMESTAMPTZ  DEFAULT NULL,
    is_active              BOOLEAN      NOT NULL DEFAULT TRUE
);

-- 8. Metro schedule stops
CREATE TABLE metro_schedule_stops (
    schedule_id                 VARCHAR(20) REFERENCES metro_schedules(schedule_id) ON DELETE CASCADE,
    station_id                  VARCHAR(10) REFERENCES metro_stations(station_id),
    stop_order                  INTEGER     NOT NULL,
    travel_time_from_origin_min INTEGER     NOT NULL,
    PRIMARY KEY (schedule_id, station_id)
);

-- 9. Metro schedule operation days
CREATE TABLE metro_schedule_operates (
    schedule_id VARCHAR(20) REFERENCES metro_schedules(schedule_id) ON DELETE CASCADE,
    day_of_week SMALLINT    NOT NULL CHECK (day_of_week BETWEEN 1 AND 7), 
    PRIMARY KEY (schedule_id, day_of_week)
);

-- 10. National rail schedule table
CREATE TABLE national_rail_schedules (
    schedule_id            VARCHAR(20) PRIMARY KEY,
    line                   VARCHAR(10) NOT NULL,
    service_type           rail_service_type NOT NULL, 
    direction              transit_direction NOT NULL,
    origin_station_id      VARCHAR(10) REFERENCES national_rail_stations(station_id),
    destination_station_id VARCHAR(10) REFERENCES national_rail_stations(station_id),
    first_train_time       TIME        NOT NULL,
    last_train_time        TIME        NOT NULL,
    frequency_min          INTEGER     NOT NULL,
    deleted_at             TIMESTAMPTZ DEFAULT NULL,
    is_active              BOOLEAN     NOT NULL DEFAULT TRUE
);

-- 11. National rail schedule stops
CREATE TABLE national_rail_schedule_stops (
    schedule_id                 VARCHAR(20) REFERENCES national_rail_schedules(schedule_id) ON DELETE CASCADE,
    station_id                  VARCHAR(10) REFERENCES national_rail_stations(station_id),
    stop_order                  INTEGER     NOT NULL,
    travel_time_from_origin_min INTEGER     NOT NULL,
    is_stop                     BOOLEAN     NOT NULL,
    PRIMARY KEY (schedule_id, station_id)
);

-- 12. National rail fare classes
CREATE TABLE national_rail_schedule_fares (
    schedule_id       VARCHAR(20)  REFERENCES national_rail_schedules(schedule_id) ON DELETE CASCADE,
    fare_class        fare_class  NOT NULL, 
    base_fare_usd     NUMERIC(5,2) NOT NULL,
    per_stop_rate_usd NUMERIC(5,2) NOT NULL,
    PRIMARY KEY (schedule_id, fare_class)
);

-- 13. National rail schedule operation days
CREATE TABLE national_rail_schedule_operates (
    schedule_id VARCHAR(20) REFERENCES national_rail_schedules(schedule_id) ON DELETE CASCADE,
    day_of_week SMALLINT    NOT NULL CHECK (day_of_week BETWEEN 1 AND 7),
    PRIMARY KEY (schedule_id, day_of_week)
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
    user_id       UUID         PRIMARY KEY,
    full_name     VARCHAR(100), 
    email         VARCHAR(100) UNIQUE, 
    phone         VARCHAR(20),  
    date_of_birth DATE,         
    registered_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    deleted_at    TIMESTAMPTZ  DEFAULT NULL, 
    is_active     BOOLEAN      NOT NULL DEFAULT TRUE
);

-- 17.5 User credentials table (note: secret answer hashed, no plaintext)
CREATE TABLE user_credentials (
    user_id             UUID         PRIMARY KEY REFERENCES registered_users(user_id) ON DELETE CASCADE,
    password_hash       VARCHAR(255) NOT NULL, 
    secret_question     VARCHAR(250) NOT NULL,
    secret_answer_hash  VARCHAR(255) NOT NULL, -- note
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    deleted_at          TIMESTAMPTZ  DEFAULT NULL 
);

-- 18. National rail bookings (note: removed strong FK to schedules, use application-maintained reference; snapshot station names; larger amount precision)
CREATE TABLE national_rail_bookings (
    booking_id             VARCHAR(15)  PRIMARY KEY, 
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
    travelled_at           TIMESTAMPTZ,
    deleted_at             TIMESTAMPTZ  DEFAULT NULL 
);

-- 18.5 Metro passes table (note: breaks self-reference in metro travel history)
CREATE TABLE metro_passes (
    pass_id     VARCHAR(15)  PRIMARY KEY,
    user_id     UUID         REFERENCES registered_users(user_id),
    pass_type   pass_type  NOT NULL,
    expires_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- 19. Metro travel history (note: decoupled schedule FK; snapshot station names; larger amount precision)
CREATE TABLE metro_travel_history (
    trip_id                VARCHAR(15)  PRIMARY KEY, 
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
    deleted_at             TIMESTAMPTZ  DEFAULT NULL 
);

-- 20. Payments
CREATE TABLE payments (
    payment_id          VARCHAR(15)  PRIMARY KEY,
    national_booking_id VARCHAR(15)  REFERENCES national_rail_bookings(booking_id) ON DELETE SET NULL,
    metro_trip_id       VARCHAR(15)  REFERENCES metro_travel_history(trip_id) ON DELETE SET NULL,
    amount_usd          NUMERIC(10,2) NOT NULL, 
    method              payment_method  NOT NULL,
    status              payment_status  NOT NULL,
    paid_at             TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    deleted_at          TIMESTAMPTZ  DEFAULT NULL, 
    CONSTRAINT check_polymorphic_payment CHECK (
        (national_booking_id IS NOT NULL AND metro_trip_id IS NULL) OR
        (national_booking_id IS NULL AND metro_trip_id IS NOT NULL)
    )
);

-- 21. Feedback
CREATE TABLE feedback (
    feedback_id         VARCHAR(15)  PRIMARY KEY,
    national_booking_id VARCHAR(15)  REFERENCES national_rail_bookings(booking_id) ON DELETE SET NULL,
    metro_trip_id       VARCHAR(15)  REFERENCES metro_travel_history(trip_id) ON DELETE SET NULL,
    user_id             UUID         REFERENCES registered_users(user_id),
    rating              INTEGER      NOT NULL CHECK (rating >= 1 AND rating <= 5),
    comment             TEXT,
    submitted_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    deleted_at          TIMESTAMPTZ  DEFAULT NULL, 
    CONSTRAINT check_polymorphic_feedback CHECK (
        (national_booking_id IS NOT NULL AND metro_trip_id IS NULL) OR
        (national_booking_id IS NULL AND metro_trip_id IS NOT NULL)
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
- TODO

Relationship types:
- TODO

Key properties:
- TODO
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

- [ ] Schema design: TODO — add your table/column decisions here
- [ ] Graph schema: TODO — add your node label and relationship type decisions here
- [ ] (example) Metro schedule stop ordering: using `jsonb_array_elements` approach — easier to debug than containment operators

## Prompts That Worked

<!-- Share prompts that produced good output so teammates can reuse them. -->

### Schema design prompt that worked:
```
TODO — add a prompt here after your schema design workshop
```

### Query implementation prompt that worked:
```
TODO — add after implementing your first function
```
