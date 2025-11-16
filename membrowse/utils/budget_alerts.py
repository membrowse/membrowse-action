"""Utilities for processing budget alert data."""

from typing import Iterator, NamedTuple


class BudgetRegionAlert(NamedTuple):
    """Represents a budget alert for a specific memory region."""
    budget_name: str
    region: str
    usage: int
    limit: int
    exceeded: int


def iter_budget_alerts(budget_alerts: list) -> Iterator[BudgetRegionAlert]:
    """
    Process budget alerts and yield structured data for each exceeded region.

    Args:
        budget_alerts: List of budget alert dictionaries from the API response

    Yields:
        BudgetRegionAlert objects containing processed alert data
    """
    for budget in budget_alerts:
        budget_name = budget.get('budget_name', 'Unknown')
        exceeded_regions = budget.get('exceeded_regions', [])
        exceeded_by = budget.get('exceeded_by', {})
        current_usage = budget.get('current_usage', {})
        limits = budget.get('limits', {})

        for region in exceeded_regions:
            usage = current_usage.get(region, 0)
            limit = limits.get(region, 0)
            exceeded = exceeded_by.get(region, 0)

            yield BudgetRegionAlert(
                budget_name=budget_name,
                region=region,
                usage=usage,
                limit=limit,
                exceeded=exceeded,
            )
