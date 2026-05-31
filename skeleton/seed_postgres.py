"""
Seed PostgreSQL with all TransitFlow mock data from train-mock-data/.

Usage:
    python skeleton/seed_postgres.py

Run AFTER docker-compose up -d.
Safe to re-run: implement your inserts with ON CONFLICT DO NOTHING.
"""

import json
import os
import sys
import uuid

import psycopg2
from psycopg2.extras import execute_values

# ── resolve paths ────────────────────────────────────────────────────────────
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR    = os.path.join(PROJECT_DIR, "train-mock-data")

sys.path.insert(0, PROJECT_DIR)
from skeleton import config as cfg


def load(filename):
    with open(os.path.join(DATA_DIR, filename), encoding="utf-8") as f:
        return json.load(f)


def connect():
    return psycopg2.connect(
        host=cfg.PG_HOST,
        port=cfg.PG_PORT,
        dbname=cfg.PG_DB,
        user=cfg.PG_USER,
        password=cfg.PG_PASSWORD,
    )


def insert_many(cur, table, columns, rows):
    """Bulk insert with ON CONFLICT DO NOTHING. Returns row count inserted."""
    if not rows:
        return 0
    sql = (
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES %s "
        f"ON CONFLICT DO NOTHING"
    )
    execute_values(cur, sql, rows)
    return cur.rowcount


def to_uuid(id_str):
    """Deterministically convert any string ID like 'RU01' to a UUID format."""
    if not id_str:
        return None
    try:
        return str(uuid.UUID(id_str))
    except ValueError:
        pass
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"transitflow.{id_str}"))


# ── seeders ──────────────────────────────────────────────────────────────────

def seed_metro_stations(cur):
    data = load("metro_stations.json")
    # Pass 1: stations
    for station in data:
        cur.execute(
            """
            INSERT INTO metro_stations (station_id, name, is_interchange_metro, is_interchange_national_rail, is_active)
            VALUES (%s, %s, %s, %s, TRUE)
            ON CONFLICT (station_id) DO NOTHING
            """,
            (station["station_id"], station["name"], station["is_interchange_metro"], station["is_interchange_national_rail"])
        )
    # Pass 2: lines and adjacents
    for station in data:
        for line in station["lines"]:
            cur.execute(
                """
                INSERT INTO metro_station_lines (station_id, line)
                VALUES (%s, %s)
                ON CONFLICT (station_id, line) DO NOTHING
                """,
                (station["station_id"], line)
            )
        for adj in station["adjacent_stations"]:
            cur.execute(
                """
                INSERT INTO metro_station_adjacents (station_id, adjacent_station_id, line, travel_time_min)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (station_id, adjacent_station_id, line) DO NOTHING
                """,
                (station["station_id"], adj["station_id"], adj["line"], adj["travel_time_min"])
            )


def seed_national_rail_stations(cur):
    data = load("national_rail_stations.json")
    # Pass 1: stations
    for station in data:
        cur.execute(
            """
            INSERT INTO national_rail_stations (station_id, name, is_interchange_national_rail, is_interchange_metro, is_active)
            VALUES (%s, %s, %s, %s, TRUE)
            ON CONFLICT (station_id) DO NOTHING
            """,
            (station["station_id"], station["name"], station["is_interchange_national_rail"], station["is_interchange_metro"])
        )
    # Pass 2: lines, adjacents, and interchanges
    for station in data:
        for line in station["lines"]:
            cur.execute(
                """
                INSERT INTO national_rail_station_lines (station_id, line)
                VALUES (%s, %s)
                ON CONFLICT (station_id, line) DO NOTHING
                """,
                (station["station_id"], line)
            )
        for adj in station["adjacent_stations"]:
            cur.execute(
                """
                INSERT INTO national_rail_station_adjacents (station_id, adjacent_station_id, line, travel_time_min)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (station_id, adjacent_station_id, line) DO NOTHING
                """,
                (station["station_id"], adj["station_id"], adj["line"], adj["travel_time_min"])
            )
        # Seed interchanges
        if station.get("is_interchange_metro") and station.get("interchange_metro_station_id"):
            cur.execute(
                """
                INSERT INTO station_interchanges (metro_station_id, national_rail_station_id, transfer_time_min)
                VALUES (%s, %s, 5)
                ON CONFLICT (metro_station_id, national_rail_station_id) DO NOTHING
                """,
                (station["interchange_metro_station_id"], station["station_id"])
            )


def seed_metro_schedules(cur):
    data = load("metro_schedules.json")
    for schedule in data:
        stops_in_order_json = json.dumps(schedule["stops_in_order"])
        travel_time_json = json.dumps(schedule["travel_time_from_origin_min"])
        operates_on_json = json.dumps(schedule["operates_on"])
        cur.execute(
            """
            INSERT INTO metro_schedules (
                schedule_id, line, direction, origin_station_id, destination_station_id,
                stops_in_order, travel_time_from_origin_min, first_train_time, last_train_time,
                base_fare_usd, per_stop_rate_usd, frequency_min, operates_on, is_active
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE)
            ON CONFLICT (schedule_id) DO NOTHING
            """,
            (
                schedule["schedule_id"], schedule["line"], schedule["direction"],
                schedule["origin_station_id"], schedule["destination_station_id"],
                stops_in_order_json, travel_time_json, schedule["first_train_time"],
                schedule["last_train_time"], schedule["base_fare_usd"],
                schedule["per_stop_rate_usd"], schedule["frequency_min"], operates_on_json
            )
        )


def seed_national_rail_schedules(cur):
    data = load("national_rail_schedules.json")
    for schedule in data:
        stops_in_order_json = json.dumps(schedule["stops_in_order"])
        passed_through_json = json.dumps(schedule.get("passed_through_stations", []))
        travel_time_json = json.dumps(schedule["travel_time_from_origin_min"])
        operates_on_json = json.dumps(schedule["operates_on"])
        cur.execute(
            """
            INSERT INTO national_rail_schedules (
                schedule_id, line, service_type, direction, origin_station_id, destination_station_id,
                stops_in_order, passed_through_stations, travel_time_from_origin_min, first_train_time, last_train_time,
                frequency_min, operates_on, is_active
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE)
            ON CONFLICT (schedule_id) DO NOTHING
            """,
            (
                schedule["schedule_id"], schedule["line"], schedule["service_type"], schedule["direction"],
                schedule["origin_station_id"], schedule["destination_station_id"],
                stops_in_order_json, passed_through_json, travel_time_json, schedule["first_train_time"],
                schedule["last_train_time"], schedule["frequency_min"], operates_on_json
            )
        )
        
        # Seed fares
        for fare_class, fares in schedule["fare_classes"].items():
            cur.execute(
                """
                INSERT INTO national_rail_schedule_fares (
                    schedule_id, fare_class, base_fare_usd, per_stop_rate_usd
                ) VALUES (%s, %s, %s, %s)
                ON CONFLICT (schedule_id, fare_class) DO NOTHING
                """,
                (
                    schedule["schedule_id"], fare_class, fares["base_fare_usd"], fares["per_stop_rate_usd"]
                )
            )


def seed_seat_layouts(cur):
    data = load("national_rail_seat_layouts.json")
    for layout in data:
        cur.execute(
            """
            INSERT INTO national_rail_seat_layouts (layout_id, schedule_id)
            VALUES (%s, %s)
            ON CONFLICT (layout_id) DO NOTHING
            """,
            (layout["layout_id"], layout["schedule_id"])
        )
        for coach in layout["coaches"]:
            cur.execute(
                """
                INSERT INTO national_rail_coaches (layout_id, coach, fare_class)
                VALUES (%s, %s, %s)
                ON CONFLICT (layout_id, coach) DO NOTHING
                """,
                (layout["layout_id"], coach["coach"], coach["fare_class"])
            )
            for seat in coach["seats"]:
                cur.execute(
                    """
                    INSERT INTO national_rail_seats (layout_id, coach, seat_id, row, seat_column)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (layout_id, coach, seat_id) DO NOTHING
                    """,
                    (layout["layout_id"], coach["coach"], seat["seat_id"], seat["row"], seat["column"])
                )


def seed_users(cur):
    data = load("registered_users.json")
    for u in data:
        user_uuid = to_uuid(u["user_id"])
        cur.execute(
            """
            INSERT INTO registered_users (user_id, full_name, email, phone, date_of_birth, registered_at, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id) DO NOTHING
            """,
            (user_uuid, u["full_name"], u["email"], u["phone"], u["date_of_birth"], u["registered_at"], u["is_active"])
        )
        cur.execute(
            """
            INSERT INTO user_credentials (user_id, password_hash, secret_question, secret_answer_hash)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id) DO NOTHING
            """,
            (user_uuid, u["password"], u["secret_question"], u["secret_answer"])
        )


def seed_national_rail_bookings(cur):
    data = load("bookings.json")
    stations = load("national_rail_stations.json")
    station_names = {s["station_id"]: s["name"] for s in stations}
    for booking in data:
        origin_name = station_names[booking["origin_station_id"]]
        dest_name = station_names[booking["destination_station_id"]]
        cur.execute(
            """
            INSERT INTO national_rail_bookings (
                booking_id, user_id, schedule_id, origin_station_id, origin_station_name,
                destination_station_id, destination_station_name, travel_date, departure_time,
                ticket_type, fare_class, coach, seat_id, stops_travelled, amount_usd,
                status, booked_at, travelled_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (booking_id) DO NOTHING
            """,
            (
                booking["booking_id"], to_uuid(booking["user_id"]), booking["schedule_id"],
                booking["origin_station_id"], origin_name,
                booking["destination_station_id"], dest_name,
                booking["travel_date"], booking["departure_time"],
                booking["ticket_type"], booking["fare_class"], booking["coach"],
                booking["seat_id"], booking["stops_travelled"], booking["amount_usd"],
                booking["status"], booking["booked_at"], booking["travelled_at"]
            )
        )


def seed_metro_travels(cur):
    data = load("metro_travel_history.json")
    stations = load("metro_stations.json")
    station_names = {s["station_id"]: s["name"] for s in stations}
    for trip in data:
        origin_name = station_names[trip["origin_station_id"]]
        dest_name = station_names[trip["destination_station_id"]]
        
        pass_id_ref = None
        if trip["ticket_type"] == "day_pass":
            ref = trip.get("day_pass_ref")
            if ref is None:
                pass_id = trip["trip_id"]
                expires_at = None
                if trip["travel_date"]:
                    expires_at = f"{trip['travel_date']}T23:59:59Z"
                
                cur.execute(
                    """
                    INSERT INTO metro_passes (pass_id, user_id, pass_type, expires_at, created_at)
                    VALUES (%s, %s, 'DAY_PASS', %s, %s)
                    ON CONFLICT (pass_id) DO NOTHING
                    """,
                    (pass_id, to_uuid(trip["user_id"]), expires_at, trip["purchased_at"])
                )
                pass_id_ref = pass_id
            else:
                pass_id_ref = ref

        cur.execute(
            """
            INSERT INTO metro_travel_history (
                trip_id, user_id, schedule_id, origin_station_id, origin_station_name,
                destination_station_id, destination_station_name, travel_date, ticket_type,
                pass_id_ref, stops_travelled, amount_usd, status, purchased_at, travelled_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (trip_id) DO NOTHING
            """,
            (
                trip["trip_id"], to_uuid(trip["user_id"]), trip["schedule_id"],
                trip["origin_station_id"], origin_name,
                trip["destination_station_id"], dest_name,
                trip["travel_date"], trip["ticket_type"], pass_id_ref,
                trip["stops_travelled"], trip["amount_usd"], trip["status"],
                trip.get("purchased_at"), trip.get("travelled_at")
            )
        )


def seed_payments(cur):
    data = load("payments.json")
    for pm in data:
        ref = pm["booking_id"]
        national_booking_id = ref if ref.startswith("BK") else None
        metro_trip_id = ref if ref.startswith("MT") else None
        cur.execute(
            """
            INSERT INTO payments (payment_id, national_booking_id, metro_trip_id, amount_usd, method, status, paid_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (payment_id) DO NOTHING
            """,
            (pm["payment_id"], national_booking_id, metro_trip_id, pm["amount_usd"], pm["method"], pm["status"], pm["paid_at"])
        )


def seed_feedback(cur):
    data = load("feedback.json")
    for fb in data:
        ref = fb["booking_id"]
        national_booking_id = ref if ref.startswith("BK") else None
        metro_trip_id = ref if ref.startswith("MT") else None
        cur.execute(
            """
            INSERT INTO feedback (feedback_id, national_booking_id, metro_trip_id, user_id, rating, comment, submitted_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (feedback_id) DO NOTHING
            """,
            (fb["feedback_id"], national_booking_id, metro_trip_id, to_uuid(fb["user_id"]), fb["rating"], fb["comment"], fb["submitted_at"])
        )


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    print("Connecting to PostgreSQL...")
    conn = connect()
    conn.autocommit = False
    cur = conn.cursor()

    try:
        print("Seeding tables (dependency order):")
        
        print("- Metro stations...")
        seed_metro_stations(cur)
        
        print("- National rail stations...")
        seed_national_rail_stations(cur)
        
        print("- Metro schedules...")
        seed_metro_schedules(cur)
        
        print("- National rail schedules...")
        seed_national_rail_schedules(cur)
        
        print("- Seat layouts...")
        seed_seat_layouts(cur)
        
        print("- Users...")
        seed_users(cur)
        
        print("- Bookings...")
        seed_national_rail_bookings(cur)
        
        print("- Metro travels...")
        seed_metro_travels(cur)
        
        print("- Payments...")
        seed_payments(cur)
        
        print("- Feedback...")
        seed_feedback(cur)
        
        conn.commit()
        print("\nAll done. Database seeded successfully.")
    except Exception as e:
        conn.rollback()
        print(f"\nError: {e}")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
