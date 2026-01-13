#!/usr/bin/env python3
"""
Test URL utilities.

Tests for membrowse/utils/url.py
"""

import unittest
from membrowse.utils.url import normalize_api_url


class TestNormalizeApiUrl(unittest.TestCase):
    """Test normalize_api_url function."""

    def test_base_url_without_trailing_slash(self):
        """Test that base URL gets /upload appended."""
        result = normalize_api_url('https://api.membrowse.com')
        self.assertEqual(result, 'https://api.membrowse.com/upload')

    def test_base_url_with_trailing_slash(self):
        """Test that base URL with trailing slash gets normalized."""
        result = normalize_api_url('https://api.membrowse.com/')
        self.assertEqual(result, 'https://api.membrowse.com/upload')

    def test_appspot_domain(self):
        """Test with appspot domain."""
        result = normalize_api_url('https://membrowse.appspot.com')
        self.assertEqual(result, 'https://membrowse.appspot.com/upload')

    def test_localhost(self):
        """Test with localhost URL."""
        result = normalize_api_url('http://localhost:8080')
        self.assertEqual(result, 'http://localhost:8080/upload')

    def test_localhost_with_trailing_slash(self):
        """Test localhost with trailing slash."""
        result = normalize_api_url('http://localhost:8080/')
        self.assertEqual(result, 'http://localhost:8080/upload')

    def test_custom_domain(self):
        """Test with custom domain."""
        result = normalize_api_url('https://api.example.com')
        self.assertEqual(result, 'https://api.example.com/upload')

    def test_multiple_trailing_slashes(self):
        """Test URL with multiple trailing slashes."""
        result = normalize_api_url('https://api.membrowse.com///')
        self.assertEqual(result, 'https://api.membrowse.com/upload')

    def test_url_with_port(self):
        """Test URL with custom port."""
        result = normalize_api_url('https://membrowse.com:8443')
        self.assertEqual(result, 'https://membrowse.com:8443/upload')

    def test_url_with_subdirectory(self):
        """Test URL with subdirectory path."""
        result = normalize_api_url('https://example.com/membrowse')
        self.assertEqual(result, 'https://example.com/membrowse/upload')

    def test_url_with_subdirectory_trailing_slash(self):
        """Test URL with subdirectory and trailing slash."""
        result = normalize_api_url('https://example.com/membrowse/')
        self.assertEqual(result, 'https://example.com/membrowse/upload')


if __name__ == '__main__':
    unittest.main()
