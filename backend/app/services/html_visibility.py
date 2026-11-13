"""Visible email markup, including one narrowly repairable malformed document."""
from __future__ import annotations

import re

from bs4 import BeautifulSoup


_INERT = {"head", "script", "style", "template", "noscript", "svg", "meta", "link"}
_HIDDEN_STYLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.I)


def _hidden(tag) -> bool:
    if getattr(tag, "attrs", None) is None:
        return False
    classes = {str(value).casefold() for value in tag.get("class", []) or []}
    return (tag.has_attr("hidden") or str(tag.get("aria-hidden", "")).casefold() == "true"
            or bool(_HIDDEN_STYLE.search(str(tag.get("style", ""))))
            or bool(classes & {"hidden", "preheader"}))


def visible_html_soup(html: str) -> BeautifulSoup:
    """Preserve an explicit body misplaced directly inside an unclosed head.

    Only a single actual body node can be repaired, and no hidden/inert ancestor
    may supply it. Head-only text and markup inside scripts/templates remain
    inert. This does not synthesize a body from arbitrary header contents.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    bodies = soup.find_all("body")
    if len(bodies) == 1:
        body = bodies[0]
        head = body.parent
        if head is not None and head.name == "head":
            ancestors = list(body.parents)
            if not _hidden(body) and not any(_hidden(tag) or
                    (tag is not head and tag.name in _INERT) for tag in ancestors):
                head.insert_after(body.extract())
    for tag in list(soup.find_all(_INERT)):
        if tag.parent is not None:
            tag.decompose()
    for tag in list(soup.find_all(True)):
        if tag.parent is not None and _hidden(tag):
            tag.decompose()
    return soup


def permitted_jsonld_scripts(html: str):
    """Read normal head/body metadata, excluding explicitly hidden/inert scopes.

    JSON-LD is intentionally non-rendered metadata, so an ordinary head is a
    permitted location. A template, noscript block, or explicitly hidden node
    cannot supply either a flight schedule or passenger authority.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    scripts = []
    for script in soup.find_all("script", type="application/ld+json"):
        if _hidden(script):
            continue
        if any(_hidden(tag) or tag.name in (_INERT - {"head", "meta", "link"}) for tag in script.parents):
            continue
        scripts.append(script)
    return scripts
