"""`get_customer_balance` (Service, SQL) - what one customer owes in total.

A customer total, deliberately not scoped to an address: a property manager
with four buildings owes one balance, and `SUM(job.outstanding_balance)`
over `customer_id` is that number. Money stays in cents.
"""

from pydantic import BaseModel
from sqlalchemy.orm import Session

from switchboard_core.knowledge.customer_balance import CustomerBalance
from switchboard_core.knowledge.customer_balance import (
    get_customer_balance as _get_customer_balance,
)
from switchboard_core.tools.contract import ToolResult, tool_call
from switchboard_core.tools.ids import CustomerId


class CustomerBalanceRequest(BaseModel):
    customer_id: CustomerId


class CustomerBalanceOutput(ToolResult):
    balance: CustomerBalance


@tool_call(kind="SQL", name="get_customer_balance", agent="Service")
def get_customer_balance(
    request: CustomerBalanceRequest, *, call_id: str, session: Session
) -> CustomerBalanceOutput:
    """Zero, not an error, for a customer with no jobs - `job_count` is what
    separates "owes nothing" from "no history here", and the agent needs
    that difference to answer honestly.
    """
    return CustomerBalanceOutput(
        balance=_get_customer_balance(session, request.customer_id)
    )
