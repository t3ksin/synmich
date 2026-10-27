"""DSM v6 OTP responses and richer v7 challenge responses."""

from unittest.mock import MagicMock, patch

import pytest

from synmich.core.synology_auth import LoginFailed, OTPRequired, login_with_2fa


@pytest.mark.parametrize(
    "challenge",
    [
        {"code": 403},
        {"code": 406},
        {"code": 403, "errors": {"types": [{"type": "otp"}]}},
        {"code": 403, "errors": {"token": "challenge", "types": [{"type": "otp"}]}},
    ],
)
def test_otp_prompt_works_with_and_without_challenge_metadata(challenge):
    session = MagicMock()
    session.post.return_value.json.side_effect = [
        {"success": False, "error": challenge},
        {"success": True, "data": {"sid": "sid", "did": "remembered"}},
    ]
    provider = MagicMock(return_value="012345")
    with patch("synmich.core.synology_auth.get_device_token", return_value=None):
        with patch("synmich.core.synology_auth.save_device_token") as save:
            sid = login_with_2fa(session, "https://nas", "alice", "password", otp_provider=provider)
    assert sid == "sid"
    provider.assert_called_once_with("alice")
    save.assert_called_once_with("alice", "https://nas", "remembered")
    request = session.post.call_args.kwargs["data"]
    assert request["otp_code"] == "012345"
    assert request["device_name"] == "synmich-cli"
    token = (challenge.get("errors") or {}).get("token")
    assert request["version"] == ("7" if token else "6")
    assert request.get("token") == token


def test_otp_can_be_retried_after_invalid_code():
    session = MagicMock()
    session.post.return_value.json.side_effect = [
        {"success": False, "error": {"code": 403}},
        {"success": False, "error": {"code": 404}},
        {"success": True, "data": {"sid": "sid"}},
    ]
    provider = MagicMock(side_effect=["111111", "222222"])
    with patch("synmich.core.synology_auth.get_device_token", return_value=None):
        assert login_with_2fa(session, "https://nas", "alice", "pw", otp_provider=provider) == "sid"
    assert provider.call_count == 2


def test_plain_otp_challenge_without_provider_raises_instead_of_terminal_prompt():
    session = MagicMock()
    session.post.return_value.json.return_value = {"success": False, "error": {"code": 403}}
    with patch("synmich.core.synology_auth.get_device_token", return_value=None):
        with pytest.raises(OTPRequired):
            login_with_2fa(session, "https://nas", "alice", "pw")


def test_push_only_challenge_is_explained_without_requesting_unsupported_code():
    session = MagicMock()
    session.post.return_value.json.return_value = {
        "success": False,
        "error": {"code": 403, "errors": {"types": [{"type": "push"}]}},
    }
    provider = MagicMock()
    with patch("synmich.core.synology_auth.get_device_token", return_value=None):
        with pytest.raises(LoginFailed, match="push-only"):
            login_with_2fa(session, "https://nas", "alice", "pw", otp_provider=provider)
    provider.assert_not_called()


def test_rejected_device_token_falls_back_to_plain_otp_and_saves_new_did():
    session = MagicMock()
    session.post.return_value.json.side_effect = [
        {"success": False, "error": {"code": 403}},
        {"success": False, "error": {"code": 403}},
        {"success": True, "data": {"sid": "sid", "did": "new-device"}},
    ]
    with patch("synmich.core.synology_auth.get_device_token", return_value="old-device"):
        with patch("synmich.core.synology_auth.clear_device_token") as clear:
            with patch("synmich.core.synology_auth.save_device_token") as save:
                assert (
                    login_with_2fa(
                        session, "https://nas", "alice", "pw", otp_provider=lambda _: "123456"
                    )
                    == "sid"
                )
    clear.assert_called_once_with("alice", "https://nas")
    save.assert_called_once_with("alice", "https://nas", "new-device")
