"""Real GitHub REST API evidence collection + GPT analysis -> output/prep/github.json

Never fabricates repos, files, or commits. If no valid profile/repos are
found, the output honestly reflects that instead of inventing evidence.
"""
from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any

import requests

from src.config import get_optional_key
from src.providers.openai_client import load_prompt, structured_completion

GITHUB_API = "https://api.github.com"
MAX_REPOS_ANALYZED = 5
MAX_COMMITS_PER_REPO = 5
README_EXCERPT_CHARS = 1500
MAX_SAMPLE_FILES_PER_REPO = 2
SAMPLE_FILE_EXCERPT_CHARS = 1200
SOURCE_EXTENSIONS = (
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".java", ".rb", ".rs", ".cpp", ".c",
)

GITHUB_ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "strengths_evidenced": {"type": "array", "items": {"type": "string"}},
        "concerns": {"type": "array", "items": {"type": "string"}},
        "notable_code_areas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string"},
                    "file": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["repo", "file", "note"],
                "additionalProperties": False,
            },
        },
        "commit_cadence_summary": {"type": "string"},
        "overall_summary": {"type": "string"},
    },
    "required": [
        "strengths_evidenced",
        "concerns",
        "notable_code_areas",
        "commit_cadence_summary",
        "overall_summary",
    ],
    "additionalProperties": False,
}


def _headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = get_optional_key("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def extract_username(github_url_or_handle: str) -> str | None:
    if not github_url_or_handle:
        return None
    text = github_url_or_handle.strip()
    match = re.search(r"github\.com/([A-Za-z0-9-]+)", text)
    if match:
        return match.group(1)
    if re.fullmatch(r"[A-Za-z0-9-]+", text):
        return text
    return None


def _get(url: str, params: dict | None = None) -> requests.Response:
    return requests.get(url, headers=_headers(), params=params, timeout=15)


def fetch_profile(username: str) -> dict[str, Any] | None:
    resp = _get(f"{GITHUB_API}/users/{username}")
    if resp.status_code != 200:
        return None
    return resp.json()


def fetch_repos(username: str) -> list[dict[str, Any]]:
    resp = _get(
        f"{GITHUB_API}/users/{username}/repos",
        params={"sort": "pushed", "per_page": 100, "type": "owner"},
    )
    if resp.status_code != 200:
        return []
    return [r for r in resp.json() if not r.get("fork")]


def _score_repo_relevance(repo: dict[str, Any], keywords: list[str]) -> int:
    haystack = " ".join(
        [
            repo.get("name", ""),
            repo.get("description") or "",
            repo.get("language") or "",
            " ".join(repo.get("topics") or []),
        ]
    ).lower()
    return sum(1 for kw in keywords if kw and kw.lower() in haystack)


def select_relevant_repos(
    repos: list[dict[str, Any]], keywords: list[str], limit: int = MAX_REPOS_ANALYZED
) -> list[dict[str, Any]]:
    scored = [(_score_repo_relevance(r, keywords), r) for r in repos]
    scored.sort(key=lambda pair: (pair[0], pair[1].get("pushed_at") or ""), reverse=True)
    return [r for _, r in scored[:limit]]


def fetch_languages(owner: str, repo: str) -> dict[str, int]:
    resp = _get(f"{GITHUB_API}/repos/{owner}/{repo}/languages")
    return resp.json() if resp.status_code == 200 else {}


def fetch_readme_excerpt(owner: str, repo: str) -> str:
    resp = _get(f"{GITHUB_API}/repos/{owner}/{repo}/readme")
    if resp.status_code != 200:
        return ""
    data = resp.json()
    content = data.get("content", "")
    try:
        decoded = base64.b64decode(content).decode("utf-8", errors="replace")
    except Exception:
        return ""
    return decoded[:README_EXCERPT_CHARS]


def fetch_recent_commits(owner: str, repo: str) -> list[dict[str, Any]]:
    resp = _get(
        f"{GITHUB_API}/repos/{owner}/{repo}/commits",
        params={"per_page": MAX_COMMITS_PER_REPO},
    )
    if resp.status_code != 200:
        return []
    commits = []
    for c in resp.json():
        commits.append(
            {
                "sha": c.get("sha", "")[:10],
                "message": (c.get("commit", {}).get("message") or "").split("\n")[0],
                "date": c.get("commit", {}).get("author", {}).get("date", ""),
                "url": c.get("html_url", ""),
            }
        )
    return commits


def fetch_sample_source_files(owner: str, repo: str) -> list[dict[str, str]]:
    """Fetch a small, bounded number of real source-file excerpts from the
    repo root so questions can reference actual code, not just the README.
    Intentionally shallow (root dir only, few files, capped size) to avoid
    downloading unnecessary repository content.
    """
    resp = _get(f"{GITHUB_API}/repos/{owner}/{repo}/contents")
    if resp.status_code != 200:
        return []
    entries = resp.json()
    if not isinstance(entries, list):
        return []

    candidates = [
        e for e in entries
        if e.get("type") == "file" and e.get("name", "").lower().endswith(SOURCE_EXTENSIONS)
    ]
    samples: list[dict[str, str]] = []
    for entry in candidates[:MAX_SAMPLE_FILES_PER_REPO]:
        file_resp = _get(entry["url"])
        if file_resp.status_code != 200:
            continue
        file_data = file_resp.json()
        content = file_data.get("content", "")
        try:
            decoded = base64.b64decode(content).decode("utf-8", errors="replace")
        except Exception:
            continue
        samples.append({"path": entry["name"], "excerpt": decoded[:SAMPLE_FILE_EXCERPT_CHARS]})
    return samples


def collect_raw_evidence(
    username: str, keywords: list[str]
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], str | None]:
    """Returns (profile, analyzed_repos_evidence, no_profile_reason)."""
    profile = fetch_profile(username)
    if profile is None:
        return None, [], f"No public GitHub profile found for username '{username}'."

    repos = fetch_repos(username)
    if not repos:
        return profile, [], "Profile found but no public non-fork repositories to analyze."

    selected = select_relevant_repos(repos, keywords)
    evidence: list[dict[str, Any]] = []
    for repo in selected:
        owner = repo["owner"]["login"]
        name = repo["name"]
        evidence.append(
            {
                "name": name,
                "full_name": repo.get("full_name", f"{owner}/{name}"),
                "description": repo.get("description") or "",
                "url": repo.get("html_url", ""),
                "languages": fetch_languages(owner, name),
                "readme_excerpt": fetch_readme_excerpt(owner, name),
                "topics": repo.get("topics") or [],
                "stars": repo.get("stargazers_count", 0),
                "last_pushed": repo.get("pushed_at", ""),
                "recent_commits": fetch_recent_commits(owner, name),
                "sample_files": fetch_sample_source_files(owner, name),
            }
        )
    return profile, evidence, None


def analyze_with_gpt(
    username: str,
    profile: dict[str, Any] | None,
    repo_evidence: list[dict[str, Any]],
    jd_json: dict[str, Any],
    resume_json: dict[str, Any],
) -> dict[str, Any]:
    system_prompt = load_prompt("github_analysis_v1.md")
    user_content = json.dumps(
        {
            "username": username,
            "profile": profile,
            "repositories_evidence": repo_evidence,
            "job_description": jd_json,
            "resume": resume_json,
        },
        indent=2,
    )
    return structured_completion(
        system_prompt=system_prompt,
        user_content=user_content,
        json_schema=GITHUB_ANALYSIS_SCHEMA,
        schema_name="github_analysis_schema",
    )


def build_github_profile(
    resume_json: dict[str, Any],
    jd_json: dict[str, Any],
    output_path: Path,
) -> dict[str, Any]:
    github_url = (resume_json.get("links") or {}).get("github", "")
    username = extract_username(github_url)

    result: dict[str, Any]

    if not username:
        result = {
            "username": None,
            "profile_url": None,
            "profile_found": False,
            "repositories_analyzed": [],
            "gpt_analysis": None,
            "no_profile_reason": "No GitHub link was found in the parsed resume.",
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result

    keywords = list(
        {
            *(jd_json.get("must_haves") or []),
            *(jd_json.get("nice_to_haves") or []),
            *(resume_json.get("skills") or []),
        }
    )
    # keywords may contain multi-word phrases; split into single tokens too
    tokens: list[str] = []
    for kw in keywords:
        tokens.extend(kw.split())
    keywords = list(set(keywords + tokens))

    profile, repo_evidence, no_profile_reason = collect_raw_evidence(username, keywords)

    if profile is None:
        result = {
            "username": username,
            "profile_url": f"https://github.com/{username}",
            "profile_found": False,
            "repositories_analyzed": [],
            "gpt_analysis": None,
            "no_profile_reason": no_profile_reason,
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result

    gpt_analysis = None
    if repo_evidence:
        gpt_analysis = analyze_with_gpt(username, profile, repo_evidence, jd_json, resume_json)

    result = {
        "username": username,
        "profile_url": profile.get("html_url", f"https://github.com/{username}"),
        "profile_found": True,
        "repositories_analyzed": repo_evidence,
        "gpt_analysis": gpt_analysis,
        "no_profile_reason": no_profile_reason,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result
