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
CREATE INDEX IF NOT EXISTS ON policy_documents USING hnsw (embedding vector_cosine_ops);


CREATE TABLE users (
    user_id VARCHAR(50) PRIMARY KEY, full_name VARCHAR(100) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL, password VARCHAR(255) NOT NULL,
    phone VARCHAR(20), date_of_birth DATE, secret_question TEXT,
    secret_answer TEXT, registered_at TIMESTAMP WITH TIME ZONE, is_active BOOLEAN DEFAULT TRUE
);

CREATE TABLE metro_stations (
    station_id VARCHAR(50) PRIMARY KEY, name VARCHAR(100) NOT NULL,
    zone INTEGER, lines JSONB, adjacent_stations JSONB
);

CREATE TABLE national_rail_stations (
    station_id VARCHAR(50) PRIMARY KEY, name VARCHAR(100) NOT NULL,
    lines JSONB, is_interchange_national_rail BOOLEAN,
    interchange_national_rail_lines JSONB, is_interchange_metro BOOLEAN,
    interchange_metro_station_id VARCHAR(50)
);

CREATE TABLE national_rail_schedules (
    schedule_id VARCHAR(50) PRIMARY KEY, line VARCHAR(50) NOT NULL,
    service_type VARCHAR(50), direction VARCHAR(50),
    origin_station_id VARCHAR(50) REFERENCES national_rail_stations(station_id),
    destination_station_id VARCHAR(50) REFERENCES national_rail_stations(station_id),
    first_train_time TIME, last_train_time TIME, frequency_min INTEGER,
    stops_in_order JSONB, passed_through_stations JSONB,
    travel_time_from_origin_min JSONB, fare_classes JSONB, operates_on JSONB
);

CREATE TABLE national_rail_seat_layouts (
    layout_id VARCHAR(50) PRIMARY KEY, schedule_id VARCHAR(50) REFERENCES national_rail_schedules(schedule_id), coaches JSONB
);

CREATE TABLE national_rail_bookings (
    booking_id VARCHAR(50) PRIMARY KEY, user_id VARCHAR(50) REFERENCES users(user_id),
    schedule_id VARCHAR(50) REFERENCES national_rail_schedules(schedule_id),
    travel_date DATE, departure_time TIME,
    origin_station_id VARCHAR(50) REFERENCES national_rail_stations(station_id),
    destination_station_id VARCHAR(50) REFERENCES national_rail_stations(station_id),
    fare_class VARCHAR(50), amount_usd NUMERIC(10, 2), status VARCHAR(50)
);

CREATE TABLE metro_travels (
    trip_id VARCHAR(50) PRIMARY KEY, user_id VARCHAR(50) REFERENCES users(user_id),
    schedule_id VARCHAR(50), origin_station_id VARCHAR(50) REFERENCES metro_stations(station_id),
    destination_station_id VARCHAR(50) REFERENCES metro_stations(station_id),
    travel_date DATE, ticket_type VARCHAR(50), day_pass_ref VARCHAR(50),
    stops_travelled INTEGER, amount_usd NUMERIC(10, 2), status VARCHAR(50),
    purchased_at TIMESTAMP WITH TIME ZONE, travelled_at TIMESTAMP WITH TIME ZONE
);

CREATE TABLE payments (
    payment_id VARCHAR(50) PRIMARY KEY, booking_id VARCHAR(50) NOT NULL,
    amount_usd NUMERIC(10, 2) NOT NULL, method VARCHAR(50), status VARCHAR(50), paid_at TIMESTAMP WITH TIME ZONE
);

CREATE TABLE policy_documents (
    id SERIAL PRIMARY KEY, title TEXT, content TEXT, embedding vector(768)
);