from .dashboard_abstract import AbstractDasboard
from typing import List
class OrganizationalDashboard (AbstractDasboard):
    streams: List[str] = ["issues"]
   