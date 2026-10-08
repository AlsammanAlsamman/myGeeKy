import pytest

from mygeeky import pairing
from mygeeky.config import MyGeekyConfig

CFG = MyGeekyConfig(github_username="me", orcid_id="0000-0002-1825-0097", keywords=["GWAS", "café"], topics=["genomics"])


def test_payload_round_trips_and_is_ascii():
    text = pairing.payload(CFG, "github_pat_" + "a" * 40)
    assert text.startswith("mygeeky:1:") and text.isascii() and "=" not in text
    data = pairing.decode(text)
    assert data == {"u": "me", "o": "0000-0002-1825-0097", "k": ["GWAS", "café"], "t": ["genomics"],
                    "tok": "github_pat_" + "a" * 40}
    assert "tok" not in pairing.decode(pairing.payload(CFG))


def test_only_a_strictly_read_only_token_goes_to_the_phone(monkeypatch):
    from mygeeky import auth, token_check
    monkeypatch.setattr(auth, "get_token", lambda user: "github_pat_x")
    monkeypatch.setattr(token_check, "check", lambda role, tok, user, other_token=None: {"ok": True})
    assert pairing.shareable_token(CFG)[0] == "github_pat_x"
    monkeypatch.setattr(token_check, "check", lambda role, tok, user, other_token=None: {"ok": False})
    token, why = pairing.shareable_token(CFG)
    assert token is None and "stays on this computer" in why
    monkeypatch.setattr(auth, "get_token", lambda user: None)
    assert pairing.shareable_token(CFG)[0] is None


def test_matrix_is_a_square_qr():
    m = pairing.matrix(pairing.payload(CFG))
    assert len(m) == len(m[0]) >= 25 and any(any(row) for row in m)


def test_connect_your_phone_dialog(monkeypatch):
    pytest.importorskip("PySide6")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from mygeeky.gui import app as logic
    from mygeeky.gui.qt_panel import MyGeekyPanel, PairDialog, QrWidget

    for name, value in (("get_contributions", lambda cfg: []),
                        ("get_suggestions", lambda cfg: {"followback": [], "domain_highlights": []}),
                        ("get_activity", lambda cfg, force=False: {"events": []}),
                        ("get_model_history", lambda: []),
                        ("get_friend_stats", lambda cfg: {"total_friends": 0, "new_this_week": 0,
                                                          "follow_back_rate": None, "total_labeled": 0})):
        monkeypatch.setattr(logic, name, value)
    monkeypatch.setattr(pairing, "shareable_token", lambda cfg: (None, "No token here."))
    panel = MyGeekyPanel(MyGeekyConfig(github_username="me", keywords=["GWAS"]))
    try:
        assert panel.pair_btn.text().endswith("Connect your phone")
        dialog = PairDialog(panel, {"text": "#fff", "btn_bg": "#333"})
        for w in list(panel._workers):
            w.wait(3000)
        QApplication.processEvents()
        assert dialog.findChildren(QrWidget) and "Signals token never leaves" in dialog.why.text()
        assert "disappears in" in dialog.countdown.text()
        dialog._left = 0
        dialog._tick()                              # time's up: the code is gone
        assert not dialog.isVisible()
    finally:
        panel.ticker.stop()
        for t in (panel._activity_timer, panel._signals_timer, panel._update_timer, panel._news_timer,
                  panel._dock_guard, panel._sync_timer):
            t.stop()
        for w in list(panel._workers):
            w.wait(2000)
        panel.close()
        panel.deleteLater()
