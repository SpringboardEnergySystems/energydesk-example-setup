"""
Register default fee rates for ICE EUA (emission) contracts.

The fee_rate field is a per-unit rate scaled by the 1000-hour convention
used for carbon/GO markets (see calc_contracts_hours.py).  The formula is:

    fee_amount = quantity (lots) × 1000 × fee_rate

So to obtain a fee of X EUR per lot:   fee_rate = X / 1000

Placeholder rates below can be updated via the admin or PATCH API once
the actual ICE tariff schedule is known.

Instrument/commodity PKs (stable DB fixtures):
    Commodity type  EUA       pk = 2
    Instrument type FUT       pk = 1
    Instrument type EUROPT    pk = 5
    Block size      YEAR      pk = 8
    Market          CARBON_EMISSIONS  pk = 3
    FeeType         TRADING_FEE           pk = 1
    FeeType         CLEARING_FEE          pk = 2
    FeeType         CLEARING_COMMISSION_FEE  pk = 4
"""

import logging

from energydeskapi.sdk.api_connection import ApiConnection
from energydeskapi.sdk.common_utils import init_api
from os.path import dirname

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Stable FK pks  (change only if your fixture data differs)
# ---------------------------------------------------------------------------
_COMMODITY_TYPE_EUA_PK      = 2
_INSTRUMENT_TYPE_FUT_PK     = 1
_INSTRUMENT_TYPE_EUROPT_PK  = 5
_BLOCK_SIZE_YEAR_PK         = 8
_MARKET_CARBON_EMISSIONS_PK = 3
_FEE_TYPE_TRADING_PK        = 1
_FEE_TYPE_CLEARING_PK       = 2
_FEE_TYPE_CLEARING_COMM_PK  = 4

# Rate placeholder:  rate = desired_EUR_per_lot / 1000
# (ICE EUA futures typical levels – update to live tariff when known)
_TRADING_FEE_RATE_PER_UNIT    = "0.000049"   # ≈ 0.049 EUR/lot
_CLEARING_FEE_RATE_PER_UNIT   = "0.000040"   # ≈ 0.040 EUR/lot
_CLEARING_COMM_FEE_RATE       = "0.000020"   # ≈ 0.020 EUR/lot (GCM commission)

_FEE_VALID_FROM = "2020-01-01T00:00:00Z"
_FEE_VALID_UNTIL = "2050-01-01T00:00:00Z"
_FEE_CURRENCY   = "EUR"


# ICE Futures Europe identifying constant (must match companies.py)
ICE_FUTURES_EUROPE_LEI = "549300UF4R84F48NCH34"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _url(base: str, path: str) -> str:
    full = base.rstrip("/") + "/" + path.lstrip("/")
    return full if full.endswith("/") else full + "/"


def _resolve_ice_company_pk(api_conn: ApiConnection) -> int | None:
    """Return the pk of the ICE Futures Europe company (by LEI / registry_number)."""
    for param in ({"lei_code": ICE_FUTURES_EUROPE_LEI},
                  {"registry_number": ICE_FUTURES_EUROPE_LEI}):
        res = api_conn.exec_get_url("/api/customers/companies/", param)
        results = res.get("results", res) if isinstance(res, dict) else res
        if results:
            return results[0]["pk"]
    logger.error("ICE Futures Europe company not found – cannot register fee rates")
    return None


def _resolve_ice_marketplace_pk(api_conn: ApiConnection) -> int | None:
    """Return the pk of the ICE marketplace."""
    res = api_conn.exec_get_url("/api/markets/marketplaces/", {"page_size": 200})
    results = res.get("results", res) if isinstance(res, dict) else res
    for mp in results:
        if (mp.get("name") or "").upper() == "ICE":
            return mp["pk"]
    logger.error("ICE marketplace not found – cannot register fee rates")
    return None


def _fee_rate_payload(base: str, fee_type_pk: int, instrument_pk: int,
                      rate: str, market_place_pk: int, participant_pk: int) -> dict:
    return {
        "fee_type":           _url(base, f"api/portfoliomanager/feetypes/{fee_type_pk}/"),
        "fee_rate":           rate,
        "fee_rate_currency":  _FEE_CURRENCY,
        "commodity_type":     _url(base, f"api/markets/commoditytypes/{_COMMODITY_TYPE_EUA_PK}/"),
        "block_size_category": _url(base, f"api/markets/blocksizecategories/{_BLOCK_SIZE_YEAR_PK}/"),
        "instrument_type":    _url(base, f"api/markets/instrumenttypes/{instrument_pk}/"),
        "market":             _url(base, f"api/markets/markets/{_MARKET_CARBON_EMISSIONS_PK}/"),
        "market_place":       _url(base, f"api/markets/marketplaces/{market_place_pk}/"),
        "participant":        _url(base, f"api/customers/companies/{participant_pk}/"),
        "valid_from":  _FEE_VALID_FROM,
        "valid_until": _FEE_VALID_UNTIL,
    }


def _post_fee_rate(api_conn: ApiConnection, payload: dict, label: str) -> bool:
    """POST a single fee rate; skip if a matching rate already exists (HTTP 400)."""
    success, data, status_code, error_msg = api_conn.exec_post_url(
        "/api/portfoliomanager/feerates/", payload
    )
    if success:
        pk = data.get("pk", "?") if isinstance(data, dict) else "?"
        logger.info(f"Fee rate registered: {label} (pk={pk})")
        return True
    if status_code == 400 and "Matching fee rates exist" in str(error_msg):
        logger.info(f"Fee rate already exists (skipped): {label}")
        return True
    logger.error(f"Failed to register fee rate {label}: HTTP {status_code} – {error_msg}")
    return False


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def register_ice_fee_rates(api_conn: ApiConnection) -> None:
    """Register default TRADING_FEE, CLEARING_FEE and CLEARING_COMMISSION_FEE
    rates for ICE EUA Futures and European Options.

    The function is idempotent: existing matching rates are silently skipped.
    Rates are placeholder values — update them via admin / PATCH once the
    real ICE tariff schedule is available.
    """
    logger.info("Registering ICE EUA fee rates ...")

    ice_pk = _resolve_ice_company_pk(api_conn)
    mp_pk  = _resolve_ice_marketplace_pk(api_conn)
    if ice_pk is None or mp_pk is None:
        logger.error("Skipping fee rate registration – prerequisites not found")
        return

    base = api_conn.get_base_url()

    # Fee types × instrument types matrix
    fee_specs = [
        # (fee_type_pk, instrument_pk, rate, label)
        (_FEE_TYPE_TRADING_PK,        _INSTRUMENT_TYPE_FUT_PK,    _TRADING_FEE_RATE_PER_UNIT,   "TRADING_FEE / EUA-FUT-YEAR"),
        (_FEE_TYPE_CLEARING_PK,       _INSTRUMENT_TYPE_FUT_PK,    _CLEARING_FEE_RATE_PER_UNIT,  "CLEARING_FEE / EUA-FUT-YEAR"),
        (_FEE_TYPE_CLEARING_COMM_PK,  _INSTRUMENT_TYPE_FUT_PK,    _CLEARING_COMM_FEE_RATE,      "CLEARING_COMMISSION_FEE / EUA-FUT-YEAR"),
        (_FEE_TYPE_TRADING_PK,        _INSTRUMENT_TYPE_EUROPT_PK, _TRADING_FEE_RATE_PER_UNIT,   "TRADING_FEE / EUA-EUROPT-YEAR"),
        (_FEE_TYPE_CLEARING_PK,       _INSTRUMENT_TYPE_EUROPT_PK, _CLEARING_FEE_RATE_PER_UNIT,  "CLEARING_FEE / EUA-EUROPT-YEAR"),
        (_FEE_TYPE_CLEARING_COMM_PK,  _INSTRUMENT_TYPE_EUROPT_PK, _CLEARING_COMM_FEE_RATE,      "CLEARING_COMMISSION_FEE / EUA-EUROPT-YEAR"),
    ]

    ok = failed = 0
    for fee_type_pk, instrument_pk, rate, label in fee_specs:
        payload = _fee_rate_payload(base, fee_type_pk, instrument_pk, rate, mp_pk, ice_pk)
        if _post_fee_rate(api_conn, payload, label):
            ok += 1
        else:
            failed += 1

    logger.info(f"ICE fee rate registration done – {ok} OK, {failed} failed")


# ---------------------------------------------------------------------------
# Stand-alone execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    env_dir = dirname(__file__)
    api_conn = init_api(env_dir)
    register_ice_fee_rates(api_conn)

