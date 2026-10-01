from mygeeky import scholar

PROFILE_PAGE = """
<div id="gsc_prf_in">Jane Q. Researcher</div>
<a class="gsc_prf_inta gs_ibl" href="#">Bioinformatics</a>
<a class="gsc_prf_inta gs_ibl" href="#">Population Genetics</a>
<td><a class="gsc_a_at" href="#">GWAS of lupus in Hispanic cohorts</a></td>
<td><a class="gsc_a_at" href="#">Fine-mapping &amp; colocalisation</a></td>
"""


def test_normalize_scholar_id_accepts_url_or_bare_id():
    url = "https://scholar.google.com/citations?user=khGIq6kAAAAJ&hl=en&oi=ao"
    assert scholar.normalize_scholar_id(url) == "khGIq6kAAAAJ"
    assert scholar.normalize_scholar_id("khGIq6kAAAAJ") == "khGIq6kAAAAJ"
    assert scholar.normalize_scholar_id("not a profile") == ""
    assert scholar.normalize_scholar_id("") == ""


def test_parse_scholar_page():
    parsed = scholar.parse_scholar_page(PROFILE_PAGE)
    assert parsed == {"name": "Jane Q. Researcher",
                      "interests": ["Bioinformatics", "Population Genetics"],
                      "titles": ["GWAS of lupus in Hispanic cohorts", "Fine-mapping & colocalisation"]}
    assert scholar.parse_scholar_page("<html>Please show you're not a robot</html>") is None


def test_scholar_feeds_corpus_topics_and_search_terms():
    prof = {"openalex": {"works": [{"title": "GWAS of lupus in Hispanic cohorts"}]},
            "google_scholar": scholar.parse_scholar_page(PROFILE_PAGE)}
    text = scholar.scholar_corpus(prof)
    assert text.count("GWAS of lupus in Hispanic cohorts") == 1  # already covered by OpenAlex
    assert "Fine-mapping & colocalisation" in text and "Population Genetics" in text
    assert scholar.scholar_topics(prof) == ["Bioinformatics", "Population Genetics"]
    assert scholar.scholar_keyword_counts(prof)["bioinformatics"] == 3


def test_refresh_keeps_cached_scholar_data_when_blocked(monkeypatch):
    gs = dict(scholar.parse_scholar_page(PROFILE_PAGE), user_id="khGIq6kAAAAJ")
    monkeypatch.setattr(scholar, "fetch_google_scholar", lambda sid: gs)
    first = scholar.refresh_scholar_profile(scholar_id="khGIq6kAAAAJ")
    assert first["google_scholar"]["titles"] and "google_scholar_blocked" not in first

    monkeypatch.setattr(scholar, "fetch_google_scholar", lambda sid: None)
    second = scholar.refresh_scholar_profile(scholar_id="khGIq6kAAAAJ")
    assert second["google_scholar_blocked"] is True
    assert second["google_scholar"] == gs
    assert scholar.load_scholar_profile()["google_scholar"] == gs
