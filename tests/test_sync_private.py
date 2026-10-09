import pytest

from mygeeky import sync


def test_a_public_repo_is_refused_before_anything_is_uploaded(monkeypatch):
    monkeypatch.setattr(sync, "public_on_github", lambda repo: True)
    monkeypatch.setattr(sync, "_require_git", lambda: pytest.fail("must stop before touching git"))
    with pytest.raises(sync.SyncError, match="PUBLIC"):
        sync.init("me/mygeeky-data")


def test_without_the_github_cli_a_public_repo_is_still_spotted(monkeypatch):
    monkeypatch.setattr(sync, "_has_gh", lambda: False)
    monkeypatch.setattr(sync, "public_on_github", lambda repo: True)
    assert sync._repo_is_private("me/mygeeky-data") is False
    monkeypatch.setattr(sync, "public_on_github", lambda repo: False)    # private, or not there yet
    assert sync._repo_is_private("me/mygeeky-data") is None


def test_the_steps_open_github_with_private_chosen():
    url = sync.new_repo_url("me/mygeeky-data")
    assert url.startswith("https://github.com/new?name=mygeeky-data&visibility=private")
    steps = sync.create_steps("me/mygeeky-data")
    assert "Private" in steps[1] and "empty" in steps[1] and url in steps[0]


def test_public_on_github_reads_the_visibility(monkeypatch):
    import requests

    class R:
        def __init__(self, code, private=None):
            self.status_code, self._p = code, private

        def json(self):
            return {"private": self._p}
    monkeypatch.setattr(requests, "get", lambda *a, **k: R(200, False))
    assert sync.public_on_github("me/x") is True
    monkeypatch.setattr(requests, "get", lambda *a, **k: R(404))
    assert sync.public_on_github("me/x") is False
    monkeypatch.setattr(requests, "get", lambda *a, **k: R(403))
    assert sync.public_on_github("me/x") is None
