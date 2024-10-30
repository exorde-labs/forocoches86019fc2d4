from setuptools import find_packages, setup

setup(
    name="forocoches86019fc2d4",
    version="0.0.5",
    packages=find_packages(),
    install_requires=[
        "exorde_data",
        "aiohttp",
        "beautifulsoup4>=4.11"
    ],
    extras_require={"dev": ["pytest", "pytest-cov", "pytest-asyncio"]},
)
