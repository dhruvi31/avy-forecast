"""
fetch_era5.py

Pulls hourly ERA5-Land weather data from the Copernicus Climate Data Store (CDS)
for each location listed in data/locations.json, for a given date.

Requires:
- A free Copernicus CDS account: https://cds.climate.copernicus.eu
- Your CDS API key set up as described below.

CDS API KEY SETUP (one-time, per machine):
  1. Log in to https://cds.climate.copernicus.eu
  2. Go to your user profile page -> "API Key" (or "How to use the CDS API")
  3. It will show two lines like:
       url: https://cds.climate.copernicus.eu/api
       key: XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX
  4. Create a file named ".cdsapirc" in your home directory containing exactly those
     two lines. On Windows this is usually C:\\Users\\YourName\\.cdsapirc
  5. In GitHub Actions, instead of a file, we pass these as secrets (covered in the
     workflow file) - you do NOT commit your API key to the repo.

Usage:
  python fetch_era5.py --date 2026-07-10
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import cdsapi

# ERA5-Land is published with a delay of roughly 5-7 days.
# Requesting "today" will always fail with a "data not available yet" error,
# so by default we fetch data from this many days ago instead.
DEFAULT_LAG_DAYS = 7

# Variables needed as SNOWPACK forcing input
ERA5_VARIABLES = [
    "2m_temperature",
    "2m_dewpoint_temperature",
    "10m_u_component_of_wind",
    "10m_v_component_of_wind",
    "surface_solar_radiation_downwards",
    "surface_thermal_radiation_downwards",
    "total_precipitation",
]

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCATIONS_FILE = REPO_ROOT / "data" / "locations.json"
RAW_DATA_DIR = REPO_ROOT / "data" / "raw"


def load_locations():
    with open(LOCATIONS_FILE, "r") as f:
        return json.load(f)


def fetch_for_location(client, location, date_str):
    """
    Fetch a small bounding box (~0.1 degree) around a single lat/lon point,
    since CDS requests are usually done as small area boxes rather than
    single points.
    """
    lat = location["lat"]
    lon = location["lon"]
    loc_id = location["id"]

    # Small bounding box around the point: [North, West, South, East]
    area = [lat + 0.05, lon - 0.05, lat - 0.05, lon + 0.05]

    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    output_file = RAW_DATA_DIR / f"{loc_id}_{date_str}.nc"

    print(f"Requesting ERA5-Land data for '{location['name']}' on {date_str}...")

    client.retrieve(
        "reanalysis-era5-land",
        {
            "variable": ERA5_VARIABLES,
            "year": date_str[:4],
            "month": date_str[5:7],
            "day": date_str[8:10],
            "time": [f"{h:02d}:00" for h in range(24)],
            "area": area,
            "data_format": "netcdf",
            "download_format": "unarchived",
        },
        str(output_file),
    )

    print(f"Saved: {output_file}")
    return output_file


def main():
    parser = argparse.ArgumentParser(description="Fetch ERA5-Land data for slope locations.")
    parser.add_argument(
        "--date",
        required=False,
        default=None,
        help=(
            "Date to fetch, format YYYY-MM-DD. If omitted, defaults to "
            f"{DEFAULT_LAG_DAYS} days before today, since ERA5-Land data "
            "is published with a delay."
        ),
    )
    args = parser.parse_args()

    if args.date is None:
        target_date = datetime.utcnow() - timedelta(days=DEFAULT_LAG_DAYS)
        args.date = target_date.strftime("%Y-%m-%d")
        print(f"No --date given, defaulting to {args.date} (today minus {DEFAULT_LAG_DAYS} days)")

    try:
        client = cdsapi.Client()
    except Exception as e:
        print("Could not initialize CDS API client.")
        print("Make sure your .cdsapirc file (or CDSAPI_URL / CDSAPI_KEY env vars) is set up.")
        print(f"Error: {e}")
        sys.exit(1)

    locations = load_locations()
    if not locations:
        print("No locations found in data/locations.json - add at least one location.")
        sys.exit(1)

    for location in locations:
        fetch_for_location(client, location, args.date)


if __name__ == "__main__":
    main()