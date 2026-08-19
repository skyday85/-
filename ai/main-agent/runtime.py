from connectors.http_fleet_backend import HttpFleetBackend
from main_agent import build_main_agent


def build_runtime_agent():
    """Production assembly for the Main Agent.

    Fleet data comes from the fleet-management service API. Database credentials
    are intentionally not accepted by this process.
    """
    return build_main_agent(HttpFleetBackend())
