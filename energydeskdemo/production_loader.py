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


def save_production_forecast(api_connection, asset_pk, timeseries_date, monthly_rows):
    """
    Store monthly production forecast for a single asset.

    monthly_rows: list of dicts with keys 'period' (YYYY-MM) and 'forecast_production_mwh'
    """
    tseries = []
    for row in monthly_rows:
        period = row['period']           # e.g. "2026-04"
        year, month = map(int, period.split('-'))
        # Use first day of the month, localized to Oslo
        gmttime_dt = pendulum.datetime(year, month, 1, tz='Europe/Oslo')
        utc_dt = gmttime_dt.in_tz('UTC')
        record = {
            'timestamp': utc_dt.strftime('%Y-%m-%dT%H:%M:%S+00:00'),
            'date': gmttime_dt.strftime('%Y-%m-%d'),
            'value': row['forecast_production_mwh'],
            'cost': 0,
        }
        tseries.append(record)

    logger.info("Saving forecast for asset pk={} date={}".format(asset_pk, timeseries_date))
    ts_date = pendulum.parse(timeseries_date, tz='Europe/Oslo')
    payload = {
        'timeseries_date': str(ts_date),
        'asset': AssetsApi.get_asset_url(api_connection, int(asset_pk)),
        'time_series_type': AssetDataApi.get_timeseries_type_url(api_connection, TimeSeriesTypesEnum.FORECASTS),
        'quantity_unit': AssetDataApi.get_timeseries_value_unit_url(api_connection, QuantityUnitEnum.MW),
        'quantity_type': AssetDataApi.get_timeseries_value_type_url(api_connection, QuantityTypeEnum.EFFECT),
        'data': tseries,
        'last_updated': str(pendulum.now('Europe/Oslo')),
    }
    res, x, y, z = AssetDataApi.upsert_timeseries(api_connection, payload)
    return res


def generate_production_assets_and_forecasts(api_conn, asset_owner_pk):
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
    df_assets = AssetsApi.get_assets_df(api_conn, parameters={'page_size':200})
    logger.info("Assets loaded:\n{}".format(df_assets[['pk', 'description']].to_string()))

    # --- Simulate monthly production per plant ---
    random.seed(42)
    start_year = 2026
    years = 10
    timeseries_date = "{}-01-01".format(start_year)  # forecast reference date

    for p in plants:
        ptype = p["type"].lower()
        cf_seasonal = cf_map[ptype]

        # Find the registered asset pk
        match = df_assets[df_assets['description'] == p["name"]]
        if match.empty:
            logger.warning("Asset not found for plant: {}".format(p["name"]))
            continue
        asset_pk = int(match.iloc[0]['pk'])

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

        save_production_forecast(api_conn, asset_pk, timeseries_date, monthly_rows)
        logger.info("Stored {} monthly forecast points for {}".format(len(monthly_rows), p["name"]))

    return all_assets


if __name__ == "__main__":
    from energydeskapi.sdk.common_utils import init_api
    from energydeskapi.customers.customers_api import CustomersApi
    from os.path import dirname
    import sys

    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(message)s',
                        handlers=[logging.StreamHandler()])

    api_conn = init_api(dirname(__file__))
    # Use the same company registry number as generate_users in main.py
    COMPANY_REGISTRY_NUMBER = "981952324"
    company = CustomersApi.get_company_from_registry_number(api_conn, COMPANY_REGISTRY_NUMBER)
    if company is None:
        print("Company with registry number {} not found – run main.py first".format(COMPANY_REGISTRY_NUMBER))
        sys.exit(1)
    asset_owner_pk = int(company['pk'])
    generate_production_assets_and_forecasts(api_conn, asset_owner_pk)
