"""Debug: Graf ve rota kontrolü"""
import sys
sys.path.insert(0, ".")

from optimization.graph_builder import build_waypoint_graph
from utils.geo import haversine_nm

G = build_waypoint_graph("KJFK", "EGLL")

print(f"=== KJFK -> EGLL ===")
print(f"Toplam düğüm: {G.number_of_nodes()}")
print(f"Toplam kenar: {G.number_of_edges()}")

# Düğüm tipleri
types = {}
for n, d in G.nodes(data=True):
    t = d.get("type", "unknown")
    types[t] = types.get(t, 0) + 1
print(f"Düğüm tipleri: {types}")

# Origin/dest arası direkt kenar var mı?
has_direct = G.has_edge("KJFK", "EGLL") or G.has_edge("EGLL", "KJFK")
print(f"Direkt KJFK→EGLL kenarı: {has_direct}")

# Origin'in komşuları
origin_neighbors = list(G.successors("KJFK"))
print(f"\nKJFK komşuları ({len(origin_neighbors)} adet):")
for n in origin_neighbors[:10]:
    d = G.nodes[n]
    dist = haversine_nm(
        G.nodes["KJFK"]["latitude"], G.nodes["KJFK"]["longitude"],
        d["latitude"], d["longitude"],
    )
    print(f"  {n} ({d.get('type')}) — {dist:.0f} NM")

# Dest'in öncelleri  
dest_predecessors = list(G.predecessors("EGLL"))
print(f"\nEGLL öncelleri ({len(dest_predecessors)} adet):")
for n in dest_predecessors[:10]:
    d = G.nodes[n]
    dist = haversine_nm(
        G.nodes["EGLL"]["latitude"], G.nodes["EGLL"]["longitude"],
        d["latitude"], d["longitude"],
    )
    print(f"  {n} ({d.get('type')}) — {dist:.0f} NM")

# A* yolu
import networkx as nx
try:
    path = nx.astar_path(G, "KJFK", "EGLL",
        heuristic=lambda a,b: haversine_nm(
            G.nodes[a]["latitude"], G.nodes[a]["longitude"],
            G.nodes[b]["latitude"], G.nodes[b]["longitude"],
        ) * 0.01,
        weight="distance_nm")
    print(f"\nA* yolu ({len(path)} düğüm): {' → '.join(path)}")
except nx.NetworkXNoPath:
    print("\n❌ A* yol bulamadı!")

# Kısa rota da kontrol et
print("\n" + "="*50)
G2 = build_waypoint_graph("LTFM", "LTBJ")
print(f"\n=== LTFM → LTBJ ===")
print(f"Toplam düğüm: {G2.number_of_nodes()}")
print(f"Toplam kenar: {G2.number_of_edges()}")
types2 = {}
for n, d in G2.nodes(data=True):
    t = d.get("type", "unknown")
    types2[t] = types2.get(t, 0) + 1
print(f"Düğüm tipleri: {types2}")
has_direct2 = G2.has_edge("LTFM", "LTBJ") or G2.has_edge("LTBJ", "LTFM")
print(f"Direkt LTFM→LTBJ kenarı: {has_direct2}")

try:
    path2 = nx.astar_path(G2, "LTFM", "LTBJ",
        heuristic=lambda a,b: haversine_nm(
            G2.nodes[a]["latitude"], G2.nodes[a]["longitude"],
            G2.nodes[b]["latitude"], G2.nodes[b]["longitude"],
        ) * 0.01,
        weight="distance_nm")
    print(f"A* yolu ({len(path2)} düğüm): {' → '.join(path2)}")
except nx.NetworkXNoPath:
    print("❌ A* yol bulamadı!")
