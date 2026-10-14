import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--workbook",
        action="store",
        default=None,
        help="Path to a built workbook, for the LibreOffice recalc oracle.",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "oracle: needs LibreOffice and a built workbook (deselected by default)",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--workbook"):
        return
    skip = pytest.mark.skip(reason="oracle test — pass --workbook to run")
    for item in items:
        if "oracle" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _never_touch_the_live_audit_log(monkeypatch):
    """The suite must never attach mcp_server.audit's file handler.

    On the BI server the live service shares logs/mcp_server/mcp_server.log
    with any other process that calls configure_logging(). A test that drives
    mcp_server.__main__.main() without stubbing it (TestMainBindWiring did,
    from Aug to 14 Oct 2026) attached the real handler inside pytest, and every
    later test that verified a token wrote "auth ok subject=user-larry" — a
    fake identity — into the client's audit trail. So: configure_logging is a
    no-op for every test, under both names it is bound to, and the teardown
    fails the test that re-attaches a file handler by any other route.
    """
    import logging
    from logging.handlers import TimedRotatingFileHandler

    try:
        import mcp_server.__main__ as main_mod
        import mcp_server.audit as audit_mod
    except ImportError:
        # Single-file runs outside the package path (the mcp_server tests put
        # the repo root on sys.path themselves): nothing importable, nothing
        # that could attach the handler — the teardown check still applies.
        main_mod = audit_mod = None
    if audit_mod is not None:
        monkeypatch.setattr(audit_mod, "configure_logging", lambda: None)
        monkeypatch.setattr(main_mod, "configure_logging", lambda: None)
    yield
    base = logging.getLogger("mcp_server")
    leaked = [h for h in base.handlers if isinstance(h, TimedRotatingFileHandler)]
    for h in leaked:  # detach first so one leak cannot cascade into later tests
        base.removeHandler(h)
        h.close()
    assert not leaked, (
        "this test attached the live audit file handler "
        f"({[h.baseFilename for h in leaked]}) — tests must never write to "
        "logs/mcp_server/"
    )
