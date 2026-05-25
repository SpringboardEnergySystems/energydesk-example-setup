from energydeskapi.customers.customers_api import CustomersApi
from energydeskapi.assets.assets_api import Asset, AssetType, AssetsApi
from energydeskapi.types.asset_enum_types import AssetCategoryEnum

def get_or_create_asset_type(api_conn, description):
    """Register an asset type by description and return its PK.
    If an asset type with the same description already exists, return its PK."""
    existing = AssetsApi.get_asset_types(api_conn)
    if existing is not None and not existing.empty:
        match = existing[existing['description'] == description]
        if not match.empty:
            return match.iloc[0]['pk']
    at = AssetType()
    at.description = description
    success, returned_data, status_code, error_msg = AssetsApi.upsert_asset_type(api_conn, at)
    if success and returned_data:
        return returned_data['pk']
    return None


def populate_asset_production_object(api_conn, description, asset_owner_pk, asset_type_pk, asset_category_enum, location):
    a = Asset()
    a.description = description
    a.extern_asset_id = description
    a.meter_id = "x"
    a.sub_meter_id = "x"
    a.asset_type = AssetsApi.get_asset_type_url(api_conn, asset_type_pk)
    a.asset_category = AssetsApi.get_asset_category_url(api_conn, asset_category_enum)
    a.asset_owner = CustomersApi.get_company_url(api_conn, asset_owner_pk)
    a.asset_manager = a.asset_owner
    a.address = ""
    a.city = ""
    a.location = location
    return a