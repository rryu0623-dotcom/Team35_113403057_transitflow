# TransitFlow System Design Documentation

---

## Section 7: Task 6 Option Extension

### 7.1 Motivation and Overview
In a real-world transit network, passengers and operators need tools to adapt to real-time service disruptions, query precise station timetables, and monitor system health. To resolve these operational requirements, we designed and implemented four key enhancements:
1. **Custom Departure Time Booking**: Allows passengers to specify their preferred hour/minute (HH:MM) when booking a ticket, rather than relying on a single daily default train, keeping booking records accurate.
2. **Real-time Service Alerts**: Tracks active operator disruptions (maintenance, signaling issues, severe delays) to warn users about delay ripple effects.
3. **Dynamic Station Departures**: Computes real-time schedules for any metro or national rail station, calculating departures throughout the day using line frequencies, offsets, and start times.
4. **Operations Analytics Dashboard**: Provides transit administrators with high-level aggregates (revenue split, busiest origin hubs, passenger ratings, payment breakdown) to monitor system performance.

---

### 7.2 Database Schema DDL Modifications
We added the `operator_alerts` table and modified `national_rail_bookings` to include a dynamic `departure_time` parameter:

```sql
-- DDL for Operator Alerts Table
CREATE TABLE operator_alerts (
    alert_id      VARCHAR(10)  PRIMARY KEY,
    line          VARCHAR(10),
    station_id    VARCHAR(10),
    severity      VARCHAR(20)  NOT NULL, -- 'low', 'medium', 'high'
    message       TEXT         NOT NULL,
    created_at    TIMESTAMPTZ  DEFAULT NOW(),
    is_active     BOOLEAN      DEFAULT TRUE
);

-- Column modification in bookings to store actual departure time (DDL snapshot)
CREATE TABLE national_rail_bookings (
    booking_id             VARCHAR(15)  PRIMARY KEY, 
    user_id                UUID         REFERENCES registered_users(user_id) ON DELETE RESTRICT,
    schedule_id            VARCHAR(20), 
    origin_station_id      VARCHAR(10), 
    origin_station_name    VARCHAR(100) NOT NULL,
    destination_station_id VARCHAR(10), 
    destination_station_name VARCHAR(100) NOT NULL,
    travel_date            DATE         NOT NULL,
    departure_time         TIME         NOT NULL,  -- Custom departure time support
    ticket_type            rail_ticket_type  NOT NULL,
    fare_class             fare_class  NOT NULL,
    coach                  VARCHAR(2)   NOT NULL,
    seat_id                VARCHAR(10)  NOT NULL,
    stops_travelled        INTEGER      NOT NULL,
    amount_usd             NUMERIC(10,2) NOT NULL,
    status                 booking_status  NOT NULL,
    booked_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    travelled_at           TIMESTAMPTZ,
    deleted_at             TIMESTAMPTZ  DEFAULT NULL 
);
```

---

### 7.3 Advanced Query Designs
The queries are implemented in [databases/relational/queries.py](file:///c:/Users/tim06/IM2002-DBMGT-Train-final/databases/relational/queries.py):

#### 1. Active Operator Alerts Query
```sql
SELECT alert_id, line, station_id, severity, message, created_at::text, is_active
FROM operator_alerts
WHERE is_active = TRUE
ORDER BY severity = 'high' DESC, severity = 'medium' DESC, created_at DESC;
```
*Rationale*: Prioritizes severe ('high') warnings first so that passengers see critical service disruptions immediately.

#### 2. Station Departures Timetable Generator
This query retrieves all active metro and rail schedules that pass through a specific station, calculates the arrival offset in minutes based on the station's index in the route, and loops from `first_train_time` to `last_train_time` incremented by the line's operating `frequency_min` to generate the complete daily schedule for the station.

#### 3. Transit Operations Analytics Dashboard
```sql
-- Query revenue and counts for National Rail and Metro
SELECT COUNT(*) AS count, SUM(amount_usd)::float AS revenue FROM national_rail_bookings WHERE status != 'cancelled';
SELECT COUNT(*) AS count, SUM(amount_usd)::float AS revenue FROM metro_travel_history WHERE status != 'cancelled';

-- Payment method split
SELECT method, COUNT(*) AS count, SUM(amount_usd)::float AS revenue
FROM payments
WHERE status = 'paid'
GROUP BY method;

-- Busiest stations
SELECT origin_station_name, COUNT(*) AS passenger_count
FROM national_rail_bookings
WHERE status != 'cancelled'
GROUP BY origin_station_name
ORDER BY passenger_count DESC
LIMIT 3;

-- Average User Rating
SELECT AVG(rating)::float AS avg_rating, COUNT(*) AS total_feedbacks FROM feedback;
```

---

### 7.4 Gradio UI Layout and Design
We restructured the frontend to expose these Task 6 queries as responsive, interactive tabs and styled them with a custom CSS theme:
1. **Glassmorphism Alert Cards**: Active alerts are color-coded (red, yellow, blue) using CSS borders and translucent backgrounds to grab attention instantly without looking cluttered.
2. **Dynamic Timetables Markdown**: Dynamic departure results are formatted in clean Markdown tables with bold timestamps.
3. **KPI Operational Cards**: Key system metrics (System Revenue, Rail Bookings, Metro Trips, Avg Rating) are styled as card grids with custom scaling transitions on hover.
4. **HTML Banners**: Replaced standard headers with a modern linear-gradient banner styling.

---

### 7.5 Verification and Testing
Automated seeder execution runs successfully and populates mock data:

```
Connecting to PostgreSQL...
Seeding tables (dependency order):
- Metro stations...
  metro_stations seeded: 20 stations, 25 lines mapping, 42 adjacencies
- National rail stations...
  national_rail_stations seeded: 10 stations, 11 lines mapping, 18 adjacencies, 3 cross-network interchanges
- Metro schedules...
  metro_schedules seeded: 8 schedules (JSONB stops/operates embedded)
  national_rail_schedules seeded: 8 schedules, 16 class fares (JSONB stops/operates embedded)
  seat_layouts templates seeded: 4 layouts, 8 coaches, 72 seats
- Users...
  registered_users & credentials seeded: 20 users (mapped with secure random UUIDs)
- Bookings...
  national_rail_bookings seeded: 20 records
- Metro travels...
  metro_passes seeded: 5 records
  metro_travel_history seeded: 24 records
- Payments...
  payments seeded: 40 polymorphic records
- Feedback...
  feedback seeded: 30 polymorphic records
- Operator Alerts (Task 6)...
  operator_alerts seeded: 3 alerts

All done. Database seeded successfully.
```

The AI agent has been validated and robustly parses natural language query intents, routing them to the correct databases even in the presence of Ollama JSON schema hallucinations. All UI components have been verified via a headless browser subagent session, logging no errors and updating values dynamically upon clicking refresh and dropdown selections.

