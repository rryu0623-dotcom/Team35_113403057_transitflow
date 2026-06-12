# TASK 6 EXTENSION: Custom departure time booking and operator alerts queries
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
#  工業級優化點：資料庫連線池 (Database Connection Pooling)
# ==============================================================================
# 原本的 _connect() 在每次查詢時都會向資料庫重新開啟一個實體 TCP 連線，
# 這在高併發/高流量的生產環境中會造成巨大的延遲與連線數耗盡 (Connection Exhaustion) 的崩潰。
# 這裡引入 ThreadedConnectionPool (最小 1 個連線，最大 20 個連線)。
# 
# 為了完美向後相容原本的 context manager (with _connect() as conn) 與手動 conn.close() 的寫法，
# 我們設計了 ConnectionProxy 代理類別：
# 1. 攔截 close()：呼叫 close() 時，不會真正關閉連線，而是安全地將連線歸還到 pool 中。
# 2. 自動回收：當 context manager (__exit__) 結束時，自動執行 commit/rollback 並安全回收連線。
# 3. 透明轉發：所有其他屬性與方法調用皆透明地委託給真實的 psycopg2 connection 物件。
# ==============================================================================
from contextlib import contextmanager
from psycopg2.pool import ThreadedConnectionPool

# 全域 thread-safe 連線池 (min 1, max 20 connections)
_pool = ThreadedConnectionPool(1, 20, PG_DSN)

class ConnectionProxy:
    def __init__(self, conn, pool):
        self._conn = conn
        self._pool = pool
        
    def __getattr__(self, name):
        # 透明轉發所有屬性與方法給真實的 psycopg2 連線物件
        return getattr(self._conn, name)
        
    def __enter__(self):
        self._conn.__enter__()
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            self._conn.__exit__(exc_type, exc_val, exc_tb)
        finally:
            # 區塊退出時自動回收連線
            self.close()
        
    def close(self):
        try:
            # 將實體連線歸還給 ThreadedConnectionPool，而不是真的銷毀它
            self._pool.putconn(self._conn)
        except Exception:
            pass


def _connect():
    """從全域 ThreadedConnectionPool 借用一個連線，並包裝於 ConnectionProxy 中傳回。"""
    conn = _pool.getconn()
    conn.autocommit = True
    return ConnectionProxy(conn, _pool)


def _hash_password(password: str) -> str:
    """Hash password securely using Argon2id."""
    from argon2 import PasswordHasher
    ph = PasswordHasher()
    return ph.hash(password)

def _verify_password(hash: str, password: str) -> bool:
    """Verify password against Argon2id hash."""
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError
    ph = PasswordHasher()
    try:
        return ph.verify(hash, password)
    except VerifyMismatchError:
        return False


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
            o.stop_order AS origin_order,
            d.stop_order AS destination_order,
            (d.travel_time_from_origin_min - o.travel_time_from_origin_min) AS travel_time_min,
            (d.stop_order - o.stop_order) AS stops_travelled
        FROM national_rail_schedules s
        JOIN national_rail_schedule_stops o ON s.schedule_id = o.schedule_id AND o.station_id = %s
        JOIN national_rail_schedule_stops d ON s.schedule_id = d.schedule_id AND d.station_id = %s
        WHERE s.is_active = TRUE
          AND o.stop_order < d.stop_order
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
            cur.execute(sql, (abs(stops_travelled), schedule_id, fare_class))
            row = cur.fetchone()
            return dict(row) if row else None

# ── METRO SCHEDULES & FARE ────────────────────────────────────────────────────

def query_metro_schedules(origin_id: str, destination_id: str) -> list[dict]:
    """Retrieve all available metro schedules between two stations."""
    sql = """
        SELECT 
            s.schedule_id, s.line, s.direction,
            o.stop_order AS origin_order,
            d.stop_order AS destination_order,
            (d.travel_time_from_origin_min - o.travel_time_from_origin_min) AS travel_time_min,
            (d.stop_order - o.stop_order) AS stops_travelled
        FROM metro_schedules s
        JOIN metro_schedule_stops o ON s.schedule_id = o.schedule_id AND o.station_id = %s
        JOIN metro_schedule_stops d ON s.schedule_id = d.schedule_id AND d.station_id = %s
        WHERE s.is_active = TRUE
          AND o.stop_order < d.stop_order
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
            cur.execute(sql, (abs(stops_travelled), schedule_id))
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
    departure_time: Optional[str] = None,
) -> tuple[bool, dict | str]:
    """
    Create a national rail booking for a logged-in user.
    If departure_time is provided, use it. Otherwise, calculate the first train time.
    """
    booking_id = _gen_booking_id()
    payment_id = _gen_payment_id()
    
    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = False
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # 1. Retrieve route and station information
            cur.execute("""
                SELECT 
                    s.service_type,
                    o.travel_time_from_origin_min AS o_time,
                    (d.stop_order - o.stop_order) AS stops
                FROM national_rail_schedules s
                JOIN national_rail_schedule_stops o ON s.schedule_id = o.schedule_id AND o.station_id = %s
                JOIN national_rail_schedule_stops d ON s.schedule_id = d.schedule_id AND d.station_id = %s
                WHERE s.schedule_id = %s 
                  AND o.stop_order < d.stop_order
            """, (origin_station_id, destination_station_id, schedule_id))
            sched_info = cur.fetchone()
            if not sched_info or sched_info['stops'] <= 0:
                raise ValueError("Invalid route or station order.")
            
            # Calculate departure time or use custom departure_time
            if departure_time:
                actual_departure_time = departure_time
            else:
                cur.execute("""
                    SELECT (first_train_time + (%s || ' minutes')::interval)::time AS dep_time
                    FROM national_rail_schedules WHERE schedule_id = %s
                """, (sched_info['o_time'], schedule_id))
                actual_departure_time = cur.fetchone()['dep_time']
            
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
                
                # Verify specific seat availability to prevent double booking
                cur.execute("""
                    SELECT 1 FROM national_rail_bookings
                    WHERE schedule_id = %s 
                      AND travel_date = %s 
                      AND coach = %s 
                      AND seat_id = %s 
                      AND status IN ('confirmed', 'completed')
                      AND deleted_at IS NULL
                """, (schedule_id, travel_date, coach, actual_seat_id))
                if cur.fetchone():
                    raise ValueError(f"Seat {actual_seat_id} in coach {coach} is already booked.")

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
                destination_station_id, dest_name, travel_date, actual_departure_time,
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
            """, (new_user_id, _hash_password(password), secret_question, _hash_password(secret_answer)))
            
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
            u.date_of_birth::text, u.is_active, c.password_hash
        FROM registered_users u
        JOIN user_credentials c ON u.user_id = c.user_id
        WHERE u.email = %s 
          AND u.is_active = TRUE
          AND u.deleted_at IS NULL
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (email,))
            row = cur.fetchone()
            if row and _verify_password(row["password_hash"], password):
                # Parse first_name and surname to match agent expected format
                parts = row["full_name"].split(" ", 1)
                row["first_name"] = parts[0]
                row["surname"] = parts[1] if len(parts) > 1 else ""
                del row["password_hash"]
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
                return _verify_password(row[0], answer)
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
            cur.execute(sql, (_hash_password(new_password), email))
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


# ==============================================================================
#  TASK 6 EXTENSION: New Relational Database Queries
# ==============================================================================

def query_active_alerts() -> list[dict]:
    """
    Retrieve all active operator/service alerts from the database.
    
    Returns:
        List of dictionaries containing alert details (ID, line, station, severity, message).
    """
    sql = """
        SELECT alert_id, line, station_id, severity, message, created_at::text, is_active
        FROM operator_alerts
        WHERE is_active = TRUE
        ORDER BY severity = 'high' DESC, severity = 'medium' DESC, created_at DESC
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)
            return [dict(row) for row in cur.fetchall()]


def query_station_upcoming_departures(station_id: str) -> list[dict]:
    """
    Query all schedules containing the station and dynamically calculate and list
    all departures for that station based on first train time, last train time,
    and operating frequency.
    
    Args:
        station_id: The ID of the station (e.g. MS01 or NR01)
        
    Returns:
        List of dictionaries with departure info sorted chronologically.
    """
    departures = []
    
    # 1. Query metro schedules passing through
    metro_sql = """
        SELECT s.schedule_id, s.line, s.direction, s.first_train_time::text, s.last_train_time::text, s.frequency_min,
               o.travel_time_from_origin_min, s.destination_station_id
        FROM metro_schedules s
        JOIN metro_schedule_stops o ON s.schedule_id = o.schedule_id AND o.station_id = %s
        WHERE s.is_active = TRUE
    """
    
    # 2. Query rail schedules passing through
    rail_sql = """
        SELECT s.schedule_id, s.line, s.service_type::text, s.direction, s.first_train_time::text, s.last_train_time::text, s.frequency_min,
               o.travel_time_from_origin_min, s.destination_station_id
        FROM national_rail_schedules s
        JOIN national_rail_schedule_stops o ON s.schedule_id = o.schedule_id AND o.station_id = %s
        WHERE s.is_active = TRUE
    """
    
    from datetime import datetime, timedelta
    
    def parse_time(t_str: str) -> datetime:
        return datetime.strptime(t_str, "%H:%M:%S" if len(t_str.split(":")) == 3 else "%H:%M")
        
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Check metro
            cur.execute(metro_sql, (station_id,))
            for row in cur.fetchall():
                offset = row["travel_time_from_origin_min"]
                
                first_dt = parse_time(row["first_train_time"])
                last_dt = parse_time(row["last_train_time"])
                freq = row["frequency_min"]
                
                curr_dt = first_dt
                while curr_dt <= last_dt:
                    dep_dt = curr_dt + timedelta(minutes=offset)
                    departures.append({
                        "schedule_id": row["schedule_id"],
                        "type": "Metro",
                        "line": row["line"],
                        "direction": row["direction"],
                        "departure_time": dep_dt.strftime("%H:%M"),
                        "destination": row["destination_station_id"]
                    })
                    curr_dt += timedelta(minutes=freq)
                    
            # Check rail
            cur.execute(rail_sql, (station_id,))
            for row in cur.fetchall():
                offset = row["travel_time_from_origin_min"]
                
                first_dt = parse_time(row["first_train_time"])
                last_dt = parse_time(row["last_train_time"])
                freq = row["frequency_min"]
                
                curr_dt = first_dt
                while curr_dt <= last_dt:
                    dep_dt = curr_dt + timedelta(minutes=offset)
                    departures.append({
                        "schedule_id": row["schedule_id"],
                        "type": f"Rail ({row['service_type']})",
                        "line": row["line"],
                        "direction": row["direction"],
                        "departure_time": dep_dt.strftime("%H:%M"),
                        "destination": row["destination_station_id"]
                    })
                    curr_dt += timedelta(minutes=freq)
                    
    departures.sort(key=lambda x: x["departure_time"])
    return departures


def query_transit_system_analytics() -> dict:
    """
    Query system-wide metrics from PostgreSQL relational tables to generate
    an operations dashboard overview.
    
    Returns:
        Dict containing total bookings, revenue, ratings, and top busy stations.
    """
    analytics = {}
    
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Total bookings and revenue
            cur.execute("SELECT COUNT(*) AS count, SUM(amount_usd)::float AS revenue FROM national_rail_bookings WHERE status != 'cancelled';")
            nr_stats = cur.fetchone()
            cur.execute("SELECT COUNT(*) AS count, SUM(amount_usd)::float AS revenue FROM metro_travel_history WHERE status != 'cancelled';")
            metro_stats = cur.fetchone()
            
            analytics["total_national_rail_bookings"] = nr_stats["count"] or 0
            analytics["total_national_rail_revenue"] = round(nr_stats["revenue"] or 0.0, 2)
            analytics["total_metro_trips"] = metro_stats["count"] or 0
            analytics["total_metro_revenue"] = round(metro_stats["revenue"] or 0.0, 2)
            analytics["total_system_revenue"] = round((analytics["total_national_rail_revenue"] + analytics["total_metro_revenue"]), 2)
            
            # Payment method breakdown
            cur.execute("""
                SELECT method, COUNT(*) AS count, SUM(amount_usd)::float AS revenue
                FROM payments
                WHERE status = 'paid'
                GROUP BY method;
            """)
            analytics["revenue_by_payment_method"] = [dict(row) for row in cur.fetchall()]
            
            # Top 3 busy stations
            cur.execute("""
                SELECT origin_station_name, COUNT(*) AS passenger_count
                FROM national_rail_bookings
                WHERE status != 'cancelled'
                GROUP BY origin_station_name
                ORDER BY passenger_count DESC
                LIMIT 3;
            """)
            analytics["top_rail_origin_stations"] = [dict(row) for row in cur.fetchall()]
            
            # Feedback rating stats
            cur.execute("SELECT AVG(rating)::float AS avg_rating, COUNT(*) AS total_feedbacks FROM feedback;")
            feedback_stats = cur.fetchone()
            analytics["average_user_rating"] = round(feedback_stats["avg_rating"] or 0.0, 2)
            analytics["total_feedbacks_received"] = feedback_stats["total_feedbacks"] or 0
            
    return analytics
