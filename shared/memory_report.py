#!/usr/bin/env python3
"""
Memory Report Generator for Embedded Firmware

This module analyzes ELF files and linker scripts to generate comprehensive
memory usage reports for embedded firmware projects.
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from elftools.elf.elffile import ELFFile
from elftools.elf.sections import SymbolTableSection
from elftools.common.exceptions import ELFError

# Memory regions will be passed as input, no need to import memory_regions


@dataclass
class MemoryRegion:
    """Represents a memory region from linker scripts"""
    start_address: int
    total_size: int
    type: str
    used_size: int = 0
    free_size: int = 0
    utilization_percent: float = 0.0
    sections: List[Dict[str, Any]] = None
    
    def __post_init__(self):
        if self.sections is None:
            self.sections = []
        self.free_size = self.total_size - self.used_size
        self.utilization_percent = (self.used_size / self.total_size * 100) if self.total_size > 0 else 0.0


@dataclass
class MemorySection:
    """Represents a section from the ELF file"""
    name: str
    address: int
    size: int
    type: str
    end_address: int = 0
    
    def __post_init__(self):
        self.end_address = self.address + self.size


@dataclass
class Symbol:
    """Represents a symbol from the ELF file"""
    name: str
    address: int
    size: int
    type: str
    binding: str
    section: str
    source_file: str = ""
    visibility: str = ""


@dataclass
class ELFMetadata:
    """Represents ELF file metadata"""
    architecture: str
    file_type: str
    machine: str
    entry_point: int
    bit_width: int
    endianness: str


class ELFAnalysisError(Exception):
    """Custom exception for ELF analysis errors"""
    pass


class ELFAnalyzer:
    """Handles ELF file analysis and data extraction"""
    
    def __init__(self, elf_path: str):
        self.elf_path = Path(elf_path)
        self._validate_elf_file()
        self._source_file_mapping = {}  # Address/symbol name -> source file mapping
        self._build_source_file_mapping()
    
    def _validate_elf_file(self) -> None:
        """Validate that the ELF file exists and is readable"""
        if not self.elf_path.exists():
            raise ELFAnalysisError(f"ELF file not found: {self.elf_path}")
        
        if not os.access(self.elf_path, os.R_OK):
            raise ELFAnalysisError(f"Cannot read ELF file: {self.elf_path}")
    
    def _build_source_file_mapping(self) -> None:
        """Build mapping from symbols/addresses to source files using DWARF debug info"""
        try:
            with open(self.elf_path, 'rb') as f:
                elffile = ELFFile(f)
                
                if not elffile.has_dwarf_info():
                    return  # No debug info available
                
                dwarfinfo = elffile.get_dwarf_info()
                
                # Iterate through all compilation units
                for cu in dwarfinfo.iter_CUs():
                    # Get the file table for this compilation unit
                    file_entries = self._get_file_entries(dwarfinfo, cu)
                    
                    # Iterate through all DIEs (Debug Information Entries) in this CU
                    for die in cu.iter_DIEs():
                        self._process_die_for_source_mapping(die, file_entries)
                        
        except (IOError, OSError, ELFError, Exception):
            # If DWARF parsing fails, continue without source file info
            pass
    
    def _get_file_entries(self, dwarfinfo, cu) -> Dict[int, str]:
        """Extract file entries from the line program"""
        file_entries = {}
        
        try:
            # Get line program for this compilation unit
            line_program = dwarfinfo.line_program_for_CU(cu)
            if line_program is None:
                return file_entries
            
            # Build file index to filename mapping
            for i, file_entry in enumerate(line_program.header.file_entry):
                if hasattr(file_entry, 'name'):
                    filename = file_entry.name.decode('utf-8') if isinstance(file_entry.name, bytes) else str(file_entry.name)
                    file_entries[i + 1] = filename  # DWARF file indices start at 1
                    
        except (AttributeError, Exception):
            # Handle different pyelftools versions or missing line program
            pass
            
        return file_entries
    
    def _process_die_for_source_mapping(self, die, file_entries: Dict[int, str]) -> None:
        """Process a DIE to extract source file information"""
        if not die.attributes:
            return
            
        # Look for relevant DIEs that have both name and file information
        die_name = None
        source_file = None
        die_address = None
        
        # Extract relevant attributes
        for attr_name, attr in die.attributes.items():
            if attr_name == 'DW_AT_name':
                if hasattr(attr, 'value'):
                    die_name = self._extract_string_value(attr.value)
            elif attr_name == 'DW_AT_decl_file':
                if hasattr(attr, 'value') and attr.value in file_entries:
                    source_file = file_entries[attr.value]
            elif attr_name in ['DW_AT_low_pc', 'DW_AT_location']:
                if hasattr(attr, 'value'):
                    try:
                        die_address = int(attr.value)
                    except (ValueError, TypeError):
                        pass
        
        # Store the mapping if we have useful information
        if die_name and source_file:
            # Map by symbol name
            self._source_file_mapping[die_name] = source_file
            
            # Also map by address if available
            if die_address is not None:
                self._source_file_mapping[die_address] = source_file
    
    def _extract_string_value(self, value) -> Optional[str]:
        """Extract string value from DWARF attribute"""
        try:
            if isinstance(value, bytes):
                return value.decode('utf-8', errors='ignore')
            elif isinstance(value, str):
                return value
            else:
                return str(value)
        except (UnicodeDecodeError, Exception):
            return None
    
    def get_metadata(self) -> ELFMetadata:
        """Extract ELF metadata"""
        try:
            with open(self.elf_path, 'rb') as f:
                elffile = ELFFile(f)
                header = elffile.header
                
                return ELFMetadata(
                    architecture=f"ELF{elffile.elfclass}",
                    file_type=self._get_file_type(header['e_type']),
                    machine=self._get_machine_type(header['e_machine']),
                    entry_point=header['e_entry'],
                    bit_width=elffile.elfclass,
                    endianness='little' if elffile.little_endian else 'big'
                )
        except (IOError, OSError, ELFError) as e:
            raise ELFAnalysisError(f"Failed to parse ELF file {self.elf_path}: {e}")
    
    def get_sections(self) -> Tuple[Dict[str, int], List[MemorySection]]:
        """Extract section information and calculate totals"""
        sections = []
        totals = {
            'text_size': 0,
            'data_size': 0,
            'bss_size': 0,
            'rodata_size': 0,
            'debug_size': 0,
            'other_size': 0,
            'total_file_size': 0
        }
        
        try:
            with open(self.elf_path, 'rb') as f:
                elffile = ELFFile(f)
                
                for section in elffile.iter_sections():
                    if not section.name or section.name.startswith('.debug'):
                        continue
                    
                    section_type = self._categorize_section(section.name)
                    size = section['sh_size']
                    
                    # Update totals
                    totals[f'{section_type}_size'] += size
                    totals['total_file_size'] += size
                    
                    sections.append(MemorySection(
                        name=section.name,
                        address=section['sh_addr'],
                        size=size,
                        type=section_type
                    ))
                    
        except (IOError, OSError, ELFError) as e:
            raise ELFAnalysisError(f"Failed to extract sections: {e}")
        
        return totals, sections
    
    def get_symbols(self) -> List[Symbol]:
        """Extract symbol information"""
        symbols = []
        
        try:
            with open(self.elf_path, 'rb') as f:
                elffile = ELFFile(f)
                
                # Build section name mapping
                section_names = {i: section.name for i, section in enumerate(elffile.iter_sections())}
                
                # Extract symbols from symbol tables
                for section in elffile.iter_sections():
                    if not isinstance(section, SymbolTableSection):
                        continue
                    
                    for symbol in section.iter_symbols():
                        if not self._is_valid_symbol(symbol):
                            continue
                        
                        section_name = self._get_symbol_section_name(symbol, section_names)
                        if section_name.startswith('.debug'):
                            continue
                        
                        symbols.append(Symbol(
                            name=symbol.name,
                            address=symbol['st_value'],
                            size=symbol['st_size'],
                            type=self._get_symbol_type(symbol['st_info']['type']),
                            binding=self._get_symbol_binding(symbol['st_info']['bind']),
                            section=section_name,
                            source_file=self._extract_source_file(symbol.name, symbol['st_value']),
                            visibility=""  # Could be extracted if needed
                        ))
                        
        except (IOError, OSError, ELFError) as e:
            raise ELFAnalysisError(f"Failed to extract symbols: {e}")
        
        return symbols
    
    def get_program_headers(self) -> List[Dict[str, Any]]:
        """Extract program headers"""
        segments = []
        
        try:
            with open(self.elf_path, 'rb') as f:
                elffile = ELFFile(f)
                
                for segment in elffile.iter_segments():
                    segments.append({
                        'type': segment['p_type'],
                        'offset': segment['p_offset'],
                        'virt_addr': segment['p_vaddr'],
                        'phys_addr': segment['p_paddr'],
                        'file_size': segment['p_filesz'],
                        'mem_size': segment['p_memsz'],
                        'flags': self._decode_segment_flags(segment['p_flags']),
                        'align': segment['p_align']
                    })
                    
        except (IOError, OSError, ELFError) as e:
            raise ELFAnalysisError(f"Failed to extract program headers: {e}")
        
        return segments
    
    def _get_file_type(self, e_type: str) -> str:
        """Map ELF file type to readable string"""
        type_map = {
            'ET_EXEC': 'EXEC',
            'ET_DYN': 'DYN',
            'ET_REL': 'REL',
            'ET_CORE': 'CORE',
        }
        return type_map.get(e_type, str(e_type))
    
    def _get_machine_type(self, e_machine: str) -> str:
        """Map ELF machine type to readable string"""
        machine_map = {
            'EM_ARM': 'ARM',
            'EM_AARCH64': 'ARM64',
            'EM_X86_64': 'x86_64',
            'EM_386': 'x86',
            'EM_XTENSA': 'Xtensa',
            'EM_RISCV': 'RISC-V',
            'EM_MIPS': 'MIPS',
        }
        return machine_map.get(e_machine, str(e_machine))
    
    def _categorize_section(self, section_name: str) -> str:
        """Categorize section based on name"""
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
    
    def _is_valid_symbol(self, symbol) -> bool:
        """Check if symbol should be included in analysis"""
        if not symbol.name or symbol.name.startswith('$'):
            return False
        
        symbol_type = symbol['st_info']['type']
        symbol_binding = symbol['st_info']['bind']
        
        # Skip local symbols unless they're significant
        if (symbol_binding == 'STB_LOCAL' and 
            symbol_type not in ['STT_FUNC', 'STT_OBJECT'] and
            symbol['st_size'] == 0):
            return False
        
        return True
    
    def _get_symbol_section_name(self, symbol, section_names: Dict[int, str]) -> str:
        """Get section name for a symbol"""
        if symbol['st_shndx'] in ['SHN_UNDEF', 'SHN_ABS']:
            return ''
        
        try:
            section_idx = symbol['st_shndx']
            if isinstance(section_idx, int) and section_idx < len(section_names):
                return section_names[section_idx]
        except (KeyError, TypeError):
            pass
        
        return ''
    
    def _get_symbol_type(self, symbol_type: str) -> str:
        """Map symbol type to readable string"""
        type_map = {
            'STT_NOTYPE': 'NOTYPE',
            'STT_OBJECT': 'OBJECT',
            'STT_FUNC': 'FUNC',
            'STT_SECTION': 'SECTION',
            'STT_FILE': 'FILE',
            'STT_COMMON': 'COMMON',
            'STT_TLS': 'TLS'
        }
        return type_map.get(symbol_type, symbol_type)
    
    def _get_symbol_binding(self, symbol_binding: str) -> str:
        """Map symbol binding to readable string"""
        binding_map = {
            'STB_LOCAL': 'LOCAL',
            'STB_GLOBAL': 'GLOBAL',
            'STB_WEAK': 'WEAK'
        }
        return binding_map.get(symbol_binding, symbol_binding)
    
    def _decode_segment_flags(self, flags: int) -> str:
        """Decode segment flags to readable string"""
        flag_str = ""
        if flags & 0x4:  # PF_R
            flag_str += "R"
        if flags & 0x2:  # PF_W
            flag_str += "W"
        if flags & 0x1:  # PF_X
            flag_str += "X"
        return flag_str or "---"
    
    def _extract_source_file(self, symbol_name: str, symbol_address: int = None) -> str:
        """Extract source file from symbol name using DWARF debug information"""
        # Try to find source file by symbol name first
        if symbol_name in self._source_file_mapping:
            source_file = self._source_file_mapping[symbol_name]
            # Extract just the filename without path for cleaner output
            return os.path.basename(source_file)
        
        # Try to find source file by address
        if symbol_address is not None and symbol_address in self._source_file_mapping:
            source_file = self._source_file_mapping[symbol_address]
            return os.path.basename(source_file)
        
        # No source file information found
        return ""


class MemoryMapper:
    """Maps ELF sections to memory regions"""
    
    @staticmethod
    def map_sections_to_regions(sections: List[MemorySection], 
                               memory_regions: Dict[str, MemoryRegion]) -> None:
        """Map sections to appropriate memory regions based on addresses"""
        for section in sections:
            region = MemoryMapper._find_region_by_address(section, memory_regions)
            if region:
                region.sections.append(section.__dict__)
            else:
                # If no address-based match, fall back to type-based mapping
                region = MemoryMapper._find_region_by_type(section, memory_regions)
                if region:
                    region.sections.append(section.__dict__)
    
    @staticmethod
    def _find_region_by_address(section: MemorySection, 
                               memory_regions: Dict[str, MemoryRegion]) -> Optional[MemoryRegion]:
        """Find memory region that contains the section's address"""
        # Skip sections with zero address (debug/metadata sections)
        if section.address == 0:
            return None
            
        for region in memory_regions.values():
            region_start = region.start_address
            region_end = region.start_address + region.total_size
            
            # Check if section address falls within this region
            if region_start <= section.address < region_end:
                return region
        
        return None
    
    @staticmethod
    def _find_region_by_type(section: MemorySection, 
                            memory_regions: Dict[str, MemoryRegion]) -> Optional[MemoryRegion]:
        """Find memory region based on section type compatibility"""
        section_type = section.type
        
        # Try to find type-specific regions first
        for region in memory_regions.values():
            if MemoryMapper._is_compatible_region(section_type, region.type):
                return region
        
        # Fall back to first available region
        return next(iter(memory_regions.values())) if memory_regions else None
    
    @staticmethod
    def _is_compatible_region(section_type: str, region_type: str) -> bool:
        """Check if section type is compatible with region type"""
        compatibility_map = {
            'text': ['FLASH', 'ROM'],
            'rodata': ['FLASH', 'ROM'],
            'data': ['RAM'],
            'bss': ['RAM']
        }
        return region_type in compatibility_map.get(section_type, [])
    
    @staticmethod
    def calculate_utilization(memory_regions: Dict[str, MemoryRegion]) -> None:
        """Calculate memory utilization for each region"""
        for region in memory_regions.values():
            region.used_size = sum(section['size'] for section in region.sections)
            region.free_size = region.total_size - region.used_size
            region.utilization_percent = (
                (region.used_size / region.total_size * 100) 
                if region.total_size > 0 else 0.0
            )


class MemoryReportGenerator:
    """Main class for generating memory reports"""
    
    def __init__(self, elf_path: str, memory_regions_data: Dict[str, Dict[str, Any]]):
        self.elf_analyzer = ELFAnalyzer(elf_path)
        self.memory_regions_data = memory_regions_data
        self.elf_path = elf_path
    
    def generate_report(self) -> Dict[str, Any]:
        """Generate comprehensive memory report"""
        try:
            # Extract ELF data
            metadata = self.elf_analyzer.get_metadata()
            symbols = self.elf_analyzer.get_symbols()
            totals, sections = self.elf_analyzer.get_sections()
            program_headers = self.elf_analyzer.get_program_headers()
            
            # Convert memory regions data to MemoryRegion objects
            memory_regions = self._convert_to_memory_regions(self.memory_regions_data)
            
            # Map sections to regions based on addresses and calculate utilization
            MemoryMapper.map_sections_to_regions(sections, memory_regions)
            MemoryMapper.calculate_utilization(memory_regions)
            
            # Build final report
            return {
                'file_path': str(self.elf_path),
                'architecture': metadata.architecture,
                'entry_point': metadata.entry_point,
                'file_type': metadata.file_type,
                'machine': metadata.machine,
                'symbols': [symbol.__dict__ for symbol in symbols],
                'program_headers': program_headers,
                'memory_layout': {name: region.__dict__ for name, region in memory_regions.items()},
                'total_sizes': totals
            }
            
        except Exception as e:
            raise ELFAnalysisError(f"Failed to generate memory report: {e}")
    
    def _convert_to_memory_regions(self, regions_data: Dict[str, Dict[str, Any]]) -> Dict[str, MemoryRegion]:
        """Convert parsed linker script data to MemoryRegion objects"""
        regions = {}
        for name, data in regions_data.items():
            regions[name] = MemoryRegion(
                start_address=data['start_address'],
                total_size=data['total_size'],
                type=data['type']
            )
        return regions


class CLIHandler:
    """Handles command-line interface"""
    
    @staticmethod
    def create_parser() -> argparse.ArgumentParser:
        """Create command-line argument parser"""
        parser = argparse.ArgumentParser(
            description='Generate memory report from ELF and linker scripts',
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
Examples:
  %(prog)s --elf-path firmware.elf --memory-regions regions.json --output report.json
  %(prog)s --elf-path app.elf --memory-regions memory_layout.json --output memory.json
  %(prog)s --elf-path test.elf --memory-regions system_regions.json --output analysis.json
            """
        )
        
        parser.add_argument(
            '--elf-path', 
            required=True, 
            help='Path to ELF file'
        )
        parser.add_argument(
            '--memory-regions', 
            required=True, 
            help='Path to JSON file containing memory regions data'
        )
        parser.add_argument(
            '--output', 
            required=True, 
            help='Output JSON file path'
        )
        
        return parser
    
    @staticmethod
    def run(args: argparse.Namespace) -> None:
        """Execute the memory report generation"""
        try:
            # Load memory regions from JSON file
            with open(args.memory_regions, 'r') as f:
                memory_regions_data = json.load(f)
            
            generator = MemoryReportGenerator(args.elf_path, memory_regions_data)
            report = generator.generate_report()
            
            # Write report to file
            with open(args.output, 'w') as f:
                json.dump(report, f, indent=2)
            
            print(f"Memory report generated successfully: {args.output}")
            
        except ELFAnalysisError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"Unexpected error: {e}", file=sys.stderr)
            sys.exit(1)


def main() -> None:
    """Main entry point"""
    parser = CLIHandler.create_parser()
    args = parser.parse_args()
    CLIHandler.run(args)


if __name__ == '__main__':
    main()