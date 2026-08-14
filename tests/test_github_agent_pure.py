"""Pure-function tests for github_agent — no network calls."""
from src.agents.github_agent import extract_username, select_relevant_repos, _score_repo_relevance


def test_extract_username_from_full_url():
    assert extract_username("https://github.com/encode") == "encode"


def test_extract_username_from_url_with_trailing_path():
    assert extract_username("https://github.com/octocat/Hello-World") == "octocat"


def test_extract_username_from_bare_handle():
    assert extract_username("encode") == "encode"


def test_extract_username_returns_none_for_garbage():
    assert extract_username("not a url or handle!!") is None


def test_extract_username_empty_string():
    assert extract_username("") is None


def test_score_repo_relevance_matches_keywords():
    repo = {"name": "rag-pipeline", "description": "A RAG system", "language": "Python", "topics": []}
    score = _score_repo_relevance(repo, ["python", "rag"])
    assert score == 2


def test_select_relevant_repos_prefers_higher_score():
    repos = [
        {"name": "a", "description": "unrelated", "language": "Go", "topics": [], "pushed_at": "2024-01-01T00:00:00Z"},
        {"name": "b", "description": "python rag app", "language": "Python", "topics": [], "pushed_at": "2023-01-01T00:00:00Z"},
    ]
    selected = select_relevant_repos(repos, ["python", "rag"], limit=1)
    assert selected[0]["name"] == "b"
