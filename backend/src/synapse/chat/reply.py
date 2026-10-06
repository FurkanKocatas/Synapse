"""The model's reply to a question with sources (ADR 0010, rule 9): its JSON schema, the
answer as it streams, and the answer once it is complete, written out as text with its
citations inline ("Kurul 7 üyedir. [1]"), which is what verification reads, what is stored and
what the page shows (answering.py).
"""

import json
import re
from collections.abc import Sequence

from synapse.chat.verification import fold


def schema(sources: int) -> dict[str, object]:
    """The reply's shape when ``sources`` sources are shown: sentences that each cite one of
    them or more, then whether they sufficed."""
    citation = {"type": "integer", "minimum": 1, "maximum": sources}
    sentence = {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "sources": {"type": "array", "items": citation, "minItems": 1},
        },
        "required": ["text", "sources"],
    }
    return {
        "type": "object",
        "properties": {
            "answer": {"type": "array", "items": sentence, "minItems": 1},
            "sufficient": {"type": "boolean"},
        },
        "required": ["answer", "sufficient"],
    }


def written(sentences: Sequence[tuple[str, Sequence[int]]]) -> str:
    """Sentences as one text, each followed by its citations: ``Kurul 7 üyedir. [1, 3]``."""
    parts = []
    for text, numbers in sentences:
        if text := text.strip():
            marker = f" [{', '.join(str(n) for n in numbers)}]" if numbers else ""
            parts.append(text + marker)
    return " ".join(parts)


class AnswerStream:
    """The answer as far as the JSON reply has streamed, written as ``written`` writes it.

    Each sentence's text shows as it comes and its citations once their list is closed, so
    what is shown is always the start of the whole answer.
    """

    _PARTS = re.compile(
        r'"text"\s*:\s*"(?P<text>(?:[^"\\]|\\.)*)(?P<closed>")?'
        r'|"sources"\s*:\s*\[(?P<sources>[^\]]*)(?P<end>\])?'
    )

    def __init__(self) -> None:
        self._raw = ""
        self._shown = ""

    def feed(self, text: str) -> str:
        """The answer's text that ``text`` completes."""
        self._raw += text
        sentences: list[tuple[str, list[int]]] = []
        for part in self._PARTS.finditer(self._raw):
            if part["text"] is not None:
                body = part["text"] if part["closed"] else _complete(part["text"])
                try:
                    sentences.append((json.loads(f'"{body}"'), []))
                except ValueError:
                    break
                if not part["closed"]:
                    break
            elif part["end"] and sentences:
                numbers = [int(n) for n in re.findall(r"\d+", part["sources"])]
                sentences[-1] = (sentences[-1][0], numbers)
        shown = written(sentences)
        if not shown.startswith(self._shown):  # pragma: no cover  (only a bad reply)
            return ""
        new = shown[len(self._shown) :]
        self._shown = shown
        return new


def _complete(body: str) -> str:
    """A JSON string's body as far as it decodes: without an escape cut short at its end, nor a
    high surrogate whose pair has not come yet."""
    end = at = 0
    while at < len(body):
        if body[at] != "\\":
            at += 1
        elif body[at + 1 : at + 2] != "u":
            at += 2
        elif re.fullmatch(r"[dD][89abAB][0-9a-fA-F]{2}", body[at + 2 : at + 6]):
            at += 12  # 😀: the pair
        else:
            at += 6
        if at <= len(body):
            end = at
    return body[:end]


def parse(content: str) -> tuple[str, bool]:
    """The reply's answer, written out, and whether the model found the sources sufficient. A
    sentence the model repeats is written once, with the citations of every time it said it
    (a small model can loop: one answer said the same sentence three times). The streamed text
    may show the repeat for a moment; the final answer replaces it."""
    try:
        reply = json.loads(content)
    except ValueError:
        return content.strip(), True
    if not isinstance(reply, dict):
        return content.strip(), True
    answer = reply.get("answer")
    sufficient = reply.get("sufficient") is not False
    if isinstance(answer, str):
        return answer.strip(), sufficient
    sentences: dict[str, tuple[str, list[int]]] = {}
    for sentence in answer if isinstance(answer, list) else []:
        if isinstance(sentence, dict) and isinstance(sentence.get("text"), str):
            numbers = sentence.get("sources")
            cited = [n for n in numbers if isinstance(n, int)] if isinstance(numbers, list) else []
            text, before = sentences.get(fold(sentence["text"]), (sentence["text"], []))
            sentences[fold(text)] = (text, [*before, *(n for n in cited if n not in before)])
    return written(list(sentences.values())), sufficient
