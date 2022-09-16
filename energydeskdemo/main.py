from energydeskapi.sdk.common_utils import init_api
from energydeskdemo.companies import generate_demo_companïes
from energydeskdemo.assets import generate_demo_assets
from energydeskdemo.users import generate_users
from energydeskdemo.portfolios import generate_demo_tradingbooks
from os.path import join, dirname, sys
import logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(message)s',
                    handlers=[logging.FileHandler("energydesk_demo.log"),
                              logging.StreamHandler()])

if __name__ == '__main__':
    api_conn = init_api(dirname(__file__))  #Loads data from .env initializing the api object
    main_asset_owner_pk=generate_demo_companïes(api_conn)  #Returns the main asset owner
    if main_asset_owner_pk is None:
        print("Cannot continue")
        sys.exit(0)
    generate_demo_assets(api_conn, main_asset_owner_pk)
    generate_users(api_conn, "666")
    generate_demo_tradingbooks(api_conn, main_asset_owner_pk)
