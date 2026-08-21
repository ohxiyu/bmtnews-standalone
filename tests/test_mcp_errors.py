from src.mcp.errors import BMTNewsMcpError


def test_bmtnews_mcp_error_string_representation() -> None:
    err = BMTNewsMcpError(code="E_TEST", message="boom", details={"k": "v"})

    assert str(err) == "E_TEST: boom"
    assert err.details == {"k": "v"}
