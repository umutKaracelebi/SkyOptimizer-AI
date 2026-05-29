import sys, json
from urllib.request import Request, urlopen
sys.stdout.reconfigure(encoding='utf-8')

data = json.dumps({
    'origin': 'LTFM', 'destination': 'LTBJ', 'aircraft_type': 'B738'
}).encode()

req = Request('http://localhost:8000/api/optimize', data=data,
              headers={'Content-Type': 'application/json'})
resp = urlopen(req)
d = json.loads(resp.read())

std = d.get('standard_route', {})
opt = d.get('optimized_route', {})

print("=== STANDARD ROUTE ===")
print(f"WP count: {std.get('waypoint_count')}")
for w in std.get('waypoints', []):
    print(f"  {w['id']:15s} ({w['type']:10s}) lat={w['latitude']:.4f} lon={w['longitude']:.4f}")

print()
print("=== OPTIMIZED ROUTE ===")
print(f"WP count: {opt.get('waypoint_count')}")
for w in opt.get('waypoints', []):
    print(f"  {w['id']:15s} ({w['type']:10s}) lat={w['latitude']:.4f} lon={w['longitude']:.4f}")

print()
same = all(
    s['id'] == o['id']
    for s, o in zip(std.get('waypoints', []), opt.get('waypoints', []))
) if len(std.get('waypoints', [])) == len(opt.get('waypoints', [])) else False
print(f"AYNI MI: {same}")
print(f"Std fuel: {std.get('estimated_fuel_kg')}")
print(f"Opt fuel: {opt.get('estimated_fuel_kg')}")
