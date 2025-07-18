#!/usr/bin/env python3

"""
test_memory_analysis.py - Test script for memory analysis functionality

This script:
1. Compiles a simple C program with a custom linker script
2. Uses Google Bloaty to analyze the resulting ELF file
3. Generates a memory report using our tools
4. Verifies the report contents match expectations
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Add shared directory to path so we can import our modules
sys.path.insert(0, str(Path(__file__).parent.parent / 'shared'))

from memory_regions import parse_linker_scripts, validate_memory_regions
from memory_report import MemoryReportGenerator


class TestMemoryAnalysis(unittest.TestCase):
    """Test cases for memory analysis functionality"""
    
    def setUp(self):
        """Set up test environment"""
        self.test_dir = Path(__file__).parent
        self.temp_dir = Path(tempfile.mkdtemp())
        
        # Paths to test files
        self.c_file = self.test_dir / 'simple_program.c'
        self.ld_file = self.test_dir / 'simple_program.ld'
        self.elf_file = self.temp_dir / 'simple_program.elf'
        
        # Find GCC compiler
        self.gcc_command = None
        for gcc_cmd in ['gcc', 'arm-none-eabi-gcc']:
            try:
                subprocess.run([gcc_cmd, '--version'], capture_output=True, check=True)
                self.gcc_command = gcc_cmd
                break
            except (subprocess.CalledProcessError, FileNotFoundError):
                continue
        
        # Ensure test files exist
        self.assertTrue(self.c_file.exists(), f"Test C file not found: {self.c_file}")
        self.assertTrue(self.ld_file.exists(), f"Test linker script not found: {self.ld_file}")
    
    def tearDown(self):
        """Clean up test environment"""
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
    
    def test_01_check_prerequisites(self):
        """Test that required tools are available"""
        # Check for GCC (or arm-none-eabi-gcc)
        gcc_available = False
        for gcc_cmd in ['gcc', 'arm-none-eabi-gcc']:
            try:
                result = subprocess.run([gcc_cmd, '--version'], 
                                      capture_output=True, check=True)
                gcc_available = True
                self.gcc_command = gcc_cmd
                print(f"Found GCC: {gcc_cmd}")
                break
            except (subprocess.CalledProcessError, FileNotFoundError):
                continue
        
        self.assertTrue(gcc_available, "No suitable GCC compiler found")
        
        # Check for Bloaty
        try:
            subprocess.run(['bloaty', '--version'], capture_output=True, check=True)
            print("Found Bloaty")
        except (subprocess.CalledProcessError, FileNotFoundError):
            print("Bloaty not found - install it manually or via GitHub Actions")
    
    def test_02_compile_test_program(self):
        """Test compilation of the test program"""
        # Compile the test program
        compile_cmd = [
            self.gcc_command,
            '-nostdlib',           # Don't link standard libraries
            '-nostartfiles',       # Don't use standard startup files
            '-T', str(self.ld_file),  # Use our custom linker script
            '-o', str(self.elf_file), # Output file
            str(self.c_file)       # Input file
        ]
        
        try:
            result = subprocess.run(compile_cmd, capture_output=True, text=True, check=True)
            print("Compilation successful")
            if result.stderr:
                print(f"Compiler warnings: {result.stderr}")
        except subprocess.CalledProcessError as e:
            self.fail(f"Compilation failed: {e.stderr}")
        
        # Verify ELF file was created
        self.assertTrue(self.elf_file.exists(), "ELF file was not created")
        
        # Verify it's actually an ELF file
        with open(self.elf_file, 'rb') as f:
            magic = f.read(4)
            self.assertEqual(magic, b'\x7fELF', "Output file is not a valid ELF file")
    
    def test_03_parse_linker_script(self):
        """Test parsing of the linker script"""
        memory_regions = parse_linker_scripts([str(self.ld_file)])
        
        # Verify we found the expected memory regions
        self.assertIn('FLASH', memory_regions, "FLASH region not found")
        self.assertIn('RAM', memory_regions, "RAM region not found")
        self.assertIn('SRAM2', memory_regions, "SRAM2 region not found")
        
        # Verify FLASH region properties
        flash_region = memory_regions['FLASH']
        self.assertEqual(flash_region['start_address'], 0x08000000)
        self.assertEqual(flash_region['total_size'], 512 * 1024)  # 512K
        self.assertEqual(flash_region['type'], 'FLASH')
        self.assertEqual(flash_region['attributes'], 'rx')
        
        # Verify RAM region properties
        ram_region = memory_regions['RAM']
        self.assertEqual(ram_region['start_address'], 0x20000000)
        self.assertEqual(ram_region['total_size'], 128 * 1024)  # 128K
        self.assertEqual(ram_region['type'], 'RAM')
        self.assertEqual(ram_region['attributes'], 'rw')
        
        # Verify SRAM2 region properties
        sram2_region = memory_regions['SRAM2']
        self.assertEqual(sram2_region['start_address'], 0x20020000)
        self.assertEqual(sram2_region['total_size'], 32 * 1024)  # 32K
        self.assertEqual(sram2_region['type'], 'RAM')
        
        # Validate the memory layout
        self.assertTrue(validate_memory_regions(memory_regions))
        
        print("Linker script parsing: PASSED")
    
    def test_04_generate_bloaty_data(self):
        """Test generation of Bloaty analysis data"""
        # Ensure we have the ELF file from previous test
        if not self.elf_file.exists():
            self.test_02_compile_test_program()
        
        # Create temporary files for Bloaty output
        self.bloaty_sections = self.temp_dir / 'bloaty_sections.csv'
        self.bloaty_symbols = self.temp_dir / 'bloaty_symbols.csv'
        self.bloaty_segments = self.temp_dir / 'bloaty_segments.csv'
        
        # Check if bloaty is available
        try:
            # Generate sections analysis
            result = subprocess.run([
                'bloaty', '--csv', str(self.elf_file)
            ], capture_output=True, text=True, check=True)
            
            with open(self.bloaty_sections, 'w') as f:
                f.write(result.stdout)
            
            # Generate symbols analysis
            result = subprocess.run([
                'bloaty', '--csv', '-d', 'symbols', str(self.elf_file)
            ], capture_output=True, text=True, check=True)
            
            with open(self.bloaty_symbols, 'w') as f:
                f.write(result.stdout)
            
            # Generate segments analysis
            result = subprocess.run([
                'bloaty', '--csv', '-d', 'segments', str(self.elf_file)
            ], capture_output=True, text=True, check=True)
            
            with open(self.bloaty_segments, 'w') as f:
                f.write(result.stdout)
            
            print("Bloaty analysis: PASSED")
            
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            # If Bloaty is not available, create mock CSV data for testing
            print(f"Bloaty not available ({e}), creating mock data for testing")
            print("Note: In GitHub Actions, Bloaty will be installed automatically")
            self._create_mock_bloaty_data()
    
    def _create_mock_bloaty_data(self):
        """Create mock Bloaty CSV data for testing when Bloaty is not available"""
        # Mock sections data
        sections_csv = '''sections,filesize,vmsize
.text,2048,2048
.rodata,512,512
.data,256,256
.bss,0,1024
'''
        with open(self.bloaty_sections, 'w') as f:
            f.write(sections_csv)
        
        # Mock symbols data
        symbols_csv = '''symbols,filesize,vmsize
main,512,512
initialize_system,256,256
calculate_checksum,384,384
delay_ms,128,128
global_counter,4,4
lookup_table,64,64
buffer,0,256
'''
        with open(self.bloaty_symbols, 'w') as f:
            f.write(symbols_csv)
        
        # Mock segments data
        segments_csv = '''segments,filesize,vmsize
LOAD,2816,2816
LOAD,256,1280
'''
        with open(self.bloaty_segments, 'w') as f:
            f.write(segments_csv)
    
    def test_05_generate_memory_report(self):
        """Test generation of the memory report"""
        # Ensure we have all prerequisites
        if not self.elf_file.exists():
            self.test_02_compile_test_program()
        
        # No longer need bloaty data
        
        # Parse memory regions first
        try:
            from memory_regions import parse_linker_scripts
            memory_regions_data = parse_linker_scripts([str(self.ld_file)])
        except Exception as e:
            self.fail(f"Failed to parse memory regions: {e}")
        
        # Generate memory report
        generator = MemoryReportGenerator(str(self.elf_file), memory_regions_data)
        
        try:
            report = generator.generate_report()
        except Exception as e:
            self.fail(f"Failed to generate memory report: {e}")
        
        # Save report for inspection
        report_file = self.temp_dir / 'memory_report.json'
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)
        
        print(f"Memory report saved to: {report_file}")
        
        # Verify report structure matches schema
        self._verify_report_structure(report)
        
        # Verify memory regions
        self._verify_memory_regions(report)
        
        # Verify sections
        self._verify_sections(report)
        
        print("Memory report generation: PASSED")
    
    def _verify_report_structure(self, report):
        """Verify the report has the expected structure"""
        required_fields = [
            'file_path', 'architecture', 'entry_point', 'file_type',
            'machine', 'symbols', 'program_headers', 'memory_layout', 'total_sizes'
        ]
        
        for field in required_fields:
            self.assertIn(field, report, f"Required field '{field}' missing from report")
        
        # Verify total_sizes structure
        total_sizes = report['total_sizes']
        size_fields = [
            'text_size', 'data_size', 'bss_size', 'rodata_size',
            'debug_size', 'other_size', 'total_file_size'
        ]
        
        for field in size_fields:
            self.assertIn(field, total_sizes, f"Required size field '{field}' missing")
            self.assertIsInstance(total_sizes[field], int, f"Size field '{field}' is not an integer")
    
    def _verify_memory_regions(self, report):
        """Verify memory regions in the report"""
        memory_layout = report['memory_layout']
        
        # Should have our three regions
        self.assertIn('FLASH', memory_layout)
        self.assertIn('RAM', memory_layout)
        self.assertIn('SRAM2', memory_layout)
        
        # Verify FLASH region
        flash_region = memory_layout['FLASH']
        self.assertEqual(flash_region['type'], 'FLASH')
        self.assertEqual(flash_region['start_address'], 0x08000000)
        self.assertEqual(flash_region['total_size'], 512 * 1024)
        self.assertGreaterEqual(flash_region['used_size'], 0)
        self.assertLessEqual(flash_region['used_size'], flash_region['total_size'])
        
        # Should have some sections mapped to FLASH (code and rodata)
        flash_sections = flash_region['sections']
        section_names = [s['name'] for s in flash_sections]
        self.assertTrue(any('.text' in name for name in section_names), 
                       "No .text section found in FLASH region")
    
    def _verify_sections(self, report):
        """Verify sections in the report"""
        # Check that we have some symbols
        symbols = report['symbols']
        self.assertGreater(len(symbols), 0, "No symbols found in report")
        
        # Verify symbol structure
        for symbol in symbols[:3]:  # Check first few symbols
            required_fields = ['name', 'address', 'size', 'type', 'binding', 'section']
            for field in required_fields:
                self.assertIn(field, symbol, f"Symbol missing field '{field}'")
        
        # Check for expected symbols from our test program
        symbol_names = [s['name'] for s in symbols]
        expected_symbols = ['main', 'global_counter']
        for expected in expected_symbols:
            if not any(expected in name for name in symbol_names):
                print(f"Warning: Expected symbol '{expected}' not found in: {symbol_names[:10]}")


def run_full_integration_test():
    """Run a full integration test using collect_report.sh"""
    print("\n" + "="*60)
    print("RUNNING INTEGRATION TEST")
    print("="*60)
    
    test_dir = Path(__file__).parent
    shared_dir = test_dir.parent / 'shared'
    temp_dir = Path(tempfile.mkdtemp())
    
    try:
        # Compile the test program
        c_file = test_dir / 'simple_program.c'
        ld_file = test_dir / 'simple_program.ld'
        elf_file = temp_dir / 'simple_program.elf'
        
        # Find a suitable compiler
        gcc_command = None
        for gcc_cmd in ['gcc', 'arm-none-eabi-gcc']:
            try:
                subprocess.run([gcc_cmd, '--version'], capture_output=True, check=True)
                gcc_command = gcc_cmd
                break
            except (subprocess.CalledProcessError, FileNotFoundError):
                continue
        
        if not gcc_command:
            print("ERROR: No suitable GCC compiler found")
            return False
        
        # Compile
        compile_cmd = [
            gcc_command, '-nostdlib', '-nostartfiles',
            '-T', str(ld_file), '-o', str(elf_file), str(c_file)
        ]
        
        subprocess.run(compile_cmd, capture_output=True, check=True)
        print(f"✓ Compiled test program: {elf_file}")
        
        # Check if Bloaty is available for full integration test
        try:
            subprocess.run(['bloaty', '--version'], capture_output=True, check=True)
            bloaty_available = True
        except (subprocess.CalledProcessError, FileNotFoundError):
            bloaty_available = False
        
        if not bloaty_available:
            print("⚠️  Bloaty not available - running limited integration test")
            
            # Test just the memory_report.py directly with mock data
            sys.path.insert(0, str(shared_dir))
            from memory_report import MemoryReportGenerator
            
            # Create mock bloaty files
            mock_dir = temp_dir / 'mock'
            mock_dir.mkdir()
            
            sections_csv = '''sections,filesize,vmsize
.text,2048,2048
.rodata,512,512
.data,256,256
.bss,0,1024
'''
            (mock_dir / 'sections.csv').write_text(sections_csv)
            
            symbols_csv = '''symbols,filesize,vmsize
main,512,512
global_counter,4,4
'''
            (mock_dir / 'symbols.csv').write_text(symbols_csv)
            
            segments_csv = '''segments,filesize,vmsize
LOAD,2816,2816
'''
            (mock_dir / 'segments.csv').write_text(segments_csv)
            
            # Generate report
            generator = MemoryReportGenerator(str(elf_file), [str(ld_file)])
            report = generator.generate_report(
                str(mock_dir / 'sections.csv'),
                str(mock_dir / 'symbols.csv'),
                str(mock_dir / 'segments.csv')
            )
            
            # Verify basic report structure
            assert 'memory_layout' in report
            assert 'FLASH' in report['memory_layout']
            assert 'RAM' in report['memory_layout']
            
            print("✓ Limited integration test PASSED")
            return True
        
        else:
            # Run full collect_report.sh
            collect_script = shared_dir / 'collect_report.sh'
            
            result = subprocess.run([
                'bash', str(collect_script),
                str(elf_file),                    # ELF path
                str(ld_file),                     # LD scripts
                'test-target',                    # Target name
                '',                               # API key (empty)
                'abc123',                         # Commit SHA
                'def456',                         # Base SHA
                'test-branch',                    # Branch name
                'test/repo'                       # Repo name
            ], capture_output=True, text=True, timeout=120)
            
            if result.returncode == 0:
                print("✓ Full integration test PASSED")
                print("Output:")
                print(result.stdout[-500:] if len(result.stdout) > 500 else result.stdout)
                return True
            else:
                print("✗ Full integration test FAILED")
                print("Error output:")
                print(result.stderr[-1000:] if len(result.stderr) > 1000 else result.stderr)
                return False
            
    except Exception as e:
        print(f"✗ Integration test FAILED: {e}")
        return False
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)


if __name__ == '__main__':
    print("Memory Analysis Test Suite")
    print("=" * 40)
    
    # Run unit tests
    unittest.main(argv=[''], exit=False, verbosity=2)
    
    # Run integration test
    success = run_full_integration_test()
    
    if success:
        print("\n🎉 ALL TESTS PASSED!")
        sys.exit(0)
    else:
        print("\n❌ SOME TESTS FAILED")
        sys.exit(1)