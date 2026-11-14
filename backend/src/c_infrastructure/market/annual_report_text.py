"""
An annual report's PDF read as text, and the windows of that text its sections are kept as. It imports no other part of
the app: the adapter runs this file as a worker process (read_report), so that process loads only the PDF library,
keeps the report's pages out of the server's own memory and off its event loop, and gives everything back when it ends.
The settings give every number and pattern it reads (sources.annual_reports).
"""

import json
import logging
import re
import sys
import unicodedata
from collections.abc import Mapping, Sequence
from contextlib import suppress
from typing import IO

from pypdf import PdfReader


def report_sections(
    report: IO[bytes],
    patterns: Mapping[str, Sequence[str]],
    lead: int,
    length: int,
    contents_share: float,
    min_text_length: int,
    leader_pattern: str,
    leader_reach: int,
) -> dict[str, str] | None:
    """
    The window of each section the report's text holds, by the section's name in `patterns` (section_windows). {} for
    a report whose pages hold fewer than `min_text_length` characters in all, as scanned images do. None when the file
    is no PDF the library can read, or is encrypted with a password a reader must type.
    """
    try:
        reader = PdfReader(report)

        if reader.is_encrypted and not reader.decrypt(""):
            return None

        text = readable_text("\n".join(page_text(reader, number) for number in range(len(reader.pages))))
    except Exception:
        return None

    if len(text) < min_text_length:
        return {}

    return section_windows(text, patterns, lead, length, contents_share, leader_pattern, leader_reach)


def page_text(reader: PdfReader, number: int) -> str:
    """One page's text, or '' for a page the library cannot read: one broken page does not lose the report."""
    try:
        return reader.pages[number].extract_text() or ""
    except Exception:
        return ""


def readable_text(extracted: str) -> str:
    """
    The pages' text as a reader would see it: compatibility characters as their ordinary ones (a PDF may write a
    character as its Kangxi radical, and digits and brackets full-width), a word of CJK ideographs that a line break
    split joined again, and every other run of white space one space.
    """
    ordinary = unicodedata.normalize("NFKC", extracted)
    ideograph = f"[{chr(0x4E00)}-{chr(0x9FFF)}]"
    joined = re.sub(rf"(?<={ideograph})[ \t]*\n[ \t]*(?={ideograph})", "", ordinary)
    return " ".join(joined.split())


def section_windows(
    text: str,
    patterns: Mapping[str, Sequence[str]],
    lead: int,
    length: int,
    contents_share: float,
    leader_pattern: str,
    leader_reach: int,
) -> dict[str, str]:
    """
    For each section, the text from `lead` characters before the first place one of its patterns matches to `length`
    characters after it, the patterns tried in order. A match in the table of contents is passed over: one within the
    first `contents_share` of the text, or with a line of leader dots (`leader_pattern`) in the `leader_reach`
    characters from it. A section none of whose patterns matches the body is left out.
    """
    contents_end = int(len(text) * contents_share)
    leaders = re.compile(leader_pattern)
    windows: dict[str, str] = {}

    for section, expressions in patterns.items():
        for expression in expressions:
            places = [match.start() for match in re.finditer(expression, text) if match.start() >= contents_end]
            body = [place for place in places if not leaders.search(text[place : place + leader_reach])]

            if body:
                windows[section] = text[max(0, body[0] - lead) : body[0] + length]
                break

    return windows


def bound_process(memory_bytes: int, cpu_seconds: int) -> None:
    """
    Limits this process where the system has such limits: it is ended once it has used `cpu_seconds` of processor
    time, and, where the system enforces it (Linux), it may address `memory_bytes` at most.
    """
    try:
        import resource
    except ImportError:
        return

    for limit, value in ((resource.RLIMIT_CPU, cpu_seconds), (resource.RLIMIT_AS, memory_bytes)):
        with suppress(ValueError, OSError):
            resource.setrlimit(limit, (value, value))


def read_report() -> None:
    """
    The worker process: the report's file is its standard input, its one argument is a JSON request, report_sections'
    arguments by name with `memory_mb` and `cpu_seconds`, and its answer is JSON on standard output. The system ends
    the process once it has used that processor time, whoever still waits for it, so a report that never finishes
    outlives no server that stopped; a report that would need more memory ends this process with an error and never
    the server.
    """
    request = json.loads(sys.argv[1])
    bound_process(request.pop("memory_mb") * 1024 * 1024, request.pop("cpu_seconds"))
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    sys.stdout.write(json.dumps(report_sections(sys.stdin.buffer, **request), ensure_ascii=False))


if __name__ == "__main__":
    read_report()
