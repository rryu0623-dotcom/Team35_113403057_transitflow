# TASK 6 EXTENSION: Added operator alerts seeding
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


def insert_many(cur, table, columns, rows, batch_size=2000):
    """Bulk insert in chunks with ON CONFLICT DO NOTHING. Returns total row count inserted."""
    if not rows:
        return 0
    total_inserted = 0
    for i in range(0, len(rows), batch_size):
        chunk = rows[i:i + batch_size]
        sql = (
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES %s "
            f"ON CONFLICT DO NOTHING"
        )
        execute_values(cur, sql, chunk)
        if cur.rowcount > 0:
            total_inserted += cur.rowcount
    return total_inserted


# ── global session state for random UUID mapping (Scheme A) ──────────────────
USER_UUID_MAP = {}


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
    
    # Build JSONB-compatible travel_time arrays (ordered by stops_in_order)
    sched_rows = []
    for s in data:
        # Convert travel_time_from_origin_min dict → ordered JSONB array matching stops_in_order
        time_array = [s["travel_time_from_origin_min"][sid] for sid in s["stops_in_order"]]
        sched_rows.append((
            s["schedule_id"],
            s["line"],
            s["direction"].strip().lower() if s.get("direction") else "northbound",
            s["origin_station_id"],
            s["destination_station_id"],
            json.dumps(s["stops_in_order"]),
            json.dumps(time_array),
            s["first_train_time"],
            s["last_train_time"],
            s["base_fare_usd"],
            s["per_stop_rate_usd"],
            s["frequency_min"],
            json.dumps(s["operates_on"]),
            True
        ))
    insert_many(
        cur,
        "metro_schedules",
        [
            "schedule_id", "line", "direction", "origin_station_id", "destination_station_id",
            "stops_in_order", "travel_time_from_origin_min",
            "first_train_time", "last_train_time", "base_fare_usd", "per_stop_rate_usd", "frequency_min",
            "operates_on", "is_active"
        ],
        sched_rows
    )
    
    print(f"  metro_schedules seeded: {len(data)} schedules (JSONB stops/operates embedded)")


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
    
    # 1. national_rail_schedules (with JSONB columns)
    sched_rows = []
    for s in data:
        # Convert travel_time_from_origin_min dict → ordered JSONB array matching stops_in_order
        time_array = [s["travel_time_from_origin_min"][sid] for sid in s["stops_in_order"]]
        sched_rows.append((
            s["schedule_id"],
            s["line"],
            s["service_type"].strip().lower() if s.get("service_type") else "normal",
            s["direction"].strip().lower() if s.get("direction") else "northbound",
            s["origin_station_id"],
            s["destination_station_id"],
            json.dumps(s["stops_in_order"]),
            json.dumps(s.get("passed_through_stations", [])),
            json.dumps(time_array),
            s["first_train_time"],
            s["last_train_time"],
            s["frequency_min"],
            json.dumps(s["operates_on"]),
            True
        ))
        
    insert_many(
        cur,
        "national_rail_schedules",
        [
            "schedule_id", "line", "service_type", "direction", "origin_station_id", "destination_station_id",
            "stops_in_order", "passed_through_stations", "travel_time_from_origin_min",
            "first_train_time", "last_train_time", "frequency_min",
            "operates_on", "is_active"
        ],
        sched_rows
    )
    
    # 2. national_rail_schedule_fares
    fares_rows = []
    for s in data:
        for fare_class, rates in s["fare_classes"].items():
            fares_rows.append((s["schedule_id"], fare_class.strip().lower(), rates["base_fare_usd"], rates["per_stop_rate_usd"]))
    insert_many(cur, "national_rail_schedule_fares", ["schedule_id", "fare_class", "base_fare_usd", "per_stop_rate_usd"], fares_rows)
    
    print(f"  national_rail_schedules seeded: {len(data)} schedules, {len(fares_rows)} class fares (JSONB stops/operates embedded)")


def seed_seat_layouts(cur):
    data = load("national_rail_seat_layouts.json")
    
    # 1. national_rail_seat_layouts (includes schedule_id reference in new schema)
    layouts_rows = [(s["layout_id"], s["schedule_id"]) for s in data]
    insert_many(cur, "national_rail_seat_layouts", ["layout_id", "schedule_id"], layouts_rows)
    
    # 2. national_rail_coaches
    coaches_rows = []
    # 3. national_rail_seats
    seats_rows = []
    
    for s in data:
        layout_id = s["layout_id"]
        for coach_info in s["coaches"]:
            coach = coach_info["coach"]
            fare_class = coach_info["fare_class"].strip().lower() if coach_info.get("fare_class") else "standard"
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
        
        # 【工業級優化點：高強度密碼與密保問答雜湊 PBKDF2】
        # 教學範例原本直接將密碼與密保答案明文存入資料庫，這在生產環境下是非常嚴重的安全漏洞。
        # 這裡改用從 queries 導入的 PBKDF2 密碼雜湊算法，確保資料庫中完全不儲存任何明文。
        creds_rows.append((
            real_uuid,
            _hash_password(u["password"]),  # 儲存安全 PBKDF2 密碼雜湊
            u["secret_question"],
            _hash_password(u["secret_answer"])  # 儲存安全 PBKDF2 密保答案雜湊
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
        ["user_id", "password_hash", "secret_question", "secret_answer_hash"],
        creds_rows
    )
    
    print(f"  registered_users & credentials seeded: {len(data)} users (mapped with secure random UUIDs)")


def seed_national_rail_bookings(cur):
    data = load("bookings.json")
    
    # Pre-load national rail station names for snapshot redundancy
    rail_stations_data = load("national_rail_stations.json")
    rail_station_names = {s["station_id"]: s["name"] for s in rail_stations_data}
    
    bookings_rows = []
    for b in data:
        # Resolve user UUID safely with secure default fallback
        user_uuid = USER_UUID_MAP.get(b["user_id"])
        if not user_uuid:
            num = int(b["user_id"][2:]) if b["user_id"][2:].isdigit() else 0
            user_uuid = f"00000000-0000-0000-0000-{num:012d}"
            
        # Fetch station names safely with fallback to prevent KeyError
        origin_name = rail_station_names.get(b["origin_station_id"], "Unknown Station")
        dest_name = rail_station_names.get(b["destination_station_id"], "Unknown Station")
        bookings_rows.append((
            b["booking_id"],
            user_uuid,
            b["schedule_id"],
            b["origin_station_id"],
            origin_name,
            b["destination_station_id"],
            dest_name,
            b["travel_date"],
            b["departure_time"],
            b["ticket_type"].strip().lower() if b.get("ticket_type") else "single",
            b["fare_class"].strip().lower() if b.get("fare_class") else "standard",
            b["coach"].strip().upper(),
            b["seat_id"].strip().upper(),
            b["stops_travelled"],
            b["amount_usd"],
            b["status"].strip().lower() if b.get("status") else "confirmed",
            b["booked_at"],
            b.get("travelled_at")
        ))
        
    insert_many(
        cur,
        "national_rail_bookings",
        [
            "booking_id", "user_id", "schedule_id", 
            "origin_station_id", "origin_station_name", 
            "destination_station_id", "destination_station_name",
            "travel_date", "departure_time", "ticket_type", "fare_class", "coach", "seat_id",
            "stops_travelled", "amount_usd", "status", "booked_at", "travelled_at"
        ],
        bookings_rows
    )
    print(f"  national_rail_bookings seeded: {len(data)} records")


def seed_metro_travels(cur):
    data = load("metro_travel_history.json")
    
    # Pre-load metro station names for snapshot redundancy
    metro_stations_data = load("metro_stations.json")
    metro_station_names = {s["station_id"]: s["name"] for s in metro_stations_data}
    
    # 1. First, seed metro_passes for all day_pass purchases
    passes_rows = []
    for t in data:
        ticket_type = t.get("ticket_type", "").strip().lower()
        if ticket_type == "day_pass" and t.get("day_pass_ref") is None:
            user_uuid = USER_UUID_MAP[t["user_id"]]
            purchased_at = t.get("purchased_at") or f"{t['travel_date']}T00:00:00Z"
            expires_at = f"{t['travel_date']}T23:59:59Z"
            passes_rows.append((
                t["trip_id"], # pass_id matches the purchase trip's ID
                user_uuid,
                "DAY_PASS",
                expires_at,
                purchased_at
            ))
    insert_many(cur, "metro_passes", ["pass_id", "user_id", "pass_type", "expires_at", "created_at"], passes_rows)
    print(f"  metro_passes seeded: {len(passes_rows)} records")
    
    # 2. Seed metro_travel_history referencing pass_id_ref
    travel_rows = []
    for t in data:
        user_uuid = USER_UUID_MAP[t["user_id"]]
        # Fetch station names safely with fallback to prevent KeyError
        origin_name = metro_station_names.get(t["origin_station_id"], "Unknown Station")
        dest_name = metro_station_names.get(t["destination_station_id"], "Unknown Station")
        
        ticket_type = t.get("ticket_type", "").strip().lower()
        status = t.get("status", "").strip().lower() if t.get("status") else "completed"
        
        # In the new schema: pass_id_ref references the purchased pass_id (which is its day_pass_ref or trip_id itself)
        pass_id_ref = None
        if ticket_type == "day_pass":
            pass_id_ref = t.get("day_pass_ref") or t["trip_id"]
            
        travel_rows.append((
            t["trip_id"],
            user_uuid,
            t["schedule_id"],
            t["origin_station_id"],
            origin_name,
            t["destination_station_id"],
            dest_name,
            t["travel_date"],
            ticket_type,
            pass_id_ref,
            t.get("stops_travelled"),
            t["amount_usd"],
            status,
            t.get("purchased_at"),
            t.get("travelled_at")
        ))
        
    insert_many(
        cur,
        "metro_travel_history",
        [
            "trip_id", "user_id", "schedule_id", 
            "origin_station_id", "origin_station_name", 
            "destination_station_id", "destination_station_name",
            "travel_date", "ticket_type", "pass_id_ref", "stops_travelled", "amount_usd", "status",
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
        
        method = p["method"].strip().lower() if p.get("method") else "credit_card"
        status = p["status"].strip().lower() if p.get("status") else "paid"
        
        payments_rows.append((
            p["payment_id"],
            national_booking_id,
            metro_trip_id,
            p["amount_usd"],
            method,
            status,
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


def seed_operator_alerts(cur):
    """Seed operator_alerts table for the Task 6 Extension."""
    alerts = [
        ("AL001", "M1", "MS05", "high", "M1 line services are experiencing severe signaling delays at Elm Park (MS05). Please allow extra travel time."),
        ("AL002", "NR2", "NR03", "medium", "NR2 rail service is operating with speed restrictions at Old Town Junction (NR03) due to urgent platform maintenance."),
        ("AL003", None, None, "low", "System-wide announcement: Reminder to all passengers that off-peak fares apply all day on Sundays.")
    ]
    insert_many(cur, "operator_alerts", ["alert_id", "line", "station_id", "severity", "message"], alerts)
    print(f"  operator_alerts seeded: {len(alerts)} alerts")


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
        seed_national_rail_schedules(cur)  # Must be seeded before seat layouts due to schedule_id FK reference
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

        print("- Operator Alerts (Task 6)...")
        seed_operator_alerts(cur)
        
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
