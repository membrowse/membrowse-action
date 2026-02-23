#!/usr/bin/env python3

"""
test_iar_linker_script_github.py - Tests with real-world ICF files from GitHub.

Validates the ICF parser against diverse .icf files downloaded from open-source
repositories spanning multiple MCU vendors:
  - STMicroelectronics (STM32 F7, G4, H7, H753, L4, WB)
  - NXP/Freescale (MCXA, LPC55, i.MX RT, Kinetis K66)
  - Texas Instruments (CC26x2 BIM)
  - Infineon/Cypress (PSoC 6, PMG1, Traveo II)
  - Microchip/Atmel (SAME53, SAMV71)
  - Nuvoton (M2351 TrustZone, M467)
  - HPMicro (HPM6P81 RISC-V)
  - Goodix (GR5526 BLE SoC)
  - Renesas (RA6M5 FSP)

Each test verifies:
  - Region names and count
  - Start addresses and sizes
  - Correct handling of vendor-specific patterns
"""
# pylint: disable=missing-function-docstring

import unittest
from pathlib import Path

from membrowse.linker.parser import LinkerScriptParser, LinkerScriptError


GITHUB_ICF_DIR = Path(__file__).parent / "linker_scripts" / "icf_github"


def _parse(filename):
    """Parse an ICF file and return memory regions dict."""
    path = GITHUB_ICF_DIR / filename
    parser = LinkerScriptParser(ld_scripts=[str(path)])
    return parser.parse_memory_regions()


# ===================================================================
# STMicroelectronics
# ===================================================================


class TestSTM32F767(unittest.TestCase):
    """STM32F767 (Cortex-M7): ROM + RAM + ITCMRAM."""

    def test_regions(self):
        regions = _parse("stm32f767xx_flash.icf")
        self.assertEqual(len(regions), 3)

        self.assertIn("ROM_region", regions)
        self.assertEqual(regions["ROM_region"]["address"], 0x08000000)
        self.assertEqual(regions["ROM_region"]["limit_size"], 0x200000)  # 2 MB

        self.assertIn("RAM_region", regions)
        self.assertEqual(regions["RAM_region"]["address"], 0x20000000)
        self.assertEqual(regions["RAM_region"]["limit_size"], 0x80000)  # 512 KB

        self.assertIn("ITCMRAM_region", regions)
        self.assertEqual(regions["ITCMRAM_region"]["address"], 0x00000000)
        self.assertEqual(regions["ITCMRAM_region"]["limit_size"], 0x4000)  # 16 KB


class TestSTM32G484(unittest.TestCase):
    """STM32G484 (Cortex-M4): SRAM execution config."""

    def test_regions(self):
        regions = _parse("stm32g484xx_sram.icf")
        self.assertEqual(len(regions), 3)

        # In SRAM mode, ROM_region is placed in SRAM
        self.assertIn("ROM_region", regions)
        self.assertEqual(regions["ROM_region"]["address"], 0x20000000)
        self.assertEqual(regions["ROM_region"]["limit_size"], 0xA000)  # 40 KB

        self.assertIn("RAM_region", regions)
        self.assertEqual(regions["RAM_region"]["address"], 0x2000A000)
        self.assertEqual(regions["RAM_region"]["limit_size"], 0x16000)  # 88 KB

        self.assertIn("CCMSRAM_region", regions)
        self.assertEqual(regions["CCMSRAM_region"]["address"], 0x10000000)
        self.assertEqual(regions["CCMSRAM_region"]["limit_size"], 0x8000)  # 32 KB


class TestSTM32H7A3(unittest.TestCase):
    """STM32H7A3xG: dual-bank flash with region union (|)."""

    def test_regions(self):
        regions = _parse("stm32h7a3xg_flash.icf")
        self.assertEqual(len(regions), 2)

        self.assertIn("ROM_region", regions)
        self.assertEqual(regions["ROM_region"]["address"], 0x08000000)
        # Dual-bank: bounding box of bank1 | bank2 = 0x08000000 to 0x0817FFFF
        self.assertEqual(regions["ROM_region"]["limit_size"], 0x180000)

        self.assertIn("RAM_region", regions)
        self.assertEqual(regions["RAM_region"]["address"], 0x20000000)
        self.assertEqual(regions["RAM_region"]["limit_size"], 0x20000)  # 128 KB


class TestSTM32H743xG(unittest.TestCase):
    """STM32H743xG: dual-bank flash + ITCMRAM."""

    def test_regions(self):
        regions = _parse("stm32h743xg_dual_flash.icf")
        self.assertEqual(len(regions), 3)

        self.assertIn("ROM_region", regions)
        self.assertEqual(regions["ROM_region"]["address"], 0x08000000)
        self.assertEqual(regions["ROM_region"]["limit_size"], 0x180000)  # 1.5 MB (dual-bank union)

        self.assertIn("RAM_region", regions)
        self.assertEqual(regions["RAM_region"]["address"], 0x20000000)
        self.assertEqual(regions["RAM_region"]["limit_size"], 0x20000)  # 128 KB

        self.assertIn("ITCMRAM_region", regions)
        self.assertEqual(regions["ITCMRAM_region"]["address"], 0x00000000)
        self.assertEqual(regions["ITCMRAM_region"]["limit_size"], 0x10000)  # 64 KB


class TestSTM32H753(unittest.TestCase):
    """STM32H753: 9 distinct memory regions (dual flash, AXI_SRAM, SRAM1-4, ITCM, DTCM)."""

    def test_region_count(self):
        regions = _parse("stm32h753_multi_region.icf")
        self.assertEqual(len(regions), 9)

    def test_flash_banks(self):
        regions = _parse("stm32h753_multi_region.icf")
        self.assertEqual(regions["FLASH1_region"]["address"], 0x08000000)
        self.assertEqual(regions["FLASH1_region"]["limit_size"], 0x100000)  # 1 MB
        self.assertEqual(regions["FLASH2_region"]["address"], 0x08100000)
        self.assertEqual(regions["FLASH2_region"]["limit_size"], 0x100000)  # 1 MB

    def test_sram_regions(self):
        regions = _parse("stm32h753_multi_region.icf")
        self.assertEqual(regions["AXI_SRAM_region"]["address"], 0x24000000)
        self.assertEqual(regions["AXI_SRAM_region"]["limit_size"], 0x80000)  # 512 KB
        self.assertEqual(regions["SRAM1_region"]["address"], 0x30000000)
        self.assertEqual(regions["SRAM1_region"]["limit_size"], 0x20000)  # 128 KB
        self.assertEqual(regions["SRAM2_region"]["address"], 0x30020000)
        self.assertEqual(regions["SRAM2_region"]["limit_size"], 0x20000)  # 128 KB
        self.assertEqual(regions["SRAM3_region"]["address"], 0x30040000)
        self.assertEqual(regions["SRAM3_region"]["limit_size"], 0x8000)  # 32 KB
        self.assertEqual(regions["SRAM4_region"]["address"], 0x38000000)
        self.assertEqual(regions["SRAM4_region"]["limit_size"], 0x10000)  # 64 KB

    def test_tcm_regions(self):
        regions = _parse("stm32h753_multi_region.icf")
        self.assertEqual(regions["ITCMRAM_region"]["address"], 0x00000000)
        self.assertEqual(regions["ITCMRAM_region"]["limit_size"], 0x10000)  # 64 KB
        self.assertEqual(regions["DTCMRAM_region"]["address"], 0x20000000)
        self.assertEqual(regions["DTCMRAM_region"]["limit_size"], 0x20000)  # 128 KB


class TestSTM32L4S9(unittest.TestCase):
    """STM32L4S9: SRAM execution with multiple SRAM banks."""

    def test_regions(self):
        regions = _parse("stm32l4s9xx_sram.icf")
        self.assertEqual(len(regions), 5)

        self.assertIn("ROM_region", regions)
        self.assertEqual(regions["ROM_region"]["address"], 0x20000000)
        self.assertEqual(regions["ROM_region"]["limit_size"], 0x20000)  # 128 KB

        self.assertIn("RAM_region", regions)
        self.assertEqual(regions["RAM_region"]["address"], 0x20020000)
        self.assertEqual(regions["RAM_region"]["limit_size"], 0x10000)  # 64 KB

        self.assertIn("SRAM1_region", regions)
        self.assertEqual(regions["SRAM1_region"]["address"], 0x20020000)
        self.assertEqual(regions["SRAM1_region"]["limit_size"], 0x10000)  # 64 KB

        self.assertIn("SRAM2_region", regions)
        self.assertEqual(regions["SRAM2_region"]["address"], 0x20030000)
        self.assertEqual(regions["SRAM2_region"]["limit_size"], 0x10000)  # 64 KB

        self.assertIn("SRAM3_region", regions)
        self.assertEqual(regions["SRAM3_region"]["address"], 0x20040000)
        self.assertEqual(regions["SRAM3_region"]["limit_size"], 0x60000)  # 384 KB


class TestSTM32WB55(unittest.TestCase):
    """STM32WB55: dual-core (M4+M0+) with shared RAM for IPC."""

    def test_regions(self):
        regions = _parse("stm32wb55xx_flash_cm4.icf")
        self.assertEqual(len(regions), 3)

        self.assertIn("ROM_region", regions)
        self.assertEqual(regions["ROM_region"]["address"], 0x08000000)
        self.assertEqual(regions["ROM_region"]["limit_size"], 0x80000)  # 512 KB

        self.assertIn("RAM_region", regions)
        self.assertEqual(regions["RAM_region"]["address"], 0x20000008)
        self.assertEqual(regions["RAM_region"]["limit_size"], 0x2FFF8)  # ~192 KB

        # Shared RAM for IPC mailbox
        self.assertIn("RAM_SHARED_region", regions)
        self.assertEqual(regions["RAM_SHARED_region"]["address"], 0x20030000)
        self.assertEqual(regions["RAM_SHARED_region"]["limit_size"], 0x2800)


# ===================================================================
# NXP / Freescale
# ===================================================================


class TestNXPMCXA145(unittest.TestCase):
    """NXP MCXA145: RAM execution with conditional stack/heap."""

    def test_regions(self):
        regions = _parse("nxp_mcxa145_ram.icf")
        self.assertEqual(len(regions), 3)

        self.assertIn("TEXT_region", regions)
        self.assertEqual(regions["TEXT_region"]["address"], 0x20000000)
        self.assertEqual(regions["TEXT_region"]["limit_size"], 0x6000)  # 24 KB

        self.assertIn("DATA_region", regions)
        self.assertEqual(regions["DATA_region"]["address"], 0x20006000)
        self.assertEqual(regions["DATA_region"]["limit_size"], 0xDC00)  # ~55 KB

        self.assertIn("CSTACK_region", regions)
        self.assertEqual(regions["CSTACK_region"]["address"], 0x20013C00)
        self.assertEqual(regions["CSTACK_region"]["limit_size"], 0x400)  # 1 KB

    def test_rpmsg_excluded_without_shmem(self):
        """rpmsg_sh_mem_region only defined when __use_shmem__ is set."""
        regions = _parse("nxp_mcxa145_ram.icf")
        self.assertNotIn("rpmsg_sh_mem_region", regions)


class TestNXPLPC55S36(unittest.TestCase):
    """NXP LPC55S36: flash with conditional PKC/PowerQuad/QSPI features."""

    def test_regions(self):
        regions = _parse("nxp_lpc55s36_flash.icf")
        self.assertEqual(len(regions), 3)

        self.assertIn("TEXT_region", regions)
        self.assertEqual(regions["TEXT_region"]["address"], 0x00000000)
        self.assertEqual(regions["TEXT_region"]["limit_size"], 0x3D800)  # ~246 KB

        self.assertIn("DATA_region", regions)
        self.assertEqual(regions["DATA_region"]["address"], 0x20000000)
        self.assertEqual(regions["DATA_region"]["limit_size"], 0x1BC00)  # ~111 KB

        self.assertIn("CSTACK_region", regions)
        self.assertEqual(regions["CSTACK_region"]["address"], 0x2001BC00)
        self.assertEqual(regions["CSTACK_region"]["limit_size"], 0x400)  # 1 KB

    def test_rpmsg_excluded_without_shmem(self):
        """rpmsg_sh_mem_region only defined when __use_shmem__ is set."""
        regions = _parse("nxp_lpc55s36_flash.icf")
        self.assertNotIn("rpmsg_sh_mem_region", regions)


class TestNXPiMXRT1052(unittest.TestCase):
    """NXP i.MX RT1052: XIP from external FlexSPI NOR flash."""

    def test_regions(self):
        regions = _parse("nxp_imxrt1052_flexspi.icf")
        self.assertEqual(len(regions), 4)

        self.assertIn("TEXT_region", regions)
        # XIP from external flash at 0x60000000+
        self.assertEqual(regions["TEXT_region"]["address"], 0x60002000)
        self.assertEqual(regions["TEXT_region"]["limit_size"], 0x3FFE000)  # ~64 MB

        self.assertIn("DATA_region", regions)
        self.assertEqual(regions["DATA_region"]["address"], 0x20000000)
        self.assertEqual(regions["DATA_region"]["limit_size"], 0x1FC00)  # ~127 KB

        self.assertIn("DATA2_region", regions)
        self.assertEqual(regions["DATA2_region"]["address"], 0x20200000)
        self.assertEqual(regions["DATA2_region"]["limit_size"], 0x40000)  # 256 KB

        self.assertIn("CSTACK_region", regions)
        self.assertEqual(regions["CSTACK_region"]["address"], 0x2001FC00)
        self.assertEqual(regions["CSTACK_region"]["limit_size"], 0x400)  # 1 KB


class TestNXPMK66(unittest.TestCase):
    """NXP Kinetis K66: flash with FlexNVM and FlexRAM."""

    def test_regions(self):
        regions = _parse("nxp_mk66_flash.icf")
        self.assertEqual(len(regions), 4)

        self.assertIn("ROM_region", regions)
        self.assertEqual(regions["ROM_region"]["address"], 0x00000000)
        # bounding box of non-contiguous union
        self.assertEqual(regions["ROM_region"]["limit_size"], 0x10040000)

        self.assertIn("RAM_region", regions)
        self.assertEqual(regions["RAM_region"]["address"], 0x1FFF0000)
        self.assertEqual(regions["RAM_region"]["limit_size"], 0x40000)  # 256 KB

        self.assertIn("FlexRAM_region", regions)
        self.assertEqual(regions["FlexRAM_region"]["address"], 0x14000000)
        self.assertEqual(regions["FlexRAM_region"]["limit_size"], 0x1000)  # 4 KB

        # Flash config protection region
        self.assertIn("FlashConfig_region", regions)
        self.assertEqual(regions["FlashConfig_region"]["address"], 0x00000400)
        self.assertEqual(regions["FlashConfig_region"]["limit_size"], 0x10)  # 16 bytes


# ===================================================================
# Texas Instruments
# ===================================================================


class TestTICC26x2BIM(unittest.TestCase):
    """TI CC26x2/CC13x2 Boot Image Manager with OAD support."""

    def test_regions(self):
        regions = _parse("ti_cc26x2_bim.icf")
        self.assertEqual(len(regions), 4)

        # BIM section at fixed flash page
        self.assertIn("BIM", regions)
        self.assertEqual(regions["BIM"]["address"], 0x00056000)
        self.assertEqual(regions["BIM"]["limit_size"], 0x2001)

        self.assertIn("RAM", regions)
        self.assertEqual(regions["RAM"]["address"], 0x20000FDF)
        self.assertEqual(regions["RAM"]["limit_size"], 0x13021)

        self.assertIn("CERT_ELEMENT", regions)
        self.assertEqual(regions["CERT_ELEMENT"]["address"], 0x00057F54)
        self.assertEqual(regions["CERT_ELEMENT"]["limit_size"], 0x4C)  # 76 bytes

        self.assertIn("FLASH_FN_PTR", regions)
        self.assertEqual(regions["FLASH_FN_PTR"]["address"], 0x00057FA0)
        self.assertEqual(regions["FLASH_FN_PTR"]["limit_size"], 0x4)  # 4 bytes


# ===================================================================
# Infineon / Cypress
# ===================================================================


class TestInfineonPSoC6CM0Plus(unittest.TestCase):
    """Infineon PSoC 6 CM0+: dual-core with supervisory flash regions."""

    def test_region_count(self):
        regions = _parse("infineon_psoc6_cm0plus.icf")
        # 10 regions defined, but IROM3 has end < start (Cypress bug: 0x160007FF < 0x16000800)
        self.assertEqual(len(regions), 9)

    def test_main_regions(self):
        regions = _parse("infineon_psoc6_cm0plus.icf")
        # Main flash for CM0+
        self.assertIn("IROM1_region", regions)
        self.assertEqual(regions["IROM1_region"]["address"], 0x10000000)
        self.assertEqual(regions["IROM1_region"]["limit_size"], 0x2000)  # 8 KB

        # Internal RAM
        self.assertIn("IRAM1_region", regions)
        self.assertEqual(regions["IRAM1_region"]["address"], 0x08000000)
        self.assertEqual(regions["IRAM1_region"]["limit_size"], 0x2000)  # 8 KB

    def test_supervisory_flash(self):
        regions = _parse("infineon_psoc6_cm0plus.icf")
        # Supervisory flash regions
        self.assertIn("IROM2_region", regions)
        self.assertEqual(regions["IROM2_region"]["address"], 0x14000000)
        self.assertEqual(regions["IROM2_region"]["limit_size"], 0x8000)  # 32 KB

        # External memory
        self.assertIn("EROM1_region", regions)
        self.assertEqual(regions["EROM1_region"]["address"], 0x18000000)
        self.assertEqual(regions["EROM1_region"]["limit_size"], 0x8000000)  # 128 MB

    def test_additional_irom_regions(self):
        regions = _parse("infineon_psoc6_cm0plus.icf")
        self.assertEqual(regions["IROM4_region"]["address"], 0x16001A00)
        self.assertEqual(regions["IROM4_region"]["limit_size"], 0x200)  # 512 B
        self.assertEqual(regions["IROM5_region"]["address"], 0x16005A00)
        self.assertEqual(regions["IROM5_region"]["limit_size"], 0xC00)  # 3 KB
        self.assertEqual(regions["IROM6_region"]["address"], 0x16007C00)
        self.assertEqual(regions["IROM6_region"]["limit_size"], 0x200)  # 512 B
        self.assertEqual(regions["IROM7_region"]["address"], 0x16007E00)
        self.assertEqual(regions["IROM7_region"]["limit_size"], 0x200)  # 512 B
        self.assertEqual(regions["IROM8_region"]["address"], 0x90700000)
        self.assertEqual(regions["IROM8_region"]["limit_size"], 0x100000)  # 1 MB

    def test_irom3_excluded_for_inverted_bounds(self):
        """IROM3 has end (0x160007FF) < start (0x16000800) — a bug in the Cypress ICF."""
        regions = _parse("infineon_psoc6_cm0plus.icf")
        self.assertNotIn("IROM3_region", regions)


class TestInfineonPMG1S2(unittest.TestCase):
    """Infineon PMG1S2 (USB-PD): simple flash + RAM."""

    def test_regions(self):
        regions = _parse("infineon_pmg1s2.icf")
        self.assertEqual(len(regions), 2)

        self.assertIn("IROM1_region", regions)
        self.assertEqual(regions["IROM1_region"]["address"], 0x00000000)
        self.assertEqual(regions["IROM1_region"]["limit_size"], 0x20000)  # 128 KB

        self.assertIn("IRAM1_region", regions)
        self.assertEqual(regions["IRAM1_region"]["address"], 0x20000000)
        self.assertEqual(regions["IRAM1_region"]["limit_size"], 0x2000)  # 8 KB


class TestInfineonTraveoII(unittest.TestCase):
    """Infineon Traveo II (TVIIC2D4M): dual-core automotive MCU with 12 regions."""

    def test_region_count(self):
        regions = _parse("infineon_tviic2d4m.icf")
        # 14 defined, but CODE_FLASH_CM7_0 and SRAM_CM7_0 are inside
        # if(isdefinedsymbol(_CORE_cm0plus_)) which is not set
        self.assertEqual(len(regions), 12)

    def test_code_flash(self):
        regions = _parse("infineon_tviic2d4m.icf")
        self.assertIn("CODE_FLASH", regions)
        self.assertEqual(regions["CODE_FLASH"]["address"], 0x10080000)
        self.assertEqual(regions["CODE_FLASH"]["limit_size"], 0x390000)  # ~3.5 MB

    def test_sram(self):
        regions = _parse("infineon_tviic2d4m.icf")
        self.assertIn("SRAM", regions)
        self.assertEqual(regions["SRAM"]["address"], 0x28020000)
        self.assertEqual(regions["SRAM"]["limit_size"], 0x40000)  # 256 KB

    def test_smif_regions(self):
        regions = _parse("infineon_tviic2d4m.icf")
        # 512 MB external memory regions
        self.assertIn("SMIF0_MEM", regions)
        self.assertEqual(regions["SMIF0_MEM"]["address"], 0x60000000)
        self.assertEqual(regions["SMIF0_MEM"]["limit_size"], 0x20000000)  # 512 MB

        self.assertIn("SMIF1_MEM", regions)
        self.assertEqual(regions["SMIF1_MEM"]["address"], 0x80000000)
        self.assertEqual(regions["SMIF1_MEM"]["limit_size"], 0x20000000)  # 512 MB

    def test_tcm_regions(self):
        regions = _parse("infineon_tviic2d4m.icf")
        self.assertIn("ITCM", regions)
        self.assertEqual(regions["ITCM"]["address"], 0xA0000000)
        self.assertEqual(regions["ITCM"]["limit_size"], 0x10000)  # 64 KB
        self.assertIn("DTCM", regions)
        self.assertEqual(regions["DTCM"]["address"], 0xA0010000)
        self.assertEqual(regions["DTCM"]["limit_size"], 0x10000)  # 64 KB

    def test_self_tcm_regions(self):
        regions = _parse("infineon_tviic2d4m.icf")
        self.assertEqual(regions["SELF_ITCM"]["address"], 0x00000000)
        self.assertEqual(regions["SELF_ITCM"]["limit_size"], 0x10000)  # 64 KB
        self.assertEqual(regions["SELF_DTCM"]["address"], 0x20000000)
        self.assertEqual(regions["SELF_DTCM"]["limit_size"], 0x10000)  # 64 KB

    def test_flash_regions(self):
        regions = _parse("infineon_tviic2d4m.icf")
        self.assertEqual(regions["WORK_FLASH"]["address"], 0x14000000)
        self.assertEqual(regions["WORK_FLASH"]["limit_size"], 0x40000)  # 256 KB
        self.assertEqual(regions["SFLASH"]["address"], 0x17000000)
        self.assertEqual(regions["SFLASH"]["limit_size"], 0x8000)  # 32 KB
        self.assertEqual(regions["SFLASH_ALT"]["address"], 0x17800000)
        self.assertEqual(regions["SFLASH_ALT"]["limit_size"], 0x8000)  # 32 KB

    def test_vram(self):
        regions = _parse("infineon_tviic2d4m.icf")
        self.assertEqual(regions["VRAM"]["address"], 0x24000000)
        self.assertEqual(regions["VRAM"]["limit_size"], 0x200000)  # 2 MB

    def test_cm7_regions_excluded_without_symbol(self):
        """CM7 regions only defined when _CORE_cm0plus_ is set (linker flag)."""
        regions = _parse("infineon_tviic2d4m.icf")
        self.assertNotIn("CODE_FLASH_CM7_0", regions)
        self.assertNotIn("SRAM_CM7_0", regions)


# ===================================================================
# Microchip / Atmel
# ===================================================================


class TestMicrochipSAME53(unittest.TestCase):
    """Microchip SAME53: SRAM execution + QSPI + Backup RAM."""

    def test_regions(self):
        regions = _parse("microchip_same53_sram.icf")
        self.assertEqual(len(regions), 3)

        self.assertIn("RAM_region", regions)
        self.assertEqual(regions["RAM_region"]["address"], 0x20000000)
        self.assertEqual(regions["RAM_region"]["limit_size"], 0x40000)  # 256 KB

        self.assertIn("BKUPRAM_region", regions)
        self.assertEqual(regions["BKUPRAM_region"]["address"], 0x47000000)
        self.assertEqual(regions["BKUPRAM_region"]["limit_size"], 0x2000)  # 8 KB

        self.assertIn("QSPI_region", regions)
        self.assertEqual(regions["QSPI_region"]["address"], 0x04000000)
        self.assertEqual(regions["QSPI_region"]["limit_size"], 0x1000000)  # 16 MB


class TestAtmelSAMV71(unittest.TestCase):
    """Atmel SAMV71: SRAM with non-cacheable and external RAM regions."""

    def test_regions(self):
        regions = _parse("atmel_samv71_sram.icf")
        self.assertEqual(len(regions), 4)

        self.assertIn("RAM_region", regions)
        self.assertEqual(regions["RAM_region"]["address"], 0x20400000)

        self.assertIn("RAM_NC_region", regions)
        self.assertEqual(regions["RAM_NC_region"]["limit_size"], 0x1000)  # 4 KB non-cacheable

        self.assertIn("EXTRAM_region", regions)
        self.assertEqual(regions["EXTRAM_region"]["address"], 0x70000000)
        self.assertEqual(regions["EXTRAM_region"]["limit_size"], 0x100000)  # 1 MB

        self.assertIn("FLASH_region", regions)
        self.assertEqual(regions["FLASH_region"]["address"], 0x00400000)
        self.assertEqual(regions["FLASH_region"]["limit_size"], 0x200000)  # 2 MB


# ===================================================================
# Nuvoton
# ===================================================================


class TestNuvotonM2351Secure(unittest.TestCase):
    """Nuvoton M2351: ARM TrustZone secure configuration with NSC region."""

    def test_region_count(self):
        regions = _parse("nuvoton_m2351_secure.icf")
        self.assertEqual(len(regions), 5)

    def test_has_nsc_region(self):
        regions = _parse("nuvoton_m2351_secure.icf")
        # Non-Secure Callable veneer region
        self.assertIn("NSC_region", regions)
        self.assertEqual(regions["NSC_region"]["address"], 0x3F000)
        self.assertEqual(regions["NSC_region"]["limit_size"], 0x800)  # 2 KB

    def test_main_regions(self):
        regions = _parse("nuvoton_m2351_secure.icf")
        self.assertIn("IROM_region", regions)
        self.assertEqual(regions["IROM_region"]["address"], 0x00000000)
        self.assertEqual(regions["IROM_region"]["limit_size"], 0x3F000)  # 252 KB

        self.assertIn("IRAM_region", regions)
        self.assertEqual(regions["IRAM_region"]["address"], 0x00000000)
        self.assertEqual(regions["IRAM_region"]["limit_size"], 0x20018000)  # bounding box of union

    def test_external_regions(self):
        regions = _parse("nuvoton_m2351_secure.icf")
        self.assertIn("EROM_region", regions)
        self.assertEqual(regions["EROM_region"]["address"], 0x00000000)
        self.assertEqual(regions["EROM_region"]["limit_size"], 0x1)

        self.assertIn("ERAM_region", regions)
        self.assertEqual(regions["ERAM_region"]["address"], 0x00000000)
        self.assertEqual(regions["ERAM_region"]["limit_size"], 0x1)


class TestNuvotonM467(unittest.TestCase):
    """Nuvoton M467: uses || operator in symbol defs and [] empty region syntax.

    This file exercises:
    - define symbol use_X = (expr || expr)  -- logical OR in symbol expressions
    - define region X = []                  -- empty region literal
    - if (use_X) { ... }                    -- conditional on symbol with || origin
    - !isempty(region)                      -- isempty() built-in
    """

    def test_regions(self):
        """Parser should extract IROM1 and IRAM1 regions."""
        regions = _parse("nuvoton_m467.icf")
        self.assertEqual(len(regions), 4)

        # IROM1: 0x00000000 - 0x000FFFFF (1 MB internal flash)
        self.assertIn("IROM1_region", regions)
        self.assertEqual(regions["IROM1_region"]["address"], 0x00000000)
        self.assertEqual(regions["IROM1_region"]["limit_size"], 0x100000)

        # IROM_region = IROM1_region | IROM2_region (IROM2 is empty)
        self.assertIn("IROM_region", regions)
        self.assertEqual(regions["IROM_region"]["address"], 0x00000000)
        self.assertEqual(regions["IROM_region"]["limit_size"], 0x100000)

        # IRAM1: 0x20000000 - 0x2007FFFF (512 KB)
        self.assertIn("IRAM1_region", regions)
        self.assertEqual(regions["IRAM1_region"]["address"], 0x20000000)
        self.assertEqual(regions["IRAM1_region"]["limit_size"], 0x80000)

        # IRAM_region = IRAM1_region | IRAM2_region (IRAM2 is empty)
        self.assertIn("IRAM_region", regions)
        self.assertEqual(regions["IRAM_region"]["address"], 0x20000000)
        self.assertEqual(regions["IRAM_region"]["limit_size"], 0x80000)

    def test_empty_regions_not_included(self):
        """Regions defined as [] should not appear in output."""
        regions = _parse("nuvoton_m467.icf")
        # IROM2, EROM1-3, IRAM2, ERAM1-3 are defined as [] (empty)
        for name in ("IROM2_region", "EROM1_region", "EROM2_region",
                      "EROM3_region", "IRAM2_region", "ERAM1_region",
                      "ERAM2_region", "ERAM3_region"):
            self.assertNotIn(name, regions,
                             f"Empty region {name} should not be in output")

        # Union regions where all components are empty should also be absent
        self.assertNotIn("EROM_region", regions)
        self.assertNotIn("ERAM_region", regions)


# ===================================================================
# HPMicro (RISC-V)
# ===================================================================


class TestHPMicroHPM6P81(unittest.TestCase):
    """HPMicro HPM6P81: RISC-V with 9 memory regions (flash XIP)."""

    def test_region_count(self):
        regions = _parse("hpmicro_hpm6p81_flash.icf")
        self.assertEqual(len(regions), 9)

    def test_flash_xip(self):
        regions = _parse("hpmicro_hpm6p81_flash.icf")
        self.assertIn("FLASH", regions)
        self.assertEqual(regions["FLASH"]["address"], 0x80003000)
        self.assertEqual(regions["FLASH"]["limit_size"], 0x7FD000)  # ~8 MB

    def test_ilm_dlm(self):
        regions = _parse("hpmicro_hpm6p81_flash.icf")
        self.assertIn("ILM", regions)
        self.assertEqual(regions["ILM"]["address"], 0x00000000)
        self.assertEqual(regions["ILM"]["limit_size"], 0x20000)  # 128 KB

        self.assertIn("DLM", regions)
        self.assertEqual(regions["DLM"]["address"], 0x00200000)
        self.assertEqual(regions["DLM"]["limit_size"], 0x20000)  # 128 KB

    def test_sram_regions(self):
        regions = _parse("hpmicro_hpm6p81_flash.icf")
        self.assertIn("AXI_SRAM", regions)
        self.assertEqual(regions["AXI_SRAM"]["address"], 0x01220000)
        self.assertEqual(regions["AXI_SRAM"]["limit_size"], 0x1C000)  # 112 KB

        self.assertIn("SHARE_RAM", regions)
        self.assertEqual(regions["SHARE_RAM"]["address"], 0x0123C000)
        self.assertEqual(regions["SHARE_RAM"]["limit_size"], 0x4000)  # 16 KB

        self.assertIn("AHB_SRAM", regions)
        self.assertEqual(regions["AHB_SRAM"]["address"], 0xF0200000)
        self.assertEqual(regions["AHB_SRAM"]["limit_size"], 0x8000)  # 32 KB

        self.assertIn("NONCACHEABLE_RAM", regions)
        self.assertEqual(regions["NONCACHEABLE_RAM"]["address"], 0x01200000)
        self.assertEqual(regions["NONCACHEABLE_RAM"]["limit_size"], 0x20000)  # 128 KB

    def test_boot_header(self):
        regions = _parse("hpmicro_hpm6p81_flash.icf")
        self.assertIn("BOOT_HEADER", regions)
        self.assertEqual(regions["BOOT_HEADER"]["address"], 0x80001000)
        self.assertEqual(regions["BOOT_HEADER"]["limit_size"], 0x90)  # 144 bytes

        self.assertIn("NOR_CFG_OPTION", regions)
        self.assertEqual(regions["NOR_CFG_OPTION"]["address"], 0x80000400)
        self.assertEqual(regions["NOR_CFG_OPTION"]["limit_size"], 0xC00)  # 3 KB


# ===================================================================
# Goodix (BLE SoC)
# ===================================================================


class TestGoodixGR5526(unittest.TestCase):
    """Goodix GR5526: BLE SoC with triple RAM region union."""

    def test_regions_parsed(self):
        regions = _parse("goodix_gr5526.icf")
        self.assertEqual(len(regions), 8)

    def test_rom_region(self):
        regions = _parse("goodix_gr5526.icf")
        self.assertIn("IROM1_region", regions)
        self.assertEqual(regions["IROM1_region"]["address"], 0x00204000)
        self.assertEqual(regions["IROM1_region"]["limit_size"], 0xFC000)  # ~1008 KB

        self.assertIn("IROM_region", regions)
        self.assertEqual(regions["IROM_region"]["address"], 0x00204000)
        self.assertEqual(regions["IROM_region"]["limit_size"], 0xFC000)

    def test_ram_union(self):
        regions = _parse("goodix_gr5526.icf")
        # IRAM_region = IRAM1 | IRAM2 | IRAM3 (non-contiguous, bounding box)
        self.assertIn("IRAM_region", regions)
        # Bounding box should span from IRAM3 (0x106000) to IRAM1 end (0x20078FFF)
        self.assertEqual(regions["IRAM_region"]["address"], 0x00106000)
        self.assertEqual(regions["IRAM_region"]["limit_size"], 0x1FF73000)  # bounding box

        # Individual RAM regions
        self.assertIn("IRAM1_region", regions)
        self.assertEqual(regions["IRAM1_region"]["address"], 0x2000B050)
        self.assertEqual(regions["IRAM1_region"]["limit_size"], 0x6DFB0)  # ~439 KB

        self.assertIn("IRAM2_region", regions)
        self.assertEqual(regions["IRAM2_region"]["address"], 0x2000B000)
        self.assertEqual(regions["IRAM2_region"]["limit_size"], 0x51)  # 81 bytes

        self.assertIn("IRAM3_region", regions)
        self.assertEqual(regions["IRAM3_region"]["address"], 0x00106000)
        self.assertEqual(regions["IRAM3_region"]["limit_size"], 0x5000)  # 20 KB

    def test_callstack_callheap(self):
        regions = _parse("goodix_gr5526.icf")
        self.assertIn("CALLSTACK_region", regions)
        self.assertEqual(regions["CALLSTACK_region"]["address"], 0x2007D000)
        self.assertEqual(regions["CALLSTACK_region"]["limit_size"], 0x3000)  # 12 KB

        self.assertIn("CALLHEAP_region", regions)
        self.assertEqual(regions["CALLHEAP_region"]["address"], 0x20079000)
        self.assertEqual(regions["CALLHEAP_region"]["limit_size"], 0x4000)  # 16 KB


# ===================================================================
# Renesas
# ===================================================================


class TestRenesasRA6M5(unittest.TestCase):
    """Renesas RA6M5 FSP: depends on include "memory_regions.icf" (missing).

    This file is the FSP (Flexible Software Package) linker template that
    requires a generated memory_regions.icf to provide FLASH_START, RAM_START,
    etc. Without it, all regions fail to resolve.

    Also exercises: ||, &&, ?:, alignup(), export symbol, check that.
    """

    def test_fails_without_included_memory_regions(self):
        """Parser should raise because the included file is missing."""
        with self.assertRaises(LinkerScriptError):
            _parse("renesas_ra6m5_fsp.icf")


# ===================================================================
# Cross-cutting feature tests
# ===================================================================


class TestICFRegionUnionRealWorld(unittest.TestCase):
    """Verify region union (|) works with real-world multi-bank flash layouts."""

    def test_stm32h7a3_dual_bank_union(self):
        """STM32H7A3 uses mem:[bank1] | mem:[bank2] for ROM_region."""
        regions = _parse("stm32h7a3xg_flash.icf")
        # ROM_region is a union of two flash banks
        self.assertIn("ROM_region", regions)
        self.assertEqual(regions["ROM_region"]["limit_size"], 0x180000)  # 1.5 MB bounding box

    def test_stm32h743_dual_bank_union(self):
        """STM32H743xG uses dual-bank flash union."""
        regions = _parse("stm32h743xg_dual_flash.icf")
        self.assertIn("ROM_region", regions)
        self.assertEqual(regions["ROM_region"]["limit_size"], 0x180000)  # 1.5 MB bounding box

    def test_goodix_triple_ram_union(self):
        """Goodix GR5526 uses IRAM1 | IRAM2 | IRAM3."""
        regions = _parse("goodix_gr5526.icf")
        self.assertIn("IRAM_region", regions)
        # Union of 3 non-contiguous spans
        self.assertIn("IRAM1_region", regions)
        self.assertIn("IRAM2_region", regions)
        self.assertIn("IRAM3_region", regions)

    def test_nuvoton_m2351_inline_union(self):
        """Nuvoton M2351 uses inline mem:[] | mem:[] union in region definition."""
        regions = _parse("nuvoton_m2351_secure.icf")
        self.assertIn("IROM_region", regions)
        # IROM_region = mem:[IROM1] | mem:[IROM2]
        self.assertEqual(regions["IROM_region"]["address"], 0x00000000)


class TestICFConditionalRealWorld(unittest.TestCase):
    """Verify conditional handling with real-world ICF patterns."""

    def test_nxp_conditional_stack_size(self):
        """NXP MCXA145 uses isdefinedsymbol for conditional stack sizing."""
        regions = _parse("nxp_mcxa145_ram.icf")
        # Should get default stack/heap sizes when symbols are not defined
        self.assertIn("CSTACK_region", regions)

    def test_infineon_tviic2d4m_nested_conditionals(self):
        """Traveo II uses nested conditionals for core/link type selection."""
        regions = _parse("infineon_tviic2d4m.icf")
        # 12 regions (2 CM7-only regions excluded without _CORE_cm0plus_ symbol)
        self.assertEqual(len(regions), 12)

    def test_ti_cc26x2_conditional_flash(self):
        """TI CC26x2 BIM uses conditionals for OAD flash layout."""
        regions = _parse("ti_cc26x2_bim.icf")
        self.assertIn("BIM", regions)


class TestICFMultipleArchitectures(unittest.TestCase):
    """Verify parser works across different processor architectures."""

    def test_cortex_m4(self):
        """STM32G484 (Cortex-M4)."""
        regions = _parse("stm32g484xx_sram.icf")
        self.assertEqual(len(regions), 3)

    def test_cortex_m7(self):
        """STM32F767 (Cortex-M7)."""
        regions = _parse("stm32f767xx_flash.icf")
        self.assertEqual(len(regions), 3)

    def test_riscv(self):
        """HPMicro HPM6P81 (RISC-V)."""
        regions = _parse("hpmicro_hpm6p81_flash.icf")
        self.assertEqual(len(regions), 9)


class TestICFMemoryLayoutDiversity(unittest.TestCase):
    """Verify parser handles diverse memory layouts."""

    def test_external_flash_xip(self):
        """NXP i.MX RT1052: XIP from external flash at 0x60000000+."""
        regions = _parse("nxp_imxrt1052_flexspi.icf")
        self.assertEqual(regions["TEXT_region"]["address"], 0x60002000)
        self.assertEqual(regions["TEXT_region"]["limit_size"], 0x3FFE000)  # ~64 MB

    def test_backup_ram(self):
        """Microchip SAME53: backup RAM region."""
        regions = _parse("microchip_same53_sram.icf")
        self.assertEqual(regions["BKUPRAM_region"]["address"], 0x47000000)

    def test_non_cacheable_region(self):
        """Atmel SAMV71: separate non-cacheable RAM for DMA."""
        regions = _parse("atmel_samv71_sram.icf")
        self.assertIn("RAM_NC_region", regions)

    def test_large_external_memory(self):
        """Infineon Traveo II: 512 MB SMIF regions."""
        regions = _parse("infineon_tviic2d4m.icf")
        self.assertEqual(regions["SMIF0_MEM"]["limit_size"], 0x20000000)

    def test_supervisory_flash(self):
        """Infineon PSoC 6: supervisory flash regions."""
        regions = _parse("infineon_psoc6_cm0plus.icf")
        # 7 IROM regions (IROM1-2, IROM4-8; IROM3 excluded for inverted bounds)
        irom_regions = [k for k in regions if k.startswith("IROM")]
        self.assertEqual(len(irom_regions), 7)


if __name__ == "__main__":
    unittest.main()
