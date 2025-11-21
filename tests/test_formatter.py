"""Tests for the formatter utility module."""

from membrowse.utils.formatter import (
    _format_bytes,
    _format_address,
    _create_utilization_bar,
    _format_elf_metadata,
    _format_memory_regions,
    _format_top_symbols,
    format_report_human_readable
)


class TestFormatBytes:
    """Test byte formatting."""

    def test_format_bytes_small(self):
        """Test formatting small byte values."""
        assert _format_bytes(512) == "512 bytes"
        assert _format_bytes(1023) == "1023 bytes"

    def test_format_bytes_kilobytes(self):
        """Test formatting kilobyte values."""
        assert _format_bytes(1024) == "1.00 KB"
        assert _format_bytes(2048) == "2.00 KB"
        assert _format_bytes(1536) == "1.50 KB"

    def test_format_bytes_megabytes(self):
        """Test formatting megabyte values."""
        assert _format_bytes(1024 * 1024) == "1.00 MB"
        assert _format_bytes(1024 * 1024 * 2) == "2.00 MB"
        assert _format_bytes(1024 * 1024 * 1.5) == "1.50 MB"

    def test_format_bytes_gigabytes(self):
        """Test formatting gigabyte values."""
        assert _format_bytes(1024 * 1024 * 1024) == "1.00 GB"
        assert _format_bytes(1024 * 1024 * 1024 * 2) == "2.00 GB"


class TestFormatAddress:  # pylint: disable=too-few-public-methods
    """Test address formatting."""

    def test_format_address(self):
        """Test hex address formatting."""
        assert _format_address(0x08000000) == "0x08000000"
        assert _format_address(0x20000000) == "0x20000000"
        assert _format_address(0x0) == "0x00000000"
        assert _format_address(0xFFFFFFFF) == "0xffffffff"


class TestCreateUtilizationBar:
    """Test utilization bar creation."""

    def test_create_bar_empty(self):
        """Test creating empty bar."""
        empty_bar = _create_utilization_bar(0, width=10)
        assert empty_bar == "[░░░░░░░░░░]"

    def test_create_bar_full(self):
        """Test creating full bar."""
        full_bar = _create_utilization_bar(100, width=10)
        assert full_bar == "[██████████]"

    def test_create_bar_half(self):
        """Test creating half-filled bar."""
        half_bar = _create_utilization_bar(50, width=10)
        assert half_bar == "[█████░░░░░]"

    def test_create_bar_custom_width(self):
        """Test creating bar with custom width."""
        custom_bar = _create_utilization_bar(25, width=20)
        assert custom_bar == "[█████░░░░░░░░░░░░░░░]"


class TestFormatElfMetadata:
    """Test ELF metadata formatting."""

    def test_format_elf_metadata(self):
        """Test formatting ELF metadata section."""
        report = {
            'file_path': 'firmware.elf',
            'architecture': 'ELF32',
            'machine': 'EM_ARM',
            'entry_point': 0x08000000,
            'file_type': 'ET_EXEC'
        }
        output = _format_elf_metadata(report)

        assert 'ELF Metadata' in output
        assert 'firmware.elf' in output
        assert 'ELF32' in output
        assert 'EM_ARM' in output
        assert '0x08000000' in output
        assert 'ET_EXEC' in output

    def test_format_elf_metadata_missing_fields(self):
        """Test formatting with missing fields."""
        report = {}
        output = _format_elf_metadata(report)

        assert 'ELF Metadata' in output
        assert 'N/A' in output


class TestFormatMemoryRegions:
    """Test memory region formatting."""

    def test_format_memory_regions(self):
        """Test formatting memory regions."""
        report = {
            'memory_layout': {
                'FLASH': {
                    'address': 0x08000000,
                    'limit_size': 1048576,
                    'used_size': 856234,
                    'free_size': 192342,
                    'utilization_percent': 81.7,
                    'sections': [
                        {
                            'name': '.text',
                            'address': 0x08000000,
                            'size': 654320,
                            'type': 'PROGBITS'
                        },
                        {
                            'name': '.rodata',
                            'address': 0x080a0000,
                            'size': 201914,
                            'type': 'PROGBITS'
                        }
                    ]
                },
                'RAM': {
                    'address': 0x20000000,
                    'limit_size': 131072,
                    'used_size': 45678,
                    'free_size': 85394,
                    'utilization_percent': 34.9,
                    'sections': []
                }
            }
        }

        output = _format_memory_regions(report)

        assert 'FLASH' in output
        assert 'RAM' in output
        assert '0x08000000' in output
        assert '0x20000000' in output
        # Table format should have headers
        assert 'Address Range' in output
        assert 'Utilization' in output
        assert '.text' in output
        assert '.rodata' in output

    def test_format_memory_regions_sorted_by_address(self):
        """Test that regions are sorted by address."""
        report = {
            'memory_layout': {
                'RAM': {
                    'address': 0x20000000,
                    'limit_size': 131072,
                    'used_size': 0,
                    'free_size': 131072,
                    'utilization_percent': 0,
                    'sections': []
                },
                'FLASH': {
                    'address': 0x08000000,
                    'limit_size': 1048576,
                    'used_size': 0,
                    'free_size': 1048576,
                    'utilization_percent': 0,
                    'sections': []
                }
            }
        }

        output = _format_memory_regions(report)
        # FLASH should appear before RAM
        flash_pos = output.find('FLASH')
        ram_pos = output.find('RAM')
        assert flash_pos < ram_pos


class TestFormatTopSymbols:
    """Test top symbols formatting."""

    def test_format_top_symbols(self):
        """Test formatting top symbols."""
        report = {
            'symbols': [
                {
                    'name': 'main',
                    'address': 0x08001234,
                    'size': 12456,
                    'type': 'FUNC',
                    'binding': 'GLOBAL',
                    'section': '.text',
                    'source_file': 'main.c'
                },
                {
                    'name': 'buffer',
                    'address': 0x20004000,
                    'size': 8192,
                    'type': 'OBJECT',
                    'binding': 'GLOBAL',
                    'section': '.bss',
                    'source_file': 'buffer.c'
                },
                {
                    'name': 'small_func',
                    'address': 0x08002000,
                    'size': 128,
                    'type': 'FUNC',
                    'binding': 'LOCAL',
                    'section': '.text',
                    'source_file': 'helper.c'
                }
            ]
        }

        output = _format_top_symbols(report)

        assert 'Top 20 Largest Symbols' in output
        assert 'main' in output
        assert 'buffer' in output
        assert '12,456' in output
        assert '8,192' in output

    def test_format_top_symbols_limited(self):
        """Test that only top N symbols are shown."""
        # Create 25 symbols
        symbols = [
            {
                'name': f'symbol_{i}',
                'address': 0x08000000 + i * 1000,
                'size': 1000 - i,  # Decreasing sizes
                'type': 'FUNC',
                'binding': 'GLOBAL',
                'section': '.text',
                'source_file': 'test.c'
            }
            for i in range(25)
        ]

        report = {'symbols': symbols}
        output = _format_top_symbols(report, top_n=20)

        # Should have the largest 20 symbols (indices 0-19)
        assert 'symbol_0' in output
        assert 'symbol_19' in output
        # Should NOT have smaller symbols (indices 20-24)
        assert 'symbol_20' not in output
        assert 'symbol_24' not in output

    def test_format_top_symbols_no_symbols(self):
        """Test formatting when no symbols exist."""
        report = {'symbols': []}
        output = _format_top_symbols(report)

        assert 'Top 20 Largest Symbols' in output
        assert 'No symbols found' in output

    def test_format_top_symbols_truncate_long_names(self):
        """Test that long names are truncated."""
        report = {
            'symbols': [
                {
                    'name': 'very_long_symbol_name_that_exceeds_the_width_limit_for_display',
                    'address': 0x08001234,
                    'size': 1000,
                    'type': 'FUNC',
                    'binding': 'GLOBAL',
                    'section': 'very_long_section_name_that_also_exceeds_width',
                    'source_file': 'very_long_source_file_name_that_exceeds_width_limit.c'
                }
            ]
        }

        output = _format_top_symbols(report)
        assert '...' in output

    def test_format_all_symbols(self):
        """Test that all symbols are shown when show_all=True."""
        # Create 30 symbols
        symbols = [
            {
                'name': f'symbol_{i}',
                'address': 0x08000000 + i * 1000,
                'size': 1000 - i,
                'type': 'FUNC',
                'binding': 'GLOBAL',
                'section': '.text',
                'source_file': 'test.c'
            }
            for i in range(30)
        ]

        report = {'symbols': symbols}

        # Default should show top 20
        output_top20 = _format_top_symbols(report, top_n=20, show_all=False)
        assert 'Top 20 Largest Symbols' in output_top20
        assert 'symbol_0' in output_top20
        assert 'symbol_19' in output_top20
        assert 'symbol_20' not in output_top20

        # With show_all=True should show all 30
        output_all = _format_top_symbols(report, show_all=True)
        assert 'All Symbols' in output_all
        assert 'symbol_0' in output_all
        assert 'symbol_19' in output_all
        assert 'symbol_29' in output_all


class TestFormatReportHumanReadable:  # pylint: disable=too-few-public-methods
    """Test complete report formatting."""

    def test_format_complete_report(self):
        """Test formatting a complete report."""
        report = {
            'file_path': 'firmware.elf',
            'architecture': 'ELF32',
            'machine': 'EM_ARM',
            'entry_point': 0x08000000,
            'file_type': 'ET_EXEC',
            'memory_layout': {
                'FLASH': {
                    'address': 0x08000000,
                    'limit_size': 1048576,
                    'used_size': 856234,
                    'free_size': 192342,
                    'utilization_percent': 81.7,
                    'sections': [
                        {
                            'name': '.text',
                            'address': 0x08000000,
                            'size': 654320,
                            'type': 'PROGBITS'
                        }
                    ]
                }
            },
            'symbols': [
                {
                    'name': 'main',
                    'address': 0x08001234,
                    'size': 12456,
                    'type': 'FUNC',
                    'binding': 'GLOBAL',
                    'section': '.text',
                    'source_file': 'main.c'
                }
            ]
        }

        output = format_report_human_readable(report)

        # Should contain all sections
        assert 'ELF Metadata' in output
        assert 'Top 20 Largest Symbols' in output

        # Should contain data
        assert 'firmware.elf' in output
        assert 'FLASH' in output
        assert 'main' in output
        # Should have memory region headers
        assert 'Region' in output
        assert 'Address Range' in output
