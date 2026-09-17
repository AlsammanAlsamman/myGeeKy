from collections import Counter

from mygeeky.matcher import (
    Features,
    LearnedModel,
    build_domain_vocabulary,
    compute_features,
    cross_validated_auc,
    domain_fit_score,
    heuristic_score,
    shared_ratio,
)
from mygeeky.config import MyGeekyConfig
from mygeeky.profile_builder import Profile


def test_shared_ratio_no_overlap():
    assert shared_ratio(Counter({"python": 1}), Counter({"rust": 1})) == 0.0


def test_shared_ratio_full_overlap():
    assert shared_ratio(Counter({"python": 1}), Counter({"python": 3, "go": 1})) == 1.0


def test_compute_features_identical_profiles_score_high_on_content():
    p = Profile(
        username="me",
        corpus="python machine learning bioinformatics",
        languages=Counter({"Python": 5}),
        topics=Counter({"bioinformatics": 2}),
        followers=100,
        following=120,
        updated_at="2026-09-01T00:00:00Z",
    )
    features = compute_features(p, p)
    assert features.content_similarity > 0.9
    assert features.shared_languages == 1.0
    assert features.shared_topics == 1.0


def test_heuristic_score_bounded():
    cfg = MyGeekyConfig()
    f = Features(content_similarity=1.0, follow_back_ratio=1.0, activity_recency=1.0,
                 shared_languages=1.0, shared_topics=1.0)
    score = heuristic_score(f, cfg)
    assert 0.0 <= score <= (cfg.content_similarity_weight + cfg.follow_back_ratio_weight + cfg.activity_weight) + 1e-9


def test_learned_model_untrained_returns_none():
    model = LearnedModel()
    f = Features(0.5, 0.5, 0.5, 0.5, 0.5)
    assert model.predict_proba(f) is None


def test_learned_model_trains_and_predicts():
    model = LearnedModel()
    X = [[0.9, 0.9, 0.9, 0.9, 0.9], [0.1, 0.1, 0.1, 0.1, 0.1]] * 5
    y = [1, 0] * 5
    assert model.train(X, y) is True
    proba = model.predict_proba(Features(0.9, 0.9, 0.9, 0.9, 0.9))
    assert proba is not None
    assert 0.0 <= proba <= 1.0


def test_domain_vocabulary_and_fit_score():
    vocab = build_domain_vocabulary(
        "population genetics GWAS fine-mapping population genetics bioinformatics population genetics",
        size=10,
    )
    assert vocab  # non-empty for a non-trivial corpus
    on_topic = domain_fit_score("I work on GWAS and population genetics tools", vocab)
    off_topic = domain_fit_score("I make video games in Unity", vocab)
    assert on_topic > off_topic
    assert on_topic > 0.0
    assert off_topic == 0.0


def test_domain_vocabulary_empty_corpus():
    assert build_domain_vocabulary("", size=10) == {}
    assert domain_fit_score("anything", {}) == 0.0


def test_cross_validated_auc_separable_data():
    X = [[0.9, 0.9, 0.9, 0.9, 0.9], [0.1, 0.1, 0.1, 0.1, 0.1]] * 6
    y = [1, 0] * 6
    auc = cross_validated_auc(X, y)
    assert auc is not None
    assert auc > 0.9


def test_cross_validated_auc_insufficient_data_returns_none():
    assert cross_validated_auc([[0.1] * 5, [0.2] * 5], [1, 0]) is None
