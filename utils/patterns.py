# utils/patterns.py
from __future__ import annotations

import logging
import os
from typing import List, Dict, Any, Tuple

import requests
import dotenv

dotenv.load_dotenv()

HUNTER_API_KEY = os.getenv("HUNTER_API_KEY")

logger = logging.getLogger(__name__)
logging.getLogger("smtplib").setLevel(logging.WARNING)


def _normalize_domain(domain: str) -> str:
    """
    Normalize a domain string:
    - strip protocol
    - strip path/query
    - lowercase
    """
    if not domain:
        return ""
    d = domain.strip().lower()

    # remove protocol
    if d.startswith("http://"):
        d = d[7:]
    elif d.startswith("https://"):
        d = d[8:]

    # remove path/query
    if "/" in d:
        d = d.split("/", 1)[0]
    if "?" in d:
        d = d.split("?", 1)[0]

    return d


def _split_name(name: str) -> Tuple[str, str]:
    """
    Split a full name into (first, last).
    - If only one token → last is empty.
    - Strips punctuation and lowercases.
    """
    if not name:
        return "", ""

    parts = name.strip().split()
    if not parts:
        return "", ""

    first = parts[0]
    last = parts[-1] if len(parts) > 1 else ""

    def clean(part: str) -> str:
        # keep only letters, remove dots, apostrophes, etc.
        return "".join(ch for ch in part.lower() if ch.isalpha())

    return clean(first), clean(last)


def generate_email_candidates(name: str, domain: str) -> List[str]:
    """
    Generate a list of likely email candidates for a person at a given domain.
    Does NOT validate them — just pattern generation.

    Examples:
        "John Smith", "example.com" →
            john@example.com
            john.smith@example.com
            j.smith@example.com
            johns@example.com
            jsmith@example.com
            john_smith@example.com
    """
    domain = _normalize_domain(domain)
    first, last = _split_name(name)

    if not domain or not first:
        return []

    candidates: List[str] = []

    # Base patterns
    candidates.append(f"{first}@{domain}")
    if last:
        candidates.append(f"{first}{last}@{domain}")
        candidates.append(f"{first}.{last}@{domain}")
        candidates.append(f"{first}_{last}@{domain}")
        candidates.append(f"{first[0]}{last}@{domain}")      # jsmith
        candidates.append(f"{first[0]}.{last}@{domain}")     # j.smith
        candidates.append(f"{first}{last[0]}@{domain}")      # johns
        candidates.append(f"{first[0]}_{last}@{domain}")     # j_smith

    # De-duplicate while preserving order
    seen = set()
    unique_candidates: List[str] = []
    for e in candidates:
        if e and "@" in e and e.count("@") == 1 and e not in seen:
            seen.add(e)
            unique_candidates.append(e)

    return unique_candidates


def verify_with_hunter(email: str) -> Dict[str, Any]:
    """
    Verify an email using Hunter's email verifier API.

    Returns a dict:
        {
            "ok": bool,
            "result": str | None,   # "deliverable" / "undeliverable" / "risky" / "unknown" / "error"
            "score": int | None,    # 0–100
            "status": str | None,   # legacy status; can be same as result
            "reason": str | None,   # error reason if any
            "raw": dict | None      # raw 'data' from Hunter for debugging
        }
    """
    if not email:
        return {
            "ok": False,
            "result": "error",
            "score": None,
            "status": None,
            "reason": "Empty email",
            "raw": None,
        }

    if not HUNTER_API_KEY:
        logger.warning("HUNTER_API_KEY not set; skipping Hunter verification.")
        return {
            "ok": False,
            "result": "error",
            "score": None,
            "status": None,
            "reason": "No API key configured",
            "raw": None,
        }

    url = "https://api.hunter.io/v2/email-verifier"
    params = {
        "email": email,
        "api_key": HUNTER_API_KEY,
    }

    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json().get("data", {}) if resp.content else {}

        result = data.get("result")      # "deliverable", "undeliverable", "risky", "unknown"
        score = data.get("score")        # 0–100
        status = data.get("status")      # sometimes same as result

        ok = result == "deliverable" or (result == "risky" and (score or 0) >= 70)

        return {
            "ok": ok,
            "result": result,
            "score": score,
            "status": status,
            "reason": None,
            "raw": data,
        }

    except Exception as e:
        logger.error("Hunter verification failed for %s: %s", email, e)
        return {
            "ok": False,
            "result": "error",
            "score": None,
            "status": None,
            "reason": str(e),
            "raw": None,
        }
