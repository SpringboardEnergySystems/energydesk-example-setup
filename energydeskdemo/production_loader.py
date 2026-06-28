import json
import random
import calendar
import logging
import os
import argparse
import sys

import pendulum

from energydeskapi.assets.assets_api import AssetsApi
from energydeskapi.assetdata.assetdata_api import AssetDataApi
from energydeskapi.types.asset_enum_types import AssetCategoryEnum, TimeSeriesTypesEnum
from energydeskapi.types.contract_enum_types import QuantityUnitEnum, QuantityTypeEnum

from energydeskdemo.asset_utils import get_or_create_asset_type, populate_asset_production_object

logger = logging.getLogger(__name__)

# Capacity factors per month (index 0 = January) — kept at module level so
# __main__ can reference them without going through the full generation path.
HYDRO_CF = [0.62, 0.58, 0.55, 0.50, 0.72, 0.88, 0.78, 0.62, 0.57, 0.64, 0.72, 0.68]
WIND_CF  = [0.45, 0.43, 0.39, 0.34, 0.30, 0.27, 0.26, 0.29, 0.34, 0.39, 0.44, 0.46]
CF_MAP   = {"hydro": HYDRO_CF, "wind": WIND_CF}


# ---------------------------------------------------------------------------
# Row generation (pure, no I/O)
# ---------------------------------------------------------------------------

def _build_monthly_rows(plant: dict, start_year: int = 2026, years: int = 10) -> list[dict]:
    """Generate monthly forecast rows for a single plant.

    Uses a per-plant RNG seeded from the plant name so results are
    deterministic and independent of processing order.
    """
    cf_seasonal = CF_MAP[plant["type"].lower()]
    rng = random.Random(hash(plant["name"]) & 0xFFFFFFFF)
    plant_bias = rng.uniform(0.88, 1.12)
    monthly_rows = []
    for year in range(start_year, start_year + years):
        annual_factor = rng.uniform(0.82, 1.18)
        for month in range(1, 13):
            days = calendar.monthrange(year, month)[1]
            hours = days * 24
            noise = rng.uniform(0.90, 1.10)
            cf = cf_seasonal[month - 1] * annual_factor * plant_bias * noise
            cf = max(0.05, min(cf, 0.98))
            monthly_rows.append({
                "period": "{}-{:02d}".format(year, month),
                "forecast_production_mwh": round(plant["capacity_mw"] * hours * cf, 1),
            })
    return monthly_rows


def _resolve_price_area(asset_row, plant: dict) -> str:
    """Return price_area from the appserver asset row, falling back to the JSON plant dict."""
    area = asset_row.get("price_area", "")
    if area:
        return str(area)
    return str(plant.get("price_area", ""))


# ---------------------------------------------------------------------------
# Single-asset save (appserver + optional InfluxDB)
# ---------------------------------------------------------------------------

def save_production_forecast(
    api_connection,
    asset_pk,
    asset_meta,
    timeseries_date,
    monthly_rows,
    influx_writer=None,
    write_appserver=True,
):
    """Store monthly production forecast for a single asset.

    Parameters
    ----------
    api_connection:
        Active EnergyDesk API connection.  May be ``None`` when
        ``write_appserver=False``.
    asset_pk:
        Integer primary key of the asset in the appserver database.
    asset_meta:
        Dict with asset metadata used as InfluxDB tags::

            {
                "pk":          <int>,   # same as asset_pk
                "name":        <str>,
                "asset_type":  <str>,   # e.g. "hydro" / "wind"
                "owner":       <str>,
                "lat":         <float>,
                "lon":         <float>,
                "capacity_mw": <float>,
                "price_area":  <str>,   # e.g. "NO2" — from appserver
                "bidzone":     <str>,   # "" when unknown
            }

    timeseries_date:
        ISO-format reference date string for the forecast series.
    monthly_rows:
        List of dicts with keys ``"period"`` (``"YYYY-MM"``) and
        ``"forecast_production_mwh"`` (float).
    influx_writer:
        Optional ``_InfluxWriter`` from ``build_influx_sink()``.  When
        ``None`` the InfluxDB write is skipped.
    write_appserver:
        When ``False`` the appserver blob write is skipped entirely.
        Useful for the ``--sink influx`` CLI mode where assets are already
        registered and only InfluxDB needs to be populated.
    """
    res = None

    # ------------------------------------------------------------------ #
    # 1. Appserver blob write                                              #
    # ------------------------------------------------------------------ #
    if write_appserver:
        tseries = []
        for row in monthly_rows:
            period = row['period']
            year, month = map(int, period.split('-'))
            gmttime_dt = pendulum.datetime(year, month, 1, tz='Europe/Oslo')
            utc_dt = gmttime_dt.in_tz('UTC')
            tseries.append({
                'timestamp': utc_dt.strftime('%Y-%m-%dT%H:%M:%S+00:00'),
                'date': gmttime_dt.strftime('%Y-%m-%d'),
                'value': row['forecast_production_mwh'],
                'cost': 0,
            })

        logger.info("Saving forecast to appserver for asset pk=%s date=%s", asset_pk, timeseries_date)
        ts_date = pendulum.parse(timeseries_date, tz='Europe/Oslo')
        payload = {
            'timeseries_date': str(ts_date),
            'asset': AssetsApi.get_asset_url(api_connection, int(asset_pk)),
            'time_series_type': AssetDataApi.get_timeseries_type_url(
                api_connection, TimeSeriesTypesEnum.FORECASTS
            ),
            'quantity_unit': AssetDataApi.get_timeseries_value_unit_url(
                api_connection, QuantityUnitEnum.MW
            ),
            'quantity_type': AssetDataApi.get_timeseries_value_type_url(
                api_connection, QuantityTypeEnum.EFFECT
            ),
            'data': tseries,
            'last_updated': str(pendulum.now('Europe/Oslo')),
        }
        res, _x, _y, _z = AssetDataApi.upsert_timeseries(api_connection, payload)

    # ------------------------------------------------------------------ #
    # 2. InfluxDB write                                                    #
    # ------------------------------------------------------------------ #
    if influx_writer is not None:
        try:
            from energydeskapi.timeseries.timeseries_persister import (
                write_production_forecast_to_influx,
            )
            write_production_forecast_to_influx(
                monthly_rows=monthly_rows,
                asset_meta=asset_meta,
                writer=influx_writer,
            )
        except Exception as exc:  # noqa: BLE001
            # InfluxDB failures must never abort the appserver write.
            logger.error("InfluxDB write failed for asset pk=%s: %s", asset_pk, exc)

    return res


# ---------------------------------------------------------------------------
# InfluxDB writer factories
# ---------------------------------------------------------------------------

def _build_influx_writer_strict(customer_name: str):
    """Build and verify an InfluxDB writer.  Raises on any problem.

    Used by paths where InfluxDB is the explicit target (``--sink influx``).
    Calls ``ping()`` to verify connectivity and token validity, then calls
    ``ensure_bucket_exists()`` to create the bucket when needed.  Any
    failure propagates immediately so the user sees a clear error message
    rather than silently writing nothing.

    Raises
    ------
    RuntimeError
        If the server is unreachable or the token is rejected.
    environ.ImproperlyConfigured
        If ``INFLUXDB_TOKEN`` is not set.
    influxdb_client.rest.ApiException
        On unexpected InfluxDB API errors.
    """
    from energydeskapi.timeseries.influxwriter import build_influx_sink, ensure_bucket_exists

    bucket = "{}_assetdata".format(customer_name)
    logger.info("Connecting to InfluxDB — customer_name='%s' bucket='%s'", customer_name, bucket)
    writer = build_influx_sink(bucket=bucket)
    writer.ping()                    # raises RuntimeError if unreachable / bad token
    ensure_bucket_exists(writer)     # creates bucket when missing, no-op when present
    logger.info("InfluxDB ready — url=%s org='%s' bucket='%s'", writer._url, writer.org, bucket)
    return writer


def _build_influx_writer_optional(customer_name: str):
    """Attempt to build an InfluxDB writer; return ``None`` on any failure.

    Used by paths where InfluxDB is optional (``--sink both`` /
    ``generate_production_assets_and_forecasts()``).  Logs a warning so the
    user knows the InfluxDB write was skipped, but does not abort.
    """
    try:
        return _build_influx_writer_strict(customer_name)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "InfluxDB not available — writing to appserver only.  Reason: %s", exc
        )
        return None


# ---------------------------------------------------------------------------
# Full generation (register assets + write forecasts)
# ---------------------------------------------------------------------------

def generate_production_assets_and_forecasts(api_conn, asset_owner_pk, customer_name="demo"):
    """Register demo plants and generate 10-year monthly production forecasts.

    Writes to both the appserver blob store and InfluxDB (when configured).

    Parameters
    ----------
    api_conn:
        Active EnergyDesk API connection.
    asset_owner_pk:
        Primary key of the asset owner company in the appserver database.
    customer_name:
        Short identifier used to derive the InfluxDB bucket name
        (``"{customer_name}_assetdata"``).  Defaults to ``"demo"``.
    """
    plants_path = os.path.join(os.path.dirname(__file__), "demo_plants.json")
    with open(plants_path, "r", encoding="utf-8") as f:
        plants = json.load(f)

    # --- Ensure asset types exist ---
    hydro_type_pk = get_or_create_asset_type(api_conn, "Hydro Power Plant")
    wind_type_pk  = get_or_create_asset_type(api_conn, "Wind Turbine")
    type_pk_map = {"hydro": hydro_type_pk, "wind": wind_type_pk}

    # --- Register assets ---
    asset_objects = []
    for p in plants:
        ptype = p["type"].lower()
        asset = populate_asset_production_object(
            api_conn,
            description=p["name"],
            asset_owner_pk=asset_owner_pk,
            asset_type_pk=type_pk_map[ptype],
            asset_category_enum=AssetCategoryEnum.PRODUCTION,
            location="{}, {}".format(p["lat"], p["lon"]),
        )
        asset_objects.append((p, asset))

    AssetsApi.create_assets(api_conn, [a for _, a in asset_objects])

    # Reload to get PKs and appserver-populated fields (including price_area)
    df_assets = AssetsApi.get_assets_df(api_conn, parameters={'page_size': 200})
    logger.info("Assets loaded:\n%s", df_assets[['pk', 'description']].to_string())

    # Optional InfluxDB — never aborts if unavailable
    influx_writer = _build_influx_writer_optional(customer_name)

    random.seed(42)  # global seed — keeps sequence identical to the original
    start_year = 2026
    timeseries_date = "{}-01-01".format(start_year)

    try:
        for p in plants:
            match = df_assets[df_assets['description'] == p["name"]]
            if match.empty:
                logger.warning("Asset not found for plant: %s", p["name"])
                continue
            asset_pk = int(match.iloc[0]['pk'])
            asset_row = match.iloc[0]
            asset_meta = {
                "pk":          asset_pk,
                "name":        p["name"],
                "asset_type":  p["type"].lower(),
                "owner":       p["owner"],
                "lat":         p["lat"],
                "lon":         p["lon"],
                "capacity_mw": p["capacity_mw"],
                "price_area":  _resolve_price_area(asset_row, p),
                "bidzone":     "",
            }
            cf_seasonal = CF_MAP[p["type"].lower()]
            plant_bias = random.uniform(0.88, 1.12)
            monthly_rows = []
            for year in range(start_year, start_year + 10):
                annual_factor = random.uniform(0.82, 1.18)
                for month in range(1, 13):
                    days = calendar.monthrange(year, month)[1]
                    noise = random.uniform(0.90, 1.10)
                    cf = cf_seasonal[month - 1] * annual_factor * plant_bias * noise
                    cf = max(0.05, min(cf, 0.98))
                    monthly_rows.append({
                        "period": "{}-{:02d}".format(year, month),
                        "forecast_production_mwh": round(p["capacity_mw"] * days * 24 * cf, 1),
                    })

            save_production_forecast(
                api_conn, asset_pk, asset_meta, timeseries_date, monthly_rows,
                influx_writer=influx_writer,
                write_appserver=True,
            )
            logger.info("Stored %d monthly forecast points for %s (price_area=%s)",
                        len(monthly_rows), p["name"], asset_meta["price_area"])
    finally:
        if influx_writer is not None:
            influx_writer.close()

    return [a for _, a in asset_objects]


# ---------------------------------------------------------------------------
# InfluxDB-only backfill (assets already registered)
# ---------------------------------------------------------------------------

def backfill_influx_from_existing_assets(api_conn, customer_name: str) -> None:
    """Write production forecasts to InfluxDB for assets already in the appserver.

    Does not touch the appserver — looks up existing assets by name to get
    their PKs, regenerates the forecast rows, and writes to InfluxDB only.

    Raises on any InfluxDB connectivity or configuration problem so the
    caller sees a clear error immediately rather than silently writing nothing.

    Parameters
    ----------
    api_conn:
        Active EnergyDesk API connection (read-only asset lookup).
    customer_name:
        Used to derive the InfluxDB bucket name (``"{customer_name}_assetdata"``).
    """
    plants_path = os.path.join(os.path.dirname(__file__), "demo_plants.json")
    with open(plants_path, "r", encoding="utf-8") as f:
        plants = json.load(f)

    # Strict — raises immediately on misconfiguration
    influx_writer = _build_influx_writer_strict(customer_name)

    # Fetch assets including appserver-populated fields (price_area, etc.)
    df_assets = AssetsApi.get_assets_df(api_conn, parameters={'page_size': 200})
    logger.info("Found %d assets in appserver.", len(df_assets))

    from energydeskapi.timeseries.timeseries_persister import write_production_forecast_to_influx

    try:
        total_points = 0
        for p in plants:
            match = df_assets[df_assets['description'] == p["name"]]
            if match.empty:
                logger.warning("Asset '%s' not found in appserver — skipping.", p["name"])
                continue
            asset_pk = int(match.iloc[0]['pk'])
            asset_row = match.iloc[0]
            asset_meta = {
                "pk":          asset_pk,
                "name":        p["name"],
                "asset_type":  p["type"].lower(),
                "owner":       p["owner"],
                "lat":         p["lat"],
                "lon":         p["lon"],
                "capacity_mw": p["capacity_mw"],
                "price_area":  _resolve_price_area(asset_row, p),
                "bidzone":     "",
            }
            monthly_rows = _build_monthly_rows(p)
            n = write_production_forecast_to_influx(
                monthly_rows=monthly_rows,
                asset_meta=asset_meta,
                writer=influx_writer,
            )
            total_points += n
            logger.info("  %s (price_area=%s) — wrote %d points",
                        p["name"], asset_meta["price_area"], n)

        logger.info("InfluxDB backfill complete. Total points written: %d", total_points)
    finally:
        influx_writer.close()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
        handlers=[logging.StreamHandler()],
    )

    parser = argparse.ArgumentParser(
        description="Generate demo production forecasts.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Sink options:
  both        Write to appserver blob store AND InfluxDB  (default)
  appserver   Write only to the appserver blob store
  influx      Write only to InfluxDB — assets must already exist in the
              appserver (e.g. you ran this script or main.py previously).
              Useful for testing InfluxDB without re-running the full setup.

Examples:
  python -m energydeskdemo.production_loader
  python -m energydeskdemo.production_loader --sink influx
  python -m energydeskdemo.production_loader --sink appserver
        """,
    )
    parser.add_argument(
        "--sink",
        choices=["both", "appserver", "influx"],
        default="both",
        help="Which storage backend(s) to write forecasts to (default: both).",
    )
    parser.add_argument(
        "--registry",
        default="981952324",
        help="Company registry number used to look up the asset owner (default: 981952324).",
    )
    args = parser.parse_args()

    from energydeskapi.sdk.common_utils import init_api
    from energydeskapi.customers.customers_api import CustomersApi
    from os.path import dirname

    api_conn = init_api(dirname(__file__))

    company = CustomersApi.get_company_from_registry_number(api_conn, args.registry)
    if company is None:
        print("Company with registry number '{}' not found — run main.py first.".format(args.registry))
        sys.exit(1)

    asset_owner_pk = int(company['pk'])
    customer_name = company.get('short_name', 'aademo').lower().replace(' ', '_')
    logger.info("Customer: '%s'  registry: %s", customer_name, args.registry)

    if args.sink == "influx":
        logger.info("Sink: influx only — backfilling InfluxDB from existing assets.")
        backfill_influx_from_existing_assets(api_conn, customer_name)

    elif args.sink == "appserver":
        logger.info("Sink: appserver only.")
        generate_production_assets_and_forecasts(
            api_conn, asset_owner_pk, customer_name=customer_name
        )

    else:  # "both"
        logger.info("Sink: appserver + InfluxDB.")
        generate_production_assets_and_forecasts(
            api_conn, asset_owner_pk, customer_name=customer_name
        )
