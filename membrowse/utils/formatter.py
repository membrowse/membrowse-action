"""
Human-readable formatting utilities for memory reports.
"""

from typing import Dict, List, Any


def _format_bytes(num_bytes: int) -> str:
    """Format bytes into human-readable format (KB, MB, etc.)."""
    if num_bytes < 1024:
        return f"{num_bytes} bytes"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.2f} KB"
    if num_bytes < 1024 * 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.2f} MB"
    return f"{num_bytes / (1024 * 1024 * 1024):.2f} GB"


def _format_address(address: int) -> str:
    """Format address as hex string."""
    return f"0x{address:08x}"


def _create_utilization_bar(percent: float, width: int = 20) -> str:
    """Create ASCII utilization bar.

    Args:
        percent: Utilization percentage (0-100)
        width: Width of the bar in characters

    Returns:
        ASCII bar like [████████░░░░░░░░░░░░]
    """
    filled = int(percent / 100 * width)
    empty = width - filled
    return f"[{'█' * filled}{'░' * empty}]"


def _format_elf_metadata(report: Dict[str, Any]) -> str:
    """Format ELF metadata section."""
    file_path = report.get('file_path', 'N/A')
    architecture = report.get('architecture', 'N/A')
    machine = report.get('machine', 'N/A')
    entry_point = _format_address(report.get('entry_point', 0))
    file_type = report.get('file_type', 'N/A')

    metadata_line = (
        f"ELF Metadata: {file_path}  |  "
        f"Arch: {architecture}  |  Machine: {machine}  |  "
        f"Entry: {entry_point}  |  Type: {file_type}"
    )

    lines = [
        metadata_line,
        "=" * len(metadata_line),
        ""
    ]
    return "\n".join(lines)


def _extract_region_ranges(memory_layout: Dict[str, Any]) -> List[tuple]:
    """Extract region address ranges from memory layout.

    Args:
        memory_layout: Dictionary of region name -> region data

    Returns:
        List of tuples (name, address, end_address, limit_size)
    """
    regions = []
    for name, data in memory_layout.items():
        address = data.get('address', 0)
        limit_size = data.get('limit_size', 0)
        end_address = address + limit_size
        regions.append((name, address, end_address, limit_size))
    return regions


def _detect_parent_child_relationships(memory_layout: Dict[str, Any]) -> Dict[str, List[str]]:
    """Detect parent-child relationships between memory regions based on address ranges.

    Args:
        memory_layout: Dictionary of region name -> region data

    Returns:
        Dictionary mapping parent region names to list of child region names
    """
    regions = _extract_region_ranges(memory_layout)

    # Find parent-child relationships
    # A region is a parent if another region is completely contained within it
    parent_to_children = {}

    for name1, addr1, end1, size1 in regions:
        children = []
        for name2, addr2, end2, size2 in regions:
            if name1 == name2:
                continue
            # Check if region2 is completely contained in region1
            if addr1 <= addr2 and end2 <= end1 and size2 < size1:
                children.append(name2)

        if children:
            parent_to_children[name1] = children

    return parent_to_children


def _calculate_parent_used_size(
    region_name: str,
    memory_layout: Dict[str, Any],
    parent_to_children: Dict[str, List[str]]
) -> int:
    """Calculate the used size for a parent region by summing its children.

    Args:
        region_name: Name of the region
        memory_layout: Dictionary of region name -> region data
        parent_to_children: Dictionary mapping parent names to child names

    Returns:
        Total used size (sum of children if parent, else region's own used_size)
    """
    if region_name in parent_to_children:
        # This is a parent - sum children's used sizes
        total = 0
        for child_name in parent_to_children[region_name]:
            child_data = memory_layout[child_name]
            total += child_data.get('used_size', 0)
        return total
    # Leaf region - use its own used_size
    return memory_layout[region_name].get('used_size', 0)


def _format_region_row(
    region_name: str,
    region_data: Dict[str, Any],
    used_size: int
) -> str:
    """Format a single memory region row.

    Args:
        region_name: Name of the region
        region_data: Region data dictionary
        used_size: Actual used size

    Returns:
        Formatted region row string
    """
    address = region_data.get('address', 0)
    limit_size = region_data.get('limit_size', 0)
    free_size = limit_size - used_size
    utilization = (used_size / limit_size * 100) if limit_size > 0 else 0.0
    end_address = address + limit_size

    addr_range = f"{_format_address(address)}-{_format_address(end_address)}"
    utilization_bar = f"{_create_utilization_bar(utilization)} {utilization:.1f}%"

    return (
        f"{region_name:<20} {addr_range:<30} "
        f"{limit_size:>12,} bytes  {used_size:>12,} bytes  "
        f"{free_size:>12,} bytes  {utilization_bar}"
    )


def _format_child_region(child_name: str, child_data: Dict[str, Any]) -> str:
    """Format a child region row.

    Args:
        child_name: Name of the child region
        child_data: Child region data dictionary

    Returns:
        Formatted child region row string
    """
    child_addr = child_data.get('address', 0)
    child_size = child_data.get('limit_size', 0)
    child_used = child_data.get('used_size', 0)
    child_free = child_size - child_used
    child_util = (child_used / child_size * 100) if child_size > 0 else 0.0
    child_end = child_addr + child_size

    child_addr_range = f"{_format_address(child_addr)}-{_format_address(child_end)}"
    child_util_bar = f"{_create_utilization_bar(child_util)} {child_util:.1f}%"

    return (
        f"  └─ {child_name:<15} {child_addr_range:<30} "
        f"{child_size:>12,} bytes  {child_used:>12,} bytes  "
        f"{child_free:>12,} bytes  {child_util_bar}"
    )


def _format_sections(sections: List[Dict[str, Any]], indent: str = "  ") -> List[str]:
    """Format section list.

    Args:
        sections: List of section dictionaries
        indent: Indentation string

    Returns:
        List of formatted section lines
    """
    lines = []
    for section in sorted(sections, key=lambda x: x.get('address', 0)):
        section_name = section.get('name', 'unknown')
        section_size = section.get('size', 0)
        lines.append(f"{indent}• {section_name:<15} {section_size:>12,} bytes")
    return lines


def _format_region_children(
    children: List[str],
    memory_layout: Dict[str, Any]
) -> List[str]:
    """Format child regions with their sections.

    Args:
        children: List of child region names
        memory_layout: Full memory layout dictionary

    Returns:
        List of formatted lines for children
    """
    lines = []
    for child_name in sorted(children, key=lambda n: memory_layout[n].get('address', 0)):
        child_data = memory_layout[child_name]
        lines.append(_format_child_region(child_name, child_data))

        # Show sections of child region
        child_sections = child_data.get('sections', [])
        if child_sections:
            lines.extend(_format_sections(child_sections, indent="     "))
    return lines


def _get_top_level_regions(
    memory_layout: Dict[str, Any],
    parent_to_children: Dict[str, List[str]]
) -> List[tuple]:
    """Get top-level regions (not children of other regions).

    Args:
        memory_layout: Dictionary of region name -> region data
        parent_to_children: Dictionary mapping parent names to child names

    Returns:
        List of (name, data) tuples for top-level regions, sorted by address
    """
    # Sort regions by address
    sorted_regions = sorted(
        memory_layout.items(),
        key=lambda x: x[1].get('address', 0)
    )

    # Filter to only show top-level regions (not children)
    all_children = set()
    for children in parent_to_children.values():
        all_children.update(children)

    return [(name, data) for name, data in sorted_regions if name not in all_children]


def _format_memory_regions(report: Dict[str, Any]) -> str:
    """Format memory regions as a table with hierarchy."""
    lines = []
    memory_layout = report.get('memory_layout', {})

    # Detect parent-child relationships and calculate sizes
    parent_to_children = _detect_parent_child_relationships(memory_layout)
    actual_used_sizes = {
        name: _calculate_parent_used_size(name, memory_layout, parent_to_children)
        for name in memory_layout.keys()
    }

    top_level_regions = _get_top_level_regions(memory_layout, parent_to_children)

    # Table header
    lines.append(
        f"{'Region':<20} {'Address Range':<30} {'Size':>18}  {'Used':>18}  "
        f"{'Free':>18}  {'Utilization'}"
    )
    lines.append("-" * 140)

    # Display regions
    for region_name, region_data in top_level_regions:
        lines.append(_format_region_row(region_name, region_data, actual_used_sizes[region_name]))

        # Show children and sections if present
        children = parent_to_children.get(region_name, [])
        sections = region_data.get('sections', [])

        if children or sections:
            if children:
                lines.extend(_format_region_children(children, memory_layout))
            if sections:
                lines.extend(_format_sections(sections, indent="  "))

    lines.append("")
    return "\n".join(lines)


def _format_top_symbols(report: Dict[str, Any], top_n: int = 20, show_all: bool = False) -> str:
    """Format top N largest symbols or all symbols.

    Args:
        report: Memory report dictionary
        top_n: Number of top symbols to show (ignored if show_all is True)
        show_all: If True, show all symbols instead of just top N

    Returns:
        Formatted symbols table
    """
    if show_all:
        title = "All Symbols"
    else:
        title = f"Top {top_n} Largest Symbols"

    lines = [
        title,
        "=" * len(title),
        ""
    ]

    symbols = report.get('symbols', [])

    if not symbols:
        lines.append("No symbols found.")
        lines.append("")
        return "\n".join(lines)

    # Sort by size descending
    sorted_symbols = sorted(
        symbols,
        key=lambda x: x.get('size', 0),
        reverse=True
    )

    # Limit to top_n unless show_all is True
    if not show_all:
        sorted_symbols = sorted_symbols[:top_n]

    # Header
    lines.append(
        f"{'Name':<40} {'Address':<12} {'Size':>18}  {'Type':<10} "
        f"{'Section':<20} {'Source':<30}"
    )
    lines.append("-" * 140)

    # Symbols
    for symbol in sorted_symbols:
        name = symbol.get('name', 'unknown')
        address = symbol.get('address', 0)
        size = symbol.get('size', 0)
        sym_type = symbol.get('type', 'N/A')
        section = symbol.get('section', 'N/A')
        source_file = symbol.get('source_file', 'N/A')

        # Truncate long names
        if len(name) > 38:
            name = name[:35] + "..."
        if len(section) > 18:
            section = section[:15] + "..."
        if len(source_file) > 28:
            source_file = source_file[:25] + "..."

        lines.append(
            f"{name:<40} {_format_address(address):<12} {size:>12,} bytes  "
            f"{sym_type:<10} {section:<20} {source_file:<30}"
        )

    lines.append("")
    return "\n".join(lines)


def format_report_human_readable(report: Dict[str, Any], show_all_symbols: bool = False) -> str:
    """Format memory report in human-readable format.

    Args:
        report: Memory report dictionary containing symbols, memory_layout, etc.
        show_all_symbols: If True, show all symbols instead of just top 20

    Returns:
        Formatted string with ELF metadata, memory regions, and symbols.
    """
    sections = [
        _format_elf_metadata(report),
        _format_memory_regions(report),
        _format_top_symbols(report, show_all=show_all_symbols)
    ]

    return "\n".join(sections)
