from setuptools import setup, find_packages

setup(
    name="membrowse",
    version="1.0.0",
    packages=find_packages(),
    install_requires=[
        "pyelftools>=0.29",
        "requests>=2.25.0",
    ],
    python_requires=">=3.7",
    author="MemBrowse",
    description="Memory usage analysis tools for embedded firmware",
)