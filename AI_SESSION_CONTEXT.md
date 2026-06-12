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

- [ ] Schema design:
Decision: Normalize schedule stops into junction tables (`metro_schedule_stops` and `national_rail_schedule_stops`). Why: To avoid nested arrays, ensure 1NF, and enable efficient queries on stop sequences.
Decision: Separate credentials into a dedicated `user_credentials` table. Why: To keep sensitive hash/salt values isolated from public user profiles for enhanced security.
Decision: Implement a soft delete strategy via `deleted_at` and `is_active` columns. Why: To maintain transaction history audit trails and prevent cascade delete failures on booking records.
Decision: Use PostgreSQL `num_nonnulls()` constraint for polymorphic feedback and payments relationships. Why: To ensure each polymorphic record links to exactly one valid parent entity cleanly and declaratively.
Decision: Decouple hard foreign keys from `national_rail_bookings` and `metro_travel_history` to `schedules`. Why: To allow schedules to be modified, deleted, or archived without breaking historical booking statistics.
Decision: Maintain redundant snapshot columns (`origin_station_name` and `destination_station_name`) in booking/trip tables. Why: To ensure historical accuracy of booking records even if stations are renamed or deleted in the future.
Decision: Use UUID for `registered_users` and shared UUID primary key for `user_credentials`. Why: Prevents user enumeration attacks while ensuring clean, high-performance 1-to-1 table mapping without surrogate keys.
Decision: Store `operates_on` as a JSONB object in `metro_schedules` and `national_rail_schedules`. Why: Allows flexible representation of schedule operating days while enabling GIN indexing for high-performance day-of-week checks.
Decision: Use custom PostgreSQL enum types ('booking_status', 'travel_status', 'payment_status', 'transit_direction', 'rail_service_type', 'fare_class', 'rail_ticket_type', 'metro_ticket_type', 'pass_type', 'payment_method'). Why: To enforce data integrity and restrict column values to pre-defined valid values at the type level.
Decision: Define coach codes (e.g., 'A', 'B') as VARCHAR(2) instead of ENUM in the database schema. Why: Provides flexibility for varying train sizes and layout expansions without requiring DDL alterations.
Decision: Use `NUMERIC(10,2)` for all monetary values (`amount_usd`). Why: Avoids floating-point rounding errors during price calculation and cancellation refund processing.
Decision: Create separate junction tables for metro (`metro_schedule_stops`) and rail (`national_rail_schedule_stops`). Why: Eliminates polymorphic foreign keys or structural overlap between the two distinct transit systems, enforcing strict relational boundaries.
Decision: Add `deleted_at` column to the `user_credentials` table matching `registered_users`. Why: Ensures that if a user profile is soft-deleted, their credential details are also soft-deleted.
Decision: Use nullable and cascade-protected station foreign keys in booking/trip tables. Why: Prevents deleting a station from crashing historical booking history records.
Decision: Normalize seats into a layout and coaches hierarchy rather than storing seats directly on the schedule. Why: Allows multiple schedules to share the same physical coach/seat configuration model, reducing data redundancy.
Decision: Use natural business keys (e.g. MS01, NR01) for station identifiers. Why: Station identifiers are stable, globally unique, and defined by the transit authority.
Decision: Use business identifiers (e.g. MS_SCH01, NR_SCH01) as primary keys for schedules. Why: Ensures human readability and stable referencing.
Decision: Use business identifiers (e.g. BK-XXXXXX, MP-XXXXXX, MT-XXXXXX) for external tracking and visibility. Why: Provides human-friendly external reference IDs that are easy to communicate for support/payment tracing.
Decision: Enforce `num_nonnulls(national_booking_id, metro_trip_id) = 1` constraint on `feedback`. Why: Guarantees that feedback is linked strictly to a single journey type and never both.
Decision: Enforce `num_nonnulls(national_booking_id, metro_trip_id, metro_pass_id) = 1` constraint on `payments`. Why: Allows unified payment records across bookings, single trips, and passes while enforcing strictly valid polymorphic relationships.
Decision: Explicitly specify ON DELETE actions (e.g. CASCADE, RESTRICT, SET NULL) on all foreign keys in schema.sql. Why: Prevents foreign key constraint default actions from failing static analysis checks and ensures database consistency.

- [ ] Graph schema:
Decision: Use separate node labels `MetroStation` and `NationalRailStation` linked by METRO_LINK, RAIL_LINK, and INTERCHANGE_TO. Why: To represent the dual-network structure naturally while enabling seamless cross-network pathfinding.
Decision: Model fare costs as relationship properties (`cost_standard`, `cost_first`) and add base fare in Python. Why: To optimize route searches for the cheapest path using Dijkstra pathfinding on edge weights.
Decision: Create `INTERCHANGE_TO` relationships between metro and national rail stations with a default travel time of 5.0 minutes. Why: To model cross-network physical transfers at transfer hubs, allowing unified multi-modal pathfinding.
Decision: Use Neo4j MERGE instead of CREATE in seed_neo4j.py. Why: Ensures database seeding scripts are idempotent and prevents duplicate node/relationship creation during multiple runs.

- [ ] (example) Metro schedule stop ordering: using `jsonb_array_elements` approach — easier to debug than containment operators

- [ ] Performance:
Decision: Implement a ThreadedConnectionPool wrapped in a ConnectionProxy object in `queries.py`. Why: To prevent connection exhaustion under high concurrency by reusing connections while maintaining backward compatibility with existing context manager blocks.
Decision: Create composite index `idx_nr_bookings_user_date` on `national_rail_bookings(user_id, travel_date)` and `idx_metro_history_user_date` on `metro_travel_history(user_id, travel_date)` where `deleted_at IS NULL`. Why: To speed up retrieval of user booking histories (the most frequent queries) while filtering out soft-deleted records to save index space.
Decision: Create GIN indexes on `operates_on` in schedules. Why: To optimize queries filtering schedules by active operating days using jsonb operators.
Decision: Create partial indexes `idx_payments_booking_uid` and `idx_payments_metro_uid` where foreign keys are not null. Why: Minimizes physical index size and increases cache hit rate by omitting null references in polymorphic tables.
Decision: Create composite index on `metro_schedule_stops(station_id, stop_order)`. Why: Speeds up route matching and sequence validation queries when resolving stops on a given schedule.
Decision: Apply `WHERE deleted_at IS NULL` on search indexes (like user booking indexes). Why: Keeps the indexes small and speeds up search performance on active records by excluding deleted rows from indexing.
Decision: Expose PostgreSQL on port 5433 externally while maintaining internal Docker port 5432. Why: Prevents conflicts with any pre-existing PostgreSQL server running locally on the user's host machine.

- [ ] Security:
Decision: Hash passwords and secret answers using Argon2id with unique CSPRNG salts. Why: To prevent plaintext credential leakage and protect against brute-force/rainbow table attacks.
Decision: Generate separate CSPRNG salts (`password_salt`, `secret_answer_salt`) using `secrets.token_hex(16)`. Why: Ensures high entropy, non-predictable salts for each credential to defend against dictionary/rainbow table attacks.
Decision: Normalize security answers to lowercase before hashing. Why: To ensure case-insensitive verification for user recovery answers while keeping them securely hashed.
Decision: Use specific Argon2id parameters (time_cost=3, memory_cost=65536, parallelism=4, hash_len=32). Why: Balances password cracking resilience against backend latency, fitting standard security practices while keeping login times responsive.
Decision: Use `Type.ID` as the Argon2 type (Argon2id). Why: Standardizes on the hybrid Argon2id variant which is the current state-of-the-art recommendation, protecting against both side-channel cache attacks and GPU cracking.

- [ ] Transaction:
Decision: Disable autocommit in `execute_booking` and `execute_cancellation` transactions and explicitly manage `commit()` and `rollback()`. Why: To guarantee database ACID properties and prevent partial writes (e.g. seat allocated but payment not recorded) during execution failures.
Decision: Use `FOR UPDATE OF s SKIP LOCKED` when auto-selecting any available seat. Why: To prevent race conditions and double-booking issues under high concurrency by locking the selected seat record.
Decision: Use `FOR UPDATE` on bookings during cancellation. Why: To serialize cancellation operations and prevent double-refund race conditions.

- [ ] Query optimization:
Decision: Use APOC Dijkstra algorithm for graph pathfinding. Why: It minimizes physical travel times or estimated fares using edge weight attributes rather than simple station hop counts.
Decision: Default the travel date to `date.today()` if omitted in rail availability queries. Why: To accurately report real-time available seat counts on a specific travel date.
Decision: Use `min(length(path))` in delay ripple queries. Why: To accurately trace the shortest path of delay propagation within N hops from the origin disrupted station.
Decision: Bi-directionally match paths for delay ripple queries (`(disrupted)-[:METRO_LINK|RAIL_LINK|INTERCHANGE_TO*]-(affected)`). Why: Delays propagate along links in both directions regardless of the train route travel direction.
Decision: Implement password verification fallback inside `verify_secret_answer`. Why: To support multiple hashing algorithms (Argon2id, PBKDF2) and plaintext values to handle legacy seeded data or testing framework manual overrides without errors.
Decision: Use `psycopg2.extras.RealDictCursor` for all PostgreSQL queries. Why: It maps column names directly to dictionary keys, ensuring clean JSON serialization and ease of downstream LLM parsing without manual tuple mapping.
Decision: Sort seats by row and column in `auto_select_adjacent_seats`. Why: Ensures that when adjacent seats are requested, the algorithm naturally prioritizes seats next to each other in the same coach row first before checking other rows.
Decision: Cast all TIME and TIMESTAMPTZ values to text (e.g. `departure_time::text`, `travel_date::text`) in query outputs. Why: Prevents JSON serialization errors when returning database records to Python/Gradio UI layers.
Decision: Dynamically calculate train departure time at intermediate stations by adding travel offsets (`first_train_time + travel_time_min`) in queries. Why: Accurately reflects schedule timetables across stops without hardcoding departure times for every intermediate stop in the DB.
Decision: Implement hop-limited pathfinding in alternative route searches. Why: Limits resource consumption on the Neo4j graph and avoids evaluating extremely long or impractical routes.
Decision: Defensively return early when origin and destination stations are identical in graph queries. Why: Avoids APOC Dijkstra failures or infinite loops and reduces unnecessary network roundtrips to Neo4j.
Decision: Handle hops=0 edge case in query_delay_ripple by returning the source station directly. Why: Prevents Cypher APOC graph pathfinding failure and passes live testing boundary checks.

- [ ] Application integration:
Decision: Abstract the LLM interface into an environment-switched adapter (`llm_provider.py`). Why: Enables swapping between a local Ollama instance (using llama3.2:1b and nomic-embed-text) and cloud-based Google Gemini API without changing any core agent reasoning or query logic.
Decision: Automatically inject user identity context (email, user_id) from the Gradio UI into the agent system prompt when logged in. Why: Allows the LLM to call auth-gated tools (like `get_user_bookings` or `make_booking`) dynamically without requiring the user to repeatedly provide their credentials in chat.
Decision: Seed the PostgreSQL database in strict dependency order (stations -> schedules -> layouts -> users -> bookings -> payments -> feedback). Why: To prevent foreign key constraint violations and guarantee referential integrity during the seeding phase.
Decision: Use `ON CONFLICT DO NOTHING` in SQL seed scripts. Why: Ensures the seeding scripts are fully idempotent and can be safely re-run multiple times if new data is added or if the process is interrupted.
Decision: Aggregate stops and arrival offsets using `json_agg` in `query_metro_schedules`. Why: Returns all stop sequence arrays in a single, well-structured row per schedule to the application layer, reducing the number of SQL rows returned and simplifying path reconstruction.
Decision: Include an optional sidebar toggle in the Gradio UI to display raw DB debug outputs and tool calls. Why: Accelerates debugging of LLM tool routing and database query results without checking terminal logs.
Decision: Implement a strict similarity threshold limit (`VECTOR_SIMILARITY_THRESHOLD`) in RAG similarity search. Why: Prevents the agent from retrieving irrelevant policy documents and hallucinating answers for out-of-scope customer queries.



## Prompts That Worked

<!-- Share prompts that produced good output so teammates can reuse them. -->

### Schema design prompt that worked:

#### PostgreSQL Schema Design Prompt:
```
你現在是 TransitFlow 專案的資料庫設計顧問。請幫我設計一個完整的 PostgreSQL 關聯資料庫 Schema。

【設計需求】
我們要構建一個雙網路運輸系統（地鐵 Metro + 國家鐵路 National Rail），需要支持：
1. 工作流程：使用者查詢行程 → 選擇座位 → 預訂車票 → 支付 → 歷史紀錄
2. 資料來源：train-mock-data/ 資料夾內的 JSON 檔案

【核心 Design 原則】
1. 規範化 (3NF)：避免重複欄位、使用 FK 關聯、但允許快照冗余用於審計追蹤
2. 軟刪除 (Soft Delete)：添加 `deleted_at TIMESTAMPTZ` 和 `is_active BOOLEAN` 用於稽核日誌
3. 業務識別符 (Business Keys)：表設計應優先考慮如何在使用者 UI 中顯示（例如 "BK-123456" 而非自增 ID）
4. UUID 用於敏感資料（使用者 ID）以防止 ID 列舉攻擊
5. 多態關係（Polymorphic）：用 CHECK 約束處理一對多的情況（例如支付可關聯預訂或歷史記錄）
6. 索引策略：為最頻繁的查詢（使用者歷史、排程搜尋、停靠點查詢）建立複合索引

【預期輸出】
完整的 CREATE TABLE 語句，包括：
- 所有必要的表（站點、排程、預訂、支付等）
- 適當的 PK/FK、CHECK 約束、DEFAULT 值
- 合理的數據類型（VARCHAR 長度、NUMERIC 精度等）
- 業務邏輯註解（為什麼選擇此設計）
- 性能優化索引

【注意事項】
- 使用 ENUM 型別管理固定值集合（booking_status, payment_method 等）
- 使用 JSONB 儲存變動數據（例如 operates_on 天數、passed_through_stations）
- 避免設計中有懸空 FK 或圓形相依性
- 考慮資料保留政策（哪些舊記錄應軟刪除 vs 硬刪除）
```

#### Neo4j Graph Schema Design Prompt:
```
你現在是 TransitFlow 專案的圖資料庫 (Graph Database) 設計專家。請幫我設計 Neo4j 的圖架構。

【設計需求】
我們需要表示一個城市地鐵網路（MetroStation）與國家鐵路網路（NationalRailStation）的實體站點與路線相連關係。

【核心原則】
1. 節點標籤：使用不同的 Node Label 來區分兩套網路的站點（MetroStation, NationalRailStation）。
2. 關係類型：使用 METRO_LINK、RAIL_LINK 分別連接相連的相鄰站點，並使用 INTERCHANGE_TO 作為轉乘樞紐連接兩套網路。
3. 屬性設計：
   - 節點應包含 id (如 MS01, NR01), name, lines 列表等屬性。
   - 關係應包含 line 名稱、travel_time_min、cost_standard、cost_first 等邊權重屬性。
4. 提供 Cypher 語句範例，確保可使用 MERGE 防止重複載入，並建立對應的 Node Key 或 Unique Constraints。
```

### Query implementation prompt that worked:

#### Read-Only / SQL Queries Prompt:
```
你現在是 TransitFlow 專案的資料庫開發專家。
請幫我實作以下 Python 唯讀查詢函數。在撰寫程式碼時，請你「嚴格」遵守以下所有專案規則：

【核心規則】
1. 嚴格遵守 Schema：只能使用已定義的資料表與欄位名稱，絕對不可以憑空捏造。
2.防範注入攻擊：所有的變數綁定「必須」使用 `%s` 佔位符，嚴禁使用 f-string 拼接查詢變數。
3. 連線管理規範：唯讀查詢使用 `with _connect() as conn:` 搭配 `with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:`。
4. 軟刪除 (Soft Delete)：若查詢的資料表含有 `deleted_at` 或 `is_active` 欄位，請務必在 WHERE 條件中過濾（例如 `deleted_at IS NULL` 且 `is_active = TRUE`）。
5. 函數簽名與回傳型態：必須與 Stub 完全一致。查詢不到結果時，若回傳型態為 `list` 則回傳 `[]`；若為 `Optional` 則回傳 `None`，不要拋出 Exception。
```

#### Transaction Write SQL Queries Prompt:
```
你現在是 PostgreSQL 事務交易與 ACID 專家。請幫我實作寫入操作（如 execute_booking / execute_cancellation）。

【核心規則】
1. 交易原子性：必須使用 `conn = _connect(autocommit=False)`，關閉自動提交。整個邏輯必須包在 `try...except` 區塊中。
2. 悲觀鎖（Concurrency Locks）：在檢查座位或預訂前，必須先使用 `FOR UPDATE`（或 `FOR UPDATE OF s SKIP LOCKED`）鎖定特定行，以防止高並行下的雙重預訂 (Double Booking) 競爭條件。
3. 連線釋放與回滾：當任何異常發生時，必須呼叫 `conn.rollback()`；成功完成所有寫入步驟後呼叫 `conn.commit()`；並確保在 `finally` 區塊中呼叫 `conn.close()` 釋放連線以防止連線池洩漏。
```

#### Neo4j Cypher Pathfinding Queries Prompt:
```
你現在是 Neo4j 圖演算法與路徑搜尋專家。請幫我實作 Python 圖查詢函數。

【核心規則】
1. 連線管理：使用 `with _driver() as driver:` 搭配 `with driver.session() as session:` 執行查詢，並在回傳結果前將 record 轉換為 dict。
2. 防範注入：必須使用 `$param` 綁定 Cypher 參數（例如 `$origin`）。
3. APOC Dijkstra 演算法：路徑規劃（最快、最便宜）必須使用 `apoc.algo.dijkstra(start, end, 'METRO_LINK|RAIL_LINK|INTERCHANGE_TO', 'weight_property')`，其中 `weight_property` 分別傳入 `travel_time_min`、`cost_standard` 或 `cost_first`。
4. 特殊情況處理：若起點與終點相同，必須直接回傳包含單一站點、花費為 0 的防禦性結果，不呼叫 APOC。
```

### Debugging Prompt

當程式碼在執行、測試或 TA 評測時發生錯誤，可使用以下 Prompt 進行精準除錯：

#### Connection Pool Leak / Exhaustion Debugging Prompt:
```
你現在是 Python psycopg2 連線池除錯專家。

【問題描述】
程式在連續呼叫 `execute_booking` 或 `query_*` 函數後，會出現 `psycopg2.OperationalError: connection limit exceeded` 或執行緒卡死，可能是連線洩漏（Connection Leak）。

【分析任務】
請檢查以下程式碼中的 cursor 與 connection 的釋放邏輯：
1. 是否有在 `finally` 區塊中呼叫 `conn.close()`？
2. 在 `with _connect() as conn:` 結構中，如果手動將其傳遞給多個 cursor，是否正確歸還到連線池？
3. 請幫我重構這段程式碼，確保在高併發下安全釋放連線。
```

#### APOC Dijkstra Pathfinding Debugging Prompt:
```
你現在是 Neo4j 圖演算法除錯專家。

【問題描述】
呼叫 `apoc.algo.dijkstra` 回傳空值，或者出現 `apoc.algo.dijkstra is not registered` 錯誤。

【檢查清單】
1. 請檢查 Docker 容器中是否正確載入了 APOC 插件，並在 `docker-compose.yml` 中啟用了必要的安全權限設定（`dbms.security.procedures.unrestricted=apoc.*`）。
2. 檢查 Cypher 語句中的關係類型過濾器（例如 `'METRO_LINK'`）與屬性名稱是否完全一致。
3. 當起點和終點是同一個節點時，APOC Dijkstra 可能會失敗，請確認是否有加入防禦性代碼直接返回起點。
```

#### Race Condition / Double Booking Debugging Prompt:
```
你現在是資料庫並行控制 (Concurrency Control) 專家。

【問題描述】
當多個執行緒同時嘗試預訂同一個座位（相同 `schedule_id`、`travel_date`、`coach`、`seat_id`）時，系統會發生重複預訂的狀況。

【除錯指示】
1. 請幫我分析 `execute_booking` 的檢查機制。現有的 `SELECT` 檢查是否存在 Time-of-Check to Time-of-Use (TOCTOU) 的競爭條件？
2. 請指導我如何引入 PostgreSQL 悲觀鎖（使用 `FOR UPDATE OF s SKIP LOCKED` 或 `FOR UPDATE`）來保護座位資源，確保同一時間只有一個交易能夠鎖定並成功寫入預訂。
```
---
