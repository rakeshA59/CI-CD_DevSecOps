"""
A short, readable application name for a run – instead of the raw repository slug.

    writespace-v1-blueprint-OhGBxuRoQoeE  →  Writespace
    student_app                           →  Student App
The planner replaces it with a better name when it understands the code (README / UI title / LLM).
"""

import re

NOISE = {"v", "main", "master", "blueprint", "template", "repo", "git", "src", "code", "project", "final", "copy"}


def _is_noise(word: str) -> bool:
    w = word.lower()
    return (not w or w in NOISE or bool(re.fullmatch(r"v?\d+(\.\d+)*", w))
            or (len(word) >= 8 and (sum(ch.isupper() for ch in word) >= 4 or (re.search(r"\d", word) and re.search(r"[a-z]", w)
                                                                             and not w.isalpha()))))   # random hash suffixes


def clean_app_name(repo: str) -> str:
    words = [w for w in re.split(r"[-_.\s]+", repo or "") if not _is_noise(w)]
    return " ".join(w if any(c.isupper() for c in w[1:]) else w.capitalize() for w in words) or (repo or "app")


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "app"
