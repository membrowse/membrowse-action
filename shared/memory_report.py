#!/usr/bin/env python3

"""
memory_report.py - Generates JSON memory report from ELF and linker scripts

This script processes:
1. Bloaty CSV output for sections, symbols, and segments
2. Linker script files to extract memory regions
3. ELF file metadata
4. Outputs JSON report conforming to the MemBrowse schema
"""

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from memory_regions import parse_linker_scripts


class ELFAnalyzer:
    """Analyzes ELF files and extracts basic metadata"""
    
    def __init__(self, elf_path: str):
        self.elf_path = elf_path
        self._validate_elf()
    
    def _validate_elf(self):
        """Validate that the ELF file exists and is readable"""
        if not os.path.exists(self.elf_path):
            raise FileNotFoundError(f"ELF file not found: {self.elf_path}")
        
        if not os.access(self.elf_path, os.R_OK):
            raise PermissionError(f"Cannot read ELF file: {self.elf_path}")
    
    def get_elf_metadata(self) -> Dict[str, Any]:
        """Extract basic ELF metadata - defaults for now, Bloaty provides most info"""
        # Simple file inspection to determine basic architecture
        # Most embedded systems use ELF32, but we can enhance this later if needed
        return {
            'architecture': 'ELF32',  # Default, could be enhanced
            'file_type': 'EXEC',      # Default for executable
            'machine': 'ARM',         # Default, could be enhanced
            'entry_point': 0          # Will be filled from Bloaty if available
        }




class BloatyParser:
    """Parses Bloaty CSV output"""
    
    def __init__(self, bloaty_output: str, bloaty_symbols: str, bloaty_segments: str):
        self.bloaty_output = bloaty_output
        self.bloaty_symbols = bloaty_symbols
        self.bloaty_segments = bloaty_segments
    
    def parse_sections(self) -> Tuple[Dict[str, int], List[Dict[str, Any]]]:
        """Parse section information from Bloaty output"""
        sections = []
        total_sizes = {
            'text_size': 0,
            'data_size': 0,
            'bss_size': 0,
            'rodata_size': 0,
            'debug_size': 0,
            'other_size': 0,
            'total_file_size': 0
        }
        
        try:
            with open(self.bloaty_output, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    section_name = row.get('sections', '').strip()
                    file_size = int(row.get('filesize', 0))
                    vm_size = int(row.get('vmsize', 0))
                    
                    if not section_name:
                        continue
                    
                    # Categorize section
                    section_type = self._categorize_section(section_name)
                    
                    # Update total sizes
                    if section_type == 'text':
                        total_sizes['text_size'] += file_size
                    elif section_type == 'data':
                        total_sizes['data_size'] += file_size
                    elif section_type == 'bss':
                        total_sizes['bss_size'] += vm_size
                    elif section_type == 'rodata':
                        total_sizes['rodata_size'] += file_size
                    elif section_type == 'debug':
                        total_sizes['debug_size'] += file_size
                    else:
                        total_sizes['other_size'] += file_size
                    
                    total_sizes['total_file_size'] += file_size
                    
                    # Use file size for most sections, vm_size for BSS-like sections
                    section_size = vm_size if section_type == 'bss' else file_size
                    
                    sections.append({
                        'name': section_name,
                        'address': 0,  # Bloaty doesn't provide addresses in default output
                        'size': section_size,
                        'end_address': 0,  # Will be calculated after address assignment
                        'type': section_type
                    })
        
        except Exception as e:
            print(f"Warning: Failed to parse sections: {e}", file=sys.stderr)
        
        return total_sizes, sections
    
    def parse_symbols(self) -> List[Dict[str, Any]]:
        """Parse symbol information from Bloaty output"""
        symbols = []
        
        try:
            with open(self.bloaty_symbols, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    symbol_name = row.get('symbols', '').strip()
                    file_size = int(row.get('filesize', 0))
                    vm_size = int(row.get('vmsize', 0))
                    
                    if not symbol_name or symbol_name == '[None]':
                        continue
                    
                    # Determine symbol type based on name patterns
                    symbol_type = self._determine_symbol_type(symbol_name)
                    
                    symbols.append({
                        'name': symbol_name,
                        'address': 0,  # Bloaty doesn't provide addresses in symbol output
                        'size': max(file_size, vm_size),
                        'type': symbol_type,
                        'binding': 'GLOBAL',  # Default, Bloaty doesn't provide binding info
                        'section': '',  # Could be inferred from name patterns
                        'visibility': '',
                        'source_file': ''
                    })
        
        except Exception as e:
            print(f"Warning: Failed to parse symbols: {e}", file=sys.stderr)
        
        return symbols
    
    def _determine_symbol_type(self, symbol_name: str) -> str:
        """Determine symbol type based on name patterns"""
        name_lower = symbol_name.lower()
        
        # Function-like symbols
        if any(pattern in name_lower for pattern in ['main', 'init', 'handler', 'isr', 'interrupt']):
            return 'FUNC'
        # Variable-like symbols
        elif any(pattern in name_lower for pattern in ['var', 'buffer', 'array', 'data', 'config']):
            return 'OBJECT'
        # Default
        else:
            return 'NOTYPE'
    
    def parse_segments(self) -> List[Dict[str, Any]]:
        """Parse program header/segment information from Bloaty output"""
        segments = []
        
        try:
            with open(self.bloaty_segments, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    segment_name = row.get('segments', '').strip()
                    file_size = int(row.get('filesize', 0))
                    vm_size = int(row.get('vmsize', 0))
                    
                    if not segment_name:
                        continue
                    
                    # Determine flags based on segment type
                    flags = self._determine_segment_flags(segment_name)
                    
                    segments.append({
                        'type': segment_name,
                        'offset': 0,  # Bloaty doesn't provide offset info
                        'virt_addr': 0,  # Bloaty doesn't provide address info
                        'phys_addr': 0,  # Bloaty doesn't provide address info
                        'file_size': file_size,
                        'mem_size': vm_size,
                        'flags': flags,
                        'align': 1  # Default alignment
                    })
        
        except Exception as e:
            print(f"Warning: Failed to parse segments: {e}", file=sys.stderr)
        
        return segments
    
    def _determine_segment_flags(self, segment_name: str) -> str:
        """Determine segment flags based on segment type"""
        name_lower = segment_name.lower()
        
        if 'load' in name_lower:
            return 'R E'  # Read + Execute for LOAD segments
        elif 'data' in name_lower:
            return 'RW'   # Read + Write for data segments
        else:
            return 'R'    # Default to read-only
    
    def _categorize_section(self, section_name: str) -> str:
        """Categorize a section based on its name"""
        name_lower = section_name.lower()
        
        if name_lower.startswith('.text') or name_lower in ['.init', '.fini']:
            return 'text'
        elif name_lower.startswith('.data') or name_lower in ['.sdata', '.tdata']:
            return 'data'
        elif name_lower.startswith('.bss') or name_lower in ['.sbss', '.tbss']:
            return 'bss'
        elif name_lower.startswith('.rodata') or name_lower.startswith('.const'):
            return 'rodata'
        elif name_lower.startswith('.debug') or name_lower.startswith('.stab'):
            return 'debug'
        else:
            return 'other'


class MemoryReportGenerator:
    """Generates the final JSON memory report"""
    
    def __init__(self, elf_path: str, ld_scripts: List[str]):
        self.elf_analyzer = ELFAnalyzer(elf_path)
        self.ld_scripts = ld_scripts
        self.elf_path = elf_path
    
    def generate_report(self, bloaty_output: str, bloaty_symbols: str, bloaty_segments: str) -> Dict[str, Any]:
        """Generate complete memory report"""
        
        # Parse components
        bloaty_parser = BloatyParser(bloaty_output, bloaty_symbols, bloaty_segments)
        
        # Get ELF metadata
        elf_metadata = self.elf_analyzer.get_elf_metadata()
        
        # Parse memory regions from linker scripts
        memory_regions = parse_linker_scripts(self.ld_scripts)
        
        # Parse Bloaty output
        total_sizes, sections = bloaty_parser.parse_sections()
        symbols = bloaty_parser.parse_symbols()
        segments = bloaty_parser.parse_segments()
        
        # Map sections to memory regions based on linker script information
        self._map_sections_to_regions(sections, memory_regions)
        
        # Calculate memory utilization
        self._calculate_memory_utilization(memory_regions)
        
        # Build final report
        report = {
            'file_path': self.elf_path,
            'architecture': elf_metadata.get('architecture', 'Unknown'),
            'entry_point': elf_metadata.get('entry_point', 0),
            'file_type': elf_metadata.get('file_type', 'Unknown'),
            'machine': elf_metadata.get('machine', 'Unknown'),
            'symbols': symbols,
            'program_headers': segments,
            'memory_layout': memory_regions,
            'total_sizes': total_sizes
        }
        
        return report
    
    def _map_sections_to_regions(self, sections: List[Dict[str, Any]], memory_regions: Dict[str, Dict[str, Any]]):
        """Map sections to memory regions based on section types and memory region types"""
        # Since Bloaty doesn't provide exact addresses, we'll map based on section and region types
        for section in sections:
            section_type = section['type']
            mapped = False
            
            # Map sections to appropriate memory regions based on type
            for region_name, region in memory_regions.items():
                region_type = region['type']
                
                # Code sections typically go to FLASH/ROM
                if section_type == 'text' and region_type in ['FLASH', 'ROM']:
                    section['address'] = region['start_address'] + region['used_size']
                    section['end_address'] = section['address'] + section['size']
                    region['sections'].append(section)
                    mapped = True
                    break
                # Read-only data typically goes to FLASH/ROM
                elif section_type == 'rodata' and region_type in ['FLASH', 'ROM']:
                    section['address'] = region['start_address'] + region['used_size']
                    section['end_address'] = section['address'] + section['size']
                    region['sections'].append(section)
                    mapped = True
                    break
                # Data and BSS sections typically go to RAM
                elif section_type in ['data', 'bss'] and region_type == 'RAM':
                    section['address'] = region['start_address'] + region['used_size']
                    section['end_address'] = section['address'] + section['size']
                    region['sections'].append(section)
                    mapped = True
                    break
            
            # If not mapped, add to the first available region
            if not mapped and memory_regions:
                first_region = next(iter(memory_regions.values()))
                section['address'] = first_region['start_address'] + first_region['used_size']
                section['end_address'] = section['address'] + section['size']
                first_region['sections'].append(section)
    
    def _calculate_memory_utilization(self, memory_regions: Dict[str, Dict[str, Any]]):
        """Calculate memory utilization for each region"""
        for region_name, region in memory_regions.items():
            used_size = sum(section['size'] for section in region['sections'])
            total_size = region['total_size']
            
            region['used_size'] = used_size
            region['free_size'] = total_size - used_size
            region['utilization_percent'] = (used_size / total_size * 100) if total_size > 0 else 0.0


def main():
    parser = argparse.ArgumentParser(description='Generate memory report from ELF and linker scripts')
    parser.add_argument('--elf-path', required=True, help='Path to ELF file')
    parser.add_argument('--ld-scripts', required=True, nargs='+', help='Linker script paths')
    parser.add_argument('--bloaty-output', required=True, help='Bloaty CSV output file')
    parser.add_argument('--bloaty-symbols', required=True, help='Bloaty symbols CSV output file')
    parser.add_argument('--bloaty-segments', required=True, help='Bloaty segments CSV output file')
    parser.add_argument('--output', required=True, help='Output JSON file path')
    
    args = parser.parse_args()
    
    try:
        # Generate report
        generator = MemoryReportGenerator(args.elf_path, args.ld_scripts)
        report = generator.generate_report(
            args.bloaty_output,
            args.bloaty_symbols,
            args.bloaty_segments
        )
        
        # Write report to file
        with open(args.output, 'w') as f:
            json.dump(report, f, indent=2)
        
        print(f"Memory report generated successfully: {args.output}")
        
    except Exception as e:
        print(f"Error generating memory report: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()