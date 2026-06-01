"""
TransitFlow — Neo4j Seeder
Run once after starting Docker:
    python skeleton/seed_neo4j.py

Loads station and network data from train-mock-data/:
  - metro_stations.json         — city metro stations and adjacencies
  - national_rail_stations.json — national rail stations and adjacencies
"""

import json
import os
import sys

sys.path.insert(0, ".")

from neo4j import GraphDatabase
from skeleton.config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD

_DATA_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "train-mock-data")
)

def _load(filename):
    with open(os.path.join(_DATA_DIR, filename), encoding="utf-8") as f:
        return json.load(f)

def seed():
    metro_stations = _load("metro_stations.json")
    rail_stations  = _load("national_rail_stations.json")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    with driver.session() as session:

        session.run("MATCH (n) DETACH DELETE n")
        print("  Cleared existing graph data")

        # 1. Create MetroStation nodes
        print("  Creating MetroStation nodes...")
        session.run("""
            UNWIND $stations AS s
            CREATE (n:MetroStation {
                id: s.station_id,
                name: s.name,
                lines: s.lines
            })
        """, stations=metro_stations)

        # 2. Create NationalRailStation nodes
        print("  Creating NationalRailStation nodes...")
        session.run("""
            UNWIND $stations AS s
            CREATE (n:NationalRailStation {
                id: s.station_id,
                name: s.name,
                lines: s.lines
            })
        """, stations=rail_stations)

        # 3. Create METRO_LINK relationships (Metro Line)
        print("  Creating METRO_LINK relationships...")
        session.run("""
            UNWIND $stations AS s
            MATCH (a:MetroStation {id: s.station_id})
            UNWIND s.adjacent_stations AS adj
            MATCH (b:MetroStation {id: adj.station_id})
            MERGE (a)-[r:METRO_LINK {line: adj.line}]->(b)
            SET r.travel_time_min = adj.travel_time_min
        """, stations=metro_stations)

        # 4. Create RAIL_LINK relationships (National Rail Line)
        print("  Creating RAIL_LINK relationships...")
        session.run("""
            UNWIND $stations AS s
            MATCH (a:NationalRailStation {id: s.station_id})
            UNWIND s.adjacent_stations AS adj
            MATCH (b:NationalRailStation {id: adj.station_id})
            MERGE (a)-[r:RAIL_LINK {line: adj.line}]->(b)
            SET r.travel_time_min = adj.travel_time_min
        """, stations=rail_stations)

        # 5. Create INTERCHANGE_TO transfer relationships (Bidirectional)
        print("  Creating INTERCHANGE_TO relationships...")
        session.run("""
            UNWIND $stations AS s
            WITH s WHERE s.is_interchange_national_rail = true AND s.interchange_national_rail_station_id IS NOT NULL
            MATCH (m:MetroStation {id: s.station_id})
            MATCH (nr:NationalRailStation {id: s.interchange_national_rail_station_id})
            MERGE (m)-[:INTERCHANGE_TO]->(nr)
            MERGE (nr)-[:INTERCHANGE_TO]->(m)
        """, stations=metro_stations)

    driver.close()
    print("\nNeo4j graph seeded successfully.")
    print("   Open http://localhost:7475 to explore the graph.")

if __name__ == "__main__":
    print("Connecting to Neo4j...")
    seed()