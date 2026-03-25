"""Test helper functions for common test operations."""

import platform
import shutil
import subprocess
import time
from typing import List


def run_compilation(compile_cmd: List[str], success_msg: str = "Compilation successful") -> None:
    """
    Run a compilation command and handle errors.

    Args:
        compile_cmd: List of command arguments to pass to subprocess.run
        success_msg: Message to print on successful compilation

    Raises:
        subprocess.CalledProcessError: If compilation fails
    """
    result = subprocess.run(
        compile_cmd,
        capture_output=True,
        text=True,
        check=True
    )
    print(success_msg)
    if result.stderr:
        print(f"Compiler warnings: {result.stderr}")


def can_compile_embedded(compiler_cmd: str) -> bool:
    """
    Check if the compiler can handle embedded linker scripts with ARM addresses.

    On Windows, native MinGW gcc produces PE/COFF executables that cannot handle
    embedded memory addresses (e.g., 0x08000000). Only cross-compilers like
    arm-none-eabi-gcc can do this.

    Args:
        compiler_cmd: The compiler command name (e.g., 'gcc', 'arm-none-eabi-gcc')

    Returns:
        True if the compiler can handle embedded linker scripts
    """
    if compiler_cmd and compiler_cmd.startswith(('arm-none-eabi-', 'arm-linux-')):
        return True
    if platform.system() == 'Windows':
        return False
    return True


def rmtree_robust(path) -> None:
    """
    Remove a directory tree with retry logic for Windows file locking.

    On Windows, compiled executables may still be locked briefly after use.
    This retries removal a few times before giving up silently.

    Args:
        path: Path to directory to remove
    """
    for attempt in range(3):
        try:
            shutil.rmtree(path)
            return
        except PermissionError:
            if attempt < 2:
                time.sleep(0.5)
            else:
                print(f"Warning: could not fully clean up {path}")
