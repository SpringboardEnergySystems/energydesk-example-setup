from energydeskapi.customers.customers_api import CustomersApi
from energydeskapi.customers.customers_api import Company
from energydeskapi.types.company_enum_types import CompanyTypeEnum, CompanyRoleEnum

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

def generate_demo_companïes(api_conn):
    companies=[]
    companies.append(populate_company_object(api_conn, "Legoland Super Traders", "666", CompanyTypeEnum.UTILITY))
    for c in companies:
        print(c.get_dict())
    CustomersApi.create_companies(api_conn, companies)

    # Return the main company to be used for later demo objects
    main_owner=CustomersApi.get_company_from_registry_number(api_conn, "666")
    if main_owner is not None:
        return main_owner['pk']
    else:
        return None
