import click
import pytest

from mygeeky import auth, cli
from mygeeky.config import MyGeekyConfig


def _answers(monkeypatch, prompts, confirms=()):
    prompts, confirms = iter(prompts), iter(confirms)
    monkeypatch.setattr(click, "prompt", lambda *a, **k: next(prompts))
    monkeypatch.setattr(click, "confirm", lambda *a, **k: next(confirms))


def test_init_offers_sign_in_first(monkeypatch):
    _answers(monkeypatch, ["s"])
    called = []
    monkeypatch.setattr(cli, "_github_sign_in", lambda cfg: called.append("sign-in") or True)
    monkeypatch.setattr(auth, "prompt_and_store_token", lambda *a, **k: called.append("paste"))
    cli._connect_github(MyGeekyConfig(github_username="me"))
    assert called == ["sign-in"]


def test_a_failed_sign_in_can_fall_back_to_pasting_with_retries(monkeypatch):
    _answers(monkeypatch, ["s"], confirms=[True, True])      # paste instead? yes; try again? yes
    monkeypatch.setattr(cli, "_github_sign_in", lambda cfg: False)
    tries = []

    def paste(user, show_guide=True):
        tries.append(show_guide)
        if len(tries) == 1:
            raise ValueError("Nothing was pasted")
    monkeypatch.setattr(auth, "prompt_and_store_token", paste)
    cli._connect_github(MyGeekyConfig(github_username="me"))
    assert tries == [True, False]                              # the guide only the first time


def test_an_empty_paste_explains_how_to_paste(monkeypatch):
    monkeypatch.setattr(auth.getpass, "getpass", lambda prompt="": "")
    monkeypatch.setattr(auth.sys, "platform", "linux")
    with pytest.raises(ValueError, match="Ctrl\+Shift\+V"):
        auth.prompt_and_store_token("me", show_guide=False)
    monkeypatch.setattr(auth.getpass, "getpass", lambda prompt="": "^V")
    with pytest.raises(ValueError, match="doesn't look like a GitHub token"):
        auth.prompt_and_store_token("me", show_guide=False)
