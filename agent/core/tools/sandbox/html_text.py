"""HTML → читаемый текст. Автономный stdlib-скрипт: исполняется В ПЕСОЧНИЦЕ
(`python3 -c <этот файл> <url> <max_bytes>`, см. browse.py), поэтому ничего из
проекта не импортирует. Тестируется на хосте напрямую (`extract_text`).

Убирает script/style/nav/header/footer/aside, сохраняет заголовки (#), списки (-),
блоки кода (```), абзацы. Вывод: строка «Title: …», «URL: <финальный после
редиректов>», пустая строка, текст.
"""

from __future__ import annotations

import re
import sys
from html import unescape
from html.parser import HTMLParser

SKIP_TAGS = {"script", "style", "noscript", "nav", "header", "footer", "aside", "svg", "template"}
BLOCK_TAGS = {"p", "div", "section", "article", "main", "br", "tr", "table", "blockquote", "hr"}
HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._pre = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in SKIP_TAGS:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif self._skip:
            return
        elif tag in HEADINGS:
            self.parts.append("\n\n" + "#" * HEADINGS[tag] + " ")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag == "pre":
            self._pre += 1
            self.parts.append("\n```\n")
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
        elif tag == "title":
            self._in_title = False
        elif self._skip:
            return
        elif tag == "pre":
            self._pre = max(0, self._pre - 1)
            self.parts.append("\n```\n")
        elif tag in HEADINGS or tag in BLOCK_TAGS:  # li: перевод строки даёт следующий "\n- "
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data if self._pre else re.sub(r"\s+", " ", data))


def extract_text(html: str) -> tuple[str, str]:
    """(title, text) — пробелы схлопнуты, пустых строк не больше двух подряд."""
    parser = _Extractor()
    parser.feed(html)
    parser.close()
    text = "".join(parser.parts)
    text = "\n".join(line.strip() for line in text.splitlines())
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return unescape(parser.title).strip(), text


def fetch(url: str, max_bytes: int, timeout: float = 20.0) -> tuple[str, str, str]:
    """(final_url, content_type, body) через urllib; тело читается не дальше max_bytes."""
    import urllib.request

    req = urllib.request.Request(
        url, headers={"User-Agent": "git-agent-browse/1.0 (+security review bot)"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read(max_bytes + 1)
        ctype = resp.headers.get_content_type()
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.geturl(), ctype, raw[:max_bytes].decode(charset, errors="replace")


def main(argv: list[str]) -> int:
    url, max_bytes = argv[1], int(argv[2])
    final_url, ctype, body = fetch(url, max_bytes)
    if ctype == "text/html" or ctype == "application/xhtml+xml":
        title, text = extract_text(body)
    elif ctype.startswith("text/") or ctype in ("application/json", "application/xml"):
        title, text = "", body
    else:
        print(f"browse: unsupported content-type {ctype} at {final_url}")
        return 2
    print(f"Title: {title}\nURL: {final_url}\n\n{text}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except Exception as exc:  # текст для модели, не трейсбек
        print(f"browse: fetch failed: {type(exc).__name__}: {exc}")
        sys.exit(1)
