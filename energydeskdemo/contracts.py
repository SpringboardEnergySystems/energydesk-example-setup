"""
Generate demo/test contracts for ICE Emission Futures and European Options.

Configuration is at the top of this file. Products must already exist in the
energydesk appserver database (loaded via the ICE product collector).

REST calls go directly via ApiConnection.exec_post_url / exec_get_url
without relying on the old SDK contract marshalling.

Trading books:
  FUTURES_TRADING_BOOK_ID  – book to store ICE EUA futures
  OPTIONS_TRADING_BOOK_ID  – book to store ICE EUA European options (default 82)
"""

import logging
import random
import uuid
from datetime import datetime, timezone

from energydeskapi.sdk.api_connection import ApiConnection
from energydeskapi.sdk.common_utils import init_api
from os.path import dirname
from energydeskdemo.companies import register_ice_company
from energydeskdemo.fee_rates import register_ice_fee_rates

# ---------------------------------------------------------------------------
# ── CONFIGURATION ──────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------
NUM_FUTURES              = 30       # number of random futures contracts to generate
NUM_OPTIONS              = 30       # number of random option contracts to generate

FUTURES_TRADING_BOOK_ID  = 81       # Change to your futures trading book pk
OPTIONS_TRADING_BOOK_ID  = 82       # "EMISSION_OPTIONS" book

BASE_FUTURES_PRICE       = 68.0     # EUR/tonne – centre for random price
BASE_OPTION_PREMIUM      = 2.5      # EUR/tonne – centre for random premium
PRICE_JITTER_PCT         = 0.10     # ±10 % random jitter around base price

CURRENCY                 = "EUR"
CONTRACT_STATUS_PK       = 1        # 1 = REGISTERED
CONTRACT_TYPE_EEX_PK     = 2        # ContractTypeEnum.EEX – used for both futures and options
QUANTITY_TYPE_LOTS       = 7        # QuantityTypeEnum.LOTS
QUANTITY_UNIT_LOTS       = 5        # QuantityUnitEnum.LOTS

ICE_MARKETPLACE_NAME     = "ICE"
FUTURES_INSTRUMENT_CODE  = "FUT"
OPTIONS_INSTRUMENT_CODE  = "EUROPT"
EMISSION_COMMODITY_CODE  = "EUA"
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler("energydesk_client.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

def _url(base: str, path: str) -> str:
    """Build an absolute URL with a trailing slash."""
    full = base.rstrip("/") + "/" + path.lstrip("/")
    return full if full.endswith("/") else full + "/"


def _trading_book_url(base: str, pk: int) -> str:
    return _url(base, f"api/portfoliomanager/tradingbooks/{pk}/")


def _contract_type_url(base: str, pk: int) -> str:
    return _url(base, f"api/portfoliomanager/contracttypes/{pk}/")


def _contract_status_url(base: str, pk: int) -> str:
    return _url(base, f"api/portfoliomanager/contractstatuses/{pk}/")


def _qty_type_url(base: str, pk: int) -> str:
    return _url(base, f"api/portfoliomanager/quantitytypes/{pk}/")


def _qty_unit_url(base: str, pk: int) -> str:
    return _url(base, f"api/portfoliomanager/quantityunits/{pk}/")


def _company_url(base: str, pk: int) -> str:
    return _url(base, f"api/customers/companies/{pk}/")


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def _resolve_current_trader(api_conn: ApiConnection) -> str | None:
    """Return the REST URL for the currently authenticated user's profile (used as trader)."""
    base = api_conn.get_base_url()
    profile = api_conn.exec_get_url("/api/energydesk/get-user-profile/")
    if profile and isinstance(profile, dict) and "pk" in profile:
        pk = profile["pk"]
        logger.info(f"Resolved trader profile pk={pk}")
        return _url(base, f"api/customers/profiles/{pk}/")
    logger.warning("Could not resolve trader profile – trader field will be omitted")
    return None


ICE_FUTURES_EUROPE_LEI = "549300UF4R84F48NCH34"


def _resolve_ice_company(api_conn: ApiConnection) -> str | None:
    """Return the REST URL for the ICE Futures Europe company (used as counterpart).

    Looks up by LEI code first (unique and stable), then falls back to a
    name substring search in case the record was registered differently.
    """
    base = api_conn.get_base_url()

    # Primary: lookup by LEI code (stored in both lei_code and registry_number)
    result = api_conn.exec_get_url("/api/customers/companies/", {"lei_code": ICE_FUTURES_EUROPE_LEI})
    companies = result if isinstance(result, list) else (result.get("results", []) if isinstance(result, dict) else [])
    if companies:
        pk = companies[0]["pk"]
        logger.info(f"Found ICE Futures Europe by LEI code pk={pk}")
        return _company_url(base, pk)

    # Secondary: registry_number was set to the LEI code during registration
    result = api_conn.exec_get_url("/api/customers/companies/", {"registry_number": ICE_FUTURES_EUROPE_LEI})
    companies = result if isinstance(result, list) else (result.get("results", []) if isinstance(result, dict) else [])
    if companies:
        pk = companies[0]["pk"]
        logger.info(f"Found ICE Futures Europe by registry_number pk={pk}")
        return _company_url(base, pk)

    # Fallback: name substring search
    result = api_conn.exec_get_url("/api/customers/companies/", {"page_size": 500})
    companies = result if isinstance(result, list) else (result.get("results", []) if isinstance(result, dict) else [])
    for c in companies:
        name = (c.get("name") or "").upper()
        if "ICE" in name:
            pk = c["pk"]
            logger.info(f"Found ICE company (name fallback) pk={pk}, name={c.get('name','?')}")
            return _company_url(base, pk)

    logger.warning("Could not find ICE Futures Europe – counterpart will be omitted")
    return None


def _fetch_products_embedded(api_conn: ApiConnection, instrument_code: str) -> list[dict]:
    """Fetch ICE EUA products of a given instrument type from the embedded endpoint.

    Handles pagination and returns the flat list of market product dicts.
    """
    all_products: list[dict] = []
    params = {
        "market_place__name": ICE_MARKETPLACE_NAME,
        "commodity_definition__instrument_type__code": instrument_code,
        "commodity_definition__commodity_type__code": EMISSION_COMMODITY_CODE,
        "page_size": 500,
    }

    result = api_conn.exec_get_url("/api/markets/marketproducts/embedded/", params)
    if result is None:
        logger.error(f"No response fetching {instrument_code} products")
        return []

    if isinstance(result, list):
        all_products = result
    elif isinstance(result, dict):
        all_products = result.get("results", [])
        next_url = result.get("next")
        while next_url:
            trailing = next_url.replace(api_conn.get_base_url(), "")
            paged = api_conn.exec_get_url(trailing)
            if paged and isinstance(paged, dict):
                all_products.extend(paged.get("results", []))
                next_url = paged.get("next")
            else:
                break

    logger.info(f"Fetched {len(all_products)} ICE {instrument_code} EUA products")
    return all_products


# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------

def _jitter(base_price: float) -> float:
    return round(base_price * (1.0 + random.uniform(-PRICE_JITTER_PCT, PRICE_JITTER_PCT)), 2)


def _now_utc_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _unique_ext_id(prefix: str) -> str:
    return f"{prefix}-{_today_str()}-{uuid.uuid4().hex[:8].upper()}"


def _base_contract(
    base_url: str,
    product_code: str,
    trading_book_pk: int,
    price: float,
    qty: int,
    buy_or_sell: str,
    counterpart_url: str | None,
    trader_url: str | None,
    ext_id: str,
    contract_type_pk: int = CONTRACT_TYPE_EEX_PK,
    extra_tags: list[dict] | None = None,
) -> dict:
    """Return the minimal contract dict accepted by the REST API bulkinsert endpoint.

    The server resolves the full CommodityDefinition FK from product_code alone,
    so the commodity sub-dict can stay minimal.
    """
    payload = {
        "pk": 0,
        "external_contract_id": ext_id,
        "commodity": {
            "product_code": product_code,
            "commodity_profile": None,   # null for plain/baseload exchange products
        },
        "trading_book":   _trading_book_url(base_url, trading_book_pk),
        "trade_date":     _today_str(),
        "trade_time":     _now_utc_str(),
        "contract_type":  _contract_type_url(base_url, contract_type_pk),
        "contract_status": _contract_status_url(base_url, CONTRACT_STATUS_PK),
        "buy_or_sell":    buy_or_sell,
        "contract_price": {"amount": price, "currency": CURRENCY},
        "quantity":       float(qty),
        "quantity_type":  _qty_type_url(base_url, QUANTITY_TYPE_LOTS),
        "quantity_unit":  _qty_unit_url(base_url, QUANTITY_UNIT_LOTS),
        # Zero fees (model has default=0, but serializer fields declared without required=False)
        "trading_fee":           {"amount": 0.0, "currency": CURRENCY},
        "clearing_fee":          {"amount": 0.0, "currency": CURRENCY},
        "clearing_commission_fee": {"amount": 0.0, "currency": CURRENCY},
        "broker_fee":            {"amount": 0.0, "currency": CURRENCY},
        # Empty collections
        "contract_tags":       extra_tags or [],
        "certificates":        [],
        "capacity_parameters": [],
        "cascading_generated": False,
    }
    if counterpart_url:
        payload["counterpart"] = counterpart_url
    if trader_url:
        payload["trader"] = trader_url
    return payload


def _build_futures_contracts(
    api_conn: ApiConnection,
    products: list[dict],
    n: int,
    counterpart_url: str | None,
    trader_url: str | None,
) -> list[dict]:
    """Build N random ICE emission futures contract payloads."""
    if not products:
        logger.warning("No ICE FUT products available – skipping futures generation")
        return []

    base = api_conn.get_base_url()
    contracts = []

    for _ in range(n):
        product = random.choice(products)
        ticker = product.get("market_ticker", "")
        if not ticker:
            continue

        contracts.append(
            _base_contract(
                base_url=base,
                product_code=ticker,
                trading_book_pk=FUTURES_TRADING_BOOK_ID,
                price=_jitter(BASE_FUTURES_PRICE),
                qty=random.randint(1, 20),
                buy_or_sell=random.choice(["BUY", "SELL"]),
                counterpart_url=counterpart_url,
                trader_url=trader_url,
                ext_id=_unique_ext_id("ICE-FUT"),
            )
        )

    logger.info(f"Built {len(contracts)} futures contract payloads")
    return contracts


def _build_option_contracts(
    api_conn: ApiConnection,
    products: list[dict],
    n: int,
    counterpart_url: str | None,
    trader_url: str | None,
) -> list[dict]:
    """Build N random ICE European option contract payloads.

    The option ticker (e.g. FEUA112026P083) is used as product_code.
    The server resolves the full CommodityDefinition and its linked
    CommodityOption parameters (strike, expiry, underlying) from the DB.

    Option type and underlying are stored as contract_tags for easy UI
    filtering without needing to dereference the commodity definition.
    """
    if not products:
        logger.warning("No ICE EUROPT products available – skipping options generation")
        return []

    base = api_conn.get_base_url()
    contracts = []

    for _ in range(n):
        product = random.choice(products)
        ticker = product.get("market_ticker", "")
        if not ticker:
            continue

        # Extract option parameters from the embedded commodity definition
        commodity_def = product.get("commodity_definition") or {}
        params_list   = commodity_def.get("parameters_for_option", [])
        tags: list[dict] = []

        if params_list:
            p = params_list[0]
            opt_type   = p.get("option_type", "?")    # "C" or "P"
            strike     = p.get("strike_price", "?")
            expiry     = (p.get("expiration_date") or "")[:10]
            underlying = (p.get("underlying_commodity") or {}).get("product_code", "?")
            tags = [
                {
                    "pk": 0,
                    "tagname": f"OPT-{opt_type}",
                    "description": f"{opt_type} @ {strike} exp {expiry}",
                    "is_active": True,
                },
                {
                    "pk": 0,
                    "tagname": f"UND-{underlying}",
                    "description": f"Underlying: {underlying}",
                    "is_active": True,
                },
            ]

        contracts.append(
            _base_contract(
                base_url=base,
                product_code=ticker,
                trading_book_pk=OPTIONS_TRADING_BOOK_ID,
                price=_jitter(BASE_OPTION_PREMIUM),
                qty=random.randint(1, 10),
                buy_or_sell=random.choice(["BUY", "SELL"]),
                counterpart_url=counterpart_url,
                trader_url=trader_url,
                ext_id=_unique_ext_id("ICE-OPT"),
                extra_tags=tags,
            )
        )

    logger.info(f"Built {len(contracts)} option contract payloads")
    return contracts


# ---------------------------------------------------------------------------
# Single-contract POST
# ---------------------------------------------------------------------------

def _post_contracts_one_by_one(
    api_conn: ApiConnection,
    contracts: list[dict],
    label: str,
) -> tuple[int, int]:
    """POST each contract individually to POST /api/portfoliomanager/contracts/.

    Uses the single-insert endpoint so each call can be tested and
    documented independently (one contract per HTTP request).
    Returns (n_ok, n_failed).
    """
    n_ok = n_failed = 0

    for i, contract in enumerate(contracts, start=1):
        ext_id = contract.get("external_contract_id", f"#{i}")
        success, data, status_code, error_msg = api_conn.exec_post_url(
            "/api/portfoliomanager/contracts/", contract
        )
        if success:
            n_ok += 1
            stored_pk = data.get("pk", "?") if isinstance(data, dict) else "?"
            logger.info(
                f"[{label}] {i}/{len(contracts)}: stored OK "
                f"(pk={stored_pk}, ext={ext_id}, HTTP {status_code})"
            )
        else:
            n_failed += 1
            logger.error(
                f"[{label}] {i}/{len(contracts)}: FAILED "
                f"(ext={ext_id}, HTTP {status_code}) – {error_msg}"
            )

    return n_ok, n_failed


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def generate_ice_emission_contracts(api_conn: ApiConnection) -> None:
    """Generate and register random ICE emission futures and option contracts.

    Edit the CONFIG block at the top of this module to adjust counts,
    trading books, and base prices.
    """
    logger.info("=" * 60)
    logger.info("ICE Emission Contract Generator")
    logger.info(f"  Futures: {NUM_FUTURES}  →  book {FUTURES_TRADING_BOOK_ID}")
    logger.info(f"  Options: {NUM_OPTIONS}  →  book {OPTIONS_TRADING_BOOK_ID}")
    logger.info("=" * 60)

    random.seed()

    # 1. Resolve ICE as the counterpart company and current user as trader
    counterpart_url = _resolve_ice_company(api_conn)
    trader_url      = _resolve_current_trader(api_conn)

    # 2. Fetch available ICE EUA products from the server
    futures_products = _fetch_products_embedded(api_conn, FUTURES_INSTRUMENT_CODE)
    options_products = _fetch_products_embedded(api_conn, OPTIONS_INSTRUMENT_CODE)

    if not futures_products and not options_products:
        logger.error("No ICE EUA products found in the database – aborting")
        return

    # 3. Build contract payloads
    futures_contracts = _build_futures_contracts(
        api_conn, futures_products, NUM_FUTURES, counterpart_url, trader_url
    )
    option_contracts = _build_option_contracts(
        api_conn, options_products, NUM_OPTIONS, counterpart_url, trader_url
    )

    # 4. POST in batches
    total_ok = total_failed = 0

    if futures_contracts:
        ok, fail = _post_contracts_one_by_one(api_conn, futures_contracts, "FUTURES")
        total_ok    += ok
        total_failed += fail

    if option_contracts:
        ok, fail = _post_contracts_one_by_one(api_conn, option_contracts, "OPTIONS")
        total_ok    += ok
        total_failed += fail

    # 5. Summary
    logger.info("=" * 60)
    logger.info("Done – ICE Emission Contract Generator")
    logger.info(f"  Stored  : {total_ok}")
    logger.info(f"  Failed  : {total_failed}")
    logger.info("=" * 60)


# ---------------------------------------------------------------------------
# Stand-alone execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    env_dir = dirname(__file__)
    api_conn = init_api(env_dir)
    register_ice_company(api_conn)
    register_ice_fee_rates(api_conn)
    generate_ice_emission_contracts(api_conn)

