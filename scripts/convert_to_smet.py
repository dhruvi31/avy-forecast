"""
convert_to_smet.py

Converts a downloaded ERA5-Land NetCDF file (from fetch_era5.py) into a
SNOWPACK-compatible .smet meteorological input file, for a single location.

What this does:
  1. Opens the .nc file for a location
  2. Picks the grid cell closest to that location's exact lat/lon
  3. Converts units into what SNOWPACK expects:
       - Temperature: Kelvin -> Celsius
       - Dewpoint -> Relative Humidity (%) using the Magnus formula
       - u/v wind components -> wind speed (m/s) and direction (degrees)
       - Radiation: accumulated J/m2 -> average W/m2 over the hour
       - Precipitation: meters -> millimeters
  4. Writes a properly formatted .smet text file

.smet format reference: https://models.slf.ch/docserver/meteoio/SMET_specification.pdf

Usage:
  python convert_to_smet.py --date 2026-07-02
"""

import argparse
import json
import math
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import xarray as xr

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCATIONS_FILE = REPO_ROOT / "data" / "locations.json"
RAW_DATA_DIR = REPO_ROOT / "data" / "raw"
SMET_DATA_DIR = REPO_ROOT / "data" / "smet"

NODATA_VALUE = -999


def load_locations():
    with open(LOCATIONS_FILE, "r") as f:
        return json.load(f)


def dewpoint_to_relative_humidity(temp_c, dewpoint_c):
    """
    Magnus formula approximation for relative humidity (%) from
    air temperature and dewpoint temperature, both in Celsius.
    """
    a, b = 17.625, 243.04
    numerator = math.exp((a * dewpoint_c) / (b + dewpoint_c))
    denominator = math.exp((a * temp_c) / (b + temp_c))
    rh = 100 * (numerator / denominator)
    return max(0.0, min(100.0, rh))


def wind_uv_to_speed_direction(u, v):
    """
    Convert u/v wind components (m/s) to wind speed (m/s) and
    meteorological direction in degrees (direction the wind comes FROM).
    """
    speed = math.sqrt(u**2 + v**2)
    # Meteorological convention: 0 = wind from North, 90 = from East, etc.
    direction = (math.degrees(math.atan2(-u, -v))) % 360
    return speed, direction


def convert_location(location, date_str):
    loc_id = location["id"]
    nc_file = RAW_DATA_DIR / f"{loc_id}_{date_str}.nc"

    if not nc_file.exists():
        print(f"Skipping '{location['name']}' - no data file found: {nc_file}")
        return None

    print(f"Converting '{location['name']}' for {date_str}...")

    ds = xr.open_dataset(nc_file)

    # Find the grid point closest to the exact location
    target_lat = location["lat"]
    target_lon = location["lon"]

    ds_point = ds.sel(
        latitude=target_lat, longitude=target_lon, method="nearest"
    )

    SMET_DATA_DIR.mkdir(parents=True, exist_ok=True)
    output_file = SMET_DATA_DIR / f"{loc_id}_{date_str}.smet"

    # Write the .smet header
    lines = []
    lines.append("SMET 1.1 ASCII")
    lines.append("[HEADER]")
    lines.append(f"station_id       = {loc_id}")
    lines.append(f"station_name     = {location['name']}")
    lines.append(f"latitude         = {target_lat}")
    lines.append(f"longitude        = {target_lon}")
    lines.append(f"altitude         = {location.get('elevation_m', 0)}")
    lines.append("nodata           = -999")
    lines.append("tz               = 0")
    lines.append("fields           = timestamp TA RH VW DW ISWR ILWR PSUM")
    lines.append("[DATA]")

    times = ds_point["valid_time"].values if "valid_time" in ds_point else ds_point["time"].values

    for i, t in enumerate(times):
        try:
            t2m_k = float(ds_point["t2m"].isel({ds_point["t2m"].dims[0]: i}).values)
            d2m_k = float(ds_point["d2m"].isel({ds_point["d2m"].dims[0]: i}).values)
            u10 = float(ds_point["u10"].isel({ds_point["u10"].dims[0]: i}).values)
            v10 = float(ds_point["v10"].isel({ds_point["v10"].dims[0]: i}).values)
            ssrd = float(ds_point["ssrd"].isel({ds_point["ssrd"].dims[0]: i}).values)
            strd = float(ds_point["strd"].isel({ds_point["strd"].dims[0]: i}).values)
            tp = float(ds_point["tp"].isel({ds_point["tp"].dims[0]: i}).values)
        except (KeyError, ValueError) as e:
            print(f"  Skipping timestep {i}, missing variable: {e}")
            continue

        # Skip missing/NaN values
        if any(np.isnan(v) for v in [t2m_k, d2m_k, u10, v10, ssrd, strd, tp]):
            continue

        ta_c = t2m_k - 273.15
        td_c = d2m_k - 273.15
        rh = dewpoint_to_relative_humidity(ta_c, td_c)
        vw, dw = wind_uv_to_speed_direction(u10, v10)

        # ERA5-Land radiation is accumulated (J/m2) over the hour -> average W/m2
        iswr = max(0.0, ssrd / 3600.0)
        ilwr = max(0.0, strd / 3600.0)

        # Precipitation: meters -> millimeters (per hour, since ERA5-Land
        # hourly data reports accumulation over that hour)
        psum = max(0.0, tp * 1000.0)

        timestamp = np.datetime_as_string(t, unit="s")
        lines.append(
            f"{timestamp} {ta_c:.2f} {rh:.1f} {vw:.2f} {dw:.1f} "
            f"{iswr:.1f} {ilwr:.1f} {psum:.3f}"
        )

    lines.append("[/DATA]")

    with open(output_file, "w") as f:
        f.write("\n".join(lines) + "\n")

    print(f"Saved: {output_file}")
    ds.close()
    return output_file


def main():
    parser = argparse.ArgumentParser(
        description="Convert ERA5-Land NetCDF data into SNOWPACK .smet format."
    )
    parser.add_argument(
        "--date",
        required=False,
        default=None,
        help="Date matching the fetched data, format YYYY-MM-DD. If omitted, "
        "uses the same default lag as fetch_era5.py (7 days before today).",
    )
    args = parser.parse_args()

    if args.date is None:
        target_date = datetime.utcnow() - timedelta(days=7)
        args.date = target_date.strftime("%Y-%m-%d")
        print(f"No --date given, defaulting to {args.date}")

    locations = load_locations()
    if not locations:
        print("No locations found in data/locations.json")
        return

    for location in locations:
        convert_location(location, args.date)


if __name__ == "__main__":
    main()