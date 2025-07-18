#!/usr/bin/env python3

"""
elf_parser.py - ELF file parser for architecture detection

This module provides utilities to extract architecture information from ELF files
to intelligently handle different linker script syntaxes and parsing strategies.
"""

import logging
from pathlib import Path
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, Any

from elftools.elf.elffile import ELFFile
from elftools.common.exceptions import ELFError

logger = logging.getLogger(__name__)


class Architecture(Enum):
    """Supported architectures"""
    ARM = "ARM"
    XTENSA = "Xtensa" 
    RISC_V = "RISC-V"
    X86 = "x86"
    X86_64 = "x86-64"
    AARCH64 = "AArch64"
    MIPS = "MIPS"
    UNKNOWN = "Unknown"


class Platform(Enum):
    """Platform/vendor classifications"""
    STM32 = "STM32"         # ARM Cortex-M (STM32)
    ESP32 = "ESP32"         # Xtensa (ESP32)
    ESP8266 = "ESP8266"     # Xtensa (ESP8266)
    NRF = "Nordic"          # ARM Cortex-M (Nordic nRF)
    SAMD = "SAMD"           # ARM Cortex-M (Microchip SAMD)
    MIMXRT = "MIMXRT"       # ARM Cortex-M (NXP i.MX RT)
    QEMU = "QEMU"           # RISC-V or other emulated
    RENESAS = "Renesas"     # ARM Cortex-M (Renesas RA)
    RP2 = "RP2040"          # ARM Cortex-M (Raspberry Pi Pico)
    UNIX = "Unix"           # Generic Unix/Linux
    UNKNOWN = "Unknown"


@dataclass
class ELFInfo:
    """ELF file architecture information"""
    architecture: Architecture
    platform: Platform
    bit_width: int          # 32 or 64
    endianness: str         # "little" or "big"
    machine_type: int       # Raw ELF machine type
    is_embedded: bool       # True for embedded targets


class ELFParseError(Exception):
    """Exception raised when ELF parsing fails"""
    pass


class ELFParser:
    """Parser for ELF file headers to extract architecture information"""
    
    # ELF machine type constants mapped to pyelftools constants
    MACHINE_TYPES = {
        'EM_NONE': Architecture.UNKNOWN,
        'EM_SPARC': Architecture.UNKNOWN,
        'EM_386': Architecture.X86,
        'EM_MIPS': Architecture.MIPS,
        'EM_PPC': Architecture.UNKNOWN,
        'EM_S390': Architecture.UNKNOWN,
        'EM_ARM': Architecture.ARM,
        'EM_SH': Architecture.UNKNOWN,
        'EM_IA_64': Architecture.UNKNOWN,
        'EM_X86_64': Architecture.X86_64,
        'EM_XTENSA': Architecture.XTENSA,
        'EM_AARCH64': Architecture.AARCH64,
        'EM_RISCV': Architecture.RISC_V,
    }
    
    @classmethod
    def parse_elf_file(cls, elf_path: str) -> Optional[ELFInfo]:
        """Parse ELF file and extract architecture information
        
        Args:
            elf_path: Path to ELF file
            
        Returns:
            ELFInfo object with architecture details, or None if parsing fails
        """
        try:
            with open(elf_path, 'rb') as f:
                elffile = ELFFile(f)
                
                # Get machine type using pyelftools
                e_machine = elffile.header['e_machine']
                architecture = cls.MACHINE_TYPES.get(e_machine, Architecture.UNKNOWN)
                
                # Get bit width and endianness
                bit_width = elffile.elfclass
                endianness = elffile.little_endian
                
                # Get entry point
                entry_point = elffile.header['e_entry']
                
                # Determine platform based on architecture and path hints
                platform = cls._detect_platform(architecture, elf_path)
                
                return ELFInfo(
                    architecture=architecture,
                    platform=platform,
                    bit_width=bit_width,
                    endianness="little" if endianness else "big",
                    machine_type=elffile.header['e_machine'],
                    is_embedded=cls._is_embedded_platform(platform)
                )
                
        except (IOError, OSError) as e:
            logger.warning("Could not read ELF file %s: %s", elf_path, e)
            return None
        except (ELFError, ValueError) as e:
            logger.warning("Error parsing ELF file %s: %s", elf_path, e)
            return None
    
    
    @classmethod
    def _detect_platform(cls, architecture: Architecture, elf_path: str) -> Platform:
        """Detect specific platform based on architecture and path hints"""
        path_lower = elf_path.lower()
        
        # Use path hints to determine specific platform
        if architecture == Architecture.XTENSA:
            if 'esp32' in path_lower:
                return Platform.ESP32
            elif 'esp8266' in path_lower:
                return Platform.ESP8266
            else:
                return Platform.ESP32  # Default for Xtensa
                
        elif architecture == Architecture.ARM:
            if 'stm32' in path_lower:
                return Platform.STM32
            elif 'nrf' in path_lower or 'nordic' in path_lower:
                return Platform.NRF
            elif 'samd' in path_lower:
                return Platform.SAMD
            elif 'mimxrt' in path_lower or 'imxrt' in path_lower:
                return Platform.MIMXRT
            elif 'renesas' in path_lower or 'ra' in path_lower:
                return Platform.RENESAS
            elif 'rp2' in path_lower or 'pico' in path_lower:
                return Platform.RP2
            elif 'bare-arm' in path_lower:
                return Platform.STM32  # bare-arm typically uses STM32-style
            else:
                return Platform.STM32  # Default for ARM embedded
                
        elif architecture == Architecture.RISC_V:
            if 'qemu' in path_lower:
                return Platform.QEMU
            else:
                return Platform.QEMU  # Default for RISC-V
                
        elif architecture in (Architecture.X86, Architecture.X86_64):
            return Platform.UNIX
            
        else:
            return Platform.UNKNOWN
    
    @classmethod
    def _is_embedded_platform(cls, platform: Platform) -> bool:
        """Determine if platform is embedded (vs desktop/server)"""
        embedded_platforms = {
            Platform.STM32, Platform.ESP32, Platform.ESP8266,
            Platform.NRF, Platform.SAMD, Platform.MIMXRT,
            Platform.RENESAS, Platform.RP2, Platform.QEMU
        }
        return platform in embedded_platforms


def get_architecture_info(elf_path: str) -> Optional[ELFInfo]:
    """Convenience function to get architecture info from ELF file
    
    Args:
        elf_path: Path to ELF file
        
    Returns:
        ELFInfo object or None if parsing fails
    """
    return ELFParser.parse_elf_file(elf_path)


def get_linker_parsing_strategy(elf_info: ELFInfo) -> Dict[str, Any]:
    """Get parsing strategy parameters based on architecture
    
    Args:
        elf_info: ELF architecture information
        
    Returns:
        Dictionary with parsing strategy parameters
    """
    # Default strategy
    strategy = {
        'variable_patterns': ['default'],
        'memory_block_patterns': ['standard'],
        'expression_evaluation': 'safe',
        'hierarchical_validation': True,
        'default_variables': {}
    }
    
    if elf_info.platform == Platform.ESP32:
        strategy.update({
            'memory_block_patterns': ['standard', 'esp_style'],
            'default_variables': {
                'CONFIG_ESP32_SPIRAM_SIZE': 0,
                'CONFIG_PARTITION_TABLE_OFFSET': 0x8000,
            }
        })
    elif elf_info.platform == Platform.ESP8266:
        strategy.update({
            'memory_block_patterns': ['esp_style', 'standard'],
            'default_variables': {
                'FLASH_SIZE': 0x100000,  # 1MB default
            }
        })
    elif elf_info.platform == Platform.STM32:
        strategy.update({
            'memory_block_patterns': ['standard'],
            'hierarchical_validation': True,
            'default_variables': {
                '_flash_size': 0x100000,  # 1MB default
                '_ram_size': 0x20000,     # 128KB default
            }
        })
    elif elf_info.platform == Platform.NRF:
        strategy.update({
            'default_variables': {
                '_sd_size': 0,
                '_sd_ram': 0,
                '_fs_size': 65536,
                '_bootloader_head_size': 0,
                '_bootloader_tail_size': 0,
            }
        })
    elif elf_info.platform == Platform.SAMD:
        strategy.update({
            'default_variables': {
                '_etext': 0x10000,
                '_codesize': 0x10000,
                'BootSize': 0x2000
            }
        })
    elif elf_info.platform == Platform.MIMXRT:
        strategy.update({
            'default_variables': {
                'MICROPY_HW_FLASH_SIZE': 0x800000,
                'MICROPY_HW_FLASH_RESERVED': 0,
                'MICROPY_HW_SDRAM_AVAIL': 1,
                'MICROPY_HW_SDRAM_SIZE': 0x2000000
            }
        })
    elif elf_info.platform == Platform.QEMU:
        strategy.update({
            'memory_block_patterns': ['standard'],
            'default_variables': {
                'ROM_BASE': 0x80000000,
                'ROM_SIZE': 0x400000,  # 4MB
                'RAM_BASE': 0x80400000,
                'RAM_SIZE': 0x200000,  # 2MB
            }
        })
    
    return strategy