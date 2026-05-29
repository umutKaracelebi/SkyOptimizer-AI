import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')

import networkx as nx
from optimization.graph_builder import build_waypoint_graph

G = build_waypoint_graph('LTFM', 'LTBJ')

# WP cikar, sadece COR + airport
G_opt = G.copy()
wp = [n for n, d in G_opt.nodes(data=True) if d.get('type') == 'waypoint']
G_opt.remove_nodes_from(wp)

print(f"G_opt nodes: {G_opt.number_of_nodes()}, edges: {G_opt.number_of_edges()}")

# Yol var mi?
try:
    path = nx.astar_path(G_opt, 'LTFM', 'LTBJ', weight='distance_nm')
    sep = ' -> '
    print(f"COR Path ({len(path)}): {sep.join(path)}")
except nx.NetworkXNoPath:
    print("NO PATH in COR-only graph!")
    # Baglanti analiz
    ltfm_neighbors = list(G_opt.successors('LTFM'))
    print(f"LTFM neighbors: {len(ltfm_neighbors)}")
    for n in ltfm_neighbors[:5]:
        print(f"  {n} ({G_opt.nodes[n].get('type')})")
    ltbj_predecessors = list(G_opt.predecessors('LTBJ'))
    print(f"LTBJ predecessors: {len(ltbj_predecessors)}")
    for n in ltbj_predecessors[:5]:
        print(f"  {n} ({G_opt.nodes[n].get('type')})")
