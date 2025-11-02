"""Test helper functions for common test operations."""

import subprocess
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
