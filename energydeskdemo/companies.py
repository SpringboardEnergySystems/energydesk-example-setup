from energydeskapi.customers.customers_api import CustomersApi
from energydeskapi.customers.customers_api import Company
from energydeskapi.types.company_enum_types import CompanyTypeEnum, CompanyRoleEnum
import logging

logger = logging.getLogger(__name__)

# ICE Futures Europe – LEI code used as registry_number since there is no
# Norwegian organisation number.  The same value is stored in lei_code.
ICE_FUTURES_EUROPE_LEI  = "549300UF4R84F48NCH34"
ICE_FUTURES_EUROPE_NAME = "ICE Futures Europe"


def populate_company_object(api_conn, name, reg_number, company_type_enum):
    c=Company()
    c.name=name
    c.registry_number=reg_number
    c.company_type=CustomersApi.get_company_type_url(api_conn, company_type_enum)
    c.company_roles=[CustomersApi.get_company_role_url(api_conn, CompanyRoleEnum.BRP)]
    c.postal_code = "50723"
    c.city = "Billund"
    c.country = ""
    c.location = "55.7462,8.9172"
    return c


def register_ice_company(api_conn) -> int | None:
    """Ensure ICE Futures Europe is registered in the appserver.

    ICE does not have a Norwegian organisation number, so the LEI code
    (549300UF4R84F48NCH34) is stored in both ``registry_number`` and
    ``lei_code``.  The function is idempotent: it returns the pk of the
    existing record if the company is already present.

    Returns the company pk, or None on failure.
    """
    # Check by LEI code first (most reliable unique identifier)
    existing = CustomersApi.get_company_from_registry_number(api_conn, ICE_FUTURES_EUROPE_LEI)
    if existing is not None:
        pk = existing['pk']
        logger.info(f"ICE Futures Europe already registered (pk={pk})")
        return pk

    # Not found – create it
    c = Company()
    c.name            = ICE_FUTURES_EUROPE_NAME
    c.registry_number = ICE_FUTURES_EUROPE_LEI   # LEI used as registry number
    c.lei_code        = ICE_FUTURES_EUROPE_LEI
    c.alias           = "ICE"
    c.city            = "London"
    c.address         = "Milton Gate, 60 Chiswell Street"
    c.postal_code     = "EC1Y 4SA"
    # company_type = TRADING_COMPANY (7), roles = CLEARING_HOUSE (7) + GENERAL_CLEARING_MEMBER (11)
    c.company_type  = CustomersApi.get_company_type_url(api_conn, CompanyTypeEnum.TRADING_COMPANY)
    c.company_roles = [
        CustomersApi.get_company_role_url(api_conn, CompanyRoleEnum.CLEARING_HOUSE),
        CustomersApi.get_company_role_url(api_conn, CompanyRoleEnum.GENERAL_CLEARING_MEMBER),
    ]

    success, json_res, status_code, error_msg = CustomersApi.upsert_company(api_conn, c)
    if success and json_res is not None:
        pk = json_res.get('pk')
        logger.info(f"Registered ICE Futures Europe (pk={pk}, HTTP {status_code})")
        return pk
    else:
        logger.error(
            f"Failed to register ICE Futures Europe "
            f"(HTTP {status_code}): {error_msg}"
        )
        return None


def load_demo_company(api_conn, company_regnumber= "981952324"):
    # companies=[]
    # companies.append(populate_company_object(api_conn, "Legoland Super Traders", "666", CompanyTypeEnum.UTILITY))
    # for c in companies:
    #     print(c.get_dict())
    # CustomersApi.create_companies(api_conn, companies)

    # Return the main company to be used for later demo objects
    main_owner=CustomersApi.get_company_from_registry_number(api_conn, company_regnumber)
    if main_owner is not None:
        return main_owner['pk']
    else:
        return None
