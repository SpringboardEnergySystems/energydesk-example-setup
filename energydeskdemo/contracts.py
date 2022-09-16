
import environ
import logging
import copy
from random import randrange
import random
from energydeskapi.sdk.api_connection import ApiConnection
from energydeskapi.customers.customers_api import CustomersApi
from energydeskapi.customers.users_api import UsersApi
from energydeskapi.marketdata.derivatives_api import DerivativesApi
from energydeskapi.portfolios.tradingbooks_api import TradingBooksApi
from energydeskapi.contracts.contracts_api import ContractsApi, Contract
from energydeskapi.types.contract_enum_types import ContractStatusEnum, ContractTypeEnum, CommodityTypeEnum, InstrumentTypeEnum
from os.path import join, dirname
from moneyed import EUR
from energydeskapi.sdk.datetime_utils import convert_datime_to_utcstr, convert_datime_to_locstr
from dotenv import load_dotenv
from energydeskapi.sdk.money_utils import FormattedMoney
from datetime import datetime, timedelta
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(message)s',
                    handlers=[logging.FileHandler("energydesk_client.log"),
                              logging.StreamHandler()])


def generate_demo_trades(api_conn, trading_book):

    ndaq_pk=CustomersApi.get_company_from_registry_number(api_conn, "965662952")['pk']
    prof=UsersApi.get_user_profile(api_conn)
    my_user_key=prof['pk']

    all_prod_df=DerivativesApi.get_products_df(api_conn, "Nasdaq OMX", "Nordic Power", convert_datime_to_utcstr(datetime.today()))
    qtr_products=all_prod_df[all_prod_df.ticker.str.contains("BLQ") &
                    ~all_prod_df.instrument_type.str.contains("EPAD")] #Filter away EPADs in this test
    import pandas as pd
    qtr_products.index = pd.RangeIndex(len(qtr_products.index))
    random.seed(datetime.now())

    fake_deliv_from=(datetime.today() + timedelta(days=200)).replace( hour=0, minute=0, second=0, microsecond=0)
    fake_deliv_until = (datetime.today() + timedelta(days=500)).replace(hour=0, minute=0, second=0, microsecond=0)

    TradingBooksApi.fetch_tradingbooks(api_conn)
    yester = (datetime.today() + timedelta(days=-1)).replace( hour=0, minute=0, second=0, microsecond=0)
    dtstr1=convert_datime_to_utcstr(yester)
    dtstr2=convert_datime_to_locstr(yester, "Europe/Oslo")  #In order to get the date correct
    trading_book = 1  # Use lookup function to set correct trading book key. Server will check if user allowed still
    contract_type = ContractTypeEnum.FINANCIAL
    commodity_type = CommodityTypeEnum.POWER
    contract_status = ContractStatusEnum.REGISTERED
    instrument_type = InstrumentTypeEnum.FORWARD

    counterpart = api_conn.get_base_url() + "/api/customers/companies/" + str(ndaq_pk) + "/"
    marketplace = api_conn.get_base_url() + "/api/customers/companies/" + str(ndaq_pk) + "/"
    trader = api_conn.get_base_url() + "/api/customers/profiles/" + str(my_user_key) + "/"
    c=Contract("EXT ID 667", trading_book, FormattedMoney(55.30, EUR),5,
                                    FormattedMoney(2.1, EUR),
                                    FormattedMoney(2.0, EUR),
               dtstr2[0:10],dtstr1, contract_type, commodity_type, instrument_type,
               contract_status,
               "SELL",
               counterpart,
               marketplace,
               trader)
    c.pk=0
    print("Got ", c.get_dict(api_conn))

    #ContractsApi.register_contract(api_conn, [c])

    full_list=[]
    for i in range(1,100):
        ext="EXT ID " + str(i)
        c.external_contract_id=ext
        c.deliveries=[]
        rnd = randrange(len(qtr_products.index))
        rnd2 = randrange(5)
        c.buy_or_sell="BUY" if rnd2>3 else "SELL"
        selected_poduct=qtr_products.iloc[[rnd]]
        c.standard_product=selected_poduct['pk'].iloc[0]
        #c.add_delivery_period(fake_deliv_from, fake_deliv_until)
        c.contract_status = ContractStatusEnum.REGISTERED
        full_list.append(copy.deepcopy(c))
        print(c.get_dict(api_conn))

    ContractsApi.register_contract(api_conn,full_list)