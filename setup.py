from setuptools import setup, find_packages
from pathlib import Path

# Read the long description from README
this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text(encoding="utf-8")

setup(
    name="membrowse",
    version="1.0.1",
    packages=find_packages(),

    # Main CLI tool installed as a script
    scripts=[
        "scripts/membrowse",
    ],

    # Also provide Python entry point
    entry_points={
        'console_scripts': [
            'membrowse=membrowse.cli:main',
        ],
    },

    # Dependencies
    install_requires=[
        "pyelftools>=0.29",
        "requests>=2.25.0",
        "cxxfilt>=0.3.0",
    ],
    python_requires=">=3.7",

    # Metadata
    author="MemBrowse",
    author_email="support@membrowse.com",
    description="Memory footprint analysis tools for embedded firmware",
    long_description=long_description,
    long_description_content_type="text/markdown",
    license="GPL-3.0-or-later",
    keywords="embedded firmware memory analysis elf linker dwarf footprint stm32 esp32 arm risc-v",
    url="https://membrowse.com",
    project_urls={
        "Homepage": "https://membrowse.com",
        "Documentation": "https://github.com/membrowse/membrowse-action#readme",
        "Source": "https://github.com/membrowse/membrowse-action",
        "Issues": "https://github.com/membrowse/membrowse-action/issues",
        "Changelog": "https://github.com/membrowse/membrowse-action/blob/main/CHANGELOG.md",
    },

    # PyPI classifiers
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Build Tools",
        "Topic :: Software Development :: Embedded Systems",
        "Topic :: System :: Hardware",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Operating System :: OS Independent",
        "Environment :: Console",
    ],

    # Package data
    include_package_data=True,
    zip_safe=False,
)
