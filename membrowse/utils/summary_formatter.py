"""Build template context from summary API responses.

Shared helpers for enriching regions/sections/alerts are used by both
this module (summary mode) and github_comment.py (file mode).
"""

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from .budget_alerts import iter_budget_alerts


# ── Shared helpers ──────────────────────────────────────────────────

def enrich_regions(regions_data: dict) -> list[dict]:
    """Filter to changed regions and add computed delta/utilization fields."""
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
    return regions


def enrich_sections(sections_data: dict) -> tuple[list[dict], dict[str, list[dict]]]:
    """Filter to changed sections, add delta fields, and group by region.

    Returns:
        (sections, sections_by_region)
    """
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
    return sections, sections_by_region


def process_alerts(alerts_data: dict | None) -> list[dict]:
    """Convert raw budget alert data to list of dicts."""
    budgets = alerts_data.get('budgets', []) if alerts_data else []
    return [alert._asdict() for alert in iter_budget_alerts(budgets)]


def render_jinja2_template(template_path: str, context: dict) -> str:
    """Load and render a Jinja2 template.

    Raises:
        FileNotFoundError: If template file doesn't exist
        jinja2.TemplateError: If template has syntax errors
    """
    template_file = Path(template_path)
    if not template_file.exists():
        raise FileNotFoundError(f"Template file not found: {template_path}")

    env = Environment(
        loader=FileSystemLoader(template_file.parent),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template(template_file.name)
    return template.render(**context)


# ── Summary-specific context builder ────────────────────────────────

def build_summary_template_context(summary_response: dict[str, Any]) -> dict[str, Any]:
    """
    Build template context from summary API response.

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
        changes = target_data.get('changes_summary', {}).get('changes', {})
        alerts = process_alerts(target_data.get('alerts', {}))
        if alerts:
            has_any_alerts = True

        regions = enrich_regions(changes.get('regions', {}))
        sections, sections_by_region = enrich_sections(changes.get('sections', {}))

        targets.append({
            'name': target_data.get('target_name', 'Unknown'),
            'comparison_url': target_data.get('dashboard_url'),
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
