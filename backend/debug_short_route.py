"""Quick debug: LTFM -> LTBJ - basit test."""
import sys
sys.path.insert(0, ".")

from optimization.graph_builder import build_waypoint_graph
from utils.geo import haversine_nm
import networkx as nx

G = build_waypoint_graph("LTFM", "LTBJ")
print(f"Dugum: {G.number_of_nodes()}, Kenar: {G.number_of_edges()}")

if G.has_edge("LTFM", "LTBJ"):
    print(f"Direkt kenar VAR: {G.edges['LTFM','LTBJ']['distance_nm']:.1f} NM")
else:
    print("Direkt kenar YOK")

# Standart (mesafe bazli)
std_path = nx.astar_path(G, "LTFM", "LTBJ",
    heuristic=lambda n1, n2: haversine_nm(
        G.nodes[n1].get("latitude",0), G.nodes[n1].get("longitude",0),
        G.nodes[n2].get("latitude",0), G.nodes[n2].get("longitude",0)),
    weight="distance_nm")
std_dist = sum(G.edges[std_path[i], std_path[i+1]]["distance_nm"] for i in range(len(std_path)-1))
print(f"Standart: {len(std_path)} nokta, {std_dist:.1f} NM")
print(f"  Yol: {' -> '.join(std_path)}")

# LTFM komsulari
print(f"\nLTFM komsulari ({len(list(G.successors('LTFM')))} adet):")
for nb in sorted(G.successors("LTFM"), key=lambda x: G.edges["LTFM",x]["distance_nm"]):
    print(f"  {nb:15s} {G.edges['LTFM',nb]['distance_nm']:6.1f} NM")

print(f"\nLTBJ'ye gelenler ({len(list(G.predecessors('LTBJ')))} adet):")
for nb in sorted(G.predecessors("LTBJ"), key=lambda x: G.edges[x,"LTBJ"]["distance_nm"]):
    print(f"  {nb:15s} {G.edges[nb,'LTBJ']['distance_nm']:6.1f} NM")
