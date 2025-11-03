#!/usr/bin/env python3

"""
elf_parser.py - ELF file parser for architecture detection

This module provides utilities to extract architecture information from ELF files
to intelligently handle different linker script syntaxes and parsing strategies.
"""

import logging
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


class ELFParser:  # pylint: disable=too-few-public-methods
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
                architecture = cls.MACHINE_TYPES.get(
                    e_machine, Architecture.UNKNOWN)

                # Get bit width and endianness
                bit_width = elffile.elfclass
                endianness = elffile.little_endian

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
            logger.error("Could not read ELF file %s: %s", elf_path, e)
            return None
        except (ELFError, ValueError) as e:
            logger.error("Error parsing ELF file %s: %s", elf_path, e)
            return None

    @classmethod
    def _detect_platform(
            cls,
            architecture: Architecture,
            elf_path: str) -> Platform:
        """Detect specific platform based on architecture and path hints"""
        path_lower = elf_path.lower()

        # Platform detection mapping
        platform_map = {
            Architecture.XTENSA: cls._detect_xtensa_platform,
            Architecture.ARM: cls._detect_arm_platform,
            Architecture.RISC_V: cls._detect_riscv_platform,
        }

        if architecture in platform_map:
            return platform_map[architecture](path_lower)

        if architecture in (Architecture.X86, Architecture.X86_64):
            return Platform.UNIX

        return Platform.UNKNOWN

    @classmethod
    def _detect_xtensa_platform(cls, path_lower: str) -> Platform:
        """Detect Xtensa-specific platform"""
        if 'esp32' in path_lower:
            return Platform.ESP32
        if 'esp8266' in path_lower:
            return Platform.ESP8266
        return Platform.ESP32  # Default for Xtensa

    @classmethod
    def _detect_arm_platform(cls, path_lower: str) -> Platform:
        """Detect ARM-specific platform"""
        arm_platforms = [
            ('stm32', Platform.STM32),
            ('nrf', Platform.NRF),
            ('nordic', Platform.NRF),
            ('samd', Platform.SAMD),
            ('mimxrt', Platform.MIMXRT),
            ('imxrt', Platform.MIMXRT),
            ('renesas', Platform.RENESAS),
            ('ra', Platform.RENESAS),
            ('rp2', Platform.RP2),
            ('pico', Platform.RP2),
            ('bare-arm', Platform.STM32),
        ]

        for keyword, platform in arm_platforms:
            if keyword in path_lower:
                return platform
        return Platform.STM32  # Default for ARM embedded

    @classmethod
    def _detect_riscv_platform(cls, path_lower: str) -> Platform:
        """Detect RISC-V specific platform"""
        if 'qemu' in path_lower:
            return Platform.QEMU
        return Platform.QEMU  # Default for RISC-V

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
        })
    elif elf_info.platform == Platform.ESP8266:
        strategy.update({
            'memory_block_patterns': ['esp_style', 'standard'],
        })
    elif elf_info.platform == Platform.STM32:
        strategy.update({
            'memory_block_patterns': ['standard'],
            'hierarchical_validation': True,
        })
    elif elf_info.platform == Platform.QEMU:
        strategy.update({
            'memory_block_patterns': ['standard'],
        })
    return strategy
