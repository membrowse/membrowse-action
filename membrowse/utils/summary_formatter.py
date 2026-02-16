"""Build template context from summary API responses."""

from typing import Any

from .budget_alerts import iter_budget_alerts


def build_summary_template_context(summary_response: dict[str, Any]) -> dict[str, Any]:
    """
    Build template context from summary API response.

    Produces the same structure as github_comment._build_template_context()
    so existing Jinja2 templates (default_comment.j2, table_comment.j2) work.

    Args:
        summary_response: Parsed JSON from GET /summary API

    Returns:
        Dictionary with template variables:
        - targets: List of target data with regions, sections, alerts
        - has_alerts: True if any target has budget alerts
    """
    data = summary_response.get('data', {})
    targets_data = data.get('targets', [])

    targets = []
    has_any_alerts = False

    for target_data in targets_data:
        target_name = target_data.get('target_name', 'Unknown')
        dashboard_url = target_data.get('dashboard_url')
        changes_summary = target_data.get('changes_summary', {})
        changes = changes_summary.get('changes', {})

        regions_data = changes.get('regions', {})
        sections_data = changes.get('sections', {})

        alerts_data = target_data.get('alerts', {})
        budgets = alerts_data.get('budgets', []) if alerts_data else []
        alerts = [alert._asdict() for alert in iter_budget_alerts(budgets)]
        if alerts:
            has_any_alerts = True

        # Process regions — filter to changed, add computed fields
        regions = []
        for region in regions_data.get('modified', []):
            used_size = region.get('used_size', 0)
            old_used = region.get('old', {}).get('used_size')
            if old_used is None or old_used == used_size:
                continue
            delta = used_size - old_used
            delta_pct = (delta / old_used * 100) if old_used > 0 else 0
            limit_size = region.get('limit_size', 0)
            regions.append({
                **region,
                'delta': delta,
                'delta_str': f"+{delta:,}" if delta >= 0 else f"{delta:,}",
                'delta_pct_str': f"+{delta_pct:.1f}%" if delta >= 0 else f"{delta_pct:.1f}%",
                'utilization_pct': (used_size / limit_size * 100)
                                   if limit_size > 0 else 0,
            })

        # Process sections — filter to changed, add computed fields, group by region
        sections: list[dict] = []
        sections_by_region: dict[str, list[dict]] = {}
        for section in sections_data.get('modified', []):
            current_size = section.get('size', 0)
            old_size = section.get('old', {}).get('size')
            if old_size is None or old_size == current_size:
                continue
            delta = current_size - old_size
            enriched = {
                **section,
                'delta': delta,
                'delta_str': f"+{delta:,}" if delta >= 0 else f"{delta:,}",
            }
            sections.append(enriched)
            region_name = section.get('region', 'Unknown')
            sections_by_region.setdefault(region_name, []).append(enriched)

        targets.append({
            'name': target_name,
            'comparison_url': dashboard_url,
            'regions': regions,
            'sections': sections,
            'sections_by_region': sections_by_region,
            'symbols': {'added': [], 'removed': [], 'modified': [], 'moved': []},
            'alerts': alerts,
            'has_changes': bool(regions),
            'has_alerts': bool(alerts),
        })

    return {
        'targets': targets,
        'has_alerts': has_any_alerts,
    }
