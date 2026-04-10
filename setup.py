from setuptools import setup, find_packages

setup(
    name="crypto-grid-trader",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "ccxt>=4.2.0",
        "pandas>=2.0.0",
        "numpy>=1.24.0",
        "pydantic>=2.0.0",
        "pydantic-settings>=2.0.0",
        "loguru>=0.7.0",
        "click>=8.1.0",
        "python-dotenv>=1.0.0",
        "aiohttp>=3.9.0",
        "pyarrow>=14.0.0",
        "tabulate>=0.9.0",
    ],
    entry_points={
        "console_scripts": [
            "grid-trader=src.cli.main:cli",
        ],
    },
    python_requires=">=3.9",
)
