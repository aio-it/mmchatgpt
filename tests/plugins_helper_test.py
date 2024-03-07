import pytest
from unittest.mock import patch, Mock
from plugins import helper


@pytest.fixture
def helper_instance():
    mock_driver = Mock()
    return helper.Helper(mock_driver)


def test_strip_self_username(helper_instance):
    helper_instance.driver.client.username = "testuser"
    message = "@testuser Hello, world!"
    expected = "Hello, world!"
    result = helper_instance.strip_self_username(message)
    assert result == expected


@pytest.mark.parametrize(
    "input, expected_result, validate_type",
    [
        ("example.com", True, "domain"),
        ("1.1.1.1", True, "ip"),
        ("AS12345", True, "asn"),
        ("as12", True, "asn"),
        ("https://example.com", True, "url"),
        (
            "https://localhost/",
            {"error": "invalid input: https://localhost/ (no matches) for types url"},
            "url",
        ),
        ("2001:0db8:85a3:0000:0000:8a2e:0370:7334", {"error": "private ip"}, "ipv6"),
        ("10.0.0.1", {"error": "private ip"}, "ipv4"),
        ("abc", True, "string"),
        ("80", True, "port"),
        ("65535", True, "port"),
        (
            "65536",
            {"error": "port can not be higher than 65535"},
            "port",
        ),
    ],
)
@patch("requests.head")
def test_validate_input(
    mock_requests_head, helper_instance, input, expected_result, validate_type
):
    mock_requests_head.return_value.status_code = 200
    valid_types = [
        "domain",
        "ip",
        "ipv4",
        "ipv6",
        "url",
        "asn",
        "string",
        "argument",
        "port",
    ]
    result = helper_instance.validate_input(input, types=[validate_type])
    assert result == expected_result
