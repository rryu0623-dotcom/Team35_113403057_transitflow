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
-- ============================================================

-- Clean up existing tables to allow safe schema resets
DROP TABLE IF EXISTS station_interchanges CASCADE;
DROP TABLE IF EXISTS user_credentials CASCADE;
DROP TABLE IF EXISTS feedback CASCADE;
DROP TABLE IF EXISTS payments CASCADE;
DROP TABLE IF EXISTS metro_travel_history CASCADE;
DROP TABLE IF EXISTS national_rail_bookings CASCADE;
DROP TABLE IF EXISTS registered_users CASCADE;
DROP TABLE IF EXISTS national_rail_seats CASCADE;
DROP TABLE IF EXISTS national_rail_coaches CASCADE;
DROP TABLE IF EXISTS national_rail_seat_layouts CASCADE;
DROP TABLE IF EXISTS national_rail_schedule_operates CASCADE;
DROP TABLE IF EXISTS national_rail_schedule_fares CASCADE;
DROP TABLE IF EXISTS national_rail_schedule_stops CASCADE;
DROP TABLE IF EXISTS national_rail_schedules CASCADE;
DROP TABLE IF EXISTS metro_schedule_operates CASCADE;
DROP TABLE IF EXISTS metro_schedule_stops CASCADE;
DROP TABLE IF EXISTS metro_schedules CASCADE;
DROP TABLE IF EXISTS national_rail_station_adjacents CASCADE;
DROP TABLE IF EXISTS national_rail_station_lines CASCADE;
DROP TABLE IF EXISTS national_rail_stations CASCADE;
DROP TABLE IF EXISTS metro_station_adjacents CASCADE;
DROP TABLE IF EXISTS metro_station_lines CASCADE;
DROP TABLE IF EXISTS metro_stations CASCADE;

-- 1. 捷運車站主表 (支援軟刪除)
CREATE TABLE IF NOT EXISTS metro_stations (
    station_id                   VARCHAR(10)  PRIMARY KEY,
    name                         VARCHAR(100) NOT NULL,
    is_interchange_metro         BOOLEAN      NOT NULL,
    is_interchange_national_rail BOOLEAN      NOT NULL,
    deleted_at                   TIMESTAMPTZ  DEFAULT NULL, -- 支援軟刪除 (stations)
    is_active                    BOOLEAN      NOT NULL DEFAULT TRUE
);

-- 2. 捷運車站所屬路線 (多對多關係)
CREATE TABLE IF NOT EXISTS metro_station_lines (
    station_id VARCHAR(10) REFERENCES metro_stations(station_id) ON DELETE CASCADE,
    line       VARCHAR(10) NOT NULL,
    PRIMARY KEY (station_id, line)
);

-- 3. 捷運相鄰車站與行車時間
CREATE TABLE IF NOT EXISTS metro_station_adjacents (
    station_id          VARCHAR(10) REFERENCES metro_stations(station_id) ON DELETE CASCADE,
    adjacent_station_id VARCHAR(10) REFERENCES metro_stations(station_id) ON DELETE CASCADE,
    line                VARCHAR(10) NOT NULL,
    travel_time_min     INTEGER     NOT NULL,
    PRIMARY KEY (station_id, adjacent_station_id, line)
);

-- 4. 國鐵車站主表 (支援軟刪除)
CREATE TABLE IF NOT EXISTS national_rail_stations (
    station_id                   VARCHAR(10)  PRIMARY KEY,
    name                         VARCHAR(100) NOT NULL,
    is_interchange_national_rail BOOLEAN      NOT NULL,
    is_interchange_metro         BOOLEAN      NOT NULL,
    deleted_at                   TIMESTAMPTZ  DEFAULT NULL, -- 支援軟刪除 (stations)
    is_active                    BOOLEAN      NOT NULL DEFAULT TRUE
);

-- 5. 國鐵車站所屬路線 (多對多關係)
CREATE TABLE IF NOT EXISTS national_rail_station_lines (
    station_id VARCHAR(10) REFERENCES national_rail_stations(station_id) ON DELETE CASCADE,
    line       VARCHAR(10) NOT NULL,
    PRIMARY KEY (station_id, line)
);

-- 6. 國鐵相鄰車站與行車時間
CREATE TABLE IF NOT EXISTS national_rail_station_adjacents (
    station_id          VARCHAR(10) REFERENCES national_rail_stations(station_id) ON DELETE CASCADE,
    adjacent_station_id VARCHAR(10) REFERENCES national_rail_stations(station_id) ON DELETE CASCADE,
    line                VARCHAR(10) NOT NULL,
    travel_time_min     INTEGER     NOT NULL,
    PRIMARY KEY (station_id, adjacent_station_id, line)
);

-- 6.5 跨網車站轉乘關係表 (獨立關係表)
CREATE TABLE IF NOT EXISTS station_interchanges (
    metro_station_id         VARCHAR(10) REFERENCES metro_stations(station_id) ON DELETE CASCADE,
    national_rail_station_id VARCHAR(10) REFERENCES national_rail_stations(station_id) ON DELETE CASCADE,
    transfer_time_min        INTEGER     NOT NULL DEFAULT 5, -- 轉乘步行時間 (分鐘)
    PRIMARY KEY (metro_station_id, national_rail_station_id)
);

-- 7. 捷運營運班表主表 (支援軟刪除/車次停駛)
CREATE TABLE IF NOT EXISTS metro_schedules (
    schedule_id            VARCHAR(20)  PRIMARY KEY,
    line                   VARCHAR(10)  NOT NULL,
    direction              VARCHAR(20)  NOT NULL,
    origin_station_id      VARCHAR(10)  REFERENCES metro_stations(station_id),
    destination_station_id VARCHAR(10)  REFERENCES metro_stations(station_id),
    first_train_time       TIME         NOT NULL,
    last_train_time        TIME         NOT NULL,
    base_fare_usd          NUMERIC(5,2) NOT NULL,
    per_stop_rate_usd      NUMERIC(5,2) NOT NULL,
    frequency_min          INTEGER      NOT NULL,
    deleted_at             TIMESTAMPTZ  DEFAULT NULL, -- 支援軟刪除 (schedules)
    is_active              BOOLEAN      NOT NULL DEFAULT TRUE
);

-- 8. 捷運班表停靠站順序與累積時間
CREATE TABLE IF NOT EXISTS metro_schedule_stops (
    schedule_id                 VARCHAR(20) REFERENCES metro_schedules(schedule_id) ON DELETE CASCADE,
    station_id                  VARCHAR(10) REFERENCES metro_stations(station_id),
    stop_order                  INTEGER     NOT NULL,
    travel_time_from_origin_min INTEGER     NOT NULL,
    PRIMARY KEY (schedule_id, station_id)
);

-- 9. 捷運班表營運星期
CREATE TABLE IF NOT EXISTS metro_schedule_operates (
    schedule_id VARCHAR(20) REFERENCES metro_schedules(schedule_id) ON DELETE CASCADE,
    day_of_week VARCHAR(3)  NOT NULL,
    PRIMARY KEY (schedule_id, day_of_week)
);

-- 14. 國鐵座位配置主表
CREATE TABLE IF NOT EXISTS national_rail_seat_layouts (
    layout_id   VARCHAR(10) PRIMARY KEY
);

-- 15. 國鐵車廂配置
CREATE TABLE IF NOT EXISTS national_rail_coaches (
    layout_id  VARCHAR(10) REFERENCES national_rail_seat_layouts(layout_id) ON DELETE CASCADE,
    coach      VARCHAR(2)  NOT NULL, -- e.g. A, B
    fare_class VARCHAR(20) NOT NULL,
    PRIMARY KEY (layout_id, coach)
);

-- 16. 國鐵座位明細
CREATE TABLE IF NOT EXISTS national_rail_seats (
    layout_id   VARCHAR(10) NOT NULL,
    coach       VARCHAR(2)  NOT NULL,
    seat_id     VARCHAR(10) NOT NULL,
    row         INTEGER     NOT NULL,
    seat_column VARCHAR(2)  NOT NULL, -- column is a reserved keyword in SQL, so we use seat_column
    PRIMARY KEY (layout_id, coach, seat_id),
    FOREIGN KEY (layout_id, coach) REFERENCES national_rail_coaches(layout_id, coach) ON DELETE CASCADE
);

-- 10. 國鐵營運班表主表 (支援軟刪除/車次停駛)
CREATE TABLE IF NOT EXISTS national_rail_schedules (
    schedule_id            VARCHAR(20) PRIMARY KEY,
    line                   VARCHAR(10) NOT NULL,
    service_type           VARCHAR(20) NOT NULL, -- normal, express
    direction              VARCHAR(20) NOT NULL,
    origin_station_id      VARCHAR(10) REFERENCES national_rail_stations(station_id),
    destination_station_id VARCHAR(10) REFERENCES national_rail_stations(station_id),
    first_train_time       TIME        NOT NULL,
    last_train_time        TIME        NOT NULL,
    frequency_min          INTEGER     NOT NULL,
    layout_id              VARCHAR(10) REFERENCES national_rail_seat_layouts(layout_id) ON DELETE SET NULL,
    deleted_at             TIMESTAMPTZ DEFAULT NULL, -- 支援軟刪除 (schedules)
    is_active              BOOLEAN     NOT NULL DEFAULT TRUE
);

-- 11. 國鐵班表停靠/通過車站與累積時間
CREATE TABLE IF NOT EXISTS national_rail_schedule_stops (
    schedule_id                 VARCHAR(20) REFERENCES national_rail_schedules(schedule_id) ON DELETE CASCADE,
    station_id                  VARCHAR(10) REFERENCES national_rail_stations(station_id),
    stop_order                  INTEGER     NOT NULL,
    travel_time_from_origin_min INTEGER     NOT NULL,
    is_stop                     BOOLEAN     NOT NULL, -- TRUE if stopping, FALSE if passing
    PRIMARY KEY (schedule_id, station_id)
);

-- 12. 國鐵票價費率類別
CREATE TABLE IF NOT EXISTS national_rail_schedule_fares (
    schedule_id       VARCHAR(20)  REFERENCES national_rail_schedules(schedule_id) ON DELETE CASCADE,
    fare_class        VARCHAR(20)  NOT NULL, -- standard, first
    base_fare_usd     NUMERIC(5,2) NOT NULL,
    per_stop_rate_usd NUMERIC(5,2) NOT NULL,
    PRIMARY KEY (schedule_id, fare_class)
);

-- 13. 國鐵班表營運星期
CREATE TABLE IF NOT EXISTS national_rail_schedule_operates (
    schedule_id VARCHAR(20) REFERENCES national_rail_schedules(schedule_id) ON DELETE CASCADE,
    day_of_week VARCHAR(3)  NOT NULL,
    PRIMARY KEY (schedule_id, day_of_week)
);

-- 17. 註冊使用者表 (支援帳號去識別化與軟刪除安全機制)
CREATE TABLE IF NOT EXISTS registered_users (
    user_id         UUID         PRIMARY KEY,
    full_name       VARCHAR(100), -- 允許為 NULL，以支援去識別化 (Anonymization)
    email           VARCHAR(100) UNIQUE, -- 允許為 NULL，PostgreSQL 支援多個 NULL 共存且不視為衝突
    phone           VARCHAR(20),  -- 允許為 NULL
    date_of_birth   DATE,         -- 允許為 NULL
    registered_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ  DEFAULT NULL, -- 記錄邏輯刪除的時間 (軟刪除審計，users)
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE
);

-- 17.5 使用者認證與憑證表 (獨立儲存 Argon2id 密碼雜湊及密保問答，支援軟刪除)
CREATE TABLE IF NOT EXISTS user_credentials (
    user_id         UUID         PRIMARY KEY REFERENCES registered_users(user_id) ON DELETE CASCADE,
    password_hash   VARCHAR(255) NOT NULL, -- 夠長以容納 Argon2id 的雜湊輸出
    secret_question VARCHAR(250) NOT NULL,
    secret_answer   VARCHAR(250) NOT NULL,
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ  DEFAULT NULL -- 支援軟刪除 (credentials)
);

-- 18. 國鐵預訂紀錄 (支援軟刪除)
CREATE TABLE IF NOT EXISTS national_rail_bookings (
    booking_id             VARCHAR(15)  PRIMARY KEY, -- e.g. BK-XXXXXX
    user_id                UUID         REFERENCES registered_users(user_id),
    schedule_id            VARCHAR(20)  REFERENCES national_rail_schedules(schedule_id),
    origin_station_id      VARCHAR(10)  REFERENCES national_rail_stations(station_id),
    destination_station_id VARCHAR(10)  REFERENCES national_rail_stations(station_id),
    travel_date            DATE         NOT NULL,
    departure_time         TIME         NOT NULL,
    ticket_type            VARCHAR(20)  NOT NULL,
    fare_class             VARCHAR(20)  NOT NULL,
    coach                  VARCHAR(2)   NOT NULL,
    seat_id                VARCHAR(10)  NOT NULL,
    stops_travelled        INTEGER      NOT NULL,
    amount_usd             NUMERIC(6,2) NOT NULL,
    status                 VARCHAR(20)  NOT NULL,
    booked_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    travelled_at           TIMESTAMPTZ,
    deleted_at             TIMESTAMPTZ  DEFAULT NULL -- 支援軟刪除 (bookings)
);

-- 19. 捷運乘車歷史 (支援軟刪除)
CREATE TABLE IF NOT EXISTS metro_travel_history (
    trip_id                VARCHAR(15)  PRIMARY KEY, -- e.g. MT001
    user_id                UUID         REFERENCES registered_users(user_id),
    schedule_id            VARCHAR(20)  REFERENCES metro_schedules(schedule_id),
    origin_station_id      VARCHAR(10)  REFERENCES metro_stations(station_id),
    destination_station_id VARCHAR(10)  REFERENCES metro_stations(station_id),
    travel_date            DATE         NOT NULL,
    ticket_type            VARCHAR(20)  NOT NULL,
    day_pass_ref           VARCHAR(15)  REFERENCES metro_travel_history(trip_id),
    stops_travelled        INTEGER,
    amount_usd             NUMERIC(5,2) NOT NULL,
    status                 VARCHAR(20)  NOT NULL,
    purchased_at           TIMESTAMPTZ,
    travelled_at           TIMESTAMPTZ,
    deleted_at             TIMESTAMPTZ  DEFAULT NULL -- 支援軟刪除 (history)
);

-- 20. 付款紀錄 (嚴謹的雙外鍵 + CHECK 約束設計，支援軟刪除)
CREATE TABLE IF NOT EXISTS payments (
    payment_id          VARCHAR(15)  PRIMARY KEY,
    national_booking_id VARCHAR(15)  REFERENCES national_rail_bookings(booking_id) ON DELETE SET NULL,
    metro_trip_id       VARCHAR(15)  REFERENCES metro_travel_history(trip_id) ON DELETE SET NULL,
    amount_usd          NUMERIC(6,2) NOT NULL,
    method              VARCHAR(20)  NOT NULL,
    status              VARCHAR(20)  NOT NULL,
    paid_at             TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    deleted_at          TIMESTAMPTZ  DEFAULT NULL, -- 支援軟刪除 (payments)
    CONSTRAINT check_polymorphic_payment CHECK (
        (national_booking_id IS NOT NULL AND metro_trip_id IS NULL) OR
        (national_booking_id IS NULL AND metro_trip_id IS NOT NULL)
    )
);

-- 21. 乘車回饋 (嚴謹的雙外鍵 + CHECK 約束設計，支援軟刪除)
CREATE TABLE IF NOT EXISTS feedback (
    feedback_id         VARCHAR(15)  PRIMARY KEY,
    national_booking_id VARCHAR(15)  REFERENCES national_rail_bookings(booking_id) ON DELETE SET NULL,
    metro_trip_id       VARCHAR(15)  REFERENCES metro_travel_history(trip_id) ON DELETE SET NULL,
    user_id             UUID         REFERENCES registered_users(user_id),
    rating              INTEGER      NOT NULL CHECK (rating >= 1 AND rating <= 5),
    comment             TEXT,
    submitted_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    deleted_at          TIMESTAMPTZ  DEFAULT NULL, -- 支援軟刪除 (feedback)
    CONSTRAINT check_polymorphic_feedback CHECK (
        (national_booking_id IS NOT NULL AND metro_trip_id IS NULL) OR
        (national_booking_id IS NULL AND metro_trip_id IS NOT NULL)
    )
);




-- ============================================================
--  PERFORMANCE INDEXES (優化常規查詢與外鍵關聯搜尋)
-- ============================================================

-- 1. 優化使用者預訂歷史與可用性查詢
CREATE INDEX IF NOT EXISTS idx_bookings_user_id ON national_rail_bookings (user_id);
CREATE INDEX IF NOT EXISTS idx_bookings_schedule_date ON national_rail_bookings (schedule_id, travel_date);

-- 2. 優化捷運搭乘歷史查詢
CREATE INDEX IF NOT EXISTS idx_metro_travel_user_id ON metro_travel_history (user_id);

-- 3. 優化支付記錄多型外鍵查詢
CREATE INDEX IF NOT EXISTS idx_payments_national_booking ON payments (national_booking_id);
CREATE INDEX IF NOT EXISTS idx_payments_metro_trip ON payments (metro_trip_id);

-- 4. 優化乘車回饋多型外鍵與使用者查詢
CREATE INDEX IF NOT EXISTS idx_feedback_user_id ON feedback (user_id);
CREATE INDEX IF NOT EXISTS idx_feedback_national_booking ON feedback (national_booking_id);
CREATE INDEX IF NOT EXISTS idx_feedback_metro_trip ON feedback (metro_trip_id);

-- 5. 優化捷運與國鐵班表站點快速過濾
CREATE INDEX IF NOT EXISTS idx_metro_schedule_stops_station ON metro_schedule_stops (station_id);
CREATE INDEX IF NOT EXISTS idx_national_rail_schedule_stops_station ON national_rail_schedule_stops (station_id);




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
CREATE INDEX IF NOT EXISTS policy_documents_hnsw_idx ON policy_documents USING hnsw (embedding vector_cosine_ops);

