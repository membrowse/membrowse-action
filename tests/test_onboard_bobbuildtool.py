"""Integration test for membrowse onboard with bobbuildtool as meta build system.

Creates a temporary git repo with 5 commits, each modifying firmware source
to change memory usage, then runs membrowse onboard on the last 4 commits
with --dry-run to verify the full workflow without uploading.

- Linux: uses gcc with a sandbox recipe
- Windows: uses arm-none-eabi-gcc without sandbox

Requires bobbuildtool (pip install bobbuildtool) and a C compiler to be installed.
"""

import argparse
import logging
import os
import platform
import re
import subprocess
import shutil

import pytest

from membrowse.commands.onboard import run_onboard

IS_WINDOWS = platform.system() == 'Windows'

# Determine which compiler is available
_GCC = shutil.which('gcc')
_ARM_GCC = shutil.which('arm-none-eabi-gcc')

# Skip entire module if bob or a suitable compiler is not available
pytestmark = [
    pytest.mark.skipif(
        _GCC is None and _ARM_GCC is None,
        reason='no C compiler found (gcc or arm-none-eabi-gcc)',
    ),
    pytest.mark.skipif(
        shutil.which('bob') is None,
        reason='bobbuildtool (bob) not found on PATH',
    ),
]

# Pick compiler: prefer arm-none-eabi-gcc on Windows, gcc on Linux
CC = 'arm-none-eabi-gcc' if (IS_WINDOWS or not _GCC) else 'gcc'


def _git(repo_dir, *args, **kwargs):
    """Run a git command in the given repo directory."""
    result = subprocess.run(
        ['git'] + list(args),
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=False,
        **kwargs,
    )
    assert result.returncode == 0, (
        f"git {' '.join(args)} failed: {result.stderr}"
    )
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# Firmware source templates – each commit adds more data to change memory
# ---------------------------------------------------------------------------

LINKER_SCRIPT = """\
MEMORY
{
    FLASH (rx)  : ORIGIN = 0x08000000, LENGTH = 256K
    RAM (rwx)   : ORIGIN = 0x20000000, LENGTH = 64K
}

_Min_Heap_Size = 0x1000;
_Min_Stack_Size = 0x800;

ENTRY(main)

SECTIONS
{
    .text :
    {
        . = ALIGN(4);
        *(.text)
        *(.text*)
        . = ALIGN(4);
        _etext = .;
    } >FLASH

    .rodata :
    {
        . = ALIGN(4);
        *(.rodata)
        *(.rodata*)
        . = ALIGN(4);
    } >FLASH

    .data :
    {
        . = ALIGN(4);
        _sdata = .;
        *(.data)
        *(.data*)
        . = ALIGN(4);
        _edata = .;
    } >RAM AT> FLASH

    _sidata = LOADADDR(.data);

    .bss :
    {
        . = ALIGN(4);
        _sbss = .;
        *(.bss)
        *(.bss*)
        *(COMMON)
        . = ALIGN(4);
        _ebss = .;
    } >RAM

    ._user_heap_stack :
    {
        . = ALIGN(8);
        . = . + _Min_Heap_Size;
        . = . + _Min_Stack_Size;
        . = ALIGN(8);
    } >RAM
}
"""

BOB_CONFIG = """\
bobMinimumVersion: "0.25"
"""

BOB_SANDBOX_RECIPE = """\
provideSandbox:
    paths: ["/"]
    mount:
        - "/bin"
        - "/usr"
        - "/lib"
        - "/etc"
        - "/tmp"

packageScript: |
    mkdir -p bin usr lib etc tmp
    test -d /lib64 && mkdir -p lib64
    test -d /sbin && mkdir -p sbin
"""

# Recipe templates — compiler and sandbox dependency are filled in at runtime
BOB_FIRMWARE_RECIPE_LINUX = """\
root: True

depends:
    - sandbox

checkoutSCM:
    scm: import
    url: src

buildScript: |
    {cc} -g -nostdlib -static -T $1/linker.ld -o firmware.elf $1/firmware.c

packageScript: |
    cp $1/firmware.elf .
"""

BOB_FIRMWARE_RECIPE_WINDOWS = """\
root: True

checkoutSCM:
    scm: import
    url: src

buildScript: |
    {cc} -g -nostdlib -static -T $1/linker.ld -o firmware.elf $1/firmware.c

packageScript: |
    cp $1/firmware.elf .
"""


def _firmware_source(commit_index):
    """Generate firmware C source that varies with commit_index.

    Each successive commit adds more global data so the memory footprint
    grows, making the reports distinguishable.
    """
    extra_arrays = "\n".join(
        f"volatile uint8_t extra_buf_{i}[64];"
        for i in range(commit_index)
    )
    return f"""\
#include <stdint.h>

volatile uint32_t counter = 0x{commit_index:08x};
const uint32_t magic = 0xDEADBEEF;

{extra_arrays}

int main(void) {{
    while (1) {{
        counter++;
    }}
    return 0;
}}
"""


BOB_BUILD_CMD = "bob dev firmware --destination build"


@pytest.fixture()
def bob_repo(tmp_path):
    """Create a temporary git repo with bobbuildtool project and 5 commits."""
    repo = tmp_path / "bob_project"
    repo.mkdir()
    (repo / "build").mkdir()
    (repo / "recipes").mkdir()
    (repo / "src").mkdir()

    # Initialise git repo
    _git(repo, 'init')
    _git(repo, 'config', 'user.email', 'test@test.com')
    _git(repo, 'config', 'user.name', 'Test')

    # Write bob project files (stay constant across commits)
    (repo / "config.yaml").write_text(BOB_CONFIG)

    if IS_WINDOWS:
        firmware_recipe = BOB_FIRMWARE_RECIPE_WINDOWS.format(cc=CC)
    else:
        firmware_recipe = BOB_FIRMWARE_RECIPE_LINUX.format(cc=CC)
        (repo / "recipes" / "sandbox.yaml").write_text(BOB_SANDBOX_RECIPE)

    (repo / "recipes" / "firmware.yaml").write_text(firmware_recipe)

    # Write linker script into src/ (where bob imports from)
    (repo / "src" / "linker.ld").write_text(LINKER_SCRIPT)

    # Create 5 commits, each increasing memory usage
    commits = []
    for i in range(5):
        (repo / "src" / "firmware.c").write_text(_firmware_source(i))
        _git(repo, 'add', '-A')
        _git(repo, 'commit', '-m', f'commit {i}: add extra_buf up to index {i}')
        sha = _git(repo, 'rev-parse', 'HEAD')
        commits.append(sha)

    return repo, commits


class TestOnboardBobbuildtool:  # pylint: disable=too-few-public-methods
    """End-to-end onboard test using actual bobbuildtool as meta build system."""

    def test_dry_run_four_commits(self, bob_repo, caplog):  # pylint: disable=too-many-locals,redefined-outer-name
        """Run onboard on the last 4 commits with --dry-run.

        Verifies that:
        - The onboard command completes successfully (exit code 0)
        - All 4 commits are processed (checkout, bob build, analyse)
        - No uploads are attempted (dry-run mode)
        - Memory usage grows across commits (each adds a 64-byte buffer)
        """
        repo, commits = bob_repo
        original_cwd = os.getcwd()

        try:
            os.chdir(repo)

            args = argparse.Namespace(
                num_commits=4,
                build_script=BOB_BUILD_CMD,
                elf_path='build/firmware.elf',
                target_name='stm32f4',
                api_key='fake-key',
                api_url='https://api.membrowse.com',
                api_url_flag=None,
                ld_scripts='src/linker.ld',
                linker_defs=None,
                build_dirs=None,
                initial_commit=None,
                binary_search=False,
                dry_run=True,
                commits=None,
                initial_parent=None,
                skip_line_program=False,
            )

            with caplog.at_level(logging.INFO, logger='membrowse.commands.onboard'):
                exit_code = run_onboard(args)

            assert exit_code == 0, "onboard --dry-run should succeed"

            # Verify all 4 commits were processed via dry-run log messages
            dry_run_messages = [
                msg for msg in caplog.messages if '[DRY-RUN]' in msg
            ]
            assert len(dry_run_messages) == 4, (
                f"Expected 4 dry-run messages, got {len(dry_run_messages)}: {dry_run_messages}"
            )

            # All dry-run messages should report status=ok (successful builds)
            for msg in dry_run_messages:
                assert 'status=ok' in msg, f"Expected status=ok in: {msg}"

            # Verify each dry-run message references one of the last 4 commits
            last_four = commits[1:]  # commits 1-4 (onboard processes last N)
            for commit in last_four:
                matching = [m for m in dry_run_messages if commit in m]
                assert len(matching) == 1, (
                    f"Expected exactly one dry-run message for commit {commit[:8]}"
                )

            # Verify memory usage grows across commits by extracting RAM used_size
            # Each commit adds an extra 64-byte buffer in RAM (.bss)
            ram_sizes = []
            for msg in dry_run_messages:
                match = re.search(r'RAM: (\d+)', msg)
                assert match, f"Expected RAM size in dry-run message: {msg}"
                ram_sizes.append(int(match.group(1)))

            for i in range(1, len(ram_sizes)):
                assert ram_sizes[i] > ram_sizes[i - 1], (
                    f"RAM usage should grow: commit {i} ({ram_sizes[i]}) "
                    f"<= commit {i-1} ({ram_sizes[i-1]})"
                )

            # Verify the summary log reports 4 commits processed
            summary_messages = [
                msg for msg in caplog.messages if 'Processed' in msg
            ]
            assert any('4 commits' in msg for msg in summary_messages), (
                f"Expected summary with '4 commits': {summary_messages}"
            )

        finally:
            os.chdir(original_cwd)
