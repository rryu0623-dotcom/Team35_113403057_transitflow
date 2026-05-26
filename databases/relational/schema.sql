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

CREATE TABLE metro_stations (
    station_id VARCHAR(10) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    lines TEXT[] NOT NULL,
    is_interchange BOOLEAN NOT NULL DEFAULT FALSE,
    connected_networks TEXT[] NOT NULL DEFAULT '{}',
    latitude NUMERIC(9,6),
    longitude NUMERIC(9,6),
    deleted_at TIMESTAMPTZ
);

CREATE TABLE national_rail_stations (
    station_id VARCHAR(10) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    lines TEXT[] NOT NULL,
    is_interchange_national_rail BOOLEAN NOT NULL DEFAULT FALSE,
    interchange_national_rail_lines TEXT[] DEFAULT '{}',
    adjacent_stations JSONB DEFAULT '[]',
    deleted_at TIMESTAMPTZ
);

CREATE TABLE station_interchanges (
    interchange_id SERIAL PRIMARY KEY,
    metro_station_id VARCHAR(10) NOT NULL,
    national_rail_station_id VARCHAR(10) NOT NULL,
    walking_time_minutes INT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    deleted_at TIMESTAMPTZ,
    CONSTRAINT fk_metro_station 
        FOREIGN KEY (metro_station_id) 
        REFERENCES metro_stations(station_id),
    CONSTRAINT fk_national_rail_station 
        FOREIGN KEY (national_rail_station_id) 
        REFERENCES national_rail_stations(station_id),
    CONSTRAINT uk_interchange_pair UNIQUE (metro_station_id, national_rail_station_id)
);

CREATE TABLE schedules (
    schedule_id VARCHAR(20) PRIMARY KEY,
    network VARCHAR(20) NOT NULL CHECK (network IN ('metro', 'national_rail')),
    line VARCHAR(50) NOT NULL,
    service_type VARCHAR(50),
    direction VARCHAR(20) NOT NULL,
    origin_station_id VARCHAR(10) NOT NULL,
    destination_station_id VARCHAR(10) NOT NULL,
    first_train_time TIME NOT NULL,
    last_train_time TIME NOT NULL,
    frequency_min INT NOT NULL,
    operates_on TEXT[] NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);

CREATE TABLE schedule_stops (
    schedule_id VARCHAR(20) NOT NULL,
    stop_order INT NOT NULL,
    station_id VARCHAR(10) NOT NULL,
    travel_time_from_origin_min INT NOT NULL,
    PRIMARY KEY (schedule_id, stop_order),
    CONSTRAINT fk_schedule_stop FOREIGN KEY (schedule_id)
        REFERENCES schedules(schedule_id) ON DELETE CASCADE
);

CREATE TABLE schedule_fares (
    schedule_id VARCHAR(20) NOT NULL,
    fare_class VARCHAR(50) NOT NULL,
    base_fare_usd NUMERIC(8,2) NOT NULL,
    per_stop_rate_usd NUMERIC(8,2) NOT NULL,
    PRIMARY KEY (schedule_id, fare_class),
    CONSTRAINT fk_schedule_fare FOREIGN KEY (schedule_id)
        REFERENCES schedules(schedule_id) ON DELETE CASCADE
);

CREATE TABLE seat_layouts (
    layout_id VARCHAR(20) PRIMARY KEY,
    schedule_id VARCHAR(20) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    deleted_at TIMESTAMPTZ,
    CONSTRAINT fk_seat_layout_schedule FOREIGN KEY (schedule_id)
        REFERENCES schedules(schedule_id) ON DELETE CASCADE
);

CREATE TABLE seat_layout_coaches (
    layout_id VARCHAR(20) NOT NULL,
    coach VARCHAR(10) NOT NULL,
    fare_class VARCHAR(50) NOT NULL,
    PRIMARY KEY (layout_id, coach),
    CONSTRAINT fk_seat_layout FOREIGN KEY (layout_id)
        REFERENCES seat_layouts(layout_id) ON DELETE CASCADE
);

CREATE TABLE seat_layout_seats (
    layout_id VARCHAR(20) NOT NULL,
    coach VARCHAR(10) NOT NULL,
    seat_id VARCHAR(10) NOT NULL,
    row INT NOT NULL,
    column_label VARCHAR(5) NOT NULL,
    PRIMARY KEY (layout_id, coach, seat_id),
    CONSTRAINT fk_seat_layout_coach FOREIGN KEY (layout_id, coach)
        REFERENCES seat_layout_coaches(layout_id, coach) ON DELETE CASCADE
);

CREATE TABLE users (
    user_id UUID PRIMARY KEY,
    full_name VARCHAR(255) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    phone VARCHAR(20),
    date_of_birth DATE,
    secret_question TEXT,
    secret_answer TEXT,
    registered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_active BOOLEAN NOT NULL DEFAULT TRUE
    ,deleted_at TIMESTAMPTZ
);

CREATE TABLE user_credentials (
    user_id UUID PRIMARY KEY,
    password_hash BYTEA NOT NULL,
    salt BYTEA NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ,
    CONSTRAINT fk_user_credentials_user FOREIGN KEY (user_id)
        REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE bookings (
    booking_id VARCHAR(20) PRIMARY KEY,
    user_id UUID NOT NULL,
    schedule_id VARCHAR(20) NOT NULL,
    origin_station_id VARCHAR(10) NOT NULL,
    destination_station_id VARCHAR(10) NOT NULL,
    travel_date DATE NOT NULL,
    departure_time TIME NOT NULL,
    ticket_type VARCHAR(50) NOT NULL,
    fare_class VARCHAR(50),
    coach VARCHAR(10),
    seat_id VARCHAR(10),
    stops_travelled INT NOT NULL,
    amount_usd NUMERIC(10,2) NOT NULL,
    status VARCHAR(30) NOT NULL,
    booked_at TIMESTAMPTZ NOT NULL,
    travelled_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ,
    CONSTRAINT fk_booking_user FOREIGN KEY (user_id)
        REFERENCES users(user_id),
    CONSTRAINT fk_booking_schedule FOREIGN KEY (schedule_id)
        REFERENCES schedules(schedule_id)
);

CREATE TABLE travel_history (
    trip_id VARCHAR(20) PRIMARY KEY,
    user_id UUID NOT NULL,
    schedule_id VARCHAR(20) NOT NULL,
    origin_station_id VARCHAR(10) NOT NULL,
    destination_station_id VARCHAR(10) NOT NULL,
    travel_date DATE NOT NULL,
    ticket_type VARCHAR(50) NOT NULL,
    stops_travelled INT NOT NULL,
    amount_usd NUMERIC(10,2) NOT NULL,
    status VARCHAR(30) NOT NULL,
    purchased_at TIMESTAMPTZ NOT NULL,
    travelled_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ,
    CONSTRAINT fk_travel_history_user FOREIGN KEY (user_id)
        REFERENCES users(user_id),
    CONSTRAINT fk_travel_history_schedule FOREIGN KEY (schedule_id)
        REFERENCES schedules(schedule_id)
);

CREATE TABLE payments (
    payment_id VARCHAR(20) PRIMARY KEY,
    booking_id VARCHAR(20) NOT NULL,
    amount_usd NUMERIC(10,2) NOT NULL,
    method VARCHAR(50) NOT NULL,
    status VARCHAR(30) NOT NULL,
    paid_at TIMESTAMPTZ NOT NULL,
    deleted_at TIMESTAMPTZ,
    CONSTRAINT fk_payment_booking FOREIGN KEY (booking_id)
        REFERENCES bookings(booking_id)
);

CREATE TABLE feedback (
    feedback_id VARCHAR(20) PRIMARY KEY,
    booking_id VARCHAR(20) NOT NULL,
    user_id UUID NOT NULL,
    rating INT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment TEXT,
    submitted_at TIMESTAMPTZ NOT NULL,
    deleted_at TIMESTAMPTZ,
    CONSTRAINT fk_feedback_booking FOREIGN KEY (booking_id)
        REFERENCES bookings(booking_id),
    CONSTRAINT fk_feedback_user FOREIGN KEY (user_id)
        REFERENCES users(user_id)
);


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
