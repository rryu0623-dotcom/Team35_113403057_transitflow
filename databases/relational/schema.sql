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

-- 清理舊表
DROP TABLE IF EXISTS feedback CASCADE;
DROP TABLE IF EXISTS payments CASCADE;
DROP TABLE IF EXISTS metro_travel_history CASCADE;
DROP TABLE IF EXISTS national_rail_bookings CASCADE;
DROP TABLE IF EXISTS user_credentials CASCADE;
DROP TABLE IF EXISTS registered_users CASCADE;
DROP TABLE IF EXISTS station_interchanges CASCADE;
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
DROP TABLE IF EXISTS metro_passes CASCADE; 

-- 1. 捷運車站主表
CREATE TABLE metro_stations (
    station_id                   VARCHAR(10)  PRIMARY KEY,
    name                         VARCHAR(100) NOT NULL,
    is_interchange_metro         BOOLEAN      NOT NULL,
    is_interchange_national_rail BOOLEAN      NOT NULL,
    deleted_at                   TIMESTAMPTZ  DEFAULT NULL,
    is_active                    BOOLEAN      NOT NULL DEFAULT TRUE
);

-- 2. 捷運車站所屬路線
CREATE TABLE metro_station_lines (
    station_id VARCHAR(10) REFERENCES metro_stations(station_id) ON DELETE CASCADE,
    line       VARCHAR(10) NOT NULL,
    PRIMARY KEY (station_id, line)
);

-- 3. 捷運相鄰車站與行車時間
CREATE TABLE metro_station_adjacents (
    station_id          VARCHAR(10) REFERENCES metro_stations(station_id) ON DELETE CASCADE,
    adjacent_station_id VARCHAR(10) REFERENCES metro_stations(station_id) ON DELETE CASCADE,
    line                VARCHAR(10) NOT NULL,
    travel_time_min     INTEGER     NOT NULL,
    PRIMARY KEY (station_id, adjacent_station_id, line)
);

-- 4. 國鐵車站主表
CREATE TABLE national_rail_stations (
    station_id                   VARCHAR(10)  PRIMARY KEY,
    name                         VARCHAR(100) NOT NULL,
    is_interchange_national_rail BOOLEAN      NOT NULL,
    is_interchange_metro         BOOLEAN      NOT NULL,
    deleted_at                   TIMESTAMPTZ  DEFAULT NULL,
    is_active                    BOOLEAN      NOT NULL DEFAULT TRUE
);

-- 5. 國鐵車站所屬路線
CREATE TABLE national_rail_station_lines (
    station_id VARCHAR(10) REFERENCES national_rail_stations(station_id) ON DELETE CASCADE,
    line       VARCHAR(10) NOT NULL,
    PRIMARY KEY (station_id, line)
);

-- 6. 國鐵相鄰車站與行車時間
CREATE TABLE national_rail_station_adjacents (
    station_id          VARCHAR(10) REFERENCES national_rail_stations(station_id) ON DELETE CASCADE,
    adjacent_station_id VARCHAR(10) REFERENCES national_rail_stations(station_id) ON DELETE CASCADE,
    line                VARCHAR(10) NOT NULL,
    travel_time_min     INTEGER     NOT NULL,
    PRIMARY KEY (station_id, adjacent_station_id, line)
);

-- 6.5 跨網車站轉乘關係表
CREATE TABLE station_interchanges (
    metro_station_id         VARCHAR(10) REFERENCES metro_stations(station_id) ON DELETE CASCADE,
    national_rail_station_id VARCHAR(10) REFERENCES national_rail_stations(station_id) ON DELETE CASCADE,
    transfer_time_min        INTEGER     NOT NULL DEFAULT 5,
    PRIMARY KEY (metro_station_id, national_rail_station_id)
);

-- 7. 捷運營運班表主表
CREATE TABLE metro_schedules (
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
    deleted_at             TIMESTAMPTZ  DEFAULT NULL,
    is_active              BOOLEAN      NOT NULL DEFAULT TRUE
);

-- 8. 捷運班表停靠站順序
CREATE TABLE metro_schedule_stops (
    schedule_id                 VARCHAR(20) REFERENCES metro_schedules(schedule_id) ON DELETE CASCADE,
    station_id                  VARCHAR(10) REFERENCES metro_stations(station_id),
    stop_order                  INTEGER     NOT NULL,
    travel_time_from_origin_min INTEGER     NOT NULL,
    PRIMARY KEY (schedule_id, station_id)
);

-- 9. 捷運班表營運星期
CREATE TABLE metro_schedule_operates (
    schedule_id VARCHAR(20) REFERENCES metro_schedules(schedule_id) ON DELETE CASCADE,
    day_of_week SMALLINT    NOT NULL CHECK (day_of_week BETWEEN 1 AND 7), 
    PRIMARY KEY (schedule_id, day_of_week)
);

-- 10. 國鐵營運班表主表
CREATE TABLE national_rail_schedules (
    schedule_id            VARCHAR(20) PRIMARY KEY,
    line                   VARCHAR(10) NOT NULL,
    service_type           VARCHAR(20) NOT NULL, 
    direction              VARCHAR(20) NOT NULL,
    origin_station_id      VARCHAR(10) REFERENCES national_rail_stations(station_id),
    destination_station_id VARCHAR(10) REFERENCES national_rail_stations(station_id),
    first_train_time       TIME        NOT NULL,
    last_train_time        TIME        NOT NULL,
    frequency_min          INTEGER     NOT NULL,
    deleted_at             TIMESTAMPTZ DEFAULT NULL,
    is_active              BOOLEAN     NOT NULL DEFAULT TRUE
);

-- 11. 國鐵班表停靠/通過車站
CREATE TABLE national_rail_schedule_stops (
    schedule_id                 VARCHAR(20) REFERENCES national_rail_schedules(schedule_id) ON DELETE CASCADE,
    station_id                  VARCHAR(10) REFERENCES national_rail_stations(station_id),
    stop_order                  INTEGER     NOT NULL,
    travel_time_from_origin_min INTEGER     NOT NULL,
    is_stop                     BOOLEAN     NOT NULL,
    PRIMARY KEY (schedule_id, station_id)
);

-- 12. 國鐵票價費率類別
CREATE TABLE national_rail_schedule_fares (
    schedule_id       VARCHAR(20)  REFERENCES national_rail_schedules(schedule_id) ON DELETE CASCADE,
    fare_class        VARCHAR(20)  NOT NULL, 
    base_fare_usd     NUMERIC(5,2) NOT NULL,
    per_stop_rate_usd NUMERIC(5,2) NOT NULL,
    PRIMARY KEY (schedule_id, fare_class)
);

-- 13. 國鐵班表營運星期
CREATE TABLE national_rail_schedule_operates (
    schedule_id VARCHAR(20) REFERENCES national_rail_schedules(schedule_id) ON DELETE CASCADE,
    day_of_week SMALLINT    NOT NULL CHECK (day_of_week BETWEEN 1 AND 7),
    PRIMARY KEY (schedule_id, day_of_week)
);

-- 14. 國鐵座位配置主表
CREATE TABLE national_rail_seat_layouts (
    layout_id   VARCHAR(10) PRIMARY KEY,
    schedule_id VARCHAR(20) REFERENCES national_rail_schedules(schedule_id) ON DELETE CASCADE
);

-- 15. 國鐵車廂配置
CREATE TABLE national_rail_coaches (
    layout_id  VARCHAR(10) REFERENCES national_rail_seat_layouts(layout_id) ON DELETE CASCADE,
    coach      VARCHAR(2)  NOT NULL, 
    fare_class VARCHAR(20) NOT NULL,
    PRIMARY KEY (layout_id, coach)
);

-- 16. 國鐵座位明細
CREATE TABLE national_rail_seats (
    layout_id   VARCHAR(10) NOT NULL,
    coach       VARCHAR(2)  NOT NULL,
    seat_id     VARCHAR(10) NOT NULL,
    row         INTEGER     NOT NULL,
    seat_column VARCHAR(2)  NOT NULL, 
    PRIMARY KEY (layout_id, coach, seat_id),
    FOREIGN KEY (layout_id, coach) REFERENCES national_rail_coaches(layout_id, coach) ON DELETE CASCADE
);

-- 17. 註冊使用者表
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

-- 17.5 使用者認證與憑證表 (修正：密保答案雜湊化，拒絕明文)
CREATE TABLE user_credentials (
    user_id             UUID         PRIMARY KEY REFERENCES registered_users(user_id) ON DELETE CASCADE,
    password_hash       VARCHAR(255) NOT NULL, 
    secret_question     VARCHAR(250) NOT NULL,
    secret_answer_hash  VARCHAR(255) NOT NULL, -- 修正點
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    deleted_at          TIMESTAMPTZ  DEFAULT NULL 
);

-- 18. 國鐵預訂紀錄 (修正：移除 schedules 外鍵強連動，改用應用程式維護；冗餘儲存車站名快照；加大金額)
CREATE TABLE national_rail_bookings (
    booking_id             VARCHAR(15)  PRIMARY KEY, 
    user_id                UUID         REFERENCES registered_users(user_id) ON DELETE RESTRICT, -- 避免硬刪除用戶導致訂單消失
    schedule_id            VARCHAR(20), -- 修正：解耦強外鍵，允許舊班表物理刪除
    origin_station_id      VARCHAR(10), 
    origin_station_name    VARCHAR(100) NOT NULL, -- 修正：快照冗餘，防止車站刪除/改名後對不上帳
    destination_station_id VARCHAR(10), 
    destination_station_name VARCHAR(100) NOT NULL, -- 修正：快照冗餘
    travel_date            DATE         NOT NULL,
    departure_time         TIME         NOT NULL,
    ticket_type            VARCHAR(20)  NOT NULL,
    fare_class             VARCHAR(20)  NOT NULL,
    coach                  VARCHAR(2)   NOT NULL,
    seat_id                VARCHAR(10)  NOT NULL,
    stops_travelled        INTEGER      NOT NULL,
    amount_usd             NUMERIC(10,2) NOT NULL, -- 修正：加大金額長度防止溢位
    status                 VARCHAR(20)  NOT NULL,
    booked_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    travelled_at           TIMESTAMPTZ,
    deleted_at             TIMESTAMPTZ  DEFAULT NULL 
);

-- 18.5 捷運票券主表 (修正：解開捷運乘車歷史的自我循環參照)
CREATE TABLE metro_passes (
    pass_id     VARCHAR(15)  PRIMARY KEY,
    user_id     UUID         REFERENCES registered_users(user_id),
    pass_type   VARCHAR(20)  NOT NULL, -- 'SINGLE', 'DAY_PASS', 'MONTHLY'
    expires_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- 19. 捷運乘車歷史 (修正：解耦 schedules 外鍵；冗餘車站名快照；加大金額)
CREATE TABLE metro_travel_history (
    trip_id                VARCHAR(15)  PRIMARY KEY, 
    user_id                UUID         REFERENCES registered_users(user_id) ON DELETE RESTRICT,
    schedule_id            VARCHAR(20), -- 修正：解耦強外鍵
    origin_station_id      VARCHAR(10), 
    origin_station_name    VARCHAR(100) NOT NULL, -- 修正：快照冗餘
    destination_station_id VARCHAR(10), 
    destination_station_name VARCHAR(100) NOT NULL, -- 修正：快照冗餘
    travel_date            DATE         NOT NULL,
    ticket_type            VARCHAR(20)  NOT NULL,
    pass_id_ref            VARCHAR(15)  REFERENCES metro_passes(pass_id) ON DELETE SET NULL, -- 修正：改引用獨立票券表
    stops_travelled        INTEGER,
    amount_usd             NUMERIC(10,2) NOT NULL, -- 修正：加大金額長度
    status                 VARCHAR(20)  NOT NULL,
    purchased_at           TIMESTAMPTZ,
    travelled_at           TIMESTAMPTZ,
    deleted_at             TIMESTAMPTZ  DEFAULT NULL 
);

-- 20. 付款紀錄 
CREATE TABLE payments (
    payment_id          VARCHAR(15)  PRIMARY KEY,
    national_booking_id VARCHAR(15)  REFERENCES national_rail_bookings(booking_id) ON DELETE SET NULL,
    metro_trip_id       VARCHAR(15)  REFERENCES metro_travel_history(trip_id) ON DELETE SET NULL,
    amount_usd          NUMERIC(10,2) NOT NULL, 
    method              VARCHAR(20)  NOT NULL,
    status              VARCHAR(20)  NOT NULL,
    paid_at             TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    deleted_at          TIMESTAMPTZ  DEFAULT NULL, 
    CONSTRAINT check_polymorphic_payment CHECK (
        (national_booking_id IS NOT NULL AND metro_trip_id IS NULL) OR
        (national_booking_id IS NULL AND metro_trip_id IS NOT NULL)
    )
);

-- 21. 乘車回饋
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
--                     高效能高速索引區
-- ============================================================

-- 優化使用者個人歷史紀錄/訂單查詢 (最頻繁使用的網路 I/O 查詢)
CREATE INDEX idx_nr_bookings_user_date ON national_rail_bookings (user_id, travel_date) WHERE deleted_at IS NULL;
CREATE INDEX idx_metro_history_user_date ON metro_travel_history (user_id, travel_date) WHERE deleted_at IS NULL;

-- 優化前台使用者「依據路線、服務類型」搜尋當日班表
CREATE INDEX idx_metro_sched_search ON metro_schedules (line, is_active);
CREATE INDEX idx_nr_sched_search ON national_rail_schedules (line, service_type, is_active);

-- 部分索引 (Partial Indexes)：大幅縮小多型關聯表的反查索引體積，提升快取命中率
CREATE INDEX idx_payments_booking_uid ON payments (national_booking_id) WHERE national_booking_id IS NOT NULL;
CREATE INDEX idx_payments_metro_uid ON payments (metro_trip_id) WHERE metro_trip_id IS NOT NULL;
CREATE INDEX idx_feedback_booking_uid ON feedback (national_booking_id) WHERE national_booking_id IS NOT NULL;
CREATE INDEX idx_feedback_metro_uid ON feedback (metro_trip_id) WHERE metro_trip_id IS NOT NULL;

-- 優化後台轉乘/路徑規劃演算法（Dijkstra/A* 搜尋時的核心關聯欄位）
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
CREATE INDEX IF NOT EXISTS ON policy_documents USING hnsw (embedding vector_cosine_ops);
