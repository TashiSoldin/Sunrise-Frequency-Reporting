def pytest_addoption(parser):
    parser.addoption(
        "--workbook", action="store", default=None,
        help="Path to a built workbook, for the LibreOffice recalc oracle.",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "oracle: needs LibreOffice and a built workbook (deselected by default)")


def pytest_collection_modifyitems(config, items):
    import pytest
    if config.getoption("--workbook"):
        return
    skip = pytest.mark.skip(reason="oracle test — pass --workbook to run")
    for item in items:
        if "oracle" in item.keywords:
            item.add_marker(skip)
