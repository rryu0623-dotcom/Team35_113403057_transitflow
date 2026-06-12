"""
TransitFlow — Neo4j Graph Database Layer
=========================================
This module handles all queries to Neo4j.

GRAPH ROLE:
  - Model the dual transit network (city metro M1–M4 + national rail NR1–NR2)
  - Find fastest routes (Dijkstra by travel_time_min via APOC)
  - Find cheapest routes (Dijkstra by fare via APOC)
  - Find alternative routes avoiding a given station
  - Find cross-network interchange paths (metro → rail or rail → metro)
  - Show delay ripple: which stations are affected within N hops

STUDENT TASK
------------
Design your graph schema (node labels, relationship types, properties)
based on the data in train-mock-data/, seed it with skeleton/seed_neo4j.py,
then implement the query_ functions below.

Functions prefixed with `query_` are called by the agent (skeleton/agent.py).
"""

from __future__ import annotations

from typing import Optional

from neo4j import GraphDatabase

from skeleton.config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD


def _driver():
    """Return a Neo4j driver. Caller is responsible for closing."""
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


# ── Example ───────────────────────────────────────────────────────────────────
# The block below shows the query pattern: open a session, run Cypher, return data.

def example_count_nodes() -> int:
    """Example: count all nodes currently in the graph."""
    with _driver() as driver:
        with driver.session() as session:
            result = session.run("MATCH (n) RETURN count(n) AS total")
            return result.single()["total"]

# TODO: Implement the query_ functions below.
# ─────────────────────────────────────────────────────────────────────────────


# ── FASTEST ROUTE (Dijkstra by travel_time_min) ───────────────────────────────

def query_shortest_route(
    origin_id: str,
    destination_id: str,
    network: str = "auto",
) -> dict:
    """
    Find the fastest path between two stations, minimising total travel time.
    Uses apoc.algo.dijkstra (APOC required; enabled in docker-compose.yml).

    Design Decision: APOC Dijkstra is preferred over Cypher's shortestPath because
    shortestPath only minimizes hops (station count), whereas Dijkstra correctly
    calculates the path with the minimum sum of physical travel times.

    Args:
        origin_id:       e.g. "MS01" or "NR01"
        destination_id:  e.g. "MS09" or "NR05"
        network:         "metro", "rail", or "auto" (inferred from IDs)

    Returns:
        dict with keys: found, origin_id, destination_id,
                        total_time_min, path (list of station dicts), legs
    """
    if network == "auto":
        network = "metro" if origin_id.startswith("MS") else "rail"
    
    label = "MetroStation" if network == "metro" else "NationalRailStation"
    link = "METRO_LINK" if network == "metro" else "RAIL_LINK"
    
    with _driver() as driver:
        with driver.session() as session:
            if origin_id == destination_id:
                query = f"MATCH (s:{label} {{id: $origin}}) RETURN s.name AS name"
                res = session.run(query, origin=origin_id)
                row = res.single()
                if row:
                    return {
                        "found": True,
                        "origin_id": origin_id,
                        "destination_id": destination_id,
                        "total_time_min": 0.0,
                        "path": [{"id": origin_id, "name": row["name"]}],
                        "legs": []
                    }
                return {
                    "found": False,
                    "origin_id": origin_id,
                    "destination_id": destination_id,
                    "total_time_min": 0.0,
                    "path": [],
                    "legs": []
                }
            
            query = f"""
            MATCH (start:{label} {{id: $origin}})
            MATCH (end:{label} {{id: $destination}})
            CALL apoc.algo.dijkstra(start, end, '{link}', 'travel_time_min')
            YIELD path, weight
            RETURN
              [node IN nodes(path) | {{id: node.id, name: node.name}}] AS path_nodes,
              [rel IN relationships(path) | {{line: rel.line, travel_time_min: rel.travel_time_min}}] AS path_rels,
              weight AS total_time_min
            """
            res = session.run(query, origin=origin_id, destination=destination_id)
            row = res.single()
            if not row or not row["path_nodes"]:
                return {
                    "found": False,
                    "origin_id": origin_id,
                    "destination_id": destination_id,
                    "total_time_min": 0.0,
                    "path": [],
                    "legs": []
                }
            
            stations = row["path_nodes"]
            rels = row["path_rels"]
            legs = []
            for i in range(len(rels)):
                legs.append({
                    "from_id": stations[i]["id"],
                    "from_name": stations[i]["name"],
                    "to_id": stations[i+1]["id"],
                    "to_name": stations[i+1]["name"],
                    "line": rels[i]["line"],
                    "travel_time_min": rels[i]["travel_time_min"]
                })
            
            return {
                "found": True,
                "origin_id": origin_id,
                "destination_id": destination_id,
                "total_time_min": float(row["total_time_min"]),
                "path": stations,
                "legs": legs
            }


# ── CHEAPEST ROUTE (Dijkstra by fare) ────────────────────────────────────────

def query_cheapest_route(
    origin_id: str,
    destination_id: str,
    network: str = "auto",
    fare_class: str = "standard",
) -> dict:
    """
    Find the cheapest path between two stations, minimising total estimated fare.
    Uses apoc.algo.dijkstra with cost weights configured on relationships.

    Design Decision: Since transit fares are computed as a base fare plus a per-stop rate,
    we model standard/first-class fares as relationship properties (cost_standard, cost_first)
    and use APOC Dijkstra to find the path that minimizes accumulated per-stop cost, adding the
    base network fare at the end in Python. This ensures that route searches are truly optimized
    by cost rather than hops or travel time.

    Args:
        origin_id:       e.g. "NR01"
        destination_id:  e.g. "NR05"
        network:         "metro", "rail", or "auto"
        fare_class:      "standard" or "first" (national rail only)

    Returns:
        dict with found, total_fare_usd (approximate), stations, legs
    """
    if network == "auto":
        network = "metro" if origin_id.startswith("MS") else "rail"
    
    label = "MetroStation" if network == "metro" else "NationalRailStation"
    link = "METRO_LINK" if network == "metro" else "RAIL_LINK"
    cost_prop = "cost_first" if (network == "rail" and fare_class == "first") else "cost_standard"
    
    with _driver() as driver:
        with driver.session() as session:
            if origin_id == destination_id:
                query = f"MATCH (s:{label} {{id: $origin}}) RETURN s.name AS name"
                res = session.run(query, origin=origin_id)
                row = res.single()
                if row:
                    return {
                        "found": True,
                        "total_fare_usd": 0.0,
                        "stations": [{"id": origin_id, "name": row["name"]}],
                        "legs": []
                    }
                return {
                    "found": False,
                    "total_fare_usd": 0.0,
                    "stations": [],
                    "legs": []
                }
            
            if network == "metro":
                base_fare = 0.80
                per_stop_rate = 0.30
            else:
                if fare_class == "first":
                    base_fare = 4.00
                    per_stop_rate = 2.50
                else:
                    base_fare = 2.50
                    per_stop_rate = 1.50
            
            query = f"""
            MATCH (start:{label} {{id: $origin}})
            MATCH (end:{label} {{id: $destination}})
            CALL apoc.algo.dijkstra(start, end, '{link}', 'fare_weight', $per_stop_rate)
            YIELD path, weight
            RETURN
              [node IN nodes(path) | {{id: node.id, name: node.name}}] AS path_nodes,
              [rel IN relationships(path) | {{line: rel.line, travel_time_min: rel.travel_time_min}}] AS path_rels,
              weight AS variable_fare
            """
            res = session.run(query, origin=origin_id, destination=destination_id, per_stop_rate=float(per_stop_rate))
            row = res.single()
            if not row or not row["path_nodes"]:
                return {
                    "found": False,
                    "total_fare_usd": 0.0,
                    "stations": [],
                    "legs": []
                }
            
            stations = row["path_nodes"]
            rels = row["path_rels"]
            total_fare_usd = base_fare + row["variable_fare"]
            
            legs = []
            for i in range(len(rels)):
                legs.append({
                    "from_id": stations[i]["id"],
                    "from_name": stations[i]["name"],
                    "to_id": stations[i+1]["id"],
                    "to_name": stations[i+1]["name"],
                    "line": rels[i]["line"],
                    "travel_time_min": rels[i]["travel_time_min"]
                })
            
            return {
                "found": True,
                "total_fare_usd": round(total_fare_usd, 2),
                "stations": stations,
                "legs": legs
            }


# ── ALTERNATIVE ROUTES (avoiding a station) ───────────────────────────────────

def query_alternative_routes(
    origin_id: str,
    destination_id: str,
    avoid_station_id: str,
    network: str = "auto",
    max_routes: int = 3,
) -> list[list[dict]]:
    """
    Find paths between two stations that avoid a specific intermediate station.
    Useful for routing around a delayed or closed station.

    Args:
        origin_id:         e.g. "NR01"
        destination_id:    e.g. "NR05"
        avoid_station_id:  e.g. "NR03"
        network:           "metro", "rail", or "auto"
        max_routes:        max number of alternatives to return

    Returns:
        List of routes, each route is a list of leg dicts
    """
    if network == "auto":
        network = "metro" if origin_id.startswith("MS") else "rail"
        
    label = "MetroStation" if network == "metro" else "NationalRailStation"
    link = "METRO_LINK" if network == "metro" else "RAIL_LINK"
    
    routes = []
    with _driver() as driver:
        with driver.session() as session:
            query = f"""
            MATCH (start:{label} {{id: $origin}})
            MATCH (end:{label} {{id: $destination}})
            MATCH path = (start)-[:{link}*]->(end)
            WHERE NONE(node IN nodes(path) WHERE node.id = $avoid)
            RETURN
              [node IN nodes(path) | {{id: node.id, name: node.name}}] AS path_nodes,
              [rel IN relationships(path) | {{line: rel.line, travel_time_min: rel.travel_time_min}}] AS path_rels
            ORDER BY reduce(t = 0, r IN relationships(path) | t + r.travel_time_min)
            LIMIT $max_routes
            """
            res = session.run(query, origin=origin_id, destination=destination_id, avoid=avoid_station_id, max_routes=max_routes)
            for row in res:
                stations = row["path_nodes"]
                rels = row["path_rels"]
                legs = []
                for i in range(len(rels)):
                    legs.append({
                        "from_id": stations[i]["id"],
                        "from_name": stations[i]["name"],
                        "to_id": stations[i+1]["id"],
                        "to_name": stations[i+1]["name"],
                        "line": rels[i]["line"],
                        "travel_time_min": rels[i]["travel_time_min"]
                    })
                routes.append(legs)
    return routes


# ── CROSS-NETWORK INTERCHANGE PATH ───────────────────────────────────────────

def query_interchange_path(origin_id: str, destination_id: str) -> dict:
    """
    Find a path between a metro station and a national rail station (or vice versa)
    crossing the network boundary via interchange relationships.

    Args:
        origin_id:       e.g. "MS03" (metro) or "NR05" (national rail)
        destination_id:  e.g. "NR05" (national rail) or "MS09" (metro)

    Returns:
        dict with found, stations list, interchange points, total_time_min
    """
    with _driver() as driver:
        with driver.session() as session:
            if origin_id == destination_id:
                label = "MetroStation" if origin_id.startswith("MS") else "NationalRailStation"
                query = f"MATCH (s:{label} {{id: $origin}}) RETURN s.name AS name"
                res = session.run(query, origin=origin_id)
                row = res.single()
                if row:
                    return {
                        "found": True,
                        "stations": [{"id": origin_id, "name": row["name"]}],
                        "interchange_points": [],
                        "total_time_min": 0.0
                    }
                return {
                    "found": False,
                    "stations": [],
                    "interchange_points": [],
                    "total_time_min": 0.0
                }

            query = """
            MATCH (start {id: $origin})
            MATCH (end {id: $destination})
            CALL apoc.algo.dijkstra(start, end, 'METRO_LINK|RAIL_LINK|INTERCHANGE_TO', 'travel_time_min', 5.0)
            YIELD path, weight
            RETURN
              [node IN nodes(path) | {id: node.id, name: node.name}] AS path_nodes,
              [rel IN relationships(path) | {type: type(rel), line: coalesce(rel.line, "Interchange"), travel_time_min: coalesce(rel.travel_time_min, 5.0)}] AS path_rels,
              weight AS total_time_min
            """
            res = session.run(query, origin=origin_id, destination=destination_id)
            row = res.single()
            if not row or not row["path_nodes"]:
                return {
                    "found": False,
                    "stations": [],
                    "interchange_points": [],
                    "total_time_min": 0.0
                }

            path_nodes = row["path_nodes"]
            path_rels = row["path_rels"]
            interchange_points = []
            for i in range(len(path_rels)):
                if path_rels[i]["type"] == "INTERCHANGE_TO":
                    from_node = path_nodes[i]
                    to_node = path_nodes[i+1]
                    interchange_points.append(
                        f"{from_node['name']} ({from_node['id']}) <-> {to_node['name']} ({to_node['id']})"
                    )

            return {
                "found": True,
                "stations": path_nodes,
                "interchange_points": interchange_points,
                "total_time_min": float(row["total_time_min"])
            }


# ── DELAY RIPPLE ANALYSIS ─────────────────────────────────────────────────────

def query_delay_ripple(delayed_station_id: str, hops: int = 2) -> list[dict]:
    """
    Find all stations within N hops of a delayed or disrupted station.
    Works on both metro and national rail networks.

    Args:
        delayed_station_id: e.g. "NR03" or "MS01"
        hops:               how many connections out to search (default 2)

    Returns:
        List of dicts: {station_id, name, hops_away, lines_affected}
    """
    hops_val = int(hops)
    if hops_val < 0:
        return []
        
    with _driver() as driver:
        with driver.session() as session:
            if hops_val == 0:
                query = """
                MATCH (disrupted {id: $station_id})
                RETURN
                    disrupted.id AS station_id,
                    disrupted.name AS name,
                    0 AS hops_away,
                    coalesce(disrupted.lines, []) AS lines_affected
                """
                res = session.run(query, station_id=delayed_station_id)
                return [dict(row) for row in res]
                
            query = f"""
            MATCH (disrupted {{id: $station_id}})
            MATCH path = (disrupted)-[:METRO_LINK|RAIL_LINK|INTERCHANGE_TO*1..{hops_val}]-(affected)
            WHERE affected.id <> $station_id
            RETURN
                affected.id AS station_id,
                affected.name AS name,
                min(length(path)) AS hops_away,
                coalesce(affected.lines, []) AS lines_affected
            ORDER BY hops_away, station_id
            """
            res = session.run(query, station_id=delayed_station_id)
            return [dict(row) for row in res]


# ── STATION CONNECTIONS ───────────────────────────────────────────────────────

def query_station_connections(station_id: str) -> list[dict]:
    """
    List all direct connections from a given station.

    Args:
        station_id: e.g. "MS01" or "NR01"
    """
    with _driver() as driver:
        with driver.session() as session:
            query = """
            MATCH (start {id: $station_id})-[r:METRO_LINK|RAIL_LINK|INTERCHANGE_TO]->(target)
            RETURN
              target.id AS station_id,
              target.name AS name,
              coalesce(r.line, 'Interchange') AS line,
              coalesce(r.travel_time_min, 5.0) AS travel_time_min
            ORDER BY station_id, line
            """
            res = session.run(query, station_id=station_id)
            return [dict(row) for row in res]

