# Changelog

All notable changes to MemBrowse will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.0.1] - 2024-10-22

### Added
- Initial PyPI release with core functionality
- PyPI packaging support for easy installation via `pip install membrowse`
- Unified `membrowse` CLI with `report` and `onboard` subcommands
- ELF file analysis with DWARF debug information processing
- Linker script parsing with multi-architecture support
- Memory region extraction and validation
- Symbol-to-source file mapping
- GitHub Actions integration (pr-action and onboard-action)
- Support for ARM, Xtensa (ESP32), RISC-V, and other architectures
- API client for uploading reports to MemBrowse platform
- Comprehensive package metadata in `pyproject.toml`
- Modern Python packaging configuration following PEP 621
- MANIFEST.in for proper source distribution
- PyPI classifiers for better discoverability
- Project URLs (homepage, documentation, issues, changelog)

### Features
- Architecture-agnostic analysis relying on DWARF format
- Intelligent linker script parsing with expression evaluation
- Hierarchical memory region support
- Source file resolution from debug symbols
- Optional `--skip-line-program` flag for faster processing
- Local mode (JSON output) and upload mode (cloud integration)
- Automatic Git metadata detection in GitHub Actions

### Supported Platforms
- STM32 and ARM Cortex-M microcontrollers
- ESP32 and ESP8266 (Xtensa architecture)
- Nordic nRF series
- RISC-V embedded targets
- Any platform using ELF files and GNU LD linker scripts

[0.0.1]: https://github.com/membrowse/membrowse-action/releases/tag/v0.0.1
