"""Headless checks of the GUI OTP handoff and nested modal ownership."""

import queue
import threading
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("tkinter")
pytest.importorskip("customtkinter")

from synmich.gui.app import SynmichApp
from synmich.gui.dialogs import prompt_otp


def test_nested_otp_dialog_is_owned_by_account_form_and_restores_grab():
    parent = MagicMock()
    account_form = parent.grab_current.return_value
    with patch("synmich.gui.dialogs.ctk.CTkToplevel") as toplevel:
        with patch("synmich.gui.dialogs.ctk.CTkLabel"), patch("synmich.gui.dialogs.ctk.CTkEntry"):
            with (
                patch("synmich.gui.dialogs.W.primary_button"),
                patch("synmich.gui.dialogs.W.fix_wrapping"),
                patch("synmich.gui.dialogs.W.font"),
            ):
                assert prompt_otp(parent, "alice") is None
    toplevel.assert_called_once_with(account_form)
    toplevel.return_value.transient.assert_called_once_with(account_form)
    account_form.grab_set.assert_called_once()


def test_otp_dialog_exception_unblocks_login_worker():
    callbacks = queue.Queue()
    parent = MagicMock()
    parent.after.side_effect = lambda delay, callback: callbacks.put(callback)
    result = []
    worker = threading.Thread(target=lambda: result.append(SynmichApp._gui_otp(parent, "alice")))
    worker.start()
    callback = callbacks.get(timeout=2)
    with patch("synmich.gui.dialogs.prompt_otp", side_effect=RuntimeError("dialog failed")):
        with pytest.raises(RuntimeError, match="dialog failed"):
            callback()
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert result == [""]
