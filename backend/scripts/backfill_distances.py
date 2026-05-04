"""
Backfill distance_km for segments that were stored with NULL distance.

Run from the backend/ directory:
    python scripts/backfill_distances.py
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db import SessionLocal
from app.models import Segment
from app.services.builder import _AIRPORT_COORDS, _haversine_km

db = SessionLocal()

null_segs = db.query(Segment).filter(Segment.distance_km.is_(None)).all()
print(f"Segments with null distance: {len(null_segs)}")

fixed = 0
missing = []
for seg in null_segs:
    dep_c = _AIRPORT_COORDS.get(seg.dep_airport)
    arr_c = _AIRPORT_COORDS.get(seg.arr_airport)
    if dep_c and arr_c:
        seg.distance_km = _haversine_km(dep_c[0], dep_c[1], arr_c[0], arr_c[1])
        fixed += 1
        print(f"  {seg.dep_airport}->{seg.arr_airport}: {seg.distance_km:.0f} km")
    else:
        missing.append(f"{seg.dep_airport}->{seg.arr_airport} "
                       f"(missing: {','.join(x for x in [seg.dep_airport, seg.arr_airport] if x not in _AIRPORT_COORDS)})")

db.commit()
db.close()

print(f"\nFixed: {fixed}  |  Still missing coords: {len(missing)}")
for m in missing:
    print(f"  {m}")
