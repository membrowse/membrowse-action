from setuptools import setup, find_packages

setup(
    name="membrowse",
    version="1.0.2",
    packages=find_packages(),
    # Scripts will be installed to bin/ and may be wrapped as ELF binaries by setuptools
    # The scripts call each other directly (not via bash) to support both shell and ELF formats
    scripts=[
        "scripts/membrowse_collect_report.sh",
        "scripts/membrowse_report.sh",
        "scripts/membrowse_onboard.sh",
    ],
    install_requires=[
        "pyelftools>=0.29",
        "requests>=2.25.0",
    ],
    python_requires=">=3.7",
    author="MemBrowse",
    description="Memory usage analysis tools for embedded firmware",
)