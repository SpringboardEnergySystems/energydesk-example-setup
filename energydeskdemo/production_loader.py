import json
import random
import calendar
import logging
import os

import pendulum

from energydeskapi.assets.assets_api import AssetsApi
from energydeskapi.assetdata.assetdata_api import AssetDataApi
from energydeskapi.types.asset_enum_types import AssetCategoryEnum, TimeSeriesTypesEnum
from energydeskapi.types.contract_enum_types import QuantityUnitEnum, QuantityTypeEnum

from energydeskdemo.asset_utils import get_or_create_asset_type, populate_asset_production_object

logger = logging.getLogger(__name__)


def save_production_forecast(
    api_connection,
    asset_pk,
    asset_meta,
    timeseries_date,
    monthly_rows,
    influx_writer=None,
):
    """
    Store monthly production forecast for a single asset.

    Writes to the appserver blob store unconditionally.  When ``influx_writer``
    is provided the same data is also written to InfluxDB so forecasts can be
    aggregated and displayed directly from there.

    Parameters
    ----------
    api_connection:
        Active EnergyDesk API connection.
    asset_pk:
        Integer primary key of the asset in the appserver database.
    asset_meta:
        Dict with asset metadata used as InfluxDB tags::

            {
                "pk":          <int>   # same as asset_pk
                "name":        <str>,
                "asset_type":  <str>,  # e.g. "hydro" / "wind"
                "owner":       <str>,
                "lat":         <float>,
                "lon":         <float>,
                "capacity_mw": <float>,
                "bidzone":     <str>,  # optional, "" when unknown
            }

    timeseries_date:
        ISO-format reference date string for the forecast series.
    monthly_rows:
        List of dicts with keys ``"period"`` (``"YYYY-MM"``) and
        ``"forecast_production_mwh"`` (float).
    influx_writer:
        Optional ``_InfluxWriter`` from ``build_influx_sink()``.  When
        ``None`` only the appserver blob write is performed.
    """
    # ------------------------------------------------------------------ #
    # 1. Build the appserver payload (unchanged from original)             #
    # ------------------------------------------------------------------ #
    tseries = []
    for row in monthly_rows:
        period = row['period']           # e.g. "2026-04"
        year, month = map(int, period.split('-'))
        gmttime_dt = pendulum.datetime(year, month, 1, tz='Europe/Oslo')
        utc_dt = gmttime_dt.in_tz('UTC')
        record = {
            'timestamp': utc_dt.strftime('%Y-%m-%dT%H:%M:%S+00:00'),
            'date': gmttime_dt.strftime('%Y-%m-%d'),
            'value': row['forecast_production_mwh'],
            'cost': 0,
        }
        tseries.append(record)

    logger.info("Saving forecast for asset pk=%s date=%s", asset_pk, timeseries_date)
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
    res, x, y, z = AssetDataApi.upsert_timeseries(api_connection, payload)

    # ------------------------------------------------------------------ #
    # 2. Mirror to InfluxDB when a writer is provided                      #
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
            # InfluxDB write failures must never abort the appserver write.
            logger.error(
                "InfluxDB write failed for asset pk=%s: %s", asset_pk, exc
            )

    return res


def _build_influx_writer(customer_name: str):
    """Attempt to build an InfluxDB writer for ``{customer_name}_assetdata``.

    Returns ``None`` when the environment is not configured for InfluxDB
    (i.e. ``INFLUXDB_TOKEN`` is not set) so that the demo setup continues
    to work without InfluxDB.
    """
    try:
        from energydeskapi.timeseries.influxwriter import (
            build_influx_sink,
            ensure_bucket_exists,
        )
        bucket = "{}_assetdata".format(customer_name)
        writer = build_influx_sink(bucket=bucket)
        ensure_bucket_exists(writer)
        logger.info("InfluxDB writer ready — bucket: %s", bucket)
        return writer
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "InfluxDB not available (%s) — writing to appserver only.", exc
        )
        return None


def generate_production_assets_and_forecasts(api_conn, asset_owner_pk, customer_name="demo"):
    """Register demo plants and generate 10-year monthly production forecasts.

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

    # --- Capacity factors per month (index 0 = January) ---
    HYDRO_CF = [0.62, 0.58, 0.55, 0.50, 0.72, 0.88, 0.78, 0.62, 0.57, 0.64, 0.72, 0.68]
    WIND_CF  = [0.45, 0.43, 0.39, 0.34, 0.30, 0.27, 0.26, 0.29, 0.34, 0.39, 0.44, 0.46]

    # --- Ensure asset types exist ---
    hydro_type_pk = get_or_create_asset_type(api_conn, "Hydro Power Plant")
    wind_type_pk  = get_or_create_asset_type(api_conn, "Wind Turbine")

    type_pk_map = {
        "hydro": hydro_type_pk,
        "wind":  wind_type_pk,
    }
    cf_map = {
        "hydro": HYDRO_CF,
        "wind":  WIND_CF,
    }

    # --- Register assets and collect their PKs ---
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

    # Upsert all assets at once
    all_assets = [a for _, a in asset_objects]
    AssetsApi.create_assets(api_conn, all_assets)

    # Reload assets to get PKs
    df_assets = AssetsApi.get_assets_df(api_conn, parameters={'page_size': 200})
    logger.info("Assets loaded:\n%s", df_assets[['pk', 'description']].to_string())

    # --- Build InfluxDB writer (optional — skipped when not configured) ---
    influx_writer = _build_influx_writer(customer_name)

    # --- Simulate monthly production per plant ---
    random.seed(42)
    start_year = 2026
    years = 10
    timeseries_date = "{}-01-01".format(start_year)  # forecast reference date

    try:
        for p in plants:
            ptype = p["type"].lower()
            cf_seasonal = cf_map[ptype]

            # Find the registered asset pk
            match = df_assets[df_assets['description'] == p["name"]]
            if match.empty:
                logger.warning("Asset not found for plant: %s", p["name"])
                continue
            asset_pk = int(match.iloc[0]['pk'])

            asset_meta = {
                "pk":          asset_pk,
                "name":        p["name"],
                "asset_type":  ptype,
                "owner":       p["owner"],
                "lat":         p["lat"],
                "lon":         p["lon"],
                "capacity_mw": p["capacity_mw"],
                "bidzone":     "",  # TODO: derive from grid-area mapping
            }

            plant_bias = random.uniform(0.88, 1.12)
            monthly_rows = []

            for year in range(start_year, start_year + years):
                annual_hydro_factor = random.uniform(0.82, 1.18)
                for month in range(1, 13):
                    days = calendar.monthrange(year, month)[1]
                    hours = days * 24
                    monthly_noise = random.uniform(0.90, 1.10)
                    cf = cf_seasonal[month - 1] * annual_hydro_factor * plant_bias * monthly_noise
                    cf = max(0.05, min(cf, 0.98))
                    production_mwh = p["capacity_mw"] * hours * cf
                    monthly_rows.append({
                        "period": "{}-{:02d}".format(year, month),
                        "forecast_production_mwh": round(production_mwh, 1),
                    })

            save_production_forecast(
                api_conn,
                asset_pk,
                asset_meta,
                timeseries_date,
                monthly_rows,
                influx_writer=influx_writer,
            )
            logger.info(
                "Stored %d monthly forecast points for %s",
                len(monthly_rows), p["name"],
            )
    finally:
        if influx_writer is not None:
            influx_writer.close()

    return all_assets


if __name__ == "__main__":
    from energydeskapi.sdk.common_utils import init_api
    from energydeskapi.customers.customers_api import CustomersApi
    from os.path import dirname
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(message)s',
        handlers=[logging.StreamHandler()],
    )

    api_conn = init_api(dirname(__file__))
    # Use the same company registry number as generate_users in main.py
    COMPANY_REGISTRY_NUMBER = "981952324"
    company = CustomersApi.get_company_from_registry_number(api_conn, COMPANY_REGISTRY_NUMBER)
    if company is None:
        print("Company with registry number {} not found – run main.py first".format(
            COMPANY_REGISTRY_NUMBER
        ))
        sys.exit(1)
    asset_owner_pk = int(company['pk'])
    # Derive a customer_name slug from the company name for the InfluxDB bucket
    customer_name = company.get('short_name', 'aademo').lower().replace(' ', '_')
    generate_production_assets_and_forecasts(api_conn, asset_owner_pk, customer_name=customer_name)
