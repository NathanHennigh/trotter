"""Export local SQLite flight data into the mobile-v2 test fixture.

This is intentionally a local development bridge, not production sync. The
mobile-v2 prototype can render the user's existing stored flight paths without
requiring auth or a live API connection while the UI is still being explored.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
DB_PATH = BACKEND / "trotter.db"
OUT_PATH = ROOT / "mobile-v2" / "src" / "data" / "localFlightFixture.json"

sys.path.insert(0, str(BACKEND))
os.environ.setdefault("TROTTER_DATA_CACHE", str(BACKEND / ".cache" / "trotter-data"))

from app.services.airport_data import get_airport  # noqa: E402


def airport_point(code: str) -> dict | None:
    airport = get_airport(code)
    if airport is None:
        return None
    return {
        "code": airport.iata_code,
        "city": airport.city or airport.name,
        "name": airport.name,
        "countryCode": airport.country_code,
        "countryName": airport.country_name,
        "lat": airport.latitude,
        "lon": airport.longitude,
    }


def main() -> None:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row

    rows = con.execute(
        """
        SELECT
          s.id,
          s.trip_id,
          s.dep_airport,
          s.arr_airport,
          s.dep_time,
          s.arr_time,
          s.airline,
          s.flight_number,
          s.distance_km,
          t.title AS trip_title
        FROM segments s
        JOIN trips t ON t.id = s.trip_id
        WHERE s.mode = 'flight'
        ORDER BY s.dep_time ASC, s.id ASC
        """
    ).fetchall()

    airports: dict[str, dict] = {}
    routes: list[dict] = []
    skipped: list[dict] = []

    for row in rows:
        dep_code = str(row["dep_airport"] or "").strip().upper()
        arr_code = str(row["arr_airport"] or "").strip().upper()
        dep = airport_point(dep_code)
        arr = airport_point(arr_code)
        if dep is None or arr is None:
            skipped.append({"id": row["id"], "dep_airport": dep_code, "arr_airport": arr_code})
            continue

        airports[dep["code"]] = dep
        airports[arr["code"]] = arr
        routes.append(
            {
                "id": f"segment-{row['id']}",
                "segmentId": row["id"],
                "tripId": row["trip_id"],
                "tripTitle": row["trip_title"],
                "from": dep,
                "to": arr,
                "depTime": row["dep_time"],
                "arrTime": row["arr_time"],
                "airline": row["airline"],
                "flightNumber": row["flight_number"],
                "distanceKm": row["distance_km"],
            }
        )

    payload = {
        "source": str(DB_PATH),
        "generatedAt": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "routeCount": len(routes),
        "airportCount": len(airports),
        "skipped": skipped,
        "airports": sorted(airports.values(), key=lambda item: item["code"]),
        "routes": routes,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Exported {len(routes)} routes, {len(airports)} airports to {OUT_PATH}")
    if skipped:
        print(f"Skipped {len(skipped)} segment(s) with missing airport metadata: {skipped}")


if __name__ == "__main__":
    main()
