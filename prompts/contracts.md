Contracts are registered with the energydesk appserver and its REST API, implemened under energydesk.apps.portfoliomanager.interfaces.contracts_api.ContractsView

We may need to extend or alter the API slightly to make it easier for AI Agents to work with. And perhaps if necessary create an MCP in addition to the swagger

There is a current wrapper in python-sdk energydeskapi.contracts.contracts_api , but I want to focus on the core REST API itself and perhaps use that without the SDK so I can let new clients access directly. 

The structure for how to store a contract is to connect it to a commodotydefinition object that defines both standard market trades products and OTC structures. Also a contract will be stored on a tradingbook (portcfolio is used for valutaiton and is a collection of tradingbooks)

The dtaa model is defined in contract_market_relationships.puml but it is the REST API we need to relate to

European Options are stored with an additional reference table commodity_option linked from commodity definition and referencing the commodity definition of the underlying,

I have currently uploaded Emission futures from ICE exchange and all options availabel on these to the databased linked to the energydesk .env connection. I have also prepared a dedicated tradingbook for both options and underlying pertaining to the strategy of these Book id 82	"EMISSION_OPTIONS"	


Are you able to see how options can be stored via the REST API? And update the contracts.py script in the example setup of a set of parameters to specify number of randomly generated contracts of a given instrument type and what trading book ID to store on.


You may need to query the appserver for available products to store contracts on,. like what I do in my SDK.  You can query both for options end undelrying and commodities etc.
    params={'page_size':500, 'market_place__in':[ MarketPlaceEnum.ICE.value]}
    params['commodity_definition__instrument_type__code']=InstrumentTypeEnum.EUROPT.name
    res=ProductsApi.get_market_products_embedded(api_conn, params)

