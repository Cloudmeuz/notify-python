import base64
import hashlib
import json

import httpx
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

from cloudme_notify import ConfigurationError, FileTokenStorage, NotifyClient
from cloudme_notify.auth import SignatureSigner

from .conftest import json_response, token_body

SEND_OK = {"success": True, "message_id": "m-1", "status": "queued", "price": "120.00", "currency": "UZS", "balance": "999880.00"}


def test_the_token_request_is_signed_with_the_private_key(make_client, key_pair):
    history = []
    client = make_client([json_response(200, token_body()), json_response(200, SEND_OK)], history)

    client.sms.send(to="998901234567", message="Salom")

    body = json.loads(history[0].content)
    assert history[0].url.path == "/api/v1/oauth/token"
    assert body["client_id"] == "test-client-id"
    assert body["api_key"] == "test-api-key"
    signing_string = "\n".join(["test-client-id", str(body["timestamp"]), body["nonce"], hashlib.sha256(b"test-api-key").hexdigest()])
    key_pair["public_key"].verify(base64.b64decode(body["signature"]), signing_string.encode(), padding.PKCS1v15(), hashes.SHA256())
    assert history[1].headers["Authorization"] == "Bearer access-token-1"


def test_the_cached_token_is_reused_until_it_expires(make_client):
    history = []
    client = make_client([json_response(200, token_body()), json_response(200, SEND_OK), json_response(200, SEND_OK)], history)

    client.sms.send(to="998901234567", message="1")
    client.sms.send(to="998901234567", message="2")

    assert [request.url.path for request in history] == ["/api/v1/oauth/token", "/api/v1/messages/sms", "/api/v1/messages/sms"]


def test_an_expired_access_token_is_refreshed_with_the_refresh_token(make_client):
    history = []
    client = make_client([
        json_response(200, token_body(expires_in=10)),
        json_response(200, SEND_OK),
        json_response(200, token_body(access_token="access-token-2")),
        json_response(200, SEND_OK),
    ], history)

    client.sms.send(to="998901234567", message="1")
    client.sms.send(to="998901234567", message="2")

    assert history[2].url.path == "/api/v1/oauth/refresh"
    assert json.loads(history[2].content) == {"refresh_token": "refresh-token-1"}
    assert history[3].headers["Authorization"] == "Bearer access-token-2"


def test_a_live_401_re_authenticates_once_and_repeats_the_call(make_client):
    history = []
    client = make_client([
        json_response(200, token_body()),
        json_response(401, {"success": False, "error": {"code": "UNAUTHORIZED", "message": "revoked"}}),
        json_response(200, token_body(access_token="access-token-2")),
        json_response(200, SEND_OK),
    ], history)

    assert client.sms.send(to="998901234567", message="1").message_id == "m-1"
    assert history[2].url.path == "/api/v1/oauth/token"
    assert history[3].headers["Authorization"] == "Bearer access-token-2"


def test_file_token_storage_survives_a_new_client(make_client, tmp_path):
    storage = FileTokenStorage(tmp_path / "notify" / "tokens.json")
    make_client([json_response(200, token_body()), json_response(200, SEND_OK)], token_storage=storage).sms.send(to="1", message="x")

    history = []
    make_client([json_response(200, SEND_OK)], history, token_storage=storage).sms.send(to="1", message="y")

    assert [request.url.path for request in history] == ["/api/v1/messages/sms"]


def test_missing_credentials_or_a_bad_key_are_configuration_errors(key_pair):
    with pytest.raises(ConfigurationError):
        NotifyClient(client_id="", api_key="k", private_key=key_pair["private_pem"], base_url=NotifyClient.SANDBOX_URL)
    with pytest.raises(ConfigurationError):
        NotifyClient(client_id="c", api_key="k", private_key="-----BEGIN PRIVATE KEY-----\nnot a key\n-----END PRIVATE KEY-----", base_url=NotifyClient.SANDBOX_URL)
    with pytest.raises(ConfigurationError):
        SignatureSigner("/does/not/exist.pem")


def test_locale_is_sent_as_accept_language(make_client):
    history = []
    make_client([json_response(200, token_body()), json_response(200, SEND_OK)], history, locale="ru").sms.send(to="1", message="x")

    assert history[1].headers["Accept-Language"] == "ru"
    assert history[1].headers["User-Agent"].startswith("cloudme-notify-python/")


def test_authentication_is_retried_on_network_failure_with_a_fresh_nonce(make_client):
    history = []
    client = make_client([httpx.ConnectError("down"), json_response(200, token_body()), json_response(200, SEND_OK)], history)

    client.sms.send(to="1", message="x")

    assert json.loads(history[0].content)["nonce"] != json.loads(history[1].content)["nonce"]
