from setuptools import setup, find_packages

setup(
    name="membrowse",
    version="2.0.0",
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
    install_requires=[
        "pyelftools>=0.29",
        "requests>=2.25.0",
    ],
    python_requires=">=3.7",
    author="MemBrowse",
    description="Memory footprint analysis tools for embedded firmware",
)