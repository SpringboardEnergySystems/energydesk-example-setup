from energydeskdemo.asset_utils import get_or_create_asset_type, populate_asset_production_object
from .production_loader import generate_production_assets_and_forecasts

def generate_demo_assets(api_conn, asset_owner_pk):
    # Register asset types first (user-defined), linked to base categories
    get_or_create_asset_type(api_conn, "Wind Turbine")
    get_or_create_asset_type(api_conn, "Clearing Account")
    generate_production_assets_and_forecasts(api_conn, asset_owner_pk)

