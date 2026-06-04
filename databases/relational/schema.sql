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
    deleted_at             TIMESTAMPTZ  DEFAULT NULL 
);

-- 20. Payments
CREATE TABLE payments (
    payment_id          VARCHAR(15)  PRIMARY KEY, -- PK Design Decision: Business identifier (e.g. PM-XXXXXX) is used for payment tracing.
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
    feedback_id         VARCHAR(15)  PRIMARY KEY, -- PK Design Decision: Business identifier (e.g. FB-XXXXXX) is used for support tickets/feedback tracing.
    national_booking_id VARCHAR(15)  REFERENCES national_rail_bookings(booking_id) ON DELETE SET NULL,
    metro_trip_id       VARCHAR(15)  REFERENCES metro_travel_history(trip_id) ON DELETE SET NULL,
    user_id             UUID         REFERENCES registered_users(user_id) ON DELETE CASCADE,
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
