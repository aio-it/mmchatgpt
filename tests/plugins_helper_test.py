""" Tests for the helper plugin """

from unittest.mock import Mock, patch

import pytest

from plugins import helper


@pytest.fixture
def helper_instance():
    """helper instance fixture"""
    mock_driver = Mock()
    return helper.Helper(mock_driver)

# pylint: disable=redefined-outer-name
def test_strip_self_username(helper_instance):
    """Test strip_self_username"""
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
    mock_requests_head, helper_instance, input_val, expected_result, validate_type
):
    """Test validate_input"""
    mock_requests_head.return_value.status_code = 200

    result = helper_instance.validate_input(input_val, types=[validate_type])
    assert result == expected_result


def test_urlencode_text(helper_instance):
    """Test urlencode_text"""
    text = "Hello, world!"
    expected = "Hello%2C+world%21"
    result = helper_instance.urlencode_text(text)
    assert result == expected


def test_valkey_serialize_json(helper_instance):
    """Test valkey_serialize_json"""
    data = {"key": "value"}
    expected = '{"key": "value"}'
    result = helper_instance.valkey_serialize_json(data)
    assert result == expected


def test_valkey_deserialize_json(helper_instance):
    """Test valkey_deserialize_json"""
    data = '{"key": "value"}'
    expected = {"key": "value"}
    result = helper_instance.valkey_deserialize_json(data)
    assert result == expected


def test_create_tmp_filename(helper_instance):
    """Test create_tmp_filename"""
    extension = "png"
    begin = "/tmp/"
    end = f".{extension}"
    result = helper_instance.create_tmp_filename(extension)
    # the result should start with /tmp/ and end with .png
    assert result.startswith(begin) and result.endswith(end)
