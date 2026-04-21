#!/usr/bin/env python3
"""
Tests for fallback behaviors in ``membrowse.commands.report``:

1. Preference for a preprocessed ``<script>.tmp`` sibling over the raw
   linker script (used by build systems that run the C preprocessor on
   their linker scripts, e.g. NuttX).
2. Fallback to default Code/Data regions when linker scripts parse
   successfully but yield no memory regions (e.g. a ``SECTIONS``-only
   script with no ``MEMORY`` block). Without this fallback the platform
   rejects the upload with ``memory_layout is required``.
"""

import os
import tempfile
import unittest
from pathlib import Path

# pylint: disable=wrong-import-position
from membrowse.commands.report import (
    _parse_linker_scripts_if_provided,
    generate_report,
)


TEST_ELF = Path(__file__).parent / "test-sleep.elf"


VALID_MEMORY_LD = """
MEMORY
{
    LD_FLASH (rx) : ORIGIN = 0x08000000, LENGTH = 256K
}
"""

VALID_MEMORY_TMP = """
MEMORY
{
    TMP_FLASH (rx) : ORIGIN = 0x08000000, LENGTH = 256K
}
"""

BROKEN_LD = "THIS IS NOT A VALID LINKER SCRIPT {{{"

SECTIONS_ONLY_LD = """
SECTIONS
{
    .text : { *(.text) }
    .data : { *(.data) }
}
"""


def _require_elf():
    if not TEST_ELF.exists():
        raise unittest.SkipTest(f"Test ELF not found: {TEST_ELF}")


class TestPreprocessedLinkerScriptPreference(unittest.TestCase):
    """Verify that ``<script>.tmp`` is preferred over ``<script>`` when present."""

    @classmethod
    def setUpClass(cls):
        _require_elf()

    def test_prefers_tmp_when_both_exist(self):
        """When foo.ld.tmp exists, it is parsed instead of foo.ld."""
        with tempfile.TemporaryDirectory() as td:
            ld_path = os.path.join(td, "foo.ld")
            tmp_path = ld_path + ".tmp"
            # Intentionally write different MEMORY blocks so we can tell
            # which file was actually parsed.
            with open(ld_path, "w", encoding="utf-8") as f:
                f.write(VALID_MEMORY_LD)
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(VALID_MEMORY_TMP)

            regions = _parse_linker_scripts_if_provided(
                ld_path, str(TEST_ELF), None
            )

            self.assertIsNotNone(regions)
            self.assertIn("TMP_FLASH", regions)
            self.assertNotIn("LD_FLASH", regions)

    def test_uses_raw_ld_when_no_tmp_sibling(self):
        """When only foo.ld exists, it is parsed as-is."""
        with tempfile.TemporaryDirectory() as td:
            ld_path = os.path.join(td, "foo.ld")
            with open(ld_path, "w", encoding="utf-8") as f:
                f.write(VALID_MEMORY_LD)

            regions = _parse_linker_scripts_if_provided(
                ld_path, str(TEST_ELF), None
            )

            self.assertIsNotNone(regions)
            self.assertIn("LD_FLASH", regions)
            self.assertNotIn("TMP_FLASH", regions)

    def test_tmp_preference_is_per_script(self):
        """Mixed input: one script has a .tmp, another does not."""
        with tempfile.TemporaryDirectory() as td:
            with_tmp = os.path.join(td, "with_tmp.ld")
            with_tmp_sibling = with_tmp + ".tmp"
            without_tmp = os.path.join(td, "plain.ld")

            # with_tmp.ld is unparseable, but its .tmp sibling is valid.
            with open(with_tmp, "w", encoding="utf-8") as f:
                f.write(BROKEN_LD)
            with open(with_tmp_sibling, "w", encoding="utf-8") as f:
                f.write(VALID_MEMORY_TMP)

            # plain.ld has no sibling and must be parsed directly.
            with open(without_tmp, "w", encoding="utf-8") as f:
                f.write(VALID_MEMORY_LD)

            regions = _parse_linker_scripts_if_provided(
                f"{with_tmp} {without_tmp}", str(TEST_ELF), None
            )

            self.assertIsNotNone(regions)
            self.assertIn("TMP_FLASH", regions)
            self.assertIn("LD_FLASH", regions)

    def test_missing_raw_ld_still_raises_even_if_tmp_absent(self):
        """Nonexistent script is reported, not silently skipped."""
        with tempfile.TemporaryDirectory() as td:
            missing = os.path.join(td, "does_not_exist.ld")
            with self.assertRaises(ValueError):
                _parse_linker_scripts_if_provided(
                    missing, str(TEST_ELF), None
                )


class TestEmptyRegionsFallback(unittest.TestCase):
    """Verify fallback to default Code/Data regions when parse yields {}."""

    @classmethod
    def setUpClass(cls):
        _require_elf()

    def test_sections_only_script_falls_back_to_defaults(self):
        """A SECTIONS-only script (no MEMORY block) must not produce an
        empty ``memory_layout`` — the report would otherwise be rejected by
        the upload API."""
        with tempfile.TemporaryDirectory() as td:
            ld_path = os.path.join(td, "sections_only.ld")
            with open(ld_path, "w", encoding="utf-8") as f:
                f.write(SECTIONS_ONLY_LD)

            report = generate_report(
                str(TEST_ELF),
                ld_scripts=ld_path,
                skip_line_program=True,
            )

            layout = report.get("memory_layout")
            self.assertIsInstance(layout, dict)
            self.assertTrue(
                layout,
                "memory_layout must be non-empty when linker script "
                "yields no regions (otherwise upload is rejected)",
            )
            # Default fallback creates 'Code' and/or 'Data' regions.
            self.assertTrue(
                {"Code", "Data"} & set(layout.keys()),
                f"Expected default Code/Data regions, got: {list(layout)}",
            )

    def test_no_linker_script_still_uses_defaults(self):
        """Regression guard: the None path must keep producing defaults."""
        report = generate_report(
            str(TEST_ELF),
            ld_scripts=None,
            skip_line_program=True,
        )
        layout = report.get("memory_layout")
        self.assertIsInstance(layout, dict)
        self.assertTrue(layout)
        self.assertTrue({"Code", "Data"} & set(layout.keys()))


if __name__ == "__main__":
    unittest.main()
