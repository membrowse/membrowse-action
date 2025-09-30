#!/usr/bin/env python3
"""
API client for MemBrowse platform.

This package provides functionality for uploading memory reports
to the MemBrowse SaaS platform.
"""

from .client import MemBrowseUploader

__all__ = ['MemBrowseUploader']