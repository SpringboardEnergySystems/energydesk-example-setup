from energydeskapi.customers.customers_api import CustomersApi
from energydeskapi.customers.customers_api import Company
from energydeskapi.types.company_enum_types import CompanyTypeEnum, CompanyRoleEnum, UserRoleEnum
from energydeskapi.portfolios.tradingbooks_api import TradingBooksApi, TradingBook
from energydeskapi.portfolios.portfolio_api import PortfolioNode
from energydeskapi.portfolios.portfoliotree_api import PortfolioTreeApi
from energydeskapi.assets.assets_api import Asset, AssetsApi
from energydeskapi.types.asset_enum_types import AssetCategoryEnum
from energydeskapi.marketdata.markets_api import MarketsApi
from energydeskapi.types.contract_enum_types import ContractTypeEnum
from energydeskapi.types.market_enum_types import CommodityTypeEnum
from energydeskapi.customers.users_api import UsersApi
from energydeskapi.contracts.contracts_api import ContractsApi
import os
import logging
import json

logger = logging.getLogger(__name__)


def get_assets_by_category(api_conn, asset_category_enum):
    """Replacement for the removed get_assetsbytype_ext — filters by asset_category PK."""
    category_pk = asset_category_enum if isinstance(asset_category_enum, int) else asset_category_enum.value
    return AssetsApi.get_assets_df(api_conn, parameters={'asset_category': category_pk, 'page_size': 100})


def add_tradingbook(api_conn, description, asset_pk, manager_pk, contract_types_enum_list, commodity_types_enum_list, trader_list):
    c = TradingBook()
    c.description = description
    c.asset = AssetsApi.get_asset_url(api_conn, asset_pk)
    c.manager = CustomersApi.get_company_url(api_conn, manager_pk)
    c.contract_types = [ContractsApi.get_contract_type_url(api_conn, elem) for elem in contract_types_enum_list]
    c.commodity_types = [MarketsApi.get_commodity_type_url(api_conn, elem) for elem in commodity_types_enum_list]
    c.traders = [UsersApi.get_user_url(api_conn, elem) for elem in trader_list]
    return c


def generate_demo_tradingbooks(api_conn, owner_company):
    accounts_df = get_assets_by_category(api_conn, AssetCategoryEnum.TRADING_ACCOUNT)
    contract_types = [ContractTypeEnum.NASDAQ]
    commodity_types = [CommodityTypeEnum.POWER, CommodityTypeEnum.EUA]

    traders_df = UsersApi.get_users_df(api_conn)
    trader_list = list(traders_df['pk']) if traders_df is not None and not traders_df.empty else []
    tradingbooks = []
    for index, account in accounts_df.iterrows():
        tr = add_tradingbook(api_conn, "Trading on account " + account['description'],
                             account['pk'], owner_company, contract_types, commodity_types, trader_list)
        tradingbooks.append(tr)

    contract_types = [ContractTypeEnum.BILAT_FIXPRICE]
    wind_df = get_assets_by_category(api_conn, AssetCategoryEnum.PRODUCTION)
    print(wind_df)
    n = 0
    for index, account in wind_df.iterrows():
        tr = add_tradingbook(api_conn, "PPA trades on " + account['description'],
                             account['pk'], owner_company, contract_types, commodity_types, trader_list)
        tradingbooks.append(tr)
        n += 1
        if n > 2:
            break
    TradingBooksApi.register_tradingbooks(api_conn, tradingbooks)
    return tradingbooks


def _get_or_create_tradingbook(api_conn, book_name, owner_company_pk, trader_list):
    """Look up a trading book by name; create it if it does not exist yet.
    Returns the trading book pk, or None on failure."""
    res = TradingBooksApi.get_tradingbooks(api_conn, {'description': book_name})
    if res and res.get('results'):
        pk = res['results'][0]['pk']
        logger.info("Found existing trading book '%s' (pk=%s)", book_name, pk)
        return pk

    logger.info("Trading book '%s' not found – creating it.", book_name)
    # Find a production asset to link it to – match by name fragment if possible
    prod_df = AssetsApi.get_assets_df(
        api_conn, parameters={'asset_category': AssetCategoryEnum.PRODUCTION.value, 'page_size': 500}
    )
    asset_pk = None
    if prod_df is not None and not prod_df.empty:
        # Try to find a name match first; otherwise take the first available asset
        match = prod_df[prod_df['description'].str.contains(book_name, case=False, na=False)]
        row = match.iloc[0] if not match.empty else prod_df.iloc[0]
        asset_pk = int(row['pk'])

    if asset_pk is None:
        logger.warning("No production asset found to link trading book '%s' – skipping.", book_name)
        return None

    tb = add_tradingbook(
        api_conn,
        description=book_name,
        asset_pk=asset_pk,
        manager_pk=owner_company_pk,
        contract_types_enum_list=[ContractTypeEnum.BILAT_FIXPRICE],
        commodity_types_enum_list=[CommodityTypeEnum.POWER],
        trader_list=trader_list,
    )
    success, json_res, status_code, err = TradingBooksApi.upsert_tradingbook(api_conn, tb)
    if success and json_res:
        pk = json_res['pk']
        logger.info("Created trading book '%s' (pk=%s)", book_name, pk)
        return pk
    logger.error("Failed to create trading book '%s': %s", book_name, err)
    return None


def load_portfolios(api_conn, owner_company_pk=None, portfolios_from_config=None):
    if portfolios_from_config is None:
        portfolios_from_config = os.path.join(os.path.dirname(__file__), "aademo", "portfolios.txt")
    # Resolve owner company if not passed in
    if owner_company_pk is None:
        companies_res = CustomersApi.get_companies(api_conn)
        if companies_res and companies_res.get('results'):
            owner_company_pk = companies_res['results'][0]['pk']

    traders_df = UsersApi.get_users_df(api_conn)
    trader_list = list(traders_df['pk']) if traders_df is not None and not traders_df.empty else []

    # Read config lines
    try:
        with open(portfolios_from_config, "r", encoding="utf-8") as f:
            config_lines = f.readlines()
    except FileNotFoundError:
        logger.error("Portfolio config file not found: %s", portfolios_from_config)
        return

    # --- First pass: collect all unique trading book names from config ---
    all_tb_names = set()
    parsed_rows = []
    for line in config_lines:
        line = line.strip()
        portfolio = line.split(";")
        if len(portfolio) < 4:
            continue
        tb_names = [n.strip() for n in portfolio[3].split(",") if n.strip()]
        all_tb_names.update(tb_names)
        parsed_rows.append(portfolio)

    # --- Ensure all trading books exist (create if missing) ---
    tb_name_to_pk = {}
    for tb_name in sorted(all_tb_names):
        pk = _get_or_create_tradingbook(api_conn, tb_name, owner_company_pk, trader_list)
        if pk is not None:
            tb_name_to_pk[tb_name] = pk

    # --- Second pass: build portfolio nodes, merging rows with the same name ---
    pmap = {}
    comp_cache = {}
    for portfolio in parsed_rows:
        if len(portfolio) < 4:
            continue
        portfolio_name = portfolio[0].strip()
        company_reg    = portfolio[1].strip()
        sub_portfolios = [s.strip() for s in portfolio[2].split(",") if s.strip()]
        trading_books  = [t.strip() for t in portfolio[3].split(",") if t.strip()]
        assets         = [a.strip() for a in portfolio[4].split(",") if a.strip()] if len(portfolio) > 4 else []

        # Reuse existing node or create new one (merge rows for same portfolio)
        if portfolio_name in pmap:
            pnode = pmap[portfolio_name]
        else:
            pnode = PortfolioNode()
            pnode.description = portfolio_name
            pmap[portfolio_name] = pnode

        for spname in sub_portfolios:
            if not any(c['portfolio_name'] == spname for c in pnode.sub_portfolios):
                pnode.sub_portfolios.append({"portfolio_id": 0, "portfolio_name": spname})

        for tbname in trading_books:
            pk = tb_name_to_pk.get(tbname)
            if pk is not None:
                if pk not in pnode.trading_books:
                    pnode.trading_books.append(pk)
            else:
                logger.warning("Trading book '%s' could not be resolved for portfolio '%s'", tbname, portfolio_name)

        for a in assets:
            assres = AssetsApi.get_assets(api_conn, {'description': a})
            ass = assres.get('results') if assres else None
            if ass and ass[0]['pk'] not in pnode.assets:
                pnode.assets.append(ass[0]['pk'])

        if pnode.manager is None:
            if company_reg not in comp_cache:
                comp_cache[company_reg] = CustomersApi.get_company_from_registry_number(api_conn, company_reg)
            comp = comp_cache[company_reg]
            if comp is None:
                logger.warning("Company %s not found, skipping portfolio '%s'", company_reg, portfolio_name)
                del pmap[portfolio_name]
                continue
            pnode.manager = comp['pk']

    portfolios = list(pmap.values())

    # Build payload: all portfolios are new (pk=0).
    # Parent-child wiring is done by server: it finds a portfolio's parent by looking for a
    # parent node whose children list contains {portfolio_id: 0, portfolio_name: <this name>}.
    payload = []
    for v in pmap.values():
        # Children use portfolio_id=0 so the server knows they are new nodes to wire up
        child_dicts = [{'portfolio_id': 0, 'portfolio_name': c['portfolio_name']}
                       for c in v.sub_portfolios if c['portfolio_name'] in pmap]
        entry = {
            'pk': 0,
            'portfolio_id': 0,
            'portfolio_name': v.description,
            'description': v.description,
            'trading_books': v.trading_books,
            'percentage': v.percentage,
            'assets': v.assets,
            'children': child_dicts,
            'manager': v.manager,
            'stakeholders': getattr(v, 'stakeholders', []),
        }
        payload.append(entry)
        logger.info("Portfolio node: %s", entry)
    #logger.info("Total portfolio nodes processed: %d", json.dumps(payload, indent=2, sort_keys=True))
    PortfolioTreeApi.upsert_portfolio_tree_from_flat_dict(api_conn, payload)

