#!/usr/bin/env python3
"""
Memory report generation and coordination.

This module provides the main MemoryReportGenerator class that coordinates
the generation of comprehensive memory reports from ELF files and memory regions.
"""

import time
import logging
from typing import Dict, Any, List, Optional
from .models import MemoryRegion, MemoryReport
from .analyzer import ELFAnalyzer
from ..analysis.mapper import MemoryMapper
from .exceptions import ELFAnalysisError

# Set up logger
logger = logging.getLogger(__name__)


def make_empty_report(elf_path: Optional[str] = None, *,
                      build_failed: bool = False) -> Dict[str, Any]:
    """Create a minimal report dict with no symbol/section analysis.

    Used for commits that are skipped rather than analyzed:

    - ``build_failed=False`` (default): an identical/unchanged commit with no
      build-relevant changes. ELF-derived fields are ``None``.
    - ``build_failed=True``: a commit whose build failed. ELF-derived fields
      carry placeholder values (``entry_point=0``, ``file_type`` /
      ``machine`` = ``'unknown'``) instead of ``None``.

    Args:
        elf_path: Path recorded in ``file_path`` (``None`` when unknown).
        build_failed: Select the build-failure placeholder values.

    Returns:
        Report dictionary matching the structure of a successful report.
    """
    return {
        'file_path': elf_path,
        'architecture': None,
        'toolchain': None,
        'entry_point': 0 if build_failed else None,
        'file_type': 'unknown' if build_failed else None,
        'machine': 'unknown' if build_failed else None,
        'symbols': [],
        'program_headers': [],
        'memory_layout': {}
    }


class ReportGenerator:  # pylint: disable=too-few-public-methods
    """Main class for generating comprehensive memory reports.

    This is the primary entry point for generating memory footprint reports
    from ELF files. It coordinates ELF analysis, linker script parsing,
    and report generation.

    Example::

        import membrowse

        # Parse linker scripts first
        regions = membrowse.parse_linker_scripts(["linker.ld"])

        # Generate report
        generator = membrowse.ReportGenerator(
            elf_path="firmware.elf",
            memory_regions_data=regions
        )
        report = generator.generate_report()

        # Access results
        print(f"Architecture: {report['architecture']}")
        print(f"Symbols: {len(report['symbols'])}")
        for name, region in report['memory_layout'].items():
            print(f"{name}: {region['utilization_percent']:.1f}% used")

    Attributes:
        elf_path: Path to the ELF file being analyzed.
        elf_analyzer: The underlying ELFAnalyzer instance.
    """

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
                 self,
                 elf_path: str,
                 memory_regions_data: Dict[str,
                                           Dict[str,
                                                Any]] = None,
                 skip_line_program: bool = False,
                 map_file_path: Optional[str] = None,
                 real_limits: Optional[Dict[str, int]] = None,
                 skip_sections: Optional[List[str]] = None):
        """Initialize the report generator.

        Args:
            elf_path: Path to the ELF file to analyze.
            memory_regions_data: Dictionary of memory region definitions from
                :func:`membrowse.parse_linker_scripts`. If not provided, the report
                will not include memory layout utilization data.
            skip_line_program: Skip DWARF line program processing for faster
                analysis at the cost of reduced source file coverage (~24-31% faster).
            map_file_path: Optional path to a linker map file (GNU LD or IAR)
                for archive/object file attribution on symbols.
            real_limits: Optional mapping of region name to the real
                ``limit_size`` used as the denominator for utilization. The
                ranges in ``memory_regions_data`` are used for section
                attribution (they may be inflated to capture overflow
                sections), and these values replace each region's
                ``limit_size`` before utilization is computed.
            skip_sections: Optional list of exact ELF section names (e.g.
                ``.debug_info``) to exclude from the report. Listed sections
                are removed before mapping, so they do not contribute to any
                region's ``used_size``; symbols residing in those sections
                are also dropped to keep the report consistent.
        """
        self.elf_analyzer = ELFAnalyzer(
            elf_path, skip_line_program=skip_line_program,
            map_file_path=map_file_path)
        self.memory_regions_data = memory_regions_data
        self.elf_path = elf_path
        self.skip_line_program = skip_line_program
        self.real_limits = real_limits or {}
        self.skip_sections = set(skip_sections) if skip_sections else set()

    def generate_report(self) -> MemoryReport:  # pylint: disable=too-many-locals
        """Generate comprehensive memory report.

        Returns:
            MemoryReport TypedDict containing the complete memory analysis report with keys:

            - ``file_path`` (str): Path to the analyzed ELF file.
            - ``architecture`` (str): Target ISA, e.g., "ARM", "Xtensa",
              "RISC-V", or None if unrecognized.
            - ``toolchain`` (str): Compiler+version, e.g., "gcc-12.2.0",
              "clang-15.0.7", or None if undetectable.
            - ``machine`` (str): Target machine, e.g., "EM_ARM", "EM_XTENSA".
            - ``entry_point`` (int): Entry point address.
            - ``file_type`` (str): ELF file type, e.g., "ET_EXEC".
            - ``symbols`` (list): List of symbol dicts with keys: name, address,
              size, type, binding, section, source_file.
            - ``program_headers`` (list): ELF program headers/segments.
            - ``memory_layout`` (dict): Memory region utilization data (only if
              memory_regions_data was provided). Maps region names to dicts with:
              address, limit_size, used_size, free_size, utilization_percent, sections.

        Raises:
            ELFAnalysisError: If ELF analysis fails.

        Example::

            report = generator.generate_report()

            # Find largest functions
            functions = [s for s in report['symbols'] if s['type'] == 'STT_FUNC']
            largest = sorted(functions, key=lambda s: s['size'], reverse=True)[:5]

            # Check memory utilization
            if 'FLASH' in report['memory_layout']:
                flash = report['memory_layout']['FLASH']
                print(f"FLASH: {flash['utilization_percent']:.1f}% used")
        """
        report_start_time = time.time()
        try:
            # Extract ELF data
            metadata = self.elf_analyzer.get_metadata()
            symbols = self.elf_analyzer.get_symbols()
            sections = self.elf_analyzer.get_sections()
            program_headers = self.elf_analyzer.get_program_headers()

            # Skip user-requested sections (and their symbols) before mapping
            # so they don't contribute to any region's used_size.
            if self.skip_sections:
                sections, symbols = self._apply_section_skips(sections, symbols)

            # Convert memory regions data to MemoryRegion objects (if provided)
            memory_regions = {}
            if self.memory_regions_data:
                memory_regions = self._convert_to_memory_regions(
                    self.memory_regions_data)

                # Map sections to regions based on addresses and calculate
                # utilization
                unmapped = MemoryMapper.map_sections_to_regions(
                    sections, memory_regions)

                # If sections couldn't be mapped, try inferring regions from
                # ELF LOAD segments (e.g. when linker script symbols are
                # unresolved)
                if unmapped:
                    inferred = MemoryMapper.infer_regions_from_segments(
                        program_headers, memory_regions)
                    if inferred:
                        memory_regions.update(inferred)
                        # Re-map the previously unmapped sections
                        still_unmapped = MemoryMapper.map_sections_to_regions(
                            unmapped, memory_regions)
                        if still_unmapped:
                            logger.warning(
                                "%d section(s) could not be mapped to any "
                                "memory region: %s",
                                len(still_unmapped),
                                ', '.join(s.name for s in still_unmapped))

                # Swap attribution limit_size for the real limit (from a
                # separate limits linker script) before computing utilization.
                # Attribution used the broader range to classify overflow
                # sections; utilization math uses the real capacity.
                for name, real_size in self.real_limits.items():
                    region = memory_regions.get(name)
                    if region is not None:
                        region.limit_size = real_size

                MemoryMapper.calculate_utilization(memory_regions)

            # Calculate performance statistics
            total_time = time.time() - report_start_time
            symbols_with_source = sum(1 for s in symbols if s.source_file)

            logger.debug("Performance Summary:")
            logger.debug("  Total time: %.2fs", total_time)
            logger.debug("  Symbols processed: %d", len(symbols))
            if symbols:
                logger.debug("  Avg time per symbol: %.2fms",
                            total_time / len(symbols) * 1000)
                logger.debug("  Source mapping success: %.1f%%",
                            symbols_with_source / len(symbols) * 100)
            else:
                logger.debug("  Avg time per symbol: 0ms")
                logger.debug("  Source mapping success: 0%%")

            # Build final report
            report = {
                'file_path': str(
                    self.elf_path),
                'architecture': metadata.architecture,
                'toolchain': metadata.toolchain,
                'entry_point': metadata.entry_point,
                'file_type': metadata.file_type,
                'machine': metadata.machine,
                'symbols': [
                    symbol.__dict__ for symbol in symbols],
                'program_headers': program_headers,
                'memory_layout': {
                    name: region.to_dict() for name,
                    region in memory_regions.items()}}

            return report

        except Exception as e:
            raise ELFAnalysisError(
                f"Failed to generate memory report: {e}") from e

    def _apply_section_skips(self, sections, symbols):
        """Remove sections (and symbols inside them) whose names appear in
        ``self.skip_sections``. Names are matched exactly.

        ``present``/``missing`` are computed against every section in the
        ELF (including non-ALLOC sections like ``.debug_info``), not just
        the ALLOC ones returned by :meth:`ELFAnalyzer.get_sections`, so
        ``--skip-section .debug_info`` warns only when the section truly
        isn't there and still filters its symbols out of the report.
        """
        skip = self.skip_sections
        all_section_names = self.elf_analyzer.get_all_section_names()
        present = skip & all_section_names
        missing = skip - all_section_names

        if present:
            logger.info(
                "Skipping %d section(s) per --skip-section: %s",
                len(present), ", ".join(sorted(present)))
        if missing:
            logger.warning(
                "--skip-section name(s) not present in ELF: %s",
                ", ".join(sorted(missing)))

        kept_sections = [s for s in sections if s.name not in skip]
        kept_symbols = [s for s in symbols if s.section not in skip]
        return kept_sections, kept_symbols

    def _convert_to_memory_regions(
        self, regions_data: Dict[str, Dict[str, Any]]
    ) -> Dict[str, MemoryRegion]:
        """Convert parsed linker script data to MemoryRegion objects.

        Args:
            regions_data: Dictionary of memory region data from linker scripts

        Returns:
            Dictionary mapping region names to MemoryRegion objects
        """
        regions = {}
        for name, data in regions_data.items():
            regions[name] = MemoryRegion(
                address=data['address'],
                limit_size=data['limit_size'],
                # Type field no longer in linker parser output
                type=data.get('type', 'UNKNOWN')
            )
        return regions
