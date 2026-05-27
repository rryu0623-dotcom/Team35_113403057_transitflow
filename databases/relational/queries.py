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
            s.schedule_id,
            s.line,
            s.service_type,
            s.direction,
            to_char((s.first_train_time + (so.travel_time_from_origin_min || ' minutes')::interval)::time, 'HH24:MI') AS departure_time,
            to_char((s.first_train_time + (sd.travel_time_from_origin_min || ' minutes')::interval)::time, 'HH24:MI') AS arrival_time
        FROM national_rail_schedules s
        JOIN national_rail_schedule_stops so ON s.schedule_id = so.schedule_id AND so.station_id = %s AND so.is_stop = TRUE
        JOIN national_rail_schedule_stops sd ON s.schedule_id = sd.schedule_id AND sd.station_id = %s AND sd.is_stop = TRUE
        WHERE so.stop_order < sd.stop_order
          AND s.is_active = TRUE
        ORDER BY departure_time;
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (origin_id, destination_id))
            schedules = [dict(row) for row in cur.fetchall()]
            
            for sched in schedules:
                sched_id = sched["schedule_id"]
                # 1. Get total seats in layout
                cur.execute("""
                    SELECT count(*) AS total
                    FROM national_rail_seats
                    WHERE layout_id = (SELECT layout_id FROM national_rail_schedules WHERE schedule_id = %s);
                """, (sched_id,))
                res = cur.fetchone()
                total_seats = res["total"] if res else 0
                
                # 2. Get booked seats on this date
                booked_seats = 0
                if travel_date:
                    cur.execute("""
                        SELECT count(*) AS booked
                        FROM national_rail_bookings
                        WHERE schedule_id = %s
                          AND travel_date = %s
                          AND status != 'cancelled';
                    """, (sched_id, travel_date))
                    res_booked = cur.fetchone()
                    booked_seats = res_booked["booked"] if res_booked else 0
                    
                sched["available_seats"] = max(0, total_seats - booked_seats)
            return schedules


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
    sql = """
        SELECT base_fare_usd, per_stop_rate_usd
        FROM national_rail_schedule_fares
        WHERE schedule_id = %s AND fare_class = %s;
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (schedule_id, fare_class))
            row = cur.fetchone()
            if not row:
                return None
            base = float(row["base_fare_usd"])
            rate = float(row["per_stop_rate_usd"])
            total = round(base + rate * stops_travelled, 2)
            return {
                "fare_class": fare_class,
                "base_fare_usd": base,
                "per_stop_rate_usd": rate,
                "total_fare_usd": total
            }


# ── METRO SCHEDULES & FARE ────────────────────────────────────────────────────

def query_metro_schedules(origin_id: str, destination_id: str) -> list[dict]:
    """
    Return metro schedules that serve both origin and destination in the correct order.

    Args:
        origin_id:       e.g. "MS01"
        destination_id:  e.g. "MS09"
    """
    sql = """
        SELECT 
            s.schedule_id,
            s.line,
            s.direction,
            to_char((s.first_train_time + (so.travel_time_from_origin_min || ' minutes')::interval)::time, 'HH24:MI') AS departure_time,
            to_char((s.first_train_time + (sd.travel_time_from_origin_min || ' minutes')::interval)::time, 'HH24:MI') AS arrival_time
        FROM metro_schedules s
        JOIN metro_schedule_stops so ON s.schedule_id = so.schedule_id AND so.station_id = %s
        JOIN metro_schedule_stops sd ON s.schedule_id = sd.schedule_id AND sd.station_id = %s
        WHERE so.stop_order < sd.stop_order
          AND s.is_active = TRUE
        ORDER BY departure_time;
    """
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
    sql = """
        SELECT base_fare_usd, per_stop_rate_usd
        FROM metro_schedules
        WHERE schedule_id = %s;
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (schedule_id,))
            row = cur.fetchone()
            if not row:
                return None
            base = float(row["base_fare_usd"])
            rate = float(row["per_stop_rate_usd"])
            total = round(base + rate * stops_travelled, 2)
            return {
                "base_fare_usd": base,
                "per_stop_rate_usd": rate,
                "total_fare_usd": total
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
    sql = """
        SELECT 
            s.seat_id,
            s.coach,
            s.row,
            s.seat_column AS column
        FROM national_rail_seats s
        JOIN national_rail_coaches c ON s.layout_id = c.layout_id AND s.coach = c.coach
        WHERE s.layout_id = (SELECT layout_id FROM national_rail_schedules WHERE schedule_id = %s)
          AND c.fare_class = %s
          AND s.seat_id NOT IN (
              SELECT seat_id
              FROM national_rail_bookings
              WHERE schedule_id = %s
                AND travel_date = %s
                AND status != 'cancelled'
          )
        ORDER BY s.coach, s.row, s.seat_column;
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
    sql = """
        SELECT user_id, email, full_name, phone, date_of_birth, registered_at, is_active
        FROM registered_users
        WHERE email = %s AND is_active = TRUE;
    """
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
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # 1. Get user_id
            cur.execute("SELECT user_id FROM registered_users WHERE email = %s;", (user_email,))
            user_row = cur.fetchone()
            if not user_row:
                return {"national_rail": [], "metro": []}
            user_uuid = user_row["user_id"]
            
            # 2. Query national rail bookings
            cur.execute("""
                SELECT 
                    b.booking_id,
                    b.schedule_id,
                    s.line,
                    s.service_type,
                    so.name AS origin_station,
                    sd.name AS destination_station,
                    b.travel_date::text AS travel_date,
                    b.departure_time::text AS departure_time,
                    b.ticket_type,
                    b.fare_class,
                    b.coach,
                    b.seat_id,
                    b.stops_travelled,
                    b.amount_usd,
                    b.status,
                    b.booked_at::text AS booked_at
                FROM national_rail_bookings b
                JOIN national_rail_schedules s ON b.schedule_id = s.schedule_id
                JOIN national_rail_stations so ON b.origin_station_id = so.station_id
                JOIN national_rail_stations sd ON b.destination_station_id = sd.station_id
                WHERE b.user_id = %s
                ORDER BY b.travel_date DESC, b.departure_time DESC;
            """, (user_uuid,))
            rail_bookings = [dict(row) for row in cur.fetchall()]
            
            # 3. Query metro travel history
            cur.execute("""
                SELECT 
                    h.trip_id,
                    h.schedule_id,
                    s.line,
                    so.name AS origin_station,
                    sd.name AS destination_station,
                    h.travel_date::text AS travel_date,
                    h.ticket_type,
                    h.day_pass_ref,
                    h.stops_travelled,
                    h.amount_usd,
                    h.status,
                    h.purchased_at::text AS purchased_at,
                    h.travelled_at::text AS travelled_at
                FROM metro_travel_history h
                JOIN metro_schedules s ON h.schedule_id = s.schedule_id
                JOIN metro_stations so ON h.origin_station_id = so.station_id
                JOIN metro_stations sd ON h.destination_station_id = sd.station_id
                WHERE h.user_id = %s
                ORDER BY h.travel_date DESC, h.trip_id DESC;
            """, (user_uuid,))
            metro_trips = [dict(row) for row in cur.fetchall()]
            
            return {
                "national_rail": rail_bookings,
                "metro": metro_trips
            }


def query_payment_info(booking_id: str) -> Optional[dict]:
    """Return payment record for a booking or metro trip."""
    sql = """
        SELECT payment_id, national_booking_id, metro_trip_id, amount_usd, method, status, paid_at::text AS paid_at
        FROM payments
        WHERE national_booking_id = %s OR metro_trip_id = %s;
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
    import uuid
    conn = _connect()
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    try:
        # 1. Resolve UUID for the user_id if passed as "RUxx"
        user_uuid = user_id
        if user_id.startswith("RU"):
            cur.execute("SELECT user_id FROM registered_users WHERE email LIKE %s;", (f"{user_id.lower()}%",))
            user_row = cur.fetchone()
            if user_row:
                user_uuid = user_row["user_id"]
            else:
                # Default mapping mapping or fallback
                num = int(user_id[2:])
                user_uuid = f"00000000-0000-0000-0000-{num:012d}"
                
        # 2. Calculate departure time and stops travelled
        cur.execute("""
            SELECT 
                s.first_train_time,
                so.stop_order AS origin_order,
                sd.stop_order AS dest_order,
                so.travel_time_from_origin_min AS orig_time,
                sd.travel_time_from_origin_min AS dest_time
            FROM national_rail_schedules s
            JOIN national_rail_schedule_stops so ON s.schedule_id = so.schedule_id AND so.station_id = %s
            JOIN national_rail_schedule_stops sd ON s.schedule_id = sd.schedule_id AND sd.station_id = %s
            WHERE s.schedule_id = %s;
        """, (origin_station_id, destination_station_id, schedule_id))
        sched_info = cur.fetchone()
        if not sched_info:
            return False, "Invalid schedule or station mapping."
            
        stops_travelled = int(sched_info["dest_order"]) - int(sched_info["origin_order"])
        if stops_travelled <= 0:
            return False, "Destination must be after the origin station."
            
        # Calculate departure time: first_train_time + orig_time
        cur.execute("""
            SELECT to_char((%s::time + (%s || ' minutes')::interval)::time, 'HH24:MI:SS') AS dep_time;
        """, (sched_info["first_train_time"], sched_info["orig_time"]))
        departure_time = cur.fetchone()["dep_time"]
        
        # 3. Calculate fare amount
        cur.execute("""
            SELECT base_fare_usd, per_stop_rate_usd
            FROM national_rail_schedule_fares
            WHERE schedule_id = %s AND fare_class = %s;
        """, (schedule_id, fare_class))
        fare_info = cur.fetchone()
        if not fare_info:
            return False, "Invalid fare class specified."
        amount = round(float(fare_info["base_fare_usd"]) + float(fare_info["per_stop_rate_usd"]) * stops_travelled, 2)
        
        # 4. Handle Seat Auto Selection / Verification
        assigned_seat_id = seat_id
        assigned_coach = None
        
        # Helper to query all available seats
        cur.execute("""
            SELECT s.seat_id, s.coach, s.row, s.seat_column
            FROM national_rail_seats s
            JOIN national_rail_coaches c ON s.layout_id = c.layout_id AND s.coach = c.coach
            WHERE s.layout_id = (SELECT layout_id FROM national_rail_schedules WHERE schedule_id = %s)
              AND c.fare_class = %s
              AND s.seat_id NOT IN (
                  SELECT seat_id
                  FROM national_rail_bookings
                  WHERE schedule_id = %s
                    AND travel_date = %s
                    AND status != 'cancelled'
              )
            ORDER BY s.coach, s.row, s.seat_column;
        """, (schedule_id, fare_class, schedule_id, travel_date))
        avail_seats = [dict(row) for row in cur.fetchall()]
        
        if not avail_seats:
            return False, "No available seats in this class."
            
        if seat_id == "any":
            assigned_seat_id = avail_seats[0]["seat_id"]
            assigned_coach = avail_seats[0]["coach"]
        else:
            # Check if requested seat is in the available seats
            matching_seat = next((s for s in avail_seats if s["seat_id"] == seat_id), None)
            if not matching_seat:
                return False, f"Seat {seat_id} is already booked or invalid."
            assigned_coach = matching_seat["coach"]
            
        # 5. Insert Booking Record
        booking_id = _gen_booking_id()
        cur.execute("""
            INSERT INTO national_rail_bookings (
                booking_id, user_id, schedule_id, origin_station_id, destination_station_id,
                travel_date, departure_time, ticket_type, fare_class, coach, seat_id,
                stops_travelled, amount_usd, status, booked_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            RETURNING booking_id, user_id, schedule_id, origin_station_id, destination_station_id,
                      travel_date::text, departure_time::text, ticket_type, fare_class, coach, seat_id,
                      stops_travelled, amount_usd::float, status, booked_at::text;
        """, (
            booking_id, user_uuid, schedule_id, origin_station_id, destination_station_id,
            travel_date, departure_time, ticket_type, fare_class, assigned_coach, assigned_seat_id,
            stops_travelled, amount, "confirmed"
        ))
        booking_dict = dict(cur.fetchone())
        
        # 6. Insert Payment Record
        payment_id = _gen_payment_id()
        cur.execute("""
            INSERT INTO payments (
                payment_id, national_booking_id, metro_trip_id, amount_usd, method, status, paid_at
            ) VALUES (%s, %s, NULL, %s, %s, %s, NOW());
        """, (payment_id, booking_id, amount, "credit_card", "paid"))
        
        conn.commit()
        return True, booking_dict
        
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        cur.close()
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
    conn = _connect()
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    try:
        # 1. Resolve UUID for the user_id if passed as "RUxx"
        user_uuid = user_id
        if user_id.startswith("RU"):
            cur.execute("SELECT user_id FROM registered_users WHERE email LIKE %s;", (f"{user_id.lower()}%",))
            user_row = cur.fetchone()
            if user_row:
                user_uuid = user_row["user_id"]
            else:
                num = int(user_id[2:])
                user_uuid = f"00000000-0000-0000-0000-{num:012d}"
                
        # 2. Fetch booking and joined schedule details
        cur.execute("""
            SELECT 
                b.booking_id,
                b.user_id,
                b.amount_usd,
                b.travel_date::text AS travel_date,
                b.departure_time::text AS departure_time,
                s.service_type,
                b.status
            FROM national_rail_bookings b
            JOIN national_rail_schedules s ON b.schedule_id = s.schedule_id
            WHERE b.booking_id = %s;
        """, (booking_id,))
        booking = cur.fetchone()
        
        if not booking:
            return False, "Booking not found."
            
        if str(booking["user_id"]) != str(user_uuid):
            return False, "Unauthorised: user does not own this booking."
            
        if booking["status"] == "cancelled":
            return False, "Booking is already cancelled."
            
        # 3. Calculate time difference
        departure_str = f"{booking['travel_date']} {booking['departure_time']}"
        departure_dt = datetime.strptime(departure_str, "%Y-%m-%d %H:%M:%S")
        
        # Calculate hours difference
        now = datetime.now()
        time_diff = departure_dt - now
        hours_before = time_diff.total_seconds() / 3600.0
        
        # Determine refund percentage and fee
        refund_percent = 0
        admin_fee = 0.0
        policy_note = ""
        service = booking["service_type"]
        ticket_price = float(booking["amount_usd"])
        
        if service == "normal":
            if hours_before >= 48:
                refund_percent = 100
                admin_fee = 0.00
                policy_note = "Normal service cancellation requested >= 48 hours before departure. 100% refund."
            elif 24 <= hours_before < 48:
                refund_percent = 75
                admin_fee = 0.50
                policy_note = "Normal service cancellation requested between 24 and 48 hours before departure. 75% refund."
            elif 2 <= hours_before < 24:
                refund_percent = 50
                admin_fee = 0.50
                policy_note = "Normal service cancellation requested between 2 and 24 hours before departure. 50% refund."
            else:
                refund_percent = 0
                admin_fee = 0.00
                policy_note = "Normal service cancellation requested < 2 hours before departure. No refund."
        else: # express
            if hours_before >= 48:
                refund_percent = 100
                admin_fee = 1.00
                policy_note = "Express service cancellation requested >= 48 hours before departure. 100% refund."
            elif 24 <= hours_before < 48:
                refund_percent = 50
                admin_fee = 1.00
                policy_note = "Express service cancellation requested between 24 and 48 hours before departure. 50% refund."
            else:
                refund_percent = 0
                admin_fee = 0.00
                policy_note = "Express service cancellation requested < 24 hours before departure. No refund."
                
        # Calculate final refund amount
        refund_amount = max(0.00, round((ticket_price * refund_percent / 100.0) - admin_fee, 2))
        
        # 4. Perform DB updates
        # Update booking status
        cur.execute("""
            UPDATE national_rail_bookings
            SET status = 'cancelled', deleted_at = NOW()
            WHERE booking_id = %s;
        """, (booking_id,))
        
        # Update payment record
        cur.execute("""
            UPDATE payments
            SET status = 'refunded', amount_usd = %s, deleted_at = NOW()
            WHERE national_booking_id = %s;
        """, (refund_amount, booking_id))
        
        conn.commit()
        return True, {
            "booking_id": booking_id,
            "refund_amount_usd": refund_amount,
            "policy_note": policy_note,
            "status": "cancelled"
        }
        
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        cur.close()
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
    """
    import uuid
    conn = _connect()
    conn.autocommit = False
    cur = conn.cursor()
    
    try:
        # Check if email already exists
        cur.execute("SELECT user_id FROM registered_users WHERE email = %s;", (email,))
        if cur.fetchone():
            return False, f"Registration failed: Email {email} is already registered."
            
        user_uuid = str(uuid.uuid4())
        full_name = f"{first_name} {surname}"
        dob = f"{year_of_birth}-01-01" # Estimated date of birth
        
        # 1. Insert into registered_users
        cur.execute("""
            INSERT INTO registered_users (user_id, full_name, email, date_of_birth, registered_at, is_active)
            VALUES (%s, %s, %s, %s, NOW(), TRUE);
        """, (user_uuid, full_name, email, dob))
        
        # 2. Insert into user_credentials
        cur.execute("""
            INSERT INTO user_credentials (user_id, password_hash, secret_question, secret_answer, updated_at)
            VALUES (%s, %s, %s, %s, NOW());
        """, (user_uuid, password, secret_question, secret_answer))
        
        conn.commit()
        return True, user_uuid
        
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        cur.close()
        conn.close()


def login_user(email: str, password: str) -> Optional[dict]:
    """
    Verify credentials. Returns a user dict on success or None on failure.
    Dict keys: user_id, email, full_name, first_name, surname, phone, date_of_birth, is_active.
    """
    sql = """
        SELECT u.user_id, u.email, u.full_name, u.phone, u.date_of_birth::text AS date_of_birth, u.is_active
        FROM registered_users u
        JOIN user_credentials c ON u.user_id = c.user_id
        WHERE u.email = %s AND c.password_hash = %s AND u.is_active = TRUE;
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (email, password))
            row = cur.fetchone()
            if not row:
                return None
                
            user_dict = dict(row)
            # Parse first_name and surname from full_name
            full_name = user_dict.get("full_name") or ""
            parts = full_name.split(" ", 1)
            user_dict["first_name"] = parts[0] if len(parts) > 0 else ""
            user_dict["surname"] = parts[1] if len(parts) > 1 else ""
            return user_dict


def get_user_secret_question(email: str) -> Optional[str]:
    """Return the secret question for a registered email, or None if not found."""
    sql = """
        SELECT c.secret_question
        FROM registered_users u
        JOIN user_credentials c ON u.user_id = c.user_id
        WHERE u.email = %s AND u.is_active = TRUE;
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (email,))
            row = cur.fetchone()
            return row[0] if row else None


def verify_secret_answer(email: str, answer: str) -> bool:
    """Return True if the provided answer matches the stored secret answer (case-insensitive)."""
    sql = """
        SELECT c.secret_answer
        FROM registered_users u
        JOIN user_credentials c ON u.user_id = c.user_id
        WHERE u.email = %s AND u.is_active = TRUE;
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (email,))
            row = cur.fetchone()
            if not row:
                return False
            return row[0].strip().lower() == answer.strip().lower()


def update_password(email: str, new_password: str) -> bool:
    """Update the password for a user. Returns True if the row was updated."""
    conn = _connect()
    conn.autocommit = False
    cur = conn.cursor()
    
    try:
        # Get user_id by email
        cur.execute("SELECT user_id FROM registered_users WHERE email = %s AND is_active = TRUE;", (email,))
        row = cur.fetchone()
        if not row:
            return False
        user_uuid = row[0]
        
        # Update user_credentials
        cur.execute("""
            UPDATE user_credentials
            SET password_hash = %s, updated_at = NOW()
            WHERE user_id = %s;
        """, (new_password, user_uuid))
        
        conn.commit()
        return cur.rowcount > 0
        
    except Exception:
        conn.rollback()
        return False
    finally:
        cur.close()
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
