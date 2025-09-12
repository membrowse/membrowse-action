#!/usr/bin/env python3
"""
Demonstration of a hybrid approach for source file mapping that combines
.debug_line (for functions) with DIE analysis (for variables and context)
"""

import sys
from pathlib import Path
from elftools.elf.elffile import ELFFile

# Add shared directory to path  
sys.path.insert(0, str(Path(__file__).parent.parent / 'shared'))

from test_memory_analysis import TestMemoryAnalysis

class HybridSourceMapper:
    """
    Hybrid source file mapper that uses:
    1. .debug_line for function addresses (most reliable)
    2. DIE analysis for variables and compilation unit context
    3. Intelligent fallbacks for edge cases
    """
    
    def __init__(self, elf_path):
        self.elf_path = elf_path
        self.line_mapping = {}  # address -> source file from .debug_line
        self.die_mapping = {}   # (symbol_name, address) -> source file from DIEs
        self.cu_context = {}    # address_range -> cu_source_file
        
        self._build_line_mapping()
        self._build_die_mapping()
    
    def _build_line_mapping(self):
        """Build address-to-source mapping from .debug_line section"""
        try:
            with open(self.elf_path, 'rb') as f:
                elffile = ELFFile(f)
                
                if not elffile.has_dwarf_info():
                    return
                    
                dwarfinfo = elffile.get_dwarf_info()
                
                for cu in dwarfinfo.iter_CUs():
                    line_program = dwarfinfo.line_program_for_CU(cu)
                    if line_program is None:
                        continue
                        
                    for entry in line_program.get_entries():
                        if (entry.state and hasattr(entry.state, 'address') and 
                            entry.state.address and hasattr(entry.state, 'file') and 
                            entry.state.file):
                            
                            file_entry = line_program.header.file_entry[entry.state.file - 1]
                            if hasattr(file_entry, 'name'):
                                filename = file_entry.name
                                if isinstance(filename, bytes):
                                    filename = filename.decode('utf-8', errors='ignore')
                                
                                self.line_mapping[entry.state.address] = filename
                                
        except Exception as e:
            print(f"Error building line mapping: {e}")
    
    def _build_die_mapping(self):
        """Build symbol mapping from DIE analysis (our existing logic)"""
        # This would use our existing DIE-based logic
        # Simplified for demonstration
        pass
    
    def get_source_file(self, symbol_name, symbol_address, symbol_type):
        """
        Get source file using hybrid approach:
        1. For functions: Try .debug_line first (most reliable)
        2. For variables: Use DIE analysis (only option)
        3. Fallback strategies for both
        """
        
        if symbol_type == 'FUNC':
            # Functions: Prefer .debug_line
            if symbol_address in self.line_mapping:
                source_file = self.line_mapping[symbol_address]
                return self._extract_basename(source_file)
            
            # Fallback: Search nearby addresses in case of slight misalignment
            for offset in range(-10, 11):
                check_addr = symbol_address + offset
                if check_addr in self.line_mapping:
                    source_file = self.line_mapping[check_addr]
                    return self._extract_basename(source_file)
                    
        elif symbol_type == 'OBJECT':
            # Variables: Must use DIE analysis (no choice)
            # This is where our existing logic with CU context is essential
            pass
            
        # Final fallback: Use DIE mapping
        if (symbol_name, symbol_address) in self.die_mapping:
            return self.die_mapping[(symbol_name, symbol_address)]
            
        return ""
    
    def _extract_basename(self, filepath):
        """Extract just the filename from a full path"""
        if not filepath:
            return ""
        return Path(filepath).name

def demo_hybrid_approach():
    """Demonstrate the hybrid approach"""
    test = TestMemoryAnalysis()
    test.setUp()
    test.test_02_compile_test_program()
    
    elf_file = test.temp_dir / 'simple_program.elf'
    mapper = HybridSourceMapper(str(elf_file))
    
    print("Hybrid Source Mapping Demonstration")
    print("=" * 50)
    
    print(f"\\n.debug_line mappings found: {len(mapper.line_mapping)}")
    
    # Test with our known symbols
    from memory_report import ELFAnalyzer
    analyzer = ELFAnalyzer(str(elf_file))
    symbols = analyzer.get_symbols()
    
    print("\\nFunction symbols (can use .debug_line):")
    for symbol in symbols:
        if symbol.type == 'FUNC' and 'uart' in symbol.name.lower():
            line_result = mapper.line_mapping.get(symbol.address, "NOT FOUND")
            print(f"  {symbol.name:15} @ 0x{symbol.address:08x}")
            print(f"    .debug_line: {line_result}")
            print(f"    DIE result:  {symbol.source_file}")
            print()
    
    print("Variable symbols (must use DIE analysis):")
    for symbol in symbols:
        if symbol.type == 'OBJECT' and 'uart' in symbol.name.lower():
            line_result = mapper.line_mapping.get(symbol.address, "NOT FOUND")
            print(f"  {symbol.name:15} @ 0x{symbol.address:08x}")
            print(f"    .debug_line: {line_result} (expected - variables not in line info)")
            print(f"    DIE result:  {symbol.source_file}")
            print()

if __name__ == '__main__':
    demo_hybrid_approach()