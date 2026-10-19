"""Build template context from summary API responses.

Shared helpers for enriching regions/sections/alerts/files are used by both
this module (summary mode) and github_comment.py (file mode).
"""

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from .budget_alerts import iter_budget_alerts


# ── Shared helpers ──────────────────────────────────────────────────

def delta_str(delta: int) -> str:
    """A signed, thousands-separated delta: +1,024 or -12."""
    return f"+{delta:,}" if delta >= 0 else f"{delta:,}"


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
            'delta_str': delta_str(delta),
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
            'delta_str': delta_str(delta),
        }
        sections.append(enriched)
        region_name = section.get('region', 'Unknown')
        sections_by_region.setdefault(region_name, []).append(enriched)
    return sections, sections_by_region


def process_alerts(alerts_data: dict | None) -> list[dict]:
    """Convert raw budget alert data to list of dicts."""
    budgets = alerts_data.get('budgets', []) if alerts_data else []
    return [alert._asdict() for alert in iter_budget_alerts(budgets)]


# ── Per-file changes ────────────────────────────────────────────────

# A report's region type is the region's linker attributes ('rx', 'xrw', ...):
# 'w' (writable) is RAM, anything else is flash. Regions inferred from ELF
# segments carry a word instead ('FLASH', 'RAM'), and a linker script that
# declares no attributes leaves the type UNKNOWN; then the type's or the
# region's name decides. Flash hints come first so that DATA_FLASH is flash,
# and 'program' is listed so that PROGRAM is not RAM.
_FLASH_HINTS = ('flash', 'rom', 'code', 'text', 'program')
_RAM_HINTS = ('ram', 'tcm', 'ddr', 'data')
_ATTRIBUTE_CHARS = frozenset('rwxail!')
FILE_KINDS = ('flash', 'ram', 'other')


def _kind_from_name(name: str) -> str:
    lowered = name.lower()
    if any(hint in lowered for hint in _FLASH_HINTS):
        return 'flash'
    if any(hint in lowered for hint in _RAM_HINTS):
        return 'ram'
    return 'other'


def region_kind(name: str, region_type: str | None) -> str:
    """'flash' or 'ram' for a memory region; 'other' when neither its linker
    attributes nor its name tell."""
    if region_type and region_type.upper() != 'UNKNOWN':
        lowered_type = region_type.lower()
        if set(lowered_type) <= _ATTRIBUTE_CHARS:
            return 'ram' if 'w' in lowered_type else 'flash'
        kind = _kind_from_name(region_type)
        if kind != 'other':
            return kind
    return _kind_from_name(name)


def _file_entry(entry: dict, old_size: int, size: int, memory_layout: dict) -> dict:
    region = entry.get('region', 'Unknown')
    region_type = (memory_layout.get(region) or {}).get('type')
    delta = size - old_size
    return {
        'name': entry.get('name', 'Unknown'),
        'region': region,
        'kind': region_kind(region, region_type),
        'size': size,
        'old_size': old_size,
        'delta': delta,
        'delta_str': delta_str(delta),
    }


def enrich_files(files_data: dict | None, memory_layout: dict) -> list[dict]:
    """Every per-file change of a report (its ``changes.files``: added,
    removed and modified entries, one per file and region) as
    {name, region, kind, size, old_size, delta, delta_str}. Empty when the
    report carries no per-file changes."""
    if not files_data:
        return []
    entries = []
    for entry in files_data.get('added', []):
        entries.append(_file_entry(entry, 0, entry.get('size', 0), memory_layout))
    for entry in files_data.get('removed', []):
        entries.append(_file_entry(entry, entry.get('size', 0), 0, memory_layout))
    for entry in files_data.get('modified', []):
        old_size = entry.get('old', {}).get('size', 0)
        entries.append(_file_entry(entry, old_size, entry.get('size', 0), memory_layout))
    return entries


def _span(deltas: dict[str, int]) -> dict:
    """The spread of one file's delta over the targets it changed in:
    {min, max, min_build, max_build, builds} plus the two ends as strings.
    No builds when the file did not change in this kind of memory."""
    if not deltas:
        return {'min': 0, 'max': 0, 'min_str': '0', 'max_str': '0',
                'min_build': None, 'max_build': None, 'builds': 0}
    min_build = min(deltas, key=lambda target: (deltas[target], target))
    max_build = max(deltas, key=lambda target: (deltas[target], target))
    return {
        'min': deltas[min_build],
        'max': deltas[max_build],
        'min_str': delta_str(deltas[min_build]),
        'max_str': delta_str(deltas[max_build]),
        'min_build': min_build,
        'max_build': max_build,
        'builds': len(deltas),
    }


def summarize_file_changes(targets: list[dict]) -> list[dict]:
    """One row per changed source file across targets: for each kind of
    memory (flash, ram, other) the min and max of the file's delta over the
    targets it changed in, with the target of each end (``_span``), and
    ``builds``, how many targets the file changed in at all. A file's deltas
    in several regions of one kind are summed per target. Rows are sorted by
    their largest absolute delta, then by name.

    Each target is {'name': ..., 'files': enrich_files(...)}.
    """
    per_file: dict[str, dict[str, dict[str, int]]] = {}
    for target in targets:
        for entry in target['files']:
            by_target = per_file.setdefault(entry['name'], {}).setdefault(entry['kind'], {})
            by_target[target['name']] = by_target.get(target['name'], 0) + entry['delta']

    rows = []
    for name, kinds in per_file.items():
        row: dict[str, Any] = {'name': name}
        changed_in: set[str] = set()
        for kind in FILE_KINDS:
            deltas = {target: delta for target, delta in kinds.get(kind, {}).items() if delta}
            changed_in.update(deltas)
            row[kind] = _span(deltas)
        row['builds'] = len(changed_in)
        if changed_in:
            rows.append(row)
    def largest_delta(row: dict) -> int:
        return max(max(abs(row[kind]['min']), abs(row[kind]['max'])) for kind in FILE_KINDS)

    rows.sort(key=lambda row: (-largest_delta(row), row['name']))
    return rows


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
        - targets: List of target data with regions, sections, alerts, files
        - has_alerts: True if any target has budget alerts
        - file_changes: Per-file rows across targets (summarize_file_changes)
        - targets_with_file_changes: How many targets changed a file
        - dashboard_url: The project's dashboard at this commit
    """
    data = summary_response.get('data', {})
    targets_data = data.get('targets', [])

    targets = []
    has_any_alerts = False

    for target_data in targets_data:
        changes_summary = target_data.get('changes_summary', {})
        changes = changes_summary.get('changes', {})
        alerts = process_alerts(target_data.get('alerts', {}))
        if alerts:
            has_any_alerts = True

        regions = enrich_regions(changes.get('regions', {}))
        sections, sections_by_region = enrich_sections(changes.get('sections', {}))
        files = enrich_files(changes.get('files'), changes_summary.get('memory_layout', {}))

        targets.append({
            'name': target_data.get('target_name', 'Unknown'),
            'comparison_url': target_data.get('dashboard_url'),
            'regions': regions,
            'sections': sections,
            'sections_by_region': sections_by_region,
            'symbols': {'added': [], 'removed': [], 'modified': [], 'moved': []},
            'files': files,
            'alerts': alerts,
            'has_changes': bool(regions),
            'has_alerts': bool(alerts),
            'has_file_changes': bool(files),
        })

    return {
        'targets': targets,
        'has_alerts': has_any_alerts,
        'file_changes': summarize_file_changes(targets),
        'targets_with_file_changes': sum(1 for target in targets if target['has_file_changes']),
        'dashboard_url': data.get('dashboard_url', ''),
    }
