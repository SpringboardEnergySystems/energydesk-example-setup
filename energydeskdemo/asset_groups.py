import logging

from energydeskapi.assets.assets_api import AssetsApi
from energydeskapi.assets.asset_groups_api import AssetGroupApi
from energydeskapi.assets.assetgroup_utils import register_new_assetgroup
from energydeskapi.types.asset_enum_types import AssetCategoryEnum

logger = logging.getLogger(__name__)

# Asset type names as registered in production_loader.py
HYDRO_TYPE_NAME = "Hydro Power Plant"
WIND_TYPE_NAME = "Wind Turbine"


def delete_asset_groups(api_conn):
    """Delete all existing asset groups and their corresponding group master assets."""
    res = AssetGroupApi.get_asset_groups_embedded(
        api_conn, {'asset_type': AssetCategoryEnum.GROUPED_ASSET.value, 'page_size': 100}
    )
    if not res:
        logger.info("No asset groups to delete.")
        return
    for rec in res:
        logger.info("Deleting asset group: %s (pk=%s)", rec['description'], rec['pk'])
        AssetGroupApi.delete_asset_group(api_conn, rec['pk'])
        mn = rec.get('main_asset')
        if mn:
            AssetsApi.delete_asset(api_conn, mn['pk'])


def register_production_asset_groups(api_conn):
    """
    Create two asset groups from the registered production assets:
      - 'Hydro Power Plants'  – all assets of type "Hydro Power Plant"
      - 'Wind Turbines'       – all assets of type "Wind Turbine"
    """
    # Fetch all production assets (embedded so we get asset_type details)
    jsondata = AssetsApi.get_assets_embedded(
        api_conn, {'asset_category': AssetCategoryEnum.PRODUCTION.value, 'page_size': 500}
    )
    if not jsondata or 'results' not in jsondata:
        logger.warning("No production assets found.")
        return

    groups = {
        HYDRO_TYPE_NAME: [],
        WIND_TYPE_NAME: [],
    }

    for asset in jsondata['results']:
        atype = asset.get('asset_type', {})
        type_name = atype.get('description', '')
        if type_name in groups:
            groups[type_name].append(asset)

    group_display_names = {
        HYDRO_TYPE_NAME: "Hydro Power Plants",
        WIND_TYPE_NAME:  "Wind Turbines",
    }

    for type_name, assets in groups.items():
        if not assets:
            logger.warning("No assets found for type '%s', skipping group.", type_name)
            continue
        group_name = group_display_names[type_name]
        logger.info("Registering asset group '%s' with %d assets.", group_name, len(assets))
        success, data, status, err = register_new_assetgroup(api_conn, group_name, assets)
        if success:
            logger.info("Group '%s' created (pk=%s).", group_name, data.get('pk'))
        else:
            logger.error("Failed to create group '%s': %s", group_name, err)


def generate_demo_asset_groups(api_conn):
    """Entry point: wipe existing groups and recreate from current production assets."""
    delete_asset_groups(api_conn)
    register_production_asset_groups(api_conn)



