#!/usr/bin/env python3
"""
Memory report generation and coordination.

This module provides the main MemoryReportGenerator class that coordinates
the generation of comprehensive memory reports from ELF files and memory regions.
"""

import time
from typing import Dict, Any
from .models import MemoryRegion
from .elf_analyzer import ELFAnalyzer
from .memory_mapper import MemoryMapper
from .exceptions import ELFAnalysisError


class MemoryReportGenerator:
    """Main class for generating comprehensive memory reports"""

    def __init__(self, elf_path: str, memory_regions_data: Dict[str, Dict[str, Any]] = None):
        """Initialize the report generator.

        Args:
            elf_path: Path to the ELF file to analyze
            memory_regions_data: Dictionary of memory region definitions (optional)
        """
        self.elf_analyzer = ELFAnalyzer(elf_path)
        self.memory_regions_data = memory_regions_data
        self.elf_path = elf_path

    def generate_report(self, verbose: bool = False) -> Dict[str, Any]:
        """Generate comprehensive memory report with performance tracking.

        Args:
            verbose: Whether to print detailed performance statistics

        Returns:
            Dictionary containing the complete memory analysis report
        """
        report_start_time = time.time()
        try:
            # Extract ELF data
            metadata = self.elf_analyzer.get_metadata()
            symbols = self.elf_analyzer.get_symbols()
            _, sections = self.elf_analyzer.get_sections()
            program_headers = self.elf_analyzer.get_program_headers()

            # Convert memory regions data to MemoryRegion objects (if provided)
            memory_regions = {}
            if self.memory_regions_data:
                memory_regions = self._convert_to_memory_regions(self.memory_regions_data)

                # Map sections to regions based on addresses and calculate utilization
                MemoryMapper.map_sections_to_regions(sections, memory_regions)
                MemoryMapper.calculate_utilization(memory_regions)

            # Calculate performance statistics
            total_time = time.time() - report_start_time
            perf_stats = self.elf_analyzer.get_performance_stats()
            perf_stats['total_report_time'] = total_time
            perf_stats['symbols_processed'] = len(symbols)
            perf_stats['avg_time_per_symbol'] = total_time / len(symbols) if symbols else 0
            symbols_with_source = sum(1 for s in symbols if s.source_file)
            perf_stats['source_mapping_success_rate'] = (
                symbols_with_source / len(symbols) * 100) if symbols else 0

            # Build final report
            report = {
                'file_path': str(self.elf_path),
                'architecture': metadata.architecture,
                'entry_point': metadata.entry_point,
                'file_type': metadata.file_type,
                'machine': metadata.machine,
                'symbols': [symbol.__dict__ for symbol in symbols],
                'program_headers': program_headers,
                'memory_layout': {
                    name: region.to_dict() for name, region in memory_regions.items()
                }
            }

            # Print performance summary
            if verbose:
                self._print_performance_summary(perf_stats, len(symbols))

            return report

        except Exception as e:
            raise ELFAnalysisError(f"Failed to generate memory report: {e}") from e

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
                type=data['type']
            )
        return regions

    def _print_performance_summary(self, perf_stats: Dict[str, Any], symbol_count: int) -> None:
        """Print detailed performance summary.

        Args:
            perf_stats: Performance statistics dictionary
            symbol_count: Number of symbols processed
        """
        print("\nPerformance Summary:")
        print(f"  Total time: {perf_stats['total_report_time']:.2f}s")
        print(f"  Symbols processed: {symbol_count}")
        print(f"  Avg time per symbol: {perf_stats['avg_time_per_symbol']*1000:.2f}ms")
        print(f"  Source mapping success: {perf_stats['source_mapping_success_rate']:.1f}%")
        print(f"  Line mapping time: {perf_stats['line_mapping_time']:.2f}s")
        print(f"  Source mapping time: {perf_stats['source_mapping_time']:.2f}s")
        print(f"  Binary searches: {perf_stats['binary_searches']}")
        print(f"  Proximity searches: {perf_stats['proximity_searches']}")