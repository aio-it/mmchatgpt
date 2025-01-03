""" Tests for the helper plugin """

from unittest.mock import Mock, patch
import pytest
import pytest_asyncio
import urllib3
import certifi

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
    "input_val, expected_result, validate_type",
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


@pytest.mark.parametrize(
    "content_type,expected_type,expected_ext,test_description",
    [
        # HTML types
        ("text/html", "html", "txt", "basic HTML"),
        ("text/html;charset=utf-8", "html", "txt", "HTML with charset"),
        
        # Text types
        ("text/plain", "text", "txt", "plain text"),
        ("application/json", "text", "json", "JSON content"),
        ("application/xml", "text", "xml", "XML content"),
        
        # Image types
        ("image/jpeg", "image", "jpg", "JPEG image"),
        ("image/png", "image", "png", "PNG image"),
        ("image/gif", "image", "gif", "GIF image"),
        ("image/svg+xml", "image", "svg", "SVG image"),
        
        # Document types
        ("application/pdf", "documents", "pdf", "PDF document"),
        ("application/msword", "documents", "doc", "Word document"),
        
        # Audio/Video types
        ("audio/mpeg", "audio", "mp3", "MP3 audio"),
        ("video/mp4", "video", "mp4", "MP4 video"),
        
        # Edge cases
        ("invalid/type", "unknown", "unknown", "invalid content type"),
        ("", "unknown", "unknown", "empty content type"),
        ("text/html;charset=UTF-8", "html", "txt", "HTML with charset case insensitive"),
    ]
)
@patch('mimetypes.guess_extension')  # Add mock for mimetypes
def test_get_content_type_and_ext(mock_guess_extension, helper_instance, content_type, expected_type, expected_ext, test_description):
    """Test get_content_type_and_ext method with various content types"""
    # Configure mock to return appropriate extensions
    def mock_guess_ext(mime_type, strict=False):
        ext_map = {
            'text/plain': '.txt',
            'application/json': '.json',
            'application/xml': '.xml',
            'image/jpeg': '.jpg',
            'image/png': '.png',
            'image/gif': '.gif',
            'image/svg+xml': '.svg',
            'application/pdf': '.pdf',
            'application/msword': '.doc',
            'audio/mpeg': '.mp3',
            'video/mp4': '.mp4',
        }
        return ext_map.get(mime_type, None)
    
    mock_guess_extension.side_effect = mock_guess_ext
    
    content_group, ext = helper_instance.get_content_type_and_ext(content_type)
    assert content_group == expected_type, f"Failed: {test_description} - got {content_group} expected {expected_type}"
    assert ext == expected_ext, f"Failed: {test_description} - got {ext} expected {expected_ext}"


@pytest.mark.asyncio
@patch("requests.get")
async def test_download_webpage(mock_get, helper_instance):
    """Test download_webpage"""
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    url = "https://example.com"
    content = "<html><head><title>Example Domain</title></head><body><h1>Example Domain</h1></body></html>"
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.headers = {"Content-Type": "text/html"}
    mock_response.iter_content = Mock(return_value=[content.encode("utf-8")])
    mock_get.return_value = mock_response

    with patch("requests.get", return_value=mock_response):
        result, filename = await helper_instance.download_webpage(url)
    
    expected_result = "links:|title:Example Domain|body:Example Domain"
    assert result == expected_result
    assert filename is not None
    assert filename.startswith("/tmp/")
    assert filename.endswith(".txt")
