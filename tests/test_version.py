from importlib.metadata import version

from src.mcp import __version__


def test_package_and_mcp_versions_match() -> None:
    assert __version__ == version("bmtnews")
