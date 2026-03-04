from unittest.mock import MagicMock, patch
import pytest
import requests

from tracebit.api import TracebitClient, TracebitError


@pytest.fixture
def client():
    return TracebitClient("test-token", base_url="https://example.com")


def mock_response(status_code=200, json_data=None, text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(response=resp)
    return resp


def test_client_sets_auth_header(client):
    assert client.session.headers["Authorization"] == "Bearer test-token"


def test_generate_metadata(client):
    data = {"awsProfileName": "staging", "awsRegion": "us-east-1"}
    with patch.object(client.session, "get", return_value=mock_response(json_data=data)) as m:
        result = client.generate_metadata()
    m.assert_called_once_with("https://example.com/api/v1/credentials/generate-metadata")
    assert result["awsRegion"] == "us-east-1"


def test_issue_credentials_sends_correct_body(client):
    resp_data = {"aws": {"awsAccessKeyId": "KEY", "awsConfirmationId": "abc"}}
    with patch.object(client.session, "post", return_value=mock_response(json_data=resp_data)) as m:
        client.issue_credentials(name="myserver", types=["aws"], labels={"env": "prod"})
    body = m.call_args.kwargs["json"]
    assert body["name"] == "myserver"
    assert body["types"] == ["aws"]
    assert body["source"] == "tracebit-python"
    assert {"name": "env", "value": "prod"} in body["labels"]


def test_issue_credentials_no_labels(client):
    with patch.object(client.session, "post", return_value=mock_response()) as m:
        client.issue_credentials(name="myserver", types=["aws"])
    body = m.call_args.kwargs["json"]
    assert "labels" not in body


def test_confirm_credentials(client):
    with patch.object(client.session, "post", return_value=mock_response(status_code=204)) as m:
        client.confirm_credentials("my-guid")
    body = m.call_args.kwargs["json"]
    assert body["id"] == "my-guid"


def test_confirm_credentials_404_raises(client):
    with patch.object(client.session, "post", return_value=mock_response(status_code=404)):
        with pytest.raises(TracebitError, match="not found"):
            client.confirm_credentials("bad-guid")


def test_remove_credentials(client):
    with patch.object(client.session, "post", return_value=mock_response(status_code=204)) as m:
        client.remove_credentials("myserver", "aws")
    body = m.call_args.kwargs["json"]
    assert body["name"] == "myserver"
    assert body["type"] == "aws"
    m.assert_called_once_with(
        "https://example.com/api/_internal/v1/cli/remove",
        json=body,
    )


def test_401_raises_tracebit_error(client):
    with patch.object(client.session, "get", return_value=mock_response(status_code=401)):
        with pytest.raises(TracebitError, match="Authentication failed"):
            client.generate_metadata()


def test_400_raises_tracebit_error(client):
    with patch.object(client.session, "post",
                      return_value=mock_response(status_code=400, text="bad request")):
        with pytest.raises(TracebitError, match="bad request"):
            client.issue_credentials("x", ["aws"])
