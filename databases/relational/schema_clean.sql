-- ============================================================
--  TransitFlow PostgreSQL Schema
--  Seed data is loaded separately by: python skeleton/seed_postgres.py
--
--  TWO ROLES:
--    1. Relational  → dual-network transit data
--    2. Vector      → policy documents for RAG (provided — do not modify)
-- ============================================================

-- ============================================================
--  VECTOR SCHEMA  (RAG / Help Desk) — do not modify
-- ============================================================

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS policy_documents (
    id          SERIAL       PRIMARY KEY,
    title       VARCHAR(200) NOT NULL,
    category    VARCHAR(50)  NOT NULL,
    content     TEXT         NOT NULL,
    embedding   vector(768),
    source_file VARCHAR(200),
    created_at  TIMESTAMPTZ  DEFAULT NOW()
);

-- Index for fast cosine similarity search
CREATE INDEX IF NOT EXISTS ON policy_documents USING hnsw (embedding vector_cosine_ops);

-- ============================================================
--  RELATIONAL SCHEMA — Dual-network transit
-- ============================================================

CREATE TABLE users (
    user_id VARCHAR(50) PRIMARY KEY,
    full_name VARCHAR(100) NOT NULL,
    first_name VARCHAR(50),
    surname VARCHAR(50),
    email VARCHAR(255) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL,
    phone VARCHAR(20),
    date_of_birth DATE,
    secret_question TEXT,
    secret_answer TEXT,
    registered_at TIMESTAMP WITH TIME ZONE,
    is_active BOOLEAN DEFAULT TRUE
);

CREATE TABLE metro_stations (
    station_id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    lines JSONB,
    is_interchange_metro BOOLEAN,
    interchange_metro_lines JSONB,
    is_interchange_national_rail BOOLEAN,
    interchange_national_rail_station_id VARCHAR(50),
    adjacent_stations JSONB
);

CREATE TABLE national_rail_stations (
    station_id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    lines JSONB,
    is_interchange_national_rail BOOLEAN,
    interchange_national_rail_lines JSONB,
    is_interchange_metro BOOLEAN,
    interchange_metro_station_id VARCHAR(50),
    adjacent_stations JSONB
);

CREATE TABLE metro_schedules (
    schedule_id VARCHAR(50) PRIMARY KEY,
    line VARCHAR(50) NOT NULL,
    direction VARCHAR(50),
    origin_station_id VARCHAR(50) REFERENCES metro_stations(station_id),
    destination_station_id VARCHAR(50) REFERENCES metro_stations(station_id),
    stops_in_order JSONB,
    first_train_time TIME,
    last_train_time TIME,
    travel_time_from_origin_min JSONB,
    base_fare_usd NUMERIC(10, 2),
    per_stop_rate_usd NUMERIC(10, 2),
    frequency_min INTEGER,
    operates_on JSONB
);

CREATE TABLE national_rail_schedules (
    schedule_id VARCHAR(50) PRIMARY KEY,
    line VARCHAR(50) NOT NULL,
    service_type VARCHAR(50),
    direction VARCHAR(50),
    origin_station_id VARCHAR(50) REFERENCES national_rail_stations(station_id),
    destination_station_id VARCHAR(50) REFERENCES national_rail_stations(station_id),
    first_train_time TIME,
    last_train_time TIME,
    frequency_min INTEGER,
    stops_in_order JSONB,
    travel_time_from_origin_min JSONB,
    fare_classes JSONB,
    operates_on JSONB
);

CREATE TABLE national_rail_seat_layouts (
    layout_id VARCHAR(50) PRIMARY KEY,
    schedule_id VARCHAR(50) REFERENCES national_rail_schedules(schedule_id),
    coaches JSONB
);

CREATE TABLE national_rail_bookings (
    booking_id VARCHAR(50) PRIMARY KEY,
    user_id VARCHAR(50) REFERENCES users(user_id),
    schedule_id VARCHAR(50) REFERENCES national_rail_schedules(schedule_id),
    origin_station_id VARCHAR(50) REFERENCES national_rail_stations(station_id),
    destination_station_id VARCHAR(50) REFERENCES national_rail_stations(station_id),
    travel_date DATE,
    departure_time TIME,
    ticket_type VARCHAR(50),
    fare_class VARCHAR(50),
    coach VARCHAR(10),
    seat_id VARCHAR(10),
    stops_travelled INTEGER,
    amount_usd NUMERIC(10, 2),
    status VARCHAR(50),
    booked_at TIMESTAMP WITH TIME ZONE,
    travelled_at TIMESTAMP WITH TIME ZONE
);

CREATE TABLE metro_travels (
    trip_id VARCHAR(50) PRIMARY KEY,
    user_id VARCHAR(50) REFERENCES users(user_id),
    schedule_id VARCHAR(50) REFERENCES metro_schedules(schedule_id),
    origin_station_id VARCHAR(50) REFERENCES metro_stations(station_id),
    destination_station_id VARCHAR(50) REFERENCES metro_stations(station_id),
    travel_date DATE,
    ticket_type VARCHAR(50),
    stops_travelled INTEGER,
    amount_usd NUMERIC(10, 2),
    status VARCHAR(50),
    purchased_at TIMESTAMP WITH TIME ZONE,
    travelled_at TIMESTAMP WITH TIME ZONE
);

CREATE TABLE payments (
    payment_id VARCHAR(50) PRIMARY KEY,
    booking_id VARCHAR(50),
    amount_usd NUMERIC(10, 2),
    method VARCHAR(50),
    status VARCHAR(50),
    paid_at TIMESTAMP WITH TIME ZONE
);

CREATE TABLE feedback (
    feedback_id VARCHAR(50) PRIMARY KEY,
    booking_id VARCHAR(50),
    user_id VARCHAR(50) REFERENCES users(user_id),
    rating INTEGER,
    comment TEXT,
    submitted_at TIMESTAMP WITH TIME ZONE
);

-- ============================================================
--  INDEXES FOR PERFORMANCE
-- ============================================================

CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_national_rail_bookings_user_id ON national_rail_bookings(user_id);
CREATE INDEX idx_national_rail_bookings_status ON national_rail_bookings(status);
CREATE INDEX idx_national_rail_bookings_travel_date ON national_rail_bookings(travel_date);
CREATE INDEX idx_metro_travels_user_id ON metro_travels(user_id);
CREATE INDEX idx_metro_travels_travel_date ON metro_travels(travel_date);
CREATE INDEX idx_payments_booking_id ON payments(booking_id);
CREATE INDEX idx_feedback_booking_id ON feedback(booking_id);
CREATE INDEX idx_metro_schedules_origin_dest ON metro_schedules(origin_station_id, destination_station_id);
CREATE INDEX idx_national_rail_schedules_origin_dest ON national_rail_schedules(origin_station_id, destination_station_id);
