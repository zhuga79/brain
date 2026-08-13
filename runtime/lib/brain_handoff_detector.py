import re
from typing import Optional, Dict

LIMIT_PATTERNS = [
    (re.compile(r"You've hit your limit.*?resets", re.IGNORECASE), "limit-exhausted"),
    (re.compile(r"rate_limit_error", re.IGNORECASE), "rate-limit"),
    (re.compile(r"resource_exhausted", re.IGNORECASE), "limit-exhausted"),
    (re.compile(r"quota_exceeded", re.IGNORECASE), "limit-exhausted"),
    (re.compile(r"429 Too Many Requests", re.IGNORECASE), "rate-limit"),
    (re.compile(r"rate limit reached", re.IGNORECASE), "rate-limit"),
    (re.compile(r"exceeded your current quota", re.IGNORECASE), "limit-exhausted"),
    (re.compile(r"limit-exhausted", re.IGNORECASE), "limit-exhausted"),
]

def detect_limit(text: str) -> Optional[Dict[str, str]]:
    """
    Detects if the provided text contains known limit or quota exhaustion patterns.
    Returns a dict with the handoff reason if detected, else None.
    """
    if not text:
        return None
    
    for pat, reason in LIMIT_PATTERNS:
        if pat.search(text):
            return {"reason": reason}
            
    return None


HUMAN_PATTERNS = [
    re.compile(r"NEEDS[_-]HUMAN", re.IGNORECASE),
    re.compile(r"HUMAN[_-]REQUIRED", re.IGNORECASE),
    re.compile(r"waiting[ _-]approval", re.IGNORECASE),
    re.compile(r"awaiting[ _-](?:human|approval|sign-?off)", re.IGNORECASE),
    re.compile(r"human input required", re.IGNORECASE),
]


def detect_needs_human(text: str) -> Optional[Dict[str, str]]:
    """
    Detects semantic markers that an agent needs a human in the loop
    (approval, taste, decision) rather than a technical limit.
    Returns {"reason": "needs-human"} if detected, else None.
    """
    if not text:
        return None
    for pat in HUMAN_PATTERNS:
        if pat.search(text):
            return {"reason": "needs-human"}
    return None


def detect_handoff(text: str) -> Optional[Dict[str, str]]:
    """
    Unified handoff trigger. Technical limits take precedence over a
    human-needed signal (a rate-limited agent cannot continue regardless).
    Returns {"reason": ...} or None.
    """
    return detect_limit(text) or detect_needs_human(text)
