from energydeskapi.sdk.common_utils import init_api
from energydeskdemo.companies import load_demo_company
from energydeskdemo.assets import generate_demo_assets
from energydeskdemo.users import generate_users
from energydeskdemo.production_loader import generate_production_assets_and_forecasts
from energydeskdemo.asset_groups import generate_demo_asset_groups
from energydeskdemo.portfolios import load_portfolios
from energydeskdemo.demoproducts.loader import build_connections, retrieve_all_data
from os.path import join, dirname, sys
import logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(message)s',
                    handlers=[logging.FileHandler("energydesk_demo.log"),
                              logging.StreamHandler()])

DEMO_COMPANY_REGNUMBER="981952324"

if __name__ == '__main__':
    env_dir = dirname(__file__)
    api_conn = init_api(env_dir)  #Loads data from .env initializing the api object
    main_asset_owner_pk=load_demo_company(api_conn, company_regnumber=DEMO_COMPANY_REGNUMBER)  #Returns the main asset owner
    if main_asset_owner_pk is None:
        print("Cannot continue")
        sys.exit(0)
    generate_demo_assets(api_conn, main_asset_owner_pk)
    assets=generate_production_assets_and_forecasts(api_conn, main_asset_owner_pk)
    generate_demo_asset_groups(api_conn)
    generate_users(api_conn, DEMO_COMPANY_REGNUMBER)
    load_portfolios(api_conn, owner_company_pk=main_asset_owner_pk)
    source_conn, target_conn = build_connections(env_dir)
    retrieve_all_data(source_conn, target_conn)
