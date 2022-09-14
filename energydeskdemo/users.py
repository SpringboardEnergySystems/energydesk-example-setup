from energydeskapi.sdk.common_utils import init_api
from energydeskapi.customers.users_api import UsersApi, User
from energydeskapi.types.company_enum_types import CompanyTypeEnum, CompanyRoleEnum,UserRoleEnum

def populate_user_object(username_email, first_name, last_name, role, is_superuser, company_reg_number):
    u = User()
    u.username = username_email
    u.email = username_email  #Use the same for email and user name in demo site
    u.first_name= first_name
    u.last_name = last_name
    u.user_role=role
    u.is_superuser=is_superuser
    u.company_registry_number=company_reg_number
    return u

def generate_users(api_conn, company_registry_number="666"):
    users=[]
    users.append(populate_user_object( "legotrader1@gmail.com",
                                      "Trader 1", "Legosvensen",UserRoleEnum.TRADER, False, company_registry_number))
    users.append(populate_user_object( "legotrader2@gmail.com",
                                      "Risk Taker 1", "Legoolsen",UserRoleEnum.TRADER, False, company_registry_number))
    users.append(populate_user_object( "legoriskman@gmail.com",
                                      "Risk Manager 1", "Legopersen",UserRoleEnum.RISKMANAGER, False, company_registry_number))
    users.append(populate_user_object( "einkven@gmail.com",
                                      "Risk Manager 2", "Legopersen",UserRoleEnum.RISKMANAGER, True, company_registry_number))

    for c in users:
        print(c.get_dict())
    UsersApi.create_users(api_conn, users)


