# Contract Registration via REST API — Reference Guide

> **Scope**: Everything discovered during the ICE emission futures/options contract
> registration sessions.  Use this as the starting point for any further AI-assisted
> work on the contracts domain.

---

## 1. Server-side entry points

| Method | URL | Purpose |
|--------|-----|---------|
| `POST` | `/api/portfoliomanager/contracts/` | Single-contract insert (preferred for testing/documentation) |
| `POST` | `/api/portfoliomanager/contracts/bulkinsert/` | Batch insert (list payload) |
| `PATCH` | `/api/portfoliomanager/contracts/{pk}/` | Partial update of an existing contract |

**Implementation files (appserver)**

```
energydesk/apps/portfoliomanager/interfaces/contracts_api.py   ← view routing
energydesk/apps/portfoliomanager/interfaces/contract_create.py ← create logic
energydesk/apps/portfoliomanager/interfaces/contracts_serializers.py
```

---

## 2. Minimal contract payload (single insert)

```json
{
  "pk": 0,
  "external_contract_id": "ICE-FUT-2026-05-25-D0BCB2C7",
  "commodity": {
    "product_code": "FEUA032027",
    "commodity_profile": null
  },
  "trading_book":    "http://host/api/portfoliomanager/tradingbooks/81/",
  "trade_date":      "2026-05-25",
  "trade_time":      "2026-05-25T12:00:00Z",
  "contract_type":   "http://host/api/portfoliomanager/contracttypes/2/",
  "contract_status": "http://host/api/portfoliomanager/contractstatuses/1/",
  "buy_or_sell":     "BUY",
  "contract_price":  { "amount": 68.50, "currency": "EUR" },
  "quantity":        5.0,
  "quantity_type":   "http://host/api/portfoliomanager/quantitytypes/7/",
  "quantity_unit":   "http://host/api/portfoliomanager/quantityunits/5/",
  "trading_fee":           { "amount": 0.0, "currency": "EUR" },
  "clearing_fee":          { "amount": 0.0, "currency": "EUR" },
  "clearing_commission_fee": { "amount": 0.0, "currency": "EUR" },
  "broker_fee":            { "amount": 0.0, "currency": "EUR" },
  "counterpart":     "http://host/api/customers/companies/{ice_pk}/",
  "trader":          "http://host/api/customers/profiles/{profile_pk}/",
  "contract_tags":   [],
  "certificates":    [],
  "capacity_parameters": [],
  "cascading_generated": false
}
```

### Key rules

- **`commodity.product_code`** is the only required commodity field.
  `ContractCreate.create_contract_from_validated_data()` resolves the full
  `CommodityDefinition` FK from this code alone — no need to embed the object.
- **`commodity.commodity_profile`** must be present but can be `null` for plain
  exchange products (baseload / emissions).  Omitting it causes `commodity_profile required`
  validation error.
- **`trader`** is `NOT NULL` in the DB.  Either send the profile URL or fix the
  server to default to the authenticated user (see §6).
- All fee objects must be present (even as zeros) or omitted entirely —
  the serializer has no `required=False` on them.
- `pk: 0` signals a new record to the serializer.

---

## 3. Key FK pks (stable fixture data)

### Contract domain

| Resource | Code | pk | URL suffix |
|---|---|---|---|
| ContractType | EEX | 2 | `api/portfoliomanager/contracttypes/2/` |
| ContractStatus | REGISTERED | 1 | `api/portfoliomanager/contractstatuses/1/` |
| QuantityType | LOTS | 7 | `api/portfoliomanager/quantitytypes/7/` |
| QuantityUnit | LOTS | 5 | `api/portfoliomanager/quantityunits/5/` |

> `ContractType.EEX` (pk=2) is used as a temporary stand-in for ICE contracts
> until a dedicated ICE contract type is added.  The contract type concept is
> being phased out; instrument type + market place is the correct discriminator.

### Market domain

| Resource | Code | pk | URL suffix |
|---|---|---|---|
| CommodityType | EUA | 2 | `api/markets/commoditytypes/2/` |
| InstrumentType | FUT | 1 | `api/markets/instrumenttypes/1/` |
| InstrumentType | EUROPT | 5 | `api/markets/instrumenttypes/5/` |
| BlockSizeCategory | YEAR | 8 | `api/markets/blocksizecategories/8/` |
| Market | CARBON_EMISSIONS | 3 | `api/markets/markets/3/` |

---

## 4. Querying available products

Before generating contracts, fetch which products exist:

```python
# Futures
GET /api/markets/marketproducts/embedded/?
    market_place__name=ICE
    &commodity_definition__instrument_type__code=FUT
    &commodity_definition__commodity_type__code=EUA
    &page_size=500

# European options
GET /api/markets/marketproducts/embedded/?
    market_place__name=ICE
    &commodity_definition__instrument_type__code=EUROPT
    &commodity_definition__commodity_type__code=EUA
    &page_size=500
```

The embedded response includes the full `commodity_definition` object with:

```json
{
  "pk": 1197,
  "product_code": "FEUA032027",
  "instrument_type": { "pk": 1, "code": "FUT" },
  "commodity_type":  { "pk": 2, "code": "EUA" },
  "block_size_category": { "pk": 8, "code": "YEAR" },
  "market": { "pk": 3, "name": "CARBON_EMISSIONS" },
  "parameters_for_option": [],        // ← populated for EUROPT
  "underlying_of_option":  [...]      // ← populated for FUT (which options reference it)
}
```

For **EUROPT** products, `parameters_for_option[0]` contains:
```json
{
  "option_type":    "C",               // "C" = call, "P" = put
  "exercise_style": "EUROPEAN",
  "strike_price":   "61.000",
  "expiration_date": "2027-03-29T00:00:00Z",
  "underlying_commodity": { "pk": 1197, "product_code": "FEUA032027" }
}
```

---

## 5. Option contracts — special notes

- Use the option's own ticker (e.g. `FEUA032027C061`) as `product_code`.
- The server resolves all option parameters (strike, expiry, underlying) from
  the linked `CommodityOption` record — no need to send them in the payload.
- Option parameters can be denormalised into `contract_tags` for UI filtering
  without dereferencing the commodity definition:

```json
"contract_tags": [
  { "pk": 0, "tagname": "OPT-C", "description": "C @ 61.0 exp 2027-03-29", "is_active": true },
  { "pk": 0, "tagname": "UND-FEUA032027", "description": "Underlying: FEUA032027", "is_active": true }
]
```

---

## 6. Server-side fixes applied during implementation

### 6.1 `commodity_profile` — made optional
**File**: `energydesk/apps/markets/interfaces/serializers.py`

```python
# Before
commodity_profile = serializers.JSONField()
# After
commodity_profile = serializers.JSONField(required=False, allow_null=True)
```

Plain/baseload/exchange products don't use profiles; requiring the field caused
validation errors on every contract insert.

### 6.2 `trader` defaults to authenticated user
**File**: `energydesk/apps/portfoliomanager/interfaces/contract_create.py`

`Contract.trader` is `NOT NULL` in the DB.  When the payload omits `trader`,
the create logic now falls back to `get_login_profile(request)`:

```python
if 'trader' in validated_data and validated_data['trader'] is not None:
    contract.trader = validated_data['trader']
else:
    from energydesk.utils.djangoutils.session_utils import get_login_profile
    contract.trader = get_login_profile(request)
```

### 6.3 `contract_sub_type` assigned wrong type
**File**: `energydesk/apps/portfoliomanager/interfaces/contract_create.py`

`contract_sub_type` is a `CharField`, but the original code assigned the
`ContractType` model instance to it, causing a `TypeError` on save:

```python
# Bug: assigns model instance to CharField
contract.contract_sub_type = contract.contract_type   # WRONG

# Fix: assign the code string
contract.contract_sub_type = contract.contract_type.code
```

### 6.4 Clearing commission fee — spurious ERROR log
**File**: `energydesk/apps/portfoliomanager/utils/fee_manager.py`

`CLEARING_COMMISSION_FEE` only applies when the counterpart is a
General Clearing Member (GCM).  For direct exchange trades (ICE), the
counterpart is the exchange itself.  The original code logged `ERROR` when
the counterpart wasn't a GCM; changed to `DEBUG` since it is normal behaviour.

---

## 7. Company registration — ICE Futures Europe

ICE has no Norwegian organisation number.  The LEI code is used as
`registry_number` (required field) and also stored in `lei_code`:

```python
# energydeskdemo/companies.py  →  register_ice_company()
{
  "name":            "ICE Futures Europe",
  "registry_number": "549300UF4R84F48NCH34",   # LEI used as reg number
  "lei_code":        "549300UF4R84F48NCH34",
  "alias":           "ICE",
  "city":            "London",
  "address":         "Milton Gate, 60 Chiswell Street",
  "postal_code":     "EC1Y 4SA",
  "company_type":    "http://host/api/customers/companytypes/7/",  # TRADING_COMPANY
  "company_roles": [
    "http://host/api/customers/companyroles/7/",   # CLEARING_HOUSE
    "http://host/api/customers/companyroles/11/"   # GENERAL_CLEARING_MEMBER
  ]
}
```

The `GENERAL_CLEARING_MEMBER` role enables the `CLEARING_COMMISSION_FEE`
lookup in `fee_manager._participant_for_fee()`.

Lookup by LEI: `GET /api/customers/companies/?lei_code=549300UF4R84F48NCH34`

---

## 8. Fee rates for ICE EUA contracts

Fee rates live in `FeeRate` and are looked up at contract-save time by
`fee_manager.lookup_fee_rate()`.  The lookup key is:

```
fee_type × commodity_type × block_size_category × instrument_type
         × market × market_place × participant × currency × valid_from/until
```

**Formula** (carbon market uses hours=1000 as a fixed constant):
```
fee_amount = quantity_lots × 1000 × fee_rate
```

So to get a fee of X EUR/lot:  `fee_rate = X / 1000`

Register via `POST /api/portfoliomanager/feerates/` — idempotent (returns 400
`"Matching fee rates exist"` if a duplicate is detected, which is safe to ignore).

**Placeholder rates** (update to real ICE tariff when available):

| Fee type | Instrument | fee_rate | ≈ EUR/lot |
|---|---|---|---|
| TRADING_FEE (pk=1) | FUT (pk=1) | 0.000049 | ~0.049 |
| CLEARING_FEE (pk=2) | FUT (pk=1) | 0.000040 | ~0.040 |
| CLEARING_COMMISSION_FEE (pk=4) | FUT (pk=1) | 0.000020 | ~0.020 |
| TRADING_FEE (pk=1) | EUROPT (pk=5) | 0.000049 | ~0.049 |
| CLEARING_FEE (pk=2) | EUROPT (pk=5) | 0.000040 | ~0.040 |
| CLEARING_COMMISSION_FEE (pk=4) | EUROPT (pk=5) | 0.000020 | ~0.020 |

Example payload:
```json
{
  "fee_type":            "http://host/api/portfoliomanager/feetypes/1/",
  "fee_rate":            "0.000049",
  "fee_rate_currency":   "EUR",
  "commodity_type":      "http://host/api/markets/commoditytypes/2/",
  "block_size_category": "http://host/api/markets/blocksizecategories/8/",
  "instrument_type":     "http://host/api/markets/instrumenttypes/1/",
  "market":              "http://host/api/markets/markets/3/",
  "market_place":        "http://host/api/markets/marketplaces/{ice_mp_pk}/",
  "participant":         "http://host/api/customers/companies/{ice_co_pk}/",
  "valid_from":  "2020-01-01T00:00:00Z",
  "valid_until": "2050-01-01T00:00:00Z"
}
```

---

## 9. Execution order in `main.py`

```python
register_ice_company(api_conn)       # 1. Ensure ICE Futures Europe exists
register_ice_fee_rates(api_conn)     # 2. Seed fee rates (idempotent)
generate_ice_emission_contracts(api_conn)  # 3. POST contracts
```

---

## 10. Generated code locations

| File | Purpose |
|------|---------|
| `energydeskdemo/contracts.py` | Generates & POSTs random ICE EUA futures + option contracts |
| `energydeskdemo/companies.py` | `register_ice_company()` — idempotent ICE company upsert |
| `energydeskdemo/fee_rates.py` | `register_ice_fee_rates()` — idempotent fee rate seeding |
| `energydeskdemo/main.py` | Orchestration entry point |

---

## 11. URL patterns quick reference

```
# Portfoliomanager
/api/portfoliomanager/contracts/
/api/portfoliomanager/contracts/bulkinsert/
/api/portfoliomanager/contracts/{pk}/
/api/portfoliomanager/feerates/
/api/portfoliomanager/feetypes/
/api/portfoliomanager/tradingbooks/
/api/portfoliomanager/contracttypes/
/api/portfoliomanager/contractstatuses/
/api/portfoliomanager/quantitytypes/
/api/portfoliomanager/quantityunits/

# Markets
/api/markets/marketproducts/
/api/markets/marketproducts/embedded/
/api/markets/marketplaces/
/api/markets/markets/
/api/markets/instrumenttypes/
/api/markets/commoditytypes/
/api/markets/blocksizecategories/

# Customers
/api/customers/companies/
/api/customers/companytypes/
/api/customers/companyroles/
/api/customers/profiles/
/api/energydesk/get-user-profile/    ← returns current user's profile (pk, company etc.)
```

---

## 12. Known limitations / future work

- **`ContractType`** will be removed; `instrument_type + market_place` is the
  correct discriminator.  Currently using `EEX (pk=2)` as a placeholder for ICE.
- **Trading book IDs** are hardcoded in `contracts.py` config block
  (`FUTURES_TRADING_BOOK_ID=81`, `OPTIONS_TRADING_BOOK_ID=82`).
- **Fee rates** are placeholder values; update via PATCH or admin to real ICE tariffs.
- **MCP / OpenAPI**: The Swagger schema at `/api/schema/` or `/swagger/` can be
  used to generate client stubs.  Consider wrapping the contract endpoint in an
  MCP tool for AI-agent use.

