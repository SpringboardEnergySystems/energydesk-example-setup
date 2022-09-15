from energydeskapi.customers.customers_api import CustomersApi
from energydeskapi.customers.customers_api import Company
from energydeskapi.types.company_enum_types import CompanyTypeEnum, CompanyRoleEnum
from energydeskapi.portfolios.tradingbooks_api import TradingBooksApi, TradingBook
from energydeskapi.assets.assets_api import Asset, AssetsApi
from energydeskapi.types.asset_enum_types import AssetTypeEnum
from energydeskapi.types.contract_enum_types import CommodityTypeEnum, ContractTypeEnum
from energydeskapi.customers.users_api import UsersApi
from energydeskapi.contracts.contracts_api import ContractsApi

def add_tradingbook(api_conn, description, asset_pk, manager, contract_types_enum_list, commodity_types_enum_list, trader_list):
    c=TradingBook()
    c.description=description
    c.asset=AssetsApi.get_asset_url(api_conn, asset_pk)
    c.manager=manager
    c.contract_types=[ContractsApi.get_contract_type_url(api_conn, elem) for elem in contract_types_enum_list]
    c.commodity_types=[ContractsApi.get_commodity_type_url(api_conn,elem) for elem in commodity_types_enum_list]
    c.traders=[UsersApi.get_user_url(api_conn, elem) for elem in trader_list]
    return c

def generate_demo_tradingbooks(api_conn, owner_company):
    accounts=AssetsApi.get_assetsbytype_ext(api_conn, AssetTypeEnum.ACCOUNT)
    if len(accounts)==0:
        return
    print(accounts)
    k=accounts['pk'].iloc[0]
    asset_account=AssetsApi.get_asset_url(api_conn, k)
    print(accounts, asset_account)
    return
    companies=[]
    companies.append(add_tradingbook(api_conn, "Legoland Super Traders", "666", CompanyTypeEnum.UTILITY))
    for c in companies:
        print(c.get_dict())
    CustomersApi.create_companies(api_conn, companies)

    # Return the main company to be used for later demo objects
    main_owner=CustomersApi.get_company_from_registry_number(api_conn, "666")
    if main_owner is not None:
        return main_owner['pk']
    else:
        return None
