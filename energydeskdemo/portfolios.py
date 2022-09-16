from energydeskapi.customers.customers_api import CustomersApi
from energydeskapi.customers.customers_api import Company
from energydeskapi.types.company_enum_types import CompanyTypeEnum, CompanyRoleEnum, UserRoleEnum
from energydeskapi.portfolios.tradingbooks_api import TradingBooksApi, TradingBook
from energydeskapi.assets.assets_api import Asset, AssetsApi
from energydeskapi.types.asset_enum_types import AssetTypeEnum
from energydeskapi.marketdata.markets_api import MarketsApi
from energydeskapi.types.contract_enum_types import CommodityTypeEnum, ContractTypeEnum
from energydeskapi.customers.users_api import UsersApi
from energydeskapi.contracts.contracts_api import ContractsApi

def add_tradingbook(api_conn, description, asset_pk, manager_pk, contract_types_enum_list, commodity_types_enum_list, trader_list):
    c=TradingBook()
    c.description=description
    c.asset=AssetsApi.get_asset_url(api_conn, asset_pk)
    c.manager=CustomersApi.get_company_url(api_conn, manager_pk)
    c.contract_types=[ContractsApi.get_contract_type_url(api_conn, elem) for elem in contract_types_enum_list]
    c.commodity_types=[MarketsApi.get_commodity_type_url(api_conn,elem) for elem in commodity_types_enum_list]
    c.traders=[UsersApi.get_user_url(api_conn, elem) for elem in trader_list]
    return c

def generate_demo_tradingbooks(api_conn, owner_company):
    accounts_df=AssetsApi.get_assetsbytype_ext(api_conn, AssetTypeEnum.ACCOUNT)
    contract_types=[ ContractTypeEnum.FINANCIAL]
    commodity_types = [CommodityTypeEnum.POWER, CommodityTypeEnum.CO2]

    traders=UsersApi.get_users_by_role(api_conn, UserRoleEnum.TRADER)
    trader_list=[elem['pk'] for elem in traders]
    tradingbooks=[]
    for index, account in accounts_df.iterrows():
        tr=add_tradingbook(api_conn, "Trading on account " + account['description'],
                        account['pk'], owner_company, contract_types, commodity_types, trader_list )
        tradingbooks.append(tr)
    contract_types = [ContractTypeEnum.PHYSICAL]
    wind_df = AssetsApi.get_assetsbytype_ext(api_conn, AssetTypeEnum.WIND)
    print(wind_df)
    n=0
    for index, account in wind_df.iterrows():
        tr=add_tradingbook(api_conn, "PPA trades on " + account['description'],
                        account['pk'], owner_company, contract_types, commodity_types, trader_list )
        tradingbooks.append(tr)
        n=n+1
        if n>2:
            break
    TradingBooksApi.register_tradingbooks(api_conn, tradingbooks)
    return
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
