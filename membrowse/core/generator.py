#!/usr/bin/env python3
"""
Memory report generation and coordination.

This module provides the main MemoryReportGenerator class that coordinates
the generation of comprehensive memory reports from ELF files and memory regions.
"""

import time
import logging
from typing import Dict, Any
from .models import MemoryRegion, MemoryReport
from .analyzer import ELFAnalyzer
from ..analysis.mapper import MemoryMapper
from .exceptions import ELFAnalysisError

# Set up logger
logger = logging.getLogger(__name__)


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

    def __init__(self,
                 elf_path: str,
                 memory_regions_data: Dict[str,
                                           Dict[str,
                                                Any]] = None,
                 skip_line_program: bool = False):
        """Initialize the report generator.

        Args:
            elf_path: Path to the ELF file to analyze.
            memory_regions_data: Dictionary of memory region definitions from
                :func:`membrowse.parse_linker_scripts`. If not provided, the report
                will not include memory layout utilization data.
            skip_line_program: Skip DWARF line program processing for faster
                analysis at the cost of reduced source file coverage (~24-31% faster).
        """
        self.elf_analyzer = ELFAnalyzer(
            elf_path, skip_line_program=skip_line_program)
        self.memory_regions_data = memory_regions_data
        self.elf_path = elf_path
        self.skip_line_program = skip_line_program

    def generate_report(self) -> MemoryReport:
        """Generate comprehensive memory report.

        Returns:
            MemoryReport TypedDict containing the complete memory analysis report with keys:

            - ``file_path`` (str): Path to the analyzed ELF file.
            - ``architecture`` (str): ELF architecture, e.g., "ELF32" or "ELF64".
            - ``machine`` (str): Target machine, e.g., "EM_ARM", "EM_XTENSA".
            - ``entry_point`` (int): Entry point address.
            - ``file_type`` (str): ELF file type, e.g., "ET_EXEC".
            - ``symbols`` (list): List of symbol dicts with keys: name, address,
              size, type, binding, section, source_file, visibility.
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

            # Convert memory regions data to MemoryRegion objects (if provided)
            memory_regions = {}
            if self.memory_regions_data:
                memory_regions = self._convert_to_memory_regions(
                    self.memory_regions_data)

                # Map sections to regions based on addresses and calculate
                # utilization
                MemoryMapper.map_sections_to_regions(sections, memory_regions)
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
