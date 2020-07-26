"""Common functions and fixtures for pysqueezebox tests."""
import asyncio

import pytest


@pytest.fixture(scope="session")
def event_loop():
    """
    Re-scope the event loop to cover this session. Allows to use one aiohttp session
    for all of the tests.
    """
    loop = asyncio.get_event_loop()
    yield loop
    loop.close()


def pytest_addoption(parser):
    """Add the --ip and --port commandline options"""
    parser.addoption(
        "--ip",
        type=str,
        default=None,
        action="store",
        dest="IP",
        help="the IP address for the squeezebox server to be used for the integration tests",
    )

    parser.addoption(
        "--port",
        type=int,
        default=9000,
        action="store",
        dest="PORT",
        help="the port for the squeezebox server to be used for the integration tests",
    )

    parser.addoption(
        "--exclude-player",
        type=str,
        default=None,
        action="store",
        dest="EXCLUDE",
        help="exclude this player from being used in tests",
    )


def pytest_runtest_setup(item):
    """Skip tests marked 'integration' unless an ip address is given."""
    if "integration" in item.keywords and not item.config.getoption("--ip"):
        pytest.skip("use --ip and an ip address to run integration tests.")


def compare_playlists(i, j):
    """Compare two playlists checking only the urls."""
    if len(i) == len(j):
        for idx, val in enumerate(i):
            if j[idx]["url"] != val["url"]:
                return False
        return True
    return False
