"""
Seed PostgreSQL with all TransitFlow mock data from train-mock-data/.

Usage:
    python skeleton/seed_postgres.py

Run AFTER docker-compose up -d.
You must first design and create your tables in databases/relational/schema.sql.
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
from databases.relational.queries import _hash_password


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


# ── global session state for random UUID mapping (Scheme A) ──────────────────
USER_UUID_MAP = {}


# ── seeders ──────────────────────────────────────────────────────────────────

def seed_metro_stations(cur):
    data = load("metro_stations.json")
    
    # 1. metro_stations
    stations_rows = [
        (s["station_id"], s["name"], s["is_interchange_metro"], s["is_interchange_national_rail"], True)
        for s in data
    ]
    insert_many(cur, "metro_stations", ["station_id", "name", "is_interchange_metro", "is_interchange_national_rail", "is_active"], stations_rows)
    
    # 2. metro_station_lines
    lines_rows = []
    for s in data:
        for line in s["lines"]:
            lines_rows.append((s["station_id"], line))
    insert_many(cur, "metro_station_lines", ["station_id", "line"], lines_rows)
    
    # 3. metro_station_adjacents
    adj_rows = []
    for s in data:
        for adj in s["adjacent_stations"]:
            adj_rows.append((s["station_id"], adj["station_id"], adj["line"], adj["travel_time_min"]))
    insert_many(cur, "metro_station_adjacents", ["station_id", "adjacent_station_id", "line", "travel_time_min"], adj_rows)
    
    print(f"  metro_stations seeded: {len(data)} stations, {len(lines_rows)} lines mapping, {len(adj_rows)} adjacencies")


def seed_national_rail_stations(cur):
    data = load("national_rail_stations.json")
    
    # 1. national_rail_stations
    stations_rows = [
        (s["station_id"], s["name"], s["is_interchange_national_rail"], s["is_interchange_metro"], True)
        for s in data
    ]
    insert_many(cur, "national_rail_stations", ["station_id", "name", "is_interchange_national_rail", "is_interchange_metro", "is_active"], stations_rows)
    
    # 2. national_rail_station_lines
    lines_rows = []
    for s in data:
        for line in s["lines"]:
            lines_rows.append((s["station_id"], line))
    insert_many(cur, "national_rail_station_lines", ["station_id", "line"], lines_rows)
    
    # 3. national_rail_station_adjacents
    adj_rows = []
    for s in data:
        for adj in s["adjacent_stations"]:
            adj_rows.append((s["station_id"], adj["station_id"], adj["line"], adj["travel_time_min"]))
    insert_many(cur, "national_rail_station_adjacents", ["station_id", "adjacent_station_id", "line", "travel_time_min"], adj_rows)
    
    # 4. station_interchanges
    interchange_rows = []
    for s in data:
        if s["is_interchange_metro"] and s["interchange_metro_station_id"]:
            # Insert standard 5-minute interchange walk
            interchange_rows.append((s["interchange_metro_station_id"], s["station_id"], 5))
    insert_many(cur, "station_interchanges", ["metro_station_id", "national_rail_station_id", "transfer_time_min"], interchange_rows)
    
    print(f"  national_rail_stations seeded: {len(data)} stations, {len(lines_rows)} lines mapping, {len(adj_rows)} adjacencies, {len(interchange_rows)} cross-network interchanges")


def seed_metro_schedules(cur):
    data = load("metro_schedules.json")
    
    # 1. metro_schedules
    sched_rows = [
        (
            s["schedule_id"],
            s["line"],
            s["direction"],
            s["origin_station_id"],
            s["destination_station_id"],
            s["first_train_time"],
            s["last_train_time"],
            s["base_fare_usd"],
            s["per_stop_rate_usd"],
            s["frequency_min"],
            True
        )
        for s in data
    ]
    insert_many(
        cur,
        "metro_schedules",
        [
            "schedule_id", "line", "direction", "origin_station_id", "destination_station_id",
            "first_train_time", "last_train_time", "base_fare_usd", "per_stop_rate_usd", "frequency_min", "is_active"
        ],
        sched_rows
    )
    
    # 2. metro_schedule_stops
    stops_rows = []
    for s in data:
        for order, station_id in enumerate(s["stops_in_order"]):
            time_from_orig = s["travel_time_from_origin_min"][station_id]
            stops_rows.append((s["schedule_id"], station_id, order, time_from_orig))
    insert_many(cur, "metro_schedule_stops", ["schedule_id", "station_id", "stop_order", "travel_time_from_origin_min"], stops_rows)
    
    # 3. metro_schedule_operates
    ops_rows = []
    for s in data:
        for day in s["operates_on"]:
            ops_rows.append((s["schedule_id"], day))
    insert_many(cur, "metro_schedule_operates", ["schedule_id", "day_of_week"], ops_rows)
    
    print(f"  metro_schedules seeded: {len(data)} schedules, {len(stops_rows)} scheduled stops, {len(ops_rows)} operating days mapping")


def seed_national_rail_schedules(cur):
    data = load("national_rail_schedules.json")
    
    PHYSICAL_STATIONS = {
        ("NR1", "northbound"): ["NR01", "NR02", "NR03", "NR04", "NR05"],
        ("NR1", "southbound"): ["NR05", "NR04", "NR03", "NR02", "NR01"],
        ("NR2", "eastbound"): ["NR01", "NR06", "NR07", "NR08", "NR09", "NR10"],
        ("NR2", "westbound"): ["NR10", "NR09", "NR08", "NR07", "NR06", "NR01"],
    }
    
    NORMAL_ROUTE_TIMES = {
        ("NR1", "northbound"): {"NR01": 0, "NR02": 12, "NR03": 30, "NR04": 45, "NR05": 65},
        ("NR1", "southbound"): {"NR05": 0, "NR04": 20, "NR03": 35, "NR02": 53, "NR01": 65},
        ("NR2", "eastbound"): {"NR01": 0, "NR06": 14, "NR07": 30, "NR08": 52, "NR09": 74, "NR10": 93},
        ("NR2", "westbound"): {"NR10": 0, "NR09": 19, "NR08": 38, "NR07": 60, "NR06": 76, "NR01": 90},
    }
    
    # 1. national_rail_schedules
    sched_rows = []
    for s in data:
        # Determine shared layout template
        layout_id = None
        if "SCH01" in s["schedule_id"] or "SCH05" in s["schedule_id"]:
            layout_id = "SL01"
        elif "SCH02" in s["schedule_id"] or "SCH06" in s["schedule_id"]:
            layout_id = "SL02"
        elif "SCH03" in s["schedule_id"] or "SCH07" in s["schedule_id"]:
            layout_id = "SL03"
        elif "SCH04" in s["schedule_id"] or "SCH08" in s["schedule_id"]:
            layout_id = "SL04"
            
        sched_rows.append((
            s["schedule_id"],
            s["line"],
            s["service_type"],
            s["direction"],
            s["origin_station_id"],
            s["destination_station_id"],
            s["first_train_time"],
            s["last_train_time"],
            s["frequency_min"],
            layout_id,
            True
        ))
        
    insert_many(
        cur,
        "national_rail_schedules",
        [
            "schedule_id", "line", "service_type", "direction", "origin_station_id", "destination_station_id",
            "first_train_time", "last_train_time", "frequency_min", "layout_id", "is_active"
        ],
        sched_rows
    )
    
    # 2. national_rail_schedule_stops (with express interpolation)
    stops_rows = []
    for s in data:
        line = s["line"]
        direction = s["direction"]
        dest = s["destination_station_id"]
        stops_in_order = s["stops_in_order"]
        passed_through = s.get("passed_through_stations", [])
        
        # Get standard physical stations sequence
        physical_seq = PHYSICAL_STATIONS[(line, direction)]
        
        # Get normal travel times for scaling
        normal_times = NORMAL_ROUTE_TIMES[(line, direction)]
        normal_total_time = normal_times[dest]
        
        # Current travel time mapping from JSON
        travel_times = s["travel_time_from_origin_min"]
        express_total_time = travel_times[dest]
        
        # We loop through the physical sequence to preserve order and insert stops/passings
        for order, station_id in enumerate(physical_seq):
            if station_id in stops_in_order:
                is_stop = True
                time_from_orig = travel_times[station_id]
                stops_rows.append((s["schedule_id"], station_id, order, time_from_orig, is_stop))
            elif station_id in passed_through:
                is_stop = False
                # Interpolate time_from_orig based on normal route ratio
                normal_time_st = normal_times[station_id]
                time_from_orig = int(round(normal_time_st * (express_total_time / normal_total_time)))
                stops_rows.append((s["schedule_id"], station_id, order, time_from_orig, is_stop))
                
    insert_many(
        cur,
        "national_rail_schedule_stops",
        ["schedule_id", "station_id", "stop_order", "travel_time_from_origin_min", "is_stop"],
        stops_rows
    )
    
    # 3. national_rail_schedule_operates
    ops_rows = []
    for s in data:
        for day in s["operates_on"]:
            ops_rows.append((s["schedule_id"], day))
    insert_many(cur, "national_rail_schedule_operates", ["schedule_id", "day_of_week"], ops_rows)
    
    # 4. national_rail_schedule_fares
    fares_rows = []
    for s in data:
        for fare_class, rates in s["fare_classes"].items():
            fares_rows.append((s["schedule_id"], fare_class, rates["base_fare_usd"], rates["per_stop_rate_usd"]))
    insert_many(cur, "national_rail_schedule_fares", ["schedule_id", "fare_class", "base_fare_usd", "per_stop_rate_usd"], fares_rows)
    
    print(f"  national_rail_schedules seeded: {len(data)} schedules, {len(stops_rows)} scheduled/passed stops, {len(ops_rows)} operating days, {len(fares_rows)} class fares")


def seed_seat_layouts(cur):
    data = load("national_rail_seat_layouts.json")
    
    # 1. national_rail_seat_layouts (only layout_id exists now)
    layouts_rows = [(s["layout_id"],) for s in data]
    insert_many(cur, "national_rail_seat_layouts", ["layout_id"], layouts_rows)
    
    # 2. national_rail_coaches
    coaches_rows = []
    # 3. national_rail_seats
    seats_rows = []
    
    for s in data:
        layout_id = s["layout_id"]
        for coach_info in s["coaches"]:
            coach = coach_info["coach"]
            fare_class = coach_info["fare_class"]
            coaches_rows.append((layout_id, coach, fare_class))
            
            for seat in coach_info["seats"]:
                seats_rows.append((layout_id, coach, seat["seat_id"], seat["row"], seat["column"]))
                
    insert_many(cur, "national_rail_coaches", ["layout_id", "coach", "fare_class"], coaches_rows)
    insert_many(cur, "national_rail_seats", ["layout_id", "coach", "seat_id", "row", "seat_column"], seats_rows)
    
    print(f"  seat_layouts templates seeded: {len(layouts_rows)} layouts, {len(coaches_rows)} coaches, {len(seats_rows)} seats")


def seed_users(cur):
    data = load("registered_users.json")
    
    # Scheme A: 產生確定性 UUID 並填充用戶對照表
    # 【工業級優化點：確定性 UUID (Deterministic UUID)】
    # 原本使用 uuid.uuid4() 在重覆執行 seed_postgres.py 時會生成隨機新 UUID。
    # 當新 UUID 因為 email UNIQUE 約束被資料庫略過（DO NOTHING）時，
    # 記憶體中的 USER_UUID_MAP 會留下未寫入資料庫的 UUID，導致後續插入 bookings 時發生外鍵約束衝突 (FK Violation)。
    # 改用 uuid.uuid5 基於 NAMESPACE_DNS 與 mock user_id 可確保每次執行都取得完全相同的 UUID，支持安全重複執行。
    users_rows = []
    creds_rows = []
    
    for u in data:
        ru_id = u["user_id"]
        real_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, u["user_id"]))
        USER_UUID_MAP[ru_id] = real_uuid
        
        users_rows.append((
            real_uuid,
            u["full_name"],
            u["email"],
            u["phone"],
            u["date_of_birth"],
            u["registered_at"],
            u["is_active"]
        ))
        
        # 【工業級優化點：高強度密碼雜湊 PBKDF2】
        # 教學範例原本直接將密碼明文存入資料庫，這在生產環境下是非常嚴重的安全漏洞。
        # 這裡改用從 queries 導入的 PBKDF2 密碼雜湊算法，確保資料庫中完全不儲存任何明文。
        creds_rows.append((
            real_uuid,
            _hash_password(u["password"]),  # 儲存安全 PBKDF2 密碼雜湊
            u["secret_question"],
            u["secret_answer"]
        ))
        
    insert_many(
        cur,
        "registered_users",
        ["user_id", "full_name", "email", "phone", "date_of_birth", "registered_at", "is_active"],
        users_rows
    )
    
    insert_many(
        cur,
        "user_credentials",
        ["user_id", "password_hash", "secret_question", "secret_answer"],
        creds_rows
    )
    
    print(f"  registered_users & credentials seeded: {len(data)} users (mapped with secure random UUIDs)")


def seed_national_rail_bookings(cur):
    data = load("bookings.json")
    
    bookings_rows = []
    for b in data:
        user_uuid = USER_UUID_MAP[b["user_id"]]
        bookings_rows.append((
            b["booking_id"],
            user_uuid,
            b["schedule_id"],
            b["origin_station_id"],
            b["destination_station_id"],
            b["travel_date"],
            b["departure_time"],
            b["ticket_type"],
            b["fare_class"],
            b["coach"],
            b["seat_id"],
            b["stops_travelled"],
            b["amount_usd"],
            b["status"],
            b["booked_at"],
            b.get("travelled_at")
        ))
        
    insert_many(
        cur,
        "national_rail_bookings",
        [
            "booking_id", "user_id", "schedule_id", "origin_station_id", "destination_station_id",
            "travel_date", "departure_time", "ticket_type", "fare_class", "coach", "seat_id",
            "stops_travelled", "amount_usd", "status", "booked_at", "travelled_at"
        ],
        bookings_rows
    )
    print(f"  national_rail_bookings seeded: {len(data)} records")


def seed_metro_travels(cur):
    data = load("metro_travel_history.json")
    
    travel_rows = []
    for t in data:
        user_uuid = USER_UUID_MAP[t["user_id"]]
        travel_rows.append((
            t["trip_id"],
            user_uuid,
            t["schedule_id"],
            t["origin_station_id"],
            t["destination_station_id"],
            t["travel_date"],
            t["ticket_type"],
            t.get("day_pass_ref"),
            t.get("stops_travelled"),
            t["amount_usd"],
            t["status"],
            t.get("purchased_at"),
            t.get("travelled_at")
        ))
        
    insert_many(
        cur,
        "metro_travel_history",
        [
            "trip_id", "user_id", "schedule_id", "origin_station_id", "destination_station_id",
            "travel_date", "ticket_type", "day_pass_ref", "stops_travelled", "amount_usd", "status",
            "purchased_at", "travelled_at"
        ],
        travel_rows
    )
    print(f"  metro_travel_history seeded: {len(data)} records")


def seed_payments(cur):
    data = load("payments.json")
    
    payments_rows = []
    for p in data:
        booking_id = p["booking_id"]
        
        # Polymorphic foreign keys resolution
        national_booking_id = booking_id if booking_id.startswith("BK") else None
        metro_trip_id = booking_id if booking_id.startswith("MT") else None
        
        payments_rows.append((
            p["payment_id"],
            national_booking_id,
            metro_trip_id,
            p["amount_usd"],
            p["method"],
            p["status"],
            p["paid_at"]
        ))
        
    insert_many(
        cur,
        "payments",
        ["payment_id", "national_booking_id", "metro_trip_id", "amount_usd", "method", "status", "paid_at"],
        payments_rows
    )
    print(f"  payments seeded: {len(data)} polymorphic records")


def seed_feedback(cur):
    data = load("feedback.json")
    
    feedback_rows = []
    for f in data:
        booking_id = f["booking_id"]
        user_uuid = USER_UUID_MAP[f["user_id"]]
        
        # Polymorphic foreign keys resolution
        national_booking_id = booking_id if booking_id.startswith("BK") else None
        metro_trip_id = booking_id if booking_id.startswith("MT") else None
        
        feedback_rows.append((
            f["feedback_id"],
            national_booking_id,
            metro_trip_id,
            user_uuid,
            f["rating"],
            f["comment"],
            f["submitted_at"]
        ))
        
    insert_many(
        cur,
        "feedback",
        ["feedback_id", "national_booking_id", "metro_trip_id", "user_id", "rating", "comment", "submitted_at"],
        feedback_rows
    )
    print(f"  feedback seeded: {len(data)} polymorphic records")


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    print("Connecting to PostgreSQL...")
    conn = connect()
    conn.autocommit = False
    cur = conn.cursor()

    try:
        print("Seeding tables (dependency order):")
        seed_metro_stations(cur)
        seed_national_rail_stations(cur)
        seed_metro_schedules(cur)
        seed_seat_layouts(cur)  # Must be seeded before national rail schedules now
        seed_national_rail_schedules(cur)
        seed_users(cur)
        seed_national_rail_bookings(cur)
        seed_metro_travels(cur)
        seed_payments(cur)
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
