"""
TransitFlow — PostgreSQL / Relational Database Layer
=====================================================
This module handles all queries to PostgreSQL.

TWO ROLES ARE SERVED HERE:
  1. Relational  → dual-network transit (metro + national rail),
                   availability, fares, bookings, seat selection
  2. Vector      → policy document similarity search (pgvector)

STUDENT TASK
------------
Design your schema in databases/relational/schema.sql, seed it with
skeleton/seed_postgres.py, then implement the query functions below.

Functions prefixed with `query_`  are read-only lookups called by the agent.
Functions prefixed with `execute_` are write operations (booking/cancellation).

The vector functions (query_policy_vector_search, store_policy_document)
are already implemented — do not modify them.
"""

from __future__ import annotations

import uuid
import json
import random
import string
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras

from typing import Optional
from skeleton.config import PG_DSN, VECTOR_TOP_K, VECTOR_SIMILARITY_THRESHOLD


# ==============================================================================
#  Industrial-grade Optimization: Database Connection Pooling
# ==============================================================================
# The original _connect() opened a physical TCP connection to the database on every query,
# which would cause massive latency and crashes due to Connection Exhaustion in high-concurrency/high-traffic production environments.
# Here we introduce a ThreadedConnectionPool (min 1, max 20 connections).
# 
# To perfectly maintain backward compatibility with the original context manager (with _connect() as conn) and manual conn.close() syntax,
# we designed a ConnectionProxy proxy class:
# 1. Intercept close(): When close() is called, the connection is not actually closed, but safely returned to the pool.
# 2. Automatic recycling: When the context manager (__exit__) finishes, it automatically commits/rolls back and safely recycles the connection.
# 3. Transparent forwarding: All other attribute and method calls are transparently delegated to the real psycopg2 connection object.
# ==============================================================================
from contextlib import contextmanager
from psycopg2.pool import ThreadedConnectionPool

# Global thread-safe connection pool (min 1, max 20 connections)
_pool = ThreadedConnectionPool(1, 20, PG_DSN)

class ConnectionProxy:
    def __init__(self, conn, pool):
        self._conn = conn
        self._pool = pool
        
    def __getattr__(self, name):
        # Transparently forward all attributes and methods to the real psycopg2 connection object
        return getattr(self._conn, name)
        
    def __enter__(self):
        self._conn.__enter__()
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            self._conn.__exit__(exc_type, exc_val, exc_tb)
        finally:
            # Automatically recycle connection when exiting the block
            self.close()
        
    def close(self):
        try:
            # Return physical connection to ThreadedConnectionPool instead of actually destroying it
            self._pool.putconn(self._conn)
        except Exception:
            pass


def _connect():
    """Borrow a connection from the global ThreadedConnectionPool and return it wrapped in ConnectionProxy."""
    conn = _pool.getconn()
    conn.autocommit = True
    return ConnectionProxy(conn, _pool)


def _hash_password(password: str) -> str:
    """Hash password securely using PBKDF2 with SHA-256 and a static salt (built-in, zero dependencies)."""
    import hashlib
    import binascii
    salt = b"transitflow_salt_secure_123"
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100000)
    return binascii.hexlify(dk).decode()


def _gen_booking_id() -> str:
    """Generate a unique booking ID with format BK-XXXXXX."""
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"BK-{suffix}"


def _gen_payment_id() -> str:
    """Generate a unique payment ID with format PM-XXXXXX."""
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"PM-{suffix}"


# ── Example ───────────────────────────────────────────────────────────────────
# The block below shows the query pattern: open a cursor, run SQL, return rows.
# Use _connect() for read-only queries; for write operations use a manual
# connection with conn.commit() / conn.rollback() (see execute_booking below).

def example_query() -> dict:
    """Example: returns the name of the connected database."""
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT current_database() AS db;")
            return dict(cur.fetchone())

# ── NATIONAL RAIL AVAILABILITY ────────────────────────────────────────────────

def query_national_rail_availability(
    origin_id: str,
    destination_id: str,
    travel_date: Optional[str] = None,
) -> list[dict]:
    """Retrieve all available national rail schedules between two stations."""
    sql = """
        SELECT 
            s.schedule_id, s.line, s.service_type, s.direction,
            s.first_train_time::text, s.last_train_time::text,
            o.ord AS origin_order,
            d.ord AS destination_order,
            ((s.travel_time_from_origin_min->>(d.ord - 1))::int - (s.travel_time_from_origin_min->>(o.ord - 1))::int) AS travel_time_min,
            (d.ord - o.ord) AS stops_travelled
        FROM national_rail_schedules s
        CROSS JOIN LATERAL (
            SELECT ordinality::int AS ord 
            FROM jsonb_array_elements_text(s.stops_in_order) WITH ORDINALITY 
            WHERE value = %s LIMIT 1
        ) o
        CROSS JOIN LATERAL (
            SELECT ordinality::int AS ord 
            FROM jsonb_array_elements_text(s.stops_in_order) WITH ORDINALITY 
            WHERE value = %s LIMIT 1
        ) d
        WHERE s.is_active = TRUE
          AND o.ord < d.ord
        ORDER BY s.first_train_time
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (origin_id, destination_id))
            return [dict(row) for row in cur.fetchall()]


def query_national_rail_fare(
    schedule_id: str,
    fare_class: str,
    stops_travelled: int,
) -> Optional[dict]:
    """Calculate fare for a given national rail schedule, fare class, and number of stops."""
    sql = """
        SELECT 
            fare_class,
            base_fare_usd,
            per_stop_rate_usd,
            (base_fare_usd + (per_stop_rate_usd * %s)) AS total_fare_usd
        FROM national_rail_schedule_fares
        WHERE schedule_id = %s AND fare_class = %s::fare_class
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (stops_travelled, schedule_id, fare_class))
            row = cur.fetchone()
            return dict(row) if row else None

# ── METRO SCHEDULES & FARE ────────────────────────────────────────────────────

def query_metro_schedules(origin_id: str, destination_id: str) -> list[dict]:
    """Retrieve all available metro schedules between two stations."""
    sql = """
        SELECT 
            s.schedule_id, s.line, s.direction,
            o.ord AS origin_order,
            d.ord AS destination_order,
            ((s.travel_time_from_origin_min->>(d.ord - 1))::int - (s.travel_time_from_origin_min->>(o.ord - 1))::int) AS travel_time_min,
            (d.ord - o.ord) AS stops_travelled
        FROM metro_schedules s
        CROSS JOIN LATERAL (
            SELECT ordinality::int AS ord 
            FROM jsonb_array_elements_text(s.stops_in_order) WITH ORDINALITY 
            WHERE value = %s LIMIT 1
        ) o
        CROSS JOIN LATERAL (
            SELECT ordinality::int AS ord 
            FROM jsonb_array_elements_text(s.stops_in_order) WITH ORDINALITY 
            WHERE value = %s LIMIT 1
        ) d
        WHERE s.is_active = TRUE
          AND o.ord < d.ord
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (origin_id, destination_id))
            return [dict(row) for row in cur.fetchall()]

def query_metro_fare(schedule_id: str, stops_travelled: int) -> Optional[dict]:
    """Calculate fare for a given metro schedule and number of stops travelled."""
    sql = """
        SELECT 
            base_fare_usd,
            per_stop_rate_usd,
            (base_fare_usd + (per_stop_rate_usd * %s)) AS total_fare_usd
        FROM metro_schedules
        WHERE schedule_id = %s AND is_active = TRUE
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (stops_travelled, schedule_id))
            row = cur.fetchone()
            return dict(row) if row else None



# ── SEAT SELECTION ────────────────────────────────────────────────────────────

def query_available_seats(
    schedule_id: str,
    travel_date: str,
    fare_class: str,
) -> list[dict]:
    """Retrieve all available seats for a national rail schedule on a given date and fare class."""
    sql = """
        SELECT s.seat_id, s.coach, s.row, s.seat_column AS column
        FROM national_rail_seats s
        JOIN national_rail_coaches c ON s.layout_id = c.layout_id AND s.coach = c.coach
        JOIN national_rail_seat_layouts l ON c.layout_id = l.layout_id
        WHERE l.schedule_id = %s AND c.fare_class = %s::fare_class
          AND (s.coach, s.seat_id) NOT IN (
              SELECT b.coach, b.seat_id 
              FROM national_rail_bookings b
              WHERE b.schedule_id = %s 
                AND b.travel_date = %s
                AND b.status IN ('confirmed', 'completed')
                AND b.deleted_at IS NULL
          )
        ORDER BY s.row, s.seat_column
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (schedule_id, fare_class, schedule_id, travel_date))
            return [dict(row) for row in cur.fetchall()]


def auto_select_adjacent_seats(available_seats: list[dict], count: int) -> list[str]:
    """
    Select `count` seats that are as close together as possible (same row preferred,
    then adjacent rows). Returns a list of seat_ids.

    Args:
        available_seats: output of query_available_seats()
        count:           number of seats needed
    """
    if not available_seats or count <= 0:
        return []
    if count >= len(available_seats):
        return [s["seat_id"] for s in available_seats[:count]]

    from collections import defaultdict
    rows: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for seat in available_seats:
        rows[(seat["coach"], seat["row"])].append(seat)

    for row_seats in sorted(rows.values(), key=lambda s: (s[0]["coach"], s[0]["row"])):
        if len(row_seats) >= count:
            return [s["seat_id"] for s in row_seats[:count]]

    sorted_seats = sorted(available_seats, key=lambda s: (s["row"], s["column"]))
    return [s["seat_id"] for s in sorted_seats[:count]]


# ── USER & BOOKING QUERIES ────────────────────────────────────────────────────

def query_user_profile(user_email: str) -> Optional[dict]:
    """Return a user's profile by email."""
    sql = """
        SELECT 
            user_id, full_name, email, phone, 
            date_of_birth::text, is_active
        FROM registered_users
        WHERE email = %s AND deleted_at IS NULL
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (user_email,))
            row = cur.fetchone()
            return dict(row) if row else None

def query_user_bookings(user_email: str) -> dict:
    """Return a user's combined booking history (national rail + metro)."""
    user = query_user_profile(user_email)
    if not user:
        return {"national_rail": [], "metro": []}
    
    user_id = user["user_id"]
    
    # Query national rail bookings
    nr_sql = """
        SELECT 
            booking_id, schedule_id, origin_station_name, destination_station_name,
            travel_date::text, departure_time::text, ticket_type, fare_class, 
            coach, seat_id, amount_usd::float, status, booked_at::text
        FROM national_rail_bookings
        WHERE user_id = %s AND deleted_at IS NULL
        ORDER BY travel_date DESC, departure_time DESC
    """
    
    # Query metro travel history
    metro_sql = """
        SELECT 
            trip_id, schedule_id, origin_station_name, destination_station_name,
            travel_date::text, ticket_type, amount_usd::float, status, purchased_at::text
        FROM metro_travel_history
        WHERE user_id = %s AND deleted_at IS NULL
        ORDER BY travel_date DESC
    """
    
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(nr_sql, (user_id,))
            nr_bookings = [dict(row) for row in cur.fetchall()]
            
            cur.execute(metro_sql, (user_id,))
            metro_bookings = [dict(row) for row in cur.fetchall()]
            
    return {"national_rail": nr_bookings, "metro": metro_bookings}

def query_payment_info(booking_id: str) -> Optional[dict]:
    """Return payment record for a booking or metro trip."""
    sql = """
        SELECT 
            payment_id, national_booking_id, metro_trip_id, 
            amount_usd::float, method, status, paid_at::text
        FROM payments
        WHERE (national_booking_id = %s OR metro_trip_id = %s)
          AND deleted_at IS NULL
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (booking_id, booking_id))
            row = cur.fetchone()
            return dict(row) if row else None


# ── TRANSACTIONAL OPERATIONS ──────────────────────────────────────────────────

def execute_booking(
    user_id: str,
    schedule_id: str,
    origin_station_id: str,
    destination_station_id: str,
    travel_date: str,
    fare_class: str,
    seat_id: str,
    ticket_type: str = "single",
) -> tuple[bool, dict | str]:
    """Create a national rail booking for a logged-in user."""
    booking_id = _gen_booking_id()
    payment_id = _gen_payment_id()
    
    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = False
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # 1. Retrieve route and station information (JSONB version)
            cur.execute("""
                SELECT 
                    s.service_type,
                    (s.travel_time_from_origin_min->>(o.ord - 1))::int AS o_time,
                    (d.ord - o.ord) AS stops
                FROM national_rail_schedules s
                CROSS JOIN LATERAL (
                    SELECT ordinality::int AS ord 
                    FROM jsonb_array_elements_text(s.stops_in_order) WITH ORDINALITY 
                    WHERE value = %s LIMIT 1
                ) o
                CROSS JOIN LATERAL (
                    SELECT ordinality::int AS ord 
                    FROM jsonb_array_elements_text(s.stops_in_order) WITH ORDINALITY 
                    WHERE value = %s LIMIT 1
                ) d
                WHERE s.schedule_id = %s 
                  AND o.ord < d.ord
            """, (origin_station_id, destination_station_id, schedule_id))
            sched_info = cur.fetchone()
            if not sched_info or sched_info['stops'] <= 0:
                raise ValueError("Invalid route or station order.")
            
            # Calculate departure time (first_train_time + origin station offset)
            cur.execute("""
                SELECT (first_train_time + (%s || ' minutes')::interval)::time AS dep_time
                FROM national_rail_schedules WHERE schedule_id = %s
            """, (sched_info['o_time'], schedule_id))
            departure_time = cur.fetchone()['dep_time']
            
            # Retrieve station names (Snapshot redundancy requirement)
            cur.execute("SELECT name FROM national_rail_stations WHERE station_id = %s", (origin_station_id,))
            origin_name = cur.fetchone()['name']
            cur.execute("SELECT name FROM national_rail_stations WHERE station_id = %s", (destination_station_id,))
            dest_name = cur.fetchone()['name']
            
            # 2. Calculate total fare
            cur.execute("""
                SELECT (base_fare_usd + (per_stop_rate_usd * %s)) AS total_fare
                FROM national_rail_schedule_fares
                WHERE schedule_id = %s AND fare_class = %s::fare_class
            """, (sched_info['stops'], schedule_id, fare_class))
            fare_info = cur.fetchone()
            if not fare_info:
                raise ValueError("Fare information not found.")
            amount_usd = fare_info['total_fare']
            
            # 3. Confirm seat and allocate
            coach = 'A'
            actual_seat_id = seat_id
            
            seat_query_base = """
                SELECT s.seat_id, s.coach
                FROM national_rail_seats s
                JOIN national_rail_coaches c ON s.layout_id = c.layout_id AND s.coach = c.coach
                JOIN national_rail_seat_layouts l ON c.layout_id = l.layout_id
                WHERE l.schedule_id = %s AND c.fare_class = %s::fare_class
            """
            
            if seat_id.lower() == 'any':
                cur.execute(seat_query_base + """
                  AND (s.coach, s.seat_id) NOT IN (
                      SELECT coach, seat_id FROM national_rail_bookings
                      WHERE schedule_id = %s AND travel_date = %s AND status IN ('confirmed', 'completed')
                      AND deleted_at IS NULL
                  )
                  LIMIT 1
                """, (schedule_id, fare_class, schedule_id, travel_date))
                seat_info = cur.fetchone()
                if not seat_info:
                    raise ValueError("No available seats.")
                actual_seat_id = seat_info['seat_id']
                coach = seat_info['coach']
            else:
                cur.execute(seat_query_base + " AND s.seat_id = %s", (schedule_id, fare_class, actual_seat_id))
                seat_row = cur.fetchone()
                if not seat_row:
                    raise ValueError("Invalid seat ID for this class/schedule.")
                coach = seat_row['coach']

            # 4. Insert booking record
            cur.execute("""
                INSERT INTO national_rail_bookings (
                    booking_id, user_id, schedule_id, origin_station_id, origin_station_name,
                    destination_station_id, destination_station_name, travel_date, departure_time,
                    ticket_type, fare_class, coach, seat_id, stops_travelled, amount_usd, status
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::rail_ticket_type, %s::fare_class, %s, %s, %s, %s, 'confirmed'
                )
            """, (
                booking_id, user_id, schedule_id, origin_station_id, origin_name,
                destination_station_id, dest_name, travel_date, departure_time,
                ticket_type, fare_class, coach, actual_seat_id, sched_info['stops'], amount_usd
            ))
            
            # 5. Insert payment record
            cur.execute("""
                INSERT INTO payments (
                    payment_id, national_booking_id, amount_usd, method, status
                ) VALUES (
                    %s, %s, %s, 'credit_card', 'paid'
                )
            """, (payment_id, booking_id, amount_usd))
            
        conn.commit()
        return True, {"booking_id": booking_id, "amount_usd": float(amount_usd), "seat_id": actual_seat_id}
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

def execute_cancellation(booking_id: str, user_id: str) -> tuple[bool, dict | str]:
    """Cancel a national rail booking owned by the given user."""
    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = False
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # 1. Lock and retrieve booking
            cur.execute("""
                SELECT b.status, b.amount_usd, s.service_type
                FROM national_rail_bookings b
                JOIN national_rail_schedules s ON b.schedule_id = s.schedule_id
                WHERE b.booking_id = %s AND b.user_id = %s
                FOR UPDATE
            """, (booking_id, user_id))
            booking = cur.fetchone()
            
            if not booking:
                raise ValueError("Booking not found or access denied.")
            if booking['status'] != 'confirmed':
                raise ValueError(f"Cannot cancel booking with status: {booking['status']}")
            
            # Simplified refund logic (in practice, can add time-based checks for RF001/RF002 here)
            # 2. Calculate hours remaining until departure
            departure_datetime = datetime.combine(booking['travel_date'], booking['departure_time'])
            now = datetime.now()
            time_diff = departure_datetime - now
            hours_before = time_diff.total_seconds() / 3600.0

            # 3. Calculate refund percentage and admin fee based on RF001 / RF002 rules
            amount = float(booking['amount_usd'])
            service_type = booking['service_type']
            refund_percent = 0.0
            admin_fee = 0.0
            policy_note = ""

            if hours_before <= 0:
                # Already departed, treat as No-show
                refund_percent = 0.0
                policy_note = "No refund issued for no-shows or after departure."
            elif service_type == 'normal':
                # RF001 logic
                if hours_before >= 48:
                    refund_percent = 1.00; admin_fee = 0.00; policy_note = "Early cancellation (48+ hrs): 100% refund."
                elif 24 <= hours_before < 48:
                    refund_percent = 0.75; admin_fee = 0.50; policy_note = "Standard cancellation (24-48 hrs): 75% refund."
                elif 2 <= hours_before < 24:
                    refund_percent = 0.50; admin_fee = 0.50; policy_note = "Late cancellation (2-24 hrs): 50% refund."
                else:
                    refund_percent = 0.00; policy_note = "Less than 2 hours before departure: No refund."
            elif service_type == 'express':
                # RF002 logic
                if hours_before >= 48:
                    refund_percent = 1.00; admin_fee = 1.00; policy_note = "Early cancellation (48+ hrs): 100% refund."
                elif 24 <= hours_before < 48:
                    refund_percent = 0.50; admin_fee = 1.00; policy_note = "Late cancellation (24-48 hrs): 50% refund."
                else:
                    refund_percent = 0.00; policy_note = "Less than 24 hours before departure: No refund."

            # Calculate final refund amount (ensure not below 0)
            calculated_refund = (amount * refund_percent) - admin_fee
            refund_amount = max(0.0, round(calculated_refund, 2))
            
            # 2. Update booking status
            cur.execute("""
                UPDATE national_rail_bookings
                SET status = 'cancelled', deleted_at = NOW()
                WHERE booking_id = %s
            """, (booking_id,))
            
            # 3. Update payment status
            cur.execute("""
                UPDATE payments
                SET status = 'refunded'
                WHERE national_booking_id = %s
            """, (booking_id,))
            
        conn.commit()
        return True, {"refund_amount_usd": float(refund_amount), "policy_note": policy_note}
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

# ── AUTHENTICATION QUERIES ────────────────────────────────────────────────────



def register_user(
    email: str, first_name: str, surname: str, year_of_birth: int,
    password: str, secret_question: str, secret_answer: str,
) -> tuple[bool, str]:
    """Register a new user with email, password, and security credentials. Returns (success, user_id_or_error)."""
    # Generate UUID
    new_user_id = str(uuid.uuid4())
    date_of_birth = f"{year_of_birth}-01-01" # Assume simplified date format
    
    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = False # Start transaction
    try:
        with conn.cursor() as cur:
            # 1. Insert user profile
            cur.execute("""
                INSERT INTO registered_users (user_id, full_name, email, date_of_birth)
                VALUES (%s, %s, %s, %s)
            """, (new_user_id, f"{first_name} {surname}", email, date_of_birth))
            
            # 2. Insert authentication credentials
            cur.execute("""
                INSERT INTO user_credentials (user_id, password_hash, secret_question, secret_answer_hash)
                VALUES (%s, %s, %s, %s)
            """, (new_user_id, password, secret_question, secret_answer))
            
        conn.commit()
        return True, new_user_id
    except psycopg2.IntegrityError:
        conn.rollback()
        return False, "Email already exists."
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


def login_user(email: str, password: str) -> Optional[dict]:
    """Authenticate a user and return their profile if credentials are valid."""
    sql = """
        SELECT 
            u.user_id, u.email, u.full_name, u.phone, 
            u.date_of_birth::text, u.is_active
        FROM registered_users u
        JOIN user_credentials c ON u.user_id = c.user_id
        WHERE u.email = %s 
          AND c.password_hash = %s 
          AND u.is_active = TRUE
          AND u.deleted_at IS NULL
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (email, password))
            row = cur.fetchone()
            if row:
                # Parse first_name and surname to match agent expected format
                parts = row["full_name"].split(" ", 1)
                row["first_name"] = parts[0]
                row["surname"] = parts[1] if len(parts) > 1 else ""
                return dict(row)
            return None


def get_user_secret_question(email: str) -> Optional[str]:
    """Return the secret question for a registered email, or None if not found."""
    sql = """
        SELECT c.secret_question
        FROM registered_users u
        JOIN user_credentials c ON u.user_id = c.user_id
        WHERE u.email = %s AND u.deleted_at IS NULL
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (email,))
            row = cur.fetchone()
            return row[0] if row else None

def verify_secret_answer(email: str, answer: str) -> bool:
    """Return True if the provided answer matches the stored secret answer."""
    sql = """
        SELECT c.secret_answer_hash
        FROM registered_users u
        JOIN user_credentials c ON u.user_id = c.user_id
        WHERE u.email = %s AND u.deleted_at IS NULL
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (email,))
            row = cur.fetchone()
            if row:
                # Simple string comparison to match teaching materials
                return row[0].lower() == answer.lower()
            return False

def update_password(email: str, new_password: str) -> bool:
    """Update the password for a user. Returns True if the row was updated."""
    sql = """
        UPDATE user_credentials
        SET password_hash = %s, updated_at = NOW()
        WHERE user_id = (
            SELECT user_id FROM registered_users 
            WHERE email = %s AND deleted_at IS NULL
        )
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (new_password, email))
            return cur.rowcount > 0


# ── VECTOR / RAG QUERIES — do not modify ─────────────────────────────────────

def query_policy_vector_search(embedding: list[float], top_k: int = VECTOR_TOP_K) -> list[dict]:
    """
    Find the most relevant policy documents for a given query embedding.

    Args:
        embedding: Query vector from llm.embed(user_question)
        top_k:     Number of results to return

    Returns:
        List of dicts with title, category, content, and similarity score
    """
    sql = """
        SELECT
            title,
            category,
            content,
            1 - (embedding <=> %s::vector) AS similarity
        FROM policy_documents
        WHERE 1 - (embedding <=> %s::vector) > %s
        ORDER BY embedding <=> %s::vector
        LIMIT %s
    """
    vec_str = "[" + ",".join(str(x) for x in embedding) + "]"
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (vec_str, vec_str, VECTOR_SIMILARITY_THRESHOLD, vec_str, top_k))
            return [dict(row) for row in cur.fetchall()]


def store_policy_document(
    title: str,
    category: str,
    content: str,
    embedding: list[float],
    source_file: str = "",
) -> int:
    """
    Insert a policy document with its embedding into the database.
    Used by skeleton/seed_vectors.py — students don't need to call this directly.

    Returns:
        The new document's id
    """
    sql = """
        INSERT INTO policy_documents (title, category, content, embedding, source_file)
        VALUES (%s, %s, %s, %s::vector, %s)
        RETURNING id
    """
    vec_str = "[" + ",".join(str(x) for x in embedding) + "]"
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (title, category, content, vec_str, source_file))
            return cur.fetchone()[0]
