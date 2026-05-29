import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')

import networkx as nx
from optimization.graph_builder import build_waypoint_graph
from optimization.cost_model import CostModel
from utils.geo import haversine_nm, initial_bearing

G = build_waypoint_graph('LTFM', 'LTBJ')
cost_model = CostModel('B738')

# Kenar maliyetlerini hesapla (asil koddan kopya)
for u, v, data in G.edges(data=True):
    dist = data.get("distance_nm", 0)
    bearing = data.get("bearing", 0)
    segment = cost_model.calculate_segment_cost(distance_nm=dist, aircraft_heading=bearing)
    composite = cost_model.composite_cost(segment["fuel_kg"], segment["time_min"], segment["co2_kg"], {"fuel": 0.4, "time": 0.35, "co2": 0.25})
    data["weight"] = composite
    data["fuel_kg"] = segment["fuel_kg"]
    data["time_min"] = segment["time_min"]
    data["co2_kg"] = segment["co2_kg"]

# WP cikar
G_opt = G.copy()
wp = [n for n, d in G_opt.nodes(data=True) if d.get('type') == 'waypoint']
G_opt.remove_nodes_from(wp)

print(f"G_opt: {G_opt.number_of_nodes()} nodes, {G_opt.number_of_edges()} edges")

# Edge'lerde weight var mi?
sample_edges = list(G_opt.edges(data=True))[:3]
for u, v, d in sample_edges:
    print(f"  {u}->{v}: weight={d.get('weight','MISSING')}, fuel={d.get('fuel_kg','MISSING')}")

# A* yol bul
try:
    path = nx.astar_path(G_opt, 'LTFM', 'LTBJ', weight='weight')
    sep = ' -> '
    print(f"\nOPTIMIZE Path ({len(path)}): {sep.join(path)}")
    for n in path:
        nd = G_opt.nodes[n]
        print(f"  {n:15s} ({nd.get('type','?'):10s}) lat={nd['latitude']:.4f} lon={nd['longitude']:.4f}")
except nx.NetworkXNoPath:
    print("NO PATH!")

# Standart (COR cikarilmis)
G_std = G.copy()
cor = [n for n, d in G_std.nodes(data=True) if d.get('type') == 'corridor']
G_std.remove_nodes_from(cor)
try:
    std_path = nx.astar_path(G_std, 'LTFM', 'LTBJ', weight='distance_nm')
    print(f"\nSTANDART Path ({len(std_path)}): {sep.join(std_path)}")
    for n in std_path:
        nd = G_std.nodes[n]
        print(f"  {n:15s} ({nd.get('type','?'):10s}) lat={nd['latitude']:.4f} lon={nd['longitude']:.4f}")
except nx.NetworkXNoPath:
    print("NO STD PATH!")
