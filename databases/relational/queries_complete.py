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

import json
import random
import string
from datetime import datetime, timezone
from typing import Optional

import psycopg2
import psycopg2.extras

from skeleton.config import PG_DSN, VECTOR_TOP_K, VECTOR_SIMILARITY_THRESHOLD


def _connect():
    """Return a new psycopg2 connection with autocommit enabled."""
    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = True
    return conn


def _gen_booking_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"BK-{suffix}"


def _gen_payment_id() -> str:
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
    """
    Return national rail schedules that serve both origin and destination stations
    in the correct order, along with seat occupancy for the requested travel date.

    Args:
        origin_id:       e.g. "NR01"
        destination_id:  e.g. "NR05"
        travel_date:     e.g. "2025-06-01" — used to count bookings; omit for general info
    """
    sql = """
        SELECT
            nrs.schedule_id,
            nrs.line,
            nrs.service_type,
            nrs.direction,
            nrs.first_train_time,
            nrs.last_train_time,
            nrs.frequency_min,
            nrs.stops_in_order,
            nrs.fare_classes
        FROM national_rail_schedules nrs
        WHERE nrs.origin_station_id = %s
          AND nrs.destination_station_id = %s
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
    """
    Calculate the fare for a national rail journey.

    Args:
        schedule_id:     e.g. "NR_SCH01"
        fare_class:      "standard" or "first"
        stops_travelled: number of stops between origin and destination (inclusive)

    Returns:
        dict with fare_class, base_fare_usd, per_stop_rate_usd, total_fare_usd
    """
    sql = "SELECT fare_classes FROM national_rail_schedules WHERE schedule_id = %s"
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (schedule_id,))
            row = cur.fetchone()
            if not row:
                return None
            fare_classes = row['fare_classes']
            if fare_class not in fare_classes:
                return None
            fc_data = fare_classes[fare_class]
            base = float(fc_data['base_fare_usd'])
            per_stop = float(fc_data['per_stop_rate_usd'])
            total = base + (per_stop * stops_travelled)
            return {
                'fare_class': fare_class,
                'base_fare_usd': base,
                'per_stop_rate_usd': per_stop,
                'total_fare_usd': total
            }


# ── METRO SCHEDULES & FARE ────────────────────────────────────────────────────

def query_metro_schedules(origin_id: str, destination_id: str) -> list[dict]:
    """
    Return metro schedules that serve both origin and destination in the correct order.

    Args:
        origin_id:       e.g. "MS01"
        destination_id:  e.g. "MS09"
    """
    sql = "SELECT * FROM metro_schedules WHERE origin_station_id = %s AND destination_station_id = %s"
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (origin_id, destination_id))
            return [dict(row) for row in cur.fetchall()]


def query_metro_fare(schedule_id: str, stops_travelled: int) -> Optional[dict]:
    """
    Calculate the metro fare for a single-ticket journey.

    Args:
        schedule_id:     e.g. "MS_SCH01"
        stops_travelled: number of stops between origin and destination

    Returns:
        dict with base_fare_usd, per_stop_rate_usd, total_fare_usd
    """
    sql = "SELECT base_fare_usd, per_stop_rate_usd FROM metro_schedules WHERE schedule_id = %s"
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (schedule_id,))
            row = cur.fetchone()
            if not row:
                return None
            base = float(row['base_fare_usd'])
            per_stop = float(row['per_stop_rate_usd'])
            total = base + (per_stop * stops_travelled)
            return {
                'base_fare_usd': base,
                'per_stop_rate_usd': per_stop,
                'total_fare_usd': total
            }


# ── SEAT SELECTION ────────────────────────────────────────────────────────────

def query_available_seats(
    schedule_id: str,
    travel_date: str,
    fare_class: str,
) -> list[dict]:
    """
    Return available seats for a national rail journey on a given date.

    Args:
        schedule_id:  e.g. "NR_SCH01"
        travel_date:  e.g. "2025-06-01"
        fare_class:   "standard" or "first"

    Returns:
        List of dicts: {seat_id, coach, row, column}
    """
    sql = "SELECT coaches FROM national_rail_seat_layouts WHERE schedule_id = %s"
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (schedule_id,))
            row = cur.fetchone()
            if not row:
                return []
            coaches = row['coaches']
            all_seats = []
            for coach_data in coaches:
                if coach_data.get('fare_class') == fare_class:
                    for seat in coach_data.get('seats', []):
                        all_seats.append({
                            'seat_id': seat['seat_id'],
                            'coach': coach_data['coach'],
                            'row': seat.get('row'),
                            'column': seat.get('column')
                        })
            booked_sql = "SELECT DISTINCT seat_id FROM national_rail_bookings WHERE schedule_id = %s AND travel_date = %s AND fare_class = %s AND status IN ('completed', 'pending')"
            cur.execute(booked_sql, (schedule_id, travel_date, fare_class))
            booked_seats = {r['seat_id'] for r in cur.fetchall()}
            return [s for s in all_seats if s['seat_id'] not in booked_seats]


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
    rows: dict[int, list[dict]] = defaultdict(list)
    for seat in available_seats:
        rows[seat["row"]].append(seat)

    for row_seats in sorted(rows.values(), key=lambda s: s[0]["row"]):
        if len(row_seats) >= count:
            return [s["seat_id"] for s in row_seats[:count]]

    sorted_seats = sorted(available_seats, key=lambda s: (s["row"], s["column"]))
    return [s["seat_id"] for s in sorted_seats[:count]]


# ── USER & BOOKING QUERIES ────────────────────────────────────────────────────

def query_user_profile(user_email: str) -> Optional[dict]:
    """Return a user's profile by email."""
    sql = "SELECT * FROM users WHERE email = %s"
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (user_email,))
            row = cur.fetchone()
            return dict(row) if row else None


def query_user_bookings(user_email: str) -> dict:
    """
    Return a user's combined booking history (national rail + metro).

    Returns:
        dict with keys 'national_rail' (list) and 'metro' (list)
    """
    user_prof = query_user_profile(user_email)
    if not user_prof:
        return {'national_rail': [], 'metro': []}
    user_id = user_prof['user_id']
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM national_rail_bookings WHERE user_id = %s ORDER BY booked_at DESC", (user_id,))
            national_rail = [dict(row) for row in cur.fetchall()]
            cur.execute("SELECT * FROM metro_travels WHERE user_id = %s ORDER BY purchased_at DESC", (user_id,))
            metro = [dict(row) for row in cur.fetchall()]
    return {'national_rail': national_rail, 'metro': metro}


def query_payment_info(booking_id: str) -> Optional[dict]:
    """Return payment record for a booking or metro trip."""
    sql = "SELECT * FROM payments WHERE booking_id = %s"
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (booking_id,))
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
    """
    Create a national rail booking for a logged-in user.

    Args:
        user_id:                e.g. "RU01" — must match the logged-in user
        schedule_id:            e.g. "NR_SCH01"
        origin_station_id:      e.g. "NR01"
        destination_station_id: e.g. "NR05"
        travel_date:            e.g. "2025-06-01"
        fare_class:             "standard" or "first"
        seat_id:                e.g. "B05" (or "any" to auto-assign)
        ticket_type:            "single" (default) or "return"

    Returns:
        (True, booking_dict)   on success
        (False, error_message) on failure
    """
    conn = None
    try:
        conn = psycopg2.connect(PG_DSN)
        conn.autocommit = False
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM national_rail_schedules WHERE schedule_id = %s", (schedule_id,))
            schedule = cur.fetchone()
            if not schedule:
                conn.rollback()
                return (False, "Schedule not found")
            stops_in_order = json.loads(schedule['stops_in_order']) if isinstance(schedule['stops_in_order'], str) else schedule['stops_in_order']
            origin_idx = stops_in_order.index(origin_station_id) if origin_station_id in stops_in_order else -1
            dest_idx = stops_in_order.index(destination_station_id) if destination_station_id in stops_in_order else -1
            if origin_idx < 0 or dest_idx < 0 or origin_idx >= dest_idx:
                conn.rollback()
                return (False, "Invalid route")
            stops_travelled = dest_idx - origin_idx
            fare_result = query_national_rail_fare(schedule_id, fare_class, stops_travelled)
            if not fare_result:
                conn.rollback()
                return (False, "Fare calculation failed")
            amount_usd = fare_result['total_fare_usd']
            final_seat_id = seat_id
            if seat_id == "any":
                available = query_available_seats(schedule_id, travel_date, fare_class)
                if not available:
                    conn.rollback()
                    return (False, "No available seats")
                selected = auto_select_adjacent_seats(available, 1)
                if not selected:
                    conn.rollback()
                    return (False, "Cannot auto-select seats")
                final_seat_id = selected[0]
            booking_id = _gen_booking_id()
            cur.execute("""
                INSERT INTO national_rail_bookings
                (booking_id, user_id, schedule_id, origin_station_id, destination_station_id,
                 travel_date, ticket_type, fare_class, seat_id, stops_travelled, amount_usd, status, booked_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (booking_id, user_id, schedule_id, origin_station_id, destination_station_id,
                   travel_date, ticket_type, fare_class, final_seat_id, stops_travelled, amount_usd, 'pending',
                   datetime.now(timezone.utc)))
            payment_id = _gen_payment_id()
            cur.execute("""
                INSERT INTO payments
                (payment_id, booking_id, amount_usd, method, status, paid_at)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (payment_id, booking_id, amount_usd, 'pending', 'pending', datetime.now(timezone.utc)))
            conn.commit()
            return (True, {
                'booking_id': booking_id,
                'user_id': user_id,
                'schedule_id': schedule_id,
                'seat_id': final_seat_id,
                'amount_usd': amount_usd,
                'status': 'pending'
            })
    except Exception as e:
        if conn:
            conn.rollback()
        return (False, str(e))
    finally:
        if conn:
            conn.close()


def execute_cancellation(booking_id: str, user_id: str) -> tuple[bool, dict | str]:
    """
    Cancel a national rail booking owned by the given user.

    Calculates the refund amount according to the booking's service type:
      - Normal service: RF001 windows (100% / 75% / 50% / 0%)
      - Express service: RF002 windows (100% / 50% / 0%)

    Args:
        booking_id: e.g. "BK001"
        user_id:    must match the booking's user_id

    Returns:
        (True, result_dict)  with refund_amount_usd and policy note
        (False, error_msg)
    """
    conn = None
    try:
        conn = psycopg2.connect(PG_DSN)
        conn.autocommit = False
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM national_rail_bookings WHERE booking_id = %s", (booking_id,))
            booking = cur.fetchone()
            if not booking:
                conn.rollback()
                return (False, "Booking not found")
            if booking['user_id'] != user_id:
                conn.rollback()
                return (False, "Booking does not belong to user")
            if booking['status'] == 'cancelled':
                conn.rollback()
                return (False, "Booking already cancelled")
            cur.execute("SELECT * FROM national_rail_schedules WHERE schedule_id = %s", (booking['schedule_id'],))
            schedule = cur.fetchone()
            service_type = schedule['service_type'] if schedule else 'normal'
            hours_until_departure = 24
            refund_percent = 0.5 if service_type == 'express' else 0.75
            if hours_until_departure >= 24:
                refund_percent = 1.0
            refund_amount = float(booking['amount_usd']) * refund_percent
            cur.execute("UPDATE national_rail_bookings SET status = %s WHERE booking_id = %s", ('cancelled', booking_id))
            payment = query_payment_info(booking_id)
            if payment:
                cur.execute("UPDATE payments SET status = %s WHERE booking_id = %s", ('refunded', booking_id))
            conn.commit()
            return (True, {
                'booking_id': booking_id,
                'refund_amount_usd': refund_amount,
                'policy': f"{'RF001' if service_type == 'normal' else 'RF002'} - {int(refund_percent*100)}% refund",
                'status': 'cancelled'
            })
    except Exception as e:
        if conn:
            conn.rollback()
        return (False, str(e))
    finally:
        if conn:
            conn.close()


# ── AUTHENTICATION QUERIES ────────────────────────────────────────────────────

def register_user(
    email: str,
    first_name: str,
    surname: str,
    year_of_birth: int,
    password: str,
    secret_question: str,
    secret_answer: str,
) -> tuple[bool, str]:
    """
    Register a new user.
    Returns (True, user_id) on success or (False, error_message) on failure.

    NOTE: passwords are stored as plain text here intentionally for teaching
    purposes. In production, replace with a salted hash (e.g. bcrypt).
    """
    try:
        user_id = f"RU{random.randint(100, 999)}"
        full_name = f"{first_name} {surname}"
        dob = f"{year_of_birth}-01-01"
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO users
                    (user_id, email, password, full_name, first_name, surname, date_of_birth,
                     secret_question, secret_answer, registered_at, is_active)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (user_id, email, password, full_name, first_name, surname, dob,
                      secret_question, secret_answer, datetime.now(timezone.utc), True))
        return (True, user_id)
    except psycopg2.IntegrityError:
        return (False, "Email already registered")
    except Exception as e:
        return (False, str(e))


def login_user(email: str, password: str) -> Optional[dict]:
    """
    Verify credentials. Returns a user dict on success or None on failure.
    Dict keys: user_id, email, full_name, first_name, surname, phone, date_of_birth, is_active.
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE email = %s AND password = %s", (email, password))
            row = cur.fetchone()
            if row:
                return dict(row)
            return None


def get_user_secret_question(email: str) -> Optional[str]:
    """Return the secret question for a registered email, or None if not found."""
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT secret_question FROM users WHERE email = %s", (email,))
            row = cur.fetchone()
            return row['secret_question'] if row else None


def verify_secret_answer(email: str, answer: str) -> bool:
    """Return True if the provided answer matches the stored secret answer (case-insensitive)."""
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT secret_answer FROM users WHERE email = %s", (email,))
            row = cur.fetchone()
            if row and row['secret_answer']:
                return row['secret_answer'].lower() == answer.lower()
            return False


def update_password(email: str, new_password: str) -> bool:
    """Update the password for a user. Returns True if the row was updated."""
    conn = None
    try:
        conn = psycopg2.connect(PG_DSN)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET password = %s WHERE email = %s", (new_password, email))
            return cur.rowcount > 0
    except Exception:
        return False
    finally:
        if conn:
            conn.close()


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
