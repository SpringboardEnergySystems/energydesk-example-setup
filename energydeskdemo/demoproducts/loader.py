import json
import logging
import os
from os.path import dirname, join

import environ
import pendulum
import pytz
import requests
from energydeskapi.marketdata.spotprices_api import SpotPricesApi
from energydeskapi.marketdata.derivatives_api import DerivativesApi
from energydeskapi.sdk.api_connection import ApiTempConnection
from energydeskapi.marketdata.markets_api import MarketsApi
from energydeskapi.marketdata.products_api import ProductsApi
from marketfeed.market_product import MarketProduct, ProductPrice
from marketfeed.products.product_resolver import ProductResolver

logger = logging.getLogger(__name__)

DEFAULT_DAYS_BACK = 30


def build_connections(env_dir: str = None) -> tuple[ApiTempConnection, ApiTempConnection]:
    """Read source and target EnergyDesk connection details from the .env file.

    Required env vars:
        ENERGYDESK_URL          – target instance base URL
        ENERGYDESK_TOKEN        – target instance API token
        ENERGYDESK_SOURCE_URL   – source instance base URL
        ENERGYDESK_SOURCE_TOKEN – source instance API token

    Returns:
        (source_api_conn, target_api_conn)
    """
    env = environ.Env()
    if env_dir is None:
        env_dir = dirname(__file__)
    env_file = join(env_dir, '.env')
    if os.path.exists(env_file):
        environ.Env.read_env(env_file)
        logger.info("Loaded env from %s", env_file)
    else:
        logger.warning("No .env file found at %s – relying on OS environment", env_file)

    target_url   = env('ENERGYDESK_URL')
    target_token = env('ENERGYDESK_TOKEN')
    source_url   = env('ENERGYDESK_SOURCE_URL')
    source_token = env('ENERGYDESK_SOURCE_TOKEN')

    source_conn = ApiTempConnection(source_url, source_token)
    source_conn.set_token(source_token, "Token")
    target_conn = ApiTempConnection(target_url, target_token)
    target_conn.set_token(target_token, "Token")
    logger.info("Source: %s  |  Target: %s", source_url, target_url)
    return source_conn, target_conn


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _create_product_object(d: dict) -> MarketProduct:
    area = d['commodity_definition']['area']
    if area == "SYS" and d['market_ticker'].startswith("SYOSL"):
        area = "NO1"
    return MarketProduct(
        ticker=d['market_ticker'],
        alternative_ticker=d['market_ticker'],
        description=d['commodity_definition']['description'],
        market=d['commodity_definition']['market']['name'],
        market_place=d['market_place']['name'],
        instrument=d['commodity_definition']['instrument_type']['code'],
        currency_code="EUR",
        denomination=d['denomination'],
        price_area=area,
        commodity=d['commodity_definition']['commodity_type']['code'],
        blocksize=d['commodity_definition']['block_size_category']['code'],
        traded_from=d['traded_from'],
        traded_until=d['traded_until'],
        delivery_from=d['commodity_definition']['delivery_from'],
        delivery_until=d['commodity_definition']['delivery_until'],
        structure_type=d['commodity_definition']['structure_type']['code'],
        price_basis_code=d['commodity_definition']['price_basis']['code'],
        cascaded_date=d['commodity_definition']['cascaded_date'],
    )


def _save_spot_prices(target_conn: ApiTempConnection, currency: str, df_prices):
    logger.info("Saving %d spot price rows for %s", len(df_prices), currency)
    header = {'Authorization': 'Token ' + str(target_conn.get_token())}
    payload = {'record_type': 'spotpricescomplete'}
    payload['datarecord'] = {
        'currency': currency,
        'data': json.loads(df_prices.to_json(orient='records', date_format='iso')),
    }
    resp = requests.post(
        target_conn.get_base_url() + "/api/markets/updated-marketdata/",
        json=payload,
        headers=header,
    )
    if resp.status_code > 210:
        logger.warning("Problem saving spot prices: %s", resp.text)


def _save_price_data(target_conn: ApiTempConnection, record_type: str, marketdata):
    full_url = target_conn.get_base_url() + "/api/markets/updated-marketdata/"
    headers = target_conn.get_authorization_header()
    payload = {"record_type": record_type, "datarecord": json.dumps(marketdata)}
    resp = requests.post(full_url, data=payload, headers=headers)
    if resp.status_code > 210:
        logger.warning("Problem saving %s: %s", record_type, resp.text)


# ---------------------------------------------------------------------------
# Public retrieval functions
# ---------------------------------------------------------------------------

def retrieve_spot_prices(source_conn: ApiTempConnection, target_conn: ApiTempConnection,
                         days_back: int = DEFAULT_DAYS_BACK):
    """Fetch spot prices from source for the last *days_back* days and push to target."""
    period_from = pendulum.today("Europe/Paris").subtract(days=days_back).add(days=1).isoformat()[:10]
    parameters = {'period_from': period_from, 'resolution': '15min'}
    for currency in ('EUR', 'NOK'):
        parameters['currency_code'] = currency
        df = SpotPricesApi.get_spot_prices_df(source_conn, parameters)
        if df is None or len(df) == 0:
            logger.warning("No spot prices for %s", currency)
            continue
        logger.info("Retrieved %d spot price rows for %s", len(df), currency)
        df.index = df.index.tz_convert(pytz.UTC)
        df['datetimehour'] = df.index
        _save_spot_prices(target_conn, currency, df)


def retrieve_products(source_conn: ApiTempConnection, target_conn: ApiTempConnection):
    """Fetch all active futures products from source and push to target."""
    params = {'commodity_definition__delivery_until__gt': '2026-01-01', 'page_size': 10000}
    res = ProductsApi.get_market_products_embedded(source_conn, params)
    if res is None:
        logger.warning("No products returned from source")
        return
    count = 0
    for r in res.get('results', []):
        product = _create_product_object(r)
        MarketsApi.send_market_update(target_conn, record_type="products", marketdata=product.json)
        count += 1
    logger.info("Pushed %d products to target", count)


def retrieve_futures_prices(source_conn: ApiTempConnection, target_conn: ApiTempConnection,
                            days_back: int = DEFAULT_DAYS_BACK):
    """Fetch NASDAQ OMX futures prices in chunks of 50 days and push to target."""
    chunk = 50
    t_end = pendulum.today("Europe/Paris")
    t_start = t_end.subtract(days=days_back)
    current_end = t_end

    while current_end > t_start:
        current_start = max(current_end.subtract(days=chunk), t_start)
        df = DerivativesApi.fetch_prices_in_period(
            source_conn,
            market_place="NASDAQ_OMX",
            market_name=None,
            ticker=None,
            period_from=str(current_start)[:10],
            period_until=str(current_end)[:10],
        )
        if df is None or len(df) == 0:
            current_end = current_start
            continue

        records = json.loads(df.to_json(orient='records', date_format='iso'))
        logger.info("Got %d price records for %s – %s", len(records),
                    str(current_start)[:10], str(current_end)[:10])

        for rec in records:
            pr = ProductResolver.resolve_product(rec['ticker'])
            if pr is None:
                logger.warning("Could not resolve ticker %s", rec['ticker'])
                continue
            pp = {
                'ticker':     rec['ticker'],
                'market':     pr.market,
                'timestamp':  rec['timestamp'],
                'bid':   float(rec['bid']   or 0),
                'ask':   float(rec['ask']   or 0),
                'open':  float(rec['open']  or 0),
                'last':  float(rec['last']  or 0),
                'high':  float(rec['high']  or 0),
                'low':   float(rec['low']   or 0),
                'close': float(rec['close'] or 0),
                'prev':  float(rec['prev']  or 0),
                'fix':   float(rec['close'] or 0),
                'volume': 0,
            }
            pp_obj = ProductPrice.from_json(json.dumps(pp))
            _save_price_data(target_conn, record_type="prices", marketdata=pp_obj.__dict__)

        current_end = current_start


def retrieve_all_data(source_conn: ApiTempConnection, target_conn: ApiTempConnection,
                      days_back: int = DEFAULT_DAYS_BACK):
    """Pull spot prices, products and futures prices from source and push to target."""
    logger.info("=== Starting market data retrieval: last %d days ===", days_back)
    retrieve_spot_prices(source_conn, target_conn, days_back=days_back)
    retrieve_products(source_conn, target_conn)
    retrieve_futures_prices(source_conn, target_conn, days_back=days_back)
    logger.info("=== Market data retrieval complete ===")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(message)s',
        handlers=[
            logging.FileHandler("energydesk_client.log"),
            logging.StreamHandler(),
        ],
    )
    source_api_conn, target_api_conn = build_connections()
    retrieve_all_data(source_api_conn, target_api_conn, days_back=DEFAULT_DAYS_BACK)
