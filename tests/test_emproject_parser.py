#!/usr/bin/env python3

"""
test_emproject_parser.py - Tests for SEGGER Embedded Studio .emProject XML parsing.

Covers:
  - Format detection (DOCTYPE and <solution> root)
  - linker_section_placements_segments extraction
  - Multiple configurations (Common vs Debug/Release)
  - Hex and decimal address parsing
  - RX/RWX/etc. attribute lowercase mapping
  - Malformed XML, missing attribute, malformed segments
  - Integration through LinkerScriptParser (transparent dispatch)
  - Coexistence with ICF detector (no false positives)
"""
# pylint: disable=missing-function-docstring,protected-access,line-too-long
# line-too-long allowed: test fixtures embed verbatim SES
# linker_section_placements_segments attribute values, which are realistically
# long and lose clarity when wrapped.

import shutil
import tempfile
import unittest
from pathlib import Path

from membrowse.linker.base import LinkerFormatDetector
from membrowse.linker.emproject_parser import SEGGEREmProjectParser
from membrowse.linker.parser import LinkerScriptError, LinkerScriptParser


_MINIMAL_EMPROJECT = """\
<!DOCTYPE CrossStudio_Project_File>
<solution Name="App" target="8" version="2">
  <project Name="App">
    <configuration
      Name="Common"
      Target="STM32H743ZI"
      arm_architecture="v7EM"
      linker_section_placements_segments="FLASH1 RX 0x08000000 0x00100000;RAM1 RWX 0x24000000 0x00080000;"
      project_type="Executable" />
  </project>
</solution>
"""


_EMPROJECT_MULTI_SEGMENT = """\
<!DOCTYPE CrossStudio_Project_File>
<solution Name="App">
  <project Name="App">
    <configuration
      Name="Common"
      linker_section_placements_segments="FLASH1 RX 0x08000000 0x00100000;FLASH2 RX 0x90000000 0x10000000;RAM1 RWX 0x24000000 0x00080000;" />
  </project>
</solution>
"""


class _EmProjectTestBase(unittest.TestCase):
    """Shared setup for tests that need temp .emProject files."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_emproject(self, content, filename="App.emProject"):
        path = self.temp_dir / filename
        path.write_text(content, encoding='utf-8')
        return str(path)


class TestEmProjectFormatDetection(unittest.TestCase):
    """Content-based detection of .emProject XML."""

    def test_detects_doctype(self):
        self.assertTrue(LinkerFormatDetector.is_emproject(_MINIMAL_EMPROJECT))

    def test_detects_solution_root_without_doctype(self):
        content = '<solution Name="App"><project Name="App" /></solution>'
        self.assertTrue(LinkerFormatDetector.is_emproject(content))

    def test_rejects_icf_content(self):
        icf = (
            "define memory mem with size = 4G;\n"
            "define region FLASH = mem:[from 0x0 size 1M];\n"
        )
        self.assertFalse(LinkerFormatDetector.is_emproject(icf))

    def test_rejects_gnu_ld_content(self):
        gnu = "MEMORY { FLASH (rx) : ORIGIN = 0x0, LENGTH = 1M }"
        self.assertFalse(LinkerFormatDetector.is_emproject(gnu))

    def test_emproject_not_misclassified_as_icf(self):
        # .emProject XML may contain ICF-keyword substrings in attribute values
        # (e.g. inside linker_section_placements_macros). Detection must not
        # route them to the ICF parser.
        self.assertFalse(LinkerFormatDetector.is_icf(_MINIMAL_EMPROJECT))


class TestEmProjectParserDirect(_EmProjectTestBase):
    """Tests calling SEGGEREmProjectParser.parse() directly."""

    def test_minimal_two_regions(self):
        path = self._write_emproject(_MINIMAL_EMPROJECT)
        regions = SEGGEREmProjectParser().parse(path)

        self.assertEqual(set(regions), {"FLASH1", "RAM1"})

        flash = regions["FLASH1"]
        self.assertEqual(flash.address, 0x08000000)
        self.assertEqual(flash.limit_size, 0x00100000)
        self.assertEqual(flash.end_address, 0x080FFFFF)
        self.assertEqual(flash.attributes, "rx")

        ram = regions["RAM1"]
        self.assertEqual(ram.address, 0x24000000)
        self.assertEqual(ram.limit_size, 0x00080000)
        self.assertEqual(ram.attributes, "rwx")

    def test_multi_segment_order_preserved(self):
        path = self._write_emproject(_EMPROJECT_MULTI_SEGMENT)
        regions = SEGGEREmProjectParser().parse(path)

        self.assertEqual(
            list(regions.keys()), ["FLASH1", "FLASH2", "RAM1"]
        )
        self.assertEqual(regions["FLASH2"].address, 0x90000000)
        self.assertEqual(regions["FLASH2"].limit_size, 0x10000000)

    def test_decimal_addresses(self):
        content = _MINIMAL_EMPROJECT.replace(
            'linker_section_placements_segments="FLASH1 RX 0x08000000 0x00100000;RAM1 RWX 0x24000000 0x00080000;"',
            'linker_section_placements_segments="FLASH1 RX 134217728 1048576;RAM1 RWX 603979776 524288"',
        )
        path = self._write_emproject(content)
        regions = SEGGEREmProjectParser().parse(path)
        self.assertEqual(regions["FLASH1"].address, 0x08000000)
        self.assertEqual(regions["FLASH1"].limit_size, 0x00100000)
        self.assertEqual(regions["RAM1"].address, 0x24000000)
        self.assertEqual(regions["RAM1"].limit_size, 0x00080000)

    def test_segments_on_non_common_configuration(self):
        # When only a non-Common configuration carries the attribute the
        # parser still finds it (first-match wins via .iter()).
        content = """\
<!DOCTYPE CrossStudio_Project_File>
<solution Name="App">
  <configuration Name="Debug" gcc_debugging_level="Level 3" />
  <project Name="App">
    <configuration
      Name="Release"
      linker_section_placements_segments="FLASH1 RX 0x08000000 0x100000" />
  </project>
</solution>
"""
        path = self._write_emproject(content)
        regions = SEGGEREmProjectParser().parse(path)
        self.assertEqual(set(regions), {"FLASH1"})

    def test_malformed_xml_raises(self):
        path = self._write_emproject("<solution>not closed")
        with self.assertRaises(LinkerScriptError) as ctx:
            SEGGEREmProjectParser().parse(path)
        self.assertIn("malformed", str(ctx.exception).lower())

    def test_missing_segments_attribute_raises(self):
        content = """\
<!DOCTYPE CrossStudio_Project_File>
<solution Name="App">
  <project Name="App">
    <configuration Name="Common" Target="STM32H743ZI" />
  </project>
</solution>
"""
        path = self._write_emproject(content)
        with self.assertRaises(LinkerScriptError) as ctx:
            SEGGEREmProjectParser().parse(path)
        self.assertIn(
            "linker_section_placements_segments", str(ctx.exception)
        )

    def test_malformed_segment_skipped_other_kept(self):
        content = _MINIMAL_EMPROJECT.replace(
            'linker_section_placements_segments="FLASH1 RX 0x08000000 0x00100000;RAM1 RWX 0x24000000 0x00080000;"',
            'linker_section_placements_segments="FLASH1 RX 0x08000000 0x00100000;BAD_ONLY_TWO_FIELDS;RAM1 RWX 0x24000000 0x00080000"',
        )
        path = self._write_emproject(content)
        regions = SEGGEREmProjectParser().parse(path)
        # Malformed segment dropped; valid ones survive.
        self.assertEqual(set(regions), {"FLASH1", "RAM1"})

    def test_all_segments_malformed_raises(self):
        content = _MINIMAL_EMPROJECT.replace(
            'linker_section_placements_segments="FLASH1 RX 0x08000000 0x00100000;RAM1 RWX 0x24000000 0x00080000;"',
            'linker_section_placements_segments="JUST_GARBAGE;ALSO_GARBAGE"',
        )
        path = self._write_emproject(content)
        with self.assertRaises(LinkerScriptError) as ctx:
            SEGGEREmProjectParser().parse(path)
        self.assertIn("no valid memory regions", str(ctx.exception))

    def test_non_positive_size_skipped(self):
        content = _MINIMAL_EMPROJECT.replace(
            'linker_section_placements_segments="FLASH1 RX 0x08000000 0x00100000;RAM1 RWX 0x24000000 0x00080000;"',
            'linker_section_placements_segments="FLASH1 RX 0x08000000 0;RAM1 RWX 0x24000000 0x00080000"',
        )
        path = self._write_emproject(content)
        regions = SEGGEREmProjectParser().parse(path)
        self.assertEqual(set(regions), {"RAM1"})


class TestEmProjectThroughOrchestrator(_EmProjectTestBase):
    """Integration: LinkerScriptParser dispatches .emProject to the new parser."""

    def test_orchestrator_dispatches_to_emproject_parser(self):
        path = self._write_emproject(_EMPROJECT_MULTI_SEGMENT)
        parser = LinkerScriptParser(ld_scripts=[path])
        regions = parser.parse_memory_regions()

        self.assertEqual(set(regions), {"FLASH1", "FLASH2", "RAM1"})
        self.assertEqual(regions["FLASH1"]["address"], 0x08000000)
        self.assertEqual(regions["FLASH1"]["limit_size"], 0x00100000)
        self.assertEqual(regions["FLASH1"]["end_address"], 0x080FFFFF)
        self.assertEqual(regions["RAM1"]["address"], 0x24000000)


# ---------------------------------------------------------------------------
# Mixed .emProject + .icf scenarios
# ---------------------------------------------------------------------------

# Minimal SEGGER-style ICF that references regions defined externally
# (in the .emProject) and adds two of its own aliases.
_ICF_REFERENCING_EMPROJECT = """\
define memory with size = 4G;

// FLASH/RAM are aliases of FLASH1/RAM1 (which come from the .emProject)
define region FLASH = FLASH1;
define region RAM   = RAM1;

place at start of FLASH { block vectors };
place in RAM            { block heap };
"""

# ICF that defines a brand-new region not present in the .emProject, plus a
# reference to an external region. Used to test that cross-file references
# resolve AND that locally-defined unique regions are still emitted.
_ICF_WITH_LOCAL_AND_REFERENCE = """\
define memory with size = 4G;

define region FLASH       = FLASH1;
define region BOOTLOADER  = [from 0x08000000 size 0x00010000];
"""


class TestMixedEmProjectAndICF(_EmProjectTestBase):
    """Combined .emProject + .icf orchestrated by LinkerScriptParser."""

    def _write_icf(self, content, name="App.icf"):
        path = self.temp_dir / name
        path.write_text(content, encoding='utf-8')
        return str(path)

    def test_emproject_then_icf_resolves_aliases(self):
        emp = self._write_emproject(_MINIMAL_EMPROJECT)
        icf = self._write_icf(_ICF_REFERENCING_EMPROJECT)

        parser = LinkerScriptParser(ld_scripts=[emp, icf])
        regions = parser.parse_memory_regions()

        # FLASH1/RAM1 from the .emProject, alias rows FLASH/RAM suppressed
        # because they collapse to the same (address, limit_size).
        self.assertEqual(set(regions), {"FLASH1", "RAM1"})

    def test_icf_then_emproject_still_works(self):
        # Argument order should not matter: orchestrator parses non-ICF
        # files first regardless of CLI order.
        emp = self._write_emproject(_MINIMAL_EMPROJECT)
        icf = self._write_icf(_ICF_REFERENCING_EMPROJECT)

        parser = LinkerScriptParser(ld_scripts=[icf, emp])
        regions = parser.parse_memory_regions()

        self.assertEqual(set(regions), {"FLASH1", "RAM1"})

    def test_local_icf_region_distinct_from_external_is_emitted(self):
        emp = self._write_emproject(_MINIMAL_EMPROJECT)
        icf = self._write_icf(_ICF_WITH_LOCAL_AND_REFERENCE)

        parser = LinkerScriptParser(ld_scripts=[emp, icf])
        regions = parser.parse_memory_regions()

        # FLASH alias is suppressed (matches FLASH1's range), BOOTLOADER
        # is unique so it stays.
        self.assertEqual(set(regions), {"FLASH1", "RAM1", "BOOTLOADER"})
        self.assertEqual(regions["BOOTLOADER"]["address"], 0x08000000)
        self.assertEqual(regions["BOOTLOADER"]["limit_size"], 0x10000)

    def test_icf_alone_still_errors_when_externals_missing(self):
        # Without the .emProject, the .icf cannot resolve FLASH1/RAM1 and
        # the parser should report failure as before.
        icf = self._write_icf(_ICF_REFERENCING_EMPROJECT)
        parser = LinkerScriptParser(ld_scripts=[icf])
        with self.assertRaises(LinkerScriptError) as ctx:
            parser.parse_memory_regions()
        self.assertIn("could not resolve", str(ctx.exception))

    def test_local_icf_definition_overrides_external_with_same_name(self):
        # An .icf may locally redefine a region whose name also appears in
        # the .emProject (different range). The local definition wins —
        # the external must NOT silently shadow it.
        emp = self._write_emproject(_MINIMAL_EMPROJECT)  # FLASH1 @ 0x08000000 / 0x100000
        icf_override = (
            "define memory with size = 4G;\n"
            # Local FLASH1 with a different address and smaller size:
            "define region FLASH1 = [from 0x10000000 size 0x00010000];\n"
        )
        icf = self._write_icf(icf_override)

        parser = LinkerScriptParser(ld_scripts=[emp, icf])
        regions = parser.parse_memory_regions()

        # FLASH1 must reflect the .icf's local range, not the .emProject's.
        self.assertEqual(regions["FLASH1"]["address"], 0x10000000)
        self.assertEqual(regions["FLASH1"]["limit_size"], 0x00010000)
        # RAM1 from the .emProject is unaffected.
        self.assertEqual(regions["RAM1"]["address"], 0x24000000)
        self.assertEqual(regions["RAM1"]["limit_size"], 0x00080000)


if __name__ == "__main__":
    unittest.main()
