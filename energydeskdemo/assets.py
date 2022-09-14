from energydeskapi.customers.customers_api import CustomersApi
from energydeskapi.assets.assets_api import Asset, AssetsApi
from energydeskapi.types.asset_enum_types import AssetTypeEnum

def populate_asset_production_object(api_conn, description, asset_owner_pk, asset_type_enum, location):
    a=Asset()
    a.description=description
    a.extern_asset_id =description
    a.meter_id = "x"
    a.sub_meter_id = "x"
    a.asset_type = AssetsApi.get_asset_type_url(api_conn, asset_type_enum)
    a.asset_owner = CustomersApi.get_company_url(api_conn, asset_owner_pk)
    a.asset_manager= a.asset_owner  #In sample database make owner and manager the same
    a.location=location
    return a

def populate_asset_accounts_object(api_conn, description, asset_owner_pk, asset_type_enum, location):
    a=Asset()
    a.description=description
    a.extern_asset_id =description
    a.meter_id = "x"
    a.sub_meter_id = "x"
    a.asset_type = AssetsApi.get_asset_type_url(api_conn, asset_type_enum)
    a.asset_owner = CustomersApi.get_company_url(api_conn, asset_owner_pk)
    a.asset_manager= a.asset_owner  #In sample database make owner and manager the same
    a.location = location
    return a

def generate_demo_assets(api_conn, asset_owner_pk):
    assets=[]
    assets.append(populate_asset_production_object(api_conn,
            "Lego Windmill #1", asset_owner_pk, AssetTypeEnum.WIND, "55.734214, 9.126842"))

    assets.append(populate_asset_production_object(api_conn,
            "Lego Windmill #2", asset_owner_pk, AssetTypeEnum.WIND, "55.734366, 9.127733"))

    assets.append(populate_asset_production_object(api_conn,
            "Lego Windmill #3", asset_owner_pk, AssetTypeEnum.WIND, "55.734528, 9.128298"))

    assets.append(populate_asset_production_object(api_conn,
            "Lego Windmill #4", asset_owner_pk, AssetTypeEnum.WIND, "55.734757, 9.129099"))

    assets.append(populate_asset_production_object(api_conn,
            "Lego Windmill #5", asset_owner_pk, AssetTypeEnum.WIND, "55.735005, 9.129703"))

    assets.append(populate_asset_production_object(api_conn,
            "Lego Windmill #6", asset_owner_pk, AssetTypeEnum.WIND, "55.735316, 9.129246"))

    assets.append(populate_asset_production_object(api_conn,
            "Lego Windmill #7", asset_owner_pk, AssetTypeEnum.WIND, "55.735090, 9.128476"))

    assets.append(populate_asset_production_object(api_conn,
            "Lego Windmill #8", asset_owner_pk, AssetTypeEnum.WIND, "55.735457, 9.128835"))

    assets.append(populate_asset_production_object(api_conn,
            "Lego Windmill #9", asset_owner_pk, AssetTypeEnum.WIND, "55.735462, 9.128011"))

    assets.append(populate_asset_production_object(api_conn,
            "Lego Windmill #10", asset_owner_pk, AssetTypeEnum.WIND, "55.735059, 9.126823"))

    assets.append(populate_asset_production_object(api_conn,
            "Clearing Account #1", asset_owner_pk, AssetTypeEnum.ACCOUNT, "0,0")) # Account does not have geo loc

    for a in assets:
        print(a.get_dict())
    AssetsApi.create_assets(api_conn, assets)
    df = AssetsApi.get_assets_ext(api_conn)
    print(df)
