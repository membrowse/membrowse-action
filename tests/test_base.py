#!/usr/bin/env python3
"""
Base test utilities for memory report tests
Common functionality shared across test files
"""

import tempfile
import unittest
from pathlib import Path


class BaseTestCase(unittest.TestCase):
    """Base test case with common setup/teardown for file operations"""

    def setUp(self):
        """Set up temporary directory and file list"""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.test_files = []

    def tearDown(self):
        """Clean up test files"""
        for file_path in self.test_files:
            if file_path.exists():
                file_path.unlink()
        if self.temp_dir.exists():
            self.temp_dir.rmdir()

    def create_test_file(self, content: str, filename: str = None) -> Path:
        """Create a temporary test file with given content"""
        if filename is None:
            filename = f"test_{len(self.test_files)}.ld"

        file_path = self.temp_dir / filename
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)

        self.test_files.append(file_path)
        return file_path
