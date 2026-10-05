"""Turkish Wikisource's validated pages as an OCR test set of real scans with human truth.

    python eval/ocr/wikisource.py layout --root DIR --work DIR
    python eval/ocr/wikisource.py truth --pages pages.json --out DIR [--html DIR]

A validated page ("Doğrulanmış") was transcribed from its scan and proofread by a second
person. ``layout`` takes each page's truth from the wiki's own rendering of it (fetched as HTML:
templates expanded as the reader sees them, header and footer included) and lays the pages out
for measure.py: truth/<id>.txt and images/<id>.<condition>.jpg, the condition "scan" when the
source file holds many bytes per page (a scan) and "digital" when few (a born-digital PDF).

``truth`` turns the wikitext itself into text (templates, tables, links, footnotes) and, with
``--html``, compares it with the rendering: 99.4% of words agree, and the rest (a masthead
template it does not know, for one) is why the rendering is the truth.

The pages and images are fetched by the desktop tool (the API, then 1920-pixel thumbnails,
the size Wikimedia asks bots to use); the texts are CC BY-SA 4.0 and stay out of this
repository with the images.
"""

import argparse
import html
import json
import re
import sys
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from measure import words

# Templates that only lay the page out: nothing of theirs is read.
SILENT = {
    "girinti",
    "bb",
    "gap",
    "yç",
    "çsy",
    "boşluk bırak",
    "custom rule",
    "rule",
    "dhr",
    "nop",
    "temiz",
    "kaynakça",
    "sütun-2",
    "sütun-3",
    "sütun-sonu",
    "sütun-başı",
    "fine block/s",
    "fine block/e",
    "sola hizala/s",
    "sola hizala/e",
    "çoklu resim",
    "üç yıldız işareti",
    "ts",
    "sic",
    "clear",
    "brokenpage",
    "pb",
    "hr",
    "dotted tc line",
    "nbsp",
    "-",
}
# Templates whose first argument is the text they show.
FIRST = {
    "center",
    "orta",
    "ortala",
    "sağa hizala",
    "sola hizala",
    "right",
    "left",
    "küçük",
    "alıntı",
    "larger",
    "x-larger",
    "xx-larger",
    "xxx-larger",
    "smaller",
    "x-smaller",
    "ortalı ve hizalı",
    "sc",
    "nowrap",
    "u",
    "big",
    "small",
    "yss",
    "yarım söz son",
    "ysb",
    "yarım söz baş",
    "hws",
    "hwe",
    "lang",
    "kalın",
    "italik",
    "font",
    "blockquote",
    "c",
    "block center",
}
# Bytes per page above which a source file is taken for a scan (born-digital PDFs hold a few kB).
SCANNED = 40_000
SOFT_HYPHEN, NBSP = chr(0xAD), chr(0xA0)
# A transcriber's note in brackets: several words ("[Twitter iletileri görüntüsü]", "[Cumhuriyet
# gazetesinin iç sayfalarından"); a footnote mark ("[1]") is not one.
DESCRIBED = re.compile(r"\[[^\]\d]*[^\W\d_]{3,}\s+[^\W\d_]{2,}")
# A page with fewer letters than this holds no text to read (a photograph, a blank page).
LETTERS = 20
# Footnotes go to the page's foot, where the scan shows them.
REF = re.compile(r"<ref(?:\s[^>/]*)?>(.*?)</ref>|<ref\s[^>]*/>", re.S)


def split_args(inner: str) -> tuple[str, list[str], dict[str, str]]:
    """A template's name, positional and named arguments (its inner templates already expanded)."""
    parts, depth, current = [], 0, ""
    for ch in inner:
        if ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        if ch == "|" and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += ch
    parts.append(current)
    name = parts[0].strip().lower().replace("_", " ")
    positional, named = [], {}
    for part in parts[1:]:
        key, eq, value = part.partition("=")
        if eq and re.fullmatch(r"\s*[\w ğüşıöçĞÜŞİÖÇ-]+\s*", key):
            named[key.strip().lower()] = value.strip()
        else:
            positional.append(part.strip())
    return name, positional, named


def render(  # noqa: PLR0911  (one return per kind of template reads best)
    name: str, positional: list[str], named: dict[str, str], unknown: Counter
) -> str:
    def arg(k: int, *names: str) -> str:
        for n in names:
            if named.get(n):
                return named[n]
        return positional[k] if len(positional) > k else ""

    if name in SILENT:
        return ""
    if name in FIRST:
        return arg(0, "1", "metin", "text")
    if name == "metin girintisi":
        return arg(1, "2")
    if name in {"rh", "runningheader"} or name.startswith("rh/"):
        sides = [named.get(k, "") for k in ("left", "center", "right")]
        return "\n" + " ".join(x for x in [*positional, *sides] if x.strip()) + "\n"
    if name in {"madde", "ek madde"}:
        title = named.get("başlık", "")
        label = "Madde" if name == "madde" else "Ek madde"
        return f"\n{title}\n{label} {named.get('numara', '')}".rstrip() + " "
    if name in {"bent", "altbent"}:
        return f"\n{named.get('numara', '')}) {named.get('metin', '')}"
    if name == "fıkra":
        return f"\n({named.get('numara', '')}) {named.get('metin', '')}"
    unknown[name] += 1
    return arg(0, "1", "metin", "text")


def expand(text: str, unknown: Counter) -> str:
    """Templates, innermost first, until none is left."""
    pattern = re.compile(r"\{\{(?!\{)((?:[^{}]|\{(?!\{)|\}(?!\}))*)\}\}")
    for _ in range(20):
        new = pattern.sub(lambda m: render(*split_args(m.group(1)), unknown), text)
        if new == text:
            break
        text = new
    return text


def table(text: str) -> str:
    """Wiki tables cell by cell, one cell a line."""
    out = []
    for line in text.split("\n"):
        s = line.strip()
        if s.startswith("{|") or s.startswith("|}") or s.startswith("|-") or s.startswith("|+"):
            if s.startswith("|+"):
                out.append(s[2:])
            continue
        if s.startswith(("|", "!")):
            for cell in re.split(r"\|\||!!", s[1:]):
                shown = cell
                # "style=... | text": the attributes go
                if "|" in cell and not re.search(r"\[\[[^\]]*\|", cell):
                    head, _, rest = cell.partition("|")
                    if "=" in head or not head.strip():
                        shown = rest
                out.append(shown.strip())
            continue
        out.append(line)
    return "\n".join(out)


def truth(wikitext: str, unknown: Counter | None = None) -> str:
    unknown = Counter() if unknown is None else unknown
    text = re.sub(r"<!--.*?-->", "", wikitext, flags=re.S)
    text = re.sub(r"<pagequality[^>]*/>|<section[^>]*/>|</?noinclude>", "\n", text)
    notes: list[str] = []

    def note(match: re.Match) -> str:
        if match.group(1) is None:
            return ""
        notes.append(match.group(1))
        return str(len(notes))

    text = REF.sub(note, text)
    text = re.sub(
        r"<references\s*/>|\{\{\s*(smallrefs|references|reflist)[^}]*\}\}", "", text, flags=re.I
    )
    if notes:
        text += "\n" + "\n".join(f"{k} {n}" for k, n in enumerate(notes, 1))
    text = re.sub(
        r"\[\[(?:Dosya|File|Resim|Image|Kategori|Category):[^\[\]]*(?:\[\[[^\]]*\]\][^\[\]]*)*\]\]",
        "",
        text,
        flags=re.I,
    )
    text = expand(text, unknown)
    text = table(text)
    text = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", text)
    text = re.sub(r"\[(?:https?:)?//[^\s\]]+\s+([^\]]*)\]", r"\1", text)
    text = re.sub(r"'{2,}", "", text)
    text = re.sub(
        r"<br\s*/?>|</?(p|div|poem|center|blockquote|li|tr)\b[^>]*>", "\n", text, flags=re.I
    )
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text).replace(SOFT_HYPHEN, "")
    text = re.sub(r"^[:;#*]+\s*", "", text, flags=re.M)
    text = re.sub(r"^=+\s*(.*?)\s*=+\s*$", r"\1", text, flags=re.M)
    lines = [re.sub(r"[ \t" + NBSP + "]+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


class _Text(HTMLParser):
    BLOCK = frozenset(
        {"p", "div", "br", "li", "tr", "td", "th", "h1", "h2", "h3", "h4", "table", "dd", "dt"}
    )

    # The law template writes an article's heading in one span and numbers its clauses "f1.",
    # "f2." in another. The page prints "1.", "2.", and no number when an article has one clause.
    ARTICLE = ("id", "Madde")
    CLAUSE_NUMBER = ("id", "fıkrano")

    # A footnote marker the wiki numbers itself ("[2]" where the page prints a superscript 3).
    FOOTNOTE_MARKER = ("class", "reference")

    def __init__(self) -> None:
        super().__init__()
        self.out: list[str] = []
        self.skip = 0
        self.clause_number = False
        self.markers = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"style", "script"}:
            self.skip += 1
        if tag in self.BLOCK:
            self.out.append("\n")
        if tag == "span" and self.ARTICLE in attrs:
            self.out.append(ARTICLE_MARK)
        if tag == "span" and self.CLAUSE_NUMBER in attrs:
            self.clause_number = True
        if tag == "sup" and (self.markers or self.FOOTNOTE_MARKER in attrs):
            self.markers += 1
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in {"style", "script"} and self.skip:
            self.skip -= 1
        if tag in self.BLOCK:
            self.out.append("\n")
        if tag == "span":
            self.clause_number = False
        if tag == "sup" and self.markers:
            self.markers -= 1
            self.skip -= 1

    def handle_data(self, data):
        if self.clause_number:
            data = re.sub(r"^f(?=\d)", CLAUSE_MARK, data)
        if not self.skip:
            self.out.append(data)


ARTICLE_MARK, CLAUSE_MARK = chr(1), chr(2)


def _clause_numbers(text: str) -> str:
    """Clause numbers as printed: an article with a single clause has none. The page's last
    article may go on overleaf, so its number stays."""
    parts = text.split(ARTICLE_MARK)
    for i in range(1, len(parts) - 1):
        if parts[i].count(CLAUSE_MARK) == 1:
            parts[i] = re.sub(CLAUSE_MARK + r"1\.\s*", "", parts[i])
    return "".join(parts).replace(CLAUSE_MARK, "")


def from_html(page_html: str) -> str:
    parser = _Text()
    parser.feed(page_html)
    text = _clause_numbers("".join(parser.out))
    text = text.replace("Bu sayfa doğrulanmış", "").replace(SOFT_HYPHEN, "")
    return "\n".join(line.strip() for line in text.split("\n") if line.strip())


def layout(root: Path, work: Path, labels_path: Path | None = None) -> None:
    """``labels`` (JSON, kept with the data) names the source files whose pages are not printed
    Latin-script transcriptions: "exclude" (a translation's original, Ottoman script, two
    languages, a watermark the digitiser added), "handwriting", "photo"; and single pages by
    revision ("pages": {revid: kind}). Every other scanned page is "scan"."""
    pages = json.loads((root / "pages.json").read_text(encoding="utf-8"))
    files = json.loads((root / "files.json").read_text(encoding="utf-8"))
    labels = json.loads(labels_path.read_text(encoding="utf-8")) if labels_path else {}
    by_file, by_page = labels.get("files", {}), labels.get("pages", {})
    (work / "truth").mkdir(parents=True, exist_ok=True)
    (work / "images").mkdir(parents=True, exist_ok=True)
    kept: Counter = Counter()
    for page in pages:
        rendered = root / "html" / f"{page['revid']}.html"
        image = root / "images" / f"{page['revid']}.jpg"
        source = files.get(page["file"])
        if not (rendered.exists() and image.exists() and source):
            continue
        text = from_html(rendered.read_text(encoding="utf-8"))
        # A transcriber who described a picture instead of reading it: "[Twitter görüntüsü]".
        if sum(c.isalpha() for c in text) < LETTERS or DESCRIBED.search(text):
            kept["skipped"] += 1
            continue
        per_page = source["bytes"] / max(1, source.get("pagecount") or 1)
        condition = "scan" if per_page >= SCANNED else "digital"
        kind = by_page.get(str(page["revid"])) or by_file.get(page["file"])
        if kind == "exclude":
            kept["excluded"] += 1
            continue
        if kind:
            condition = kind
        (work / "truth" / f"{page['revid']}.txt").write_text(text + "\n", encoding="utf-8")
        link = work / "images" / f"{page['revid']}.{condition}.jpg"
        if not link.exists():
            link.symlink_to(image.resolve())
        kept[condition] += 1
    print(f"laid out: {dict(kept)} in {work}")


def main() -> None:
    options = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = options.add_subparsers(dest="command", required=True)
    lay = sub.add_parser("layout")
    lay.add_argument("--root", type=Path, required=True)
    lay.add_argument("--work", type=Path, required=True)
    lay.add_argument("--labels", type=Path)
    t = sub.add_parser("truth")
    t.add_argument("--pages", type=Path, required=True)
    t.add_argument("--out", type=Path, required=True)
    t.add_argument("--html", type=Path)
    args = options.parse_args()
    if args.command == "layout":
        layout(args.root, args.work, args.labels)
        return
    pages = json.loads(args.pages.read_text(encoding="utf-8"))
    args.out.mkdir(parents=True, exist_ok=True)
    unknown: Counter = Counter()
    kept = 0
    for page in pages:
        text = truth(page["wikitext"], unknown)
        if sum(c.isalpha() for c in text) < LETTERS:
            continue
        (args.out / f"{page['revid']}.txt").write_text(text + "\n", encoding="utf-8")
        kept += 1
    print(f"{kept} truths written; templates not known: {unknown.most_common(15)}")
    if args.html:
        lost = total = 0
        for path in sorted(args.html.glob("*.html")):
            mine = args.out / f"{path.stem}.txt"
            if not mine.exists():
                continue
            rendered = Counter(words(from_html(path.read_text(encoding="utf-8"))))
            converted = Counter(words(mine.read_text(encoding="utf-8")))
            errors = max(sum((rendered - converted).values()), sum((converted - rendered).values()))
            lost += errors
            total += sum(rendered.values())
            if errors:
                print(
                    f"  {path.stem}: {errors} of {sum(rendered.values())}; rendered only "
                    f"{list((rendered - converted).elements())[:8]}, converted only "
                    f"{list((converted - rendered).elements())[:8]}"
                )
        if total:
            print(f"conversion against the rendering: {1 - lost / total:.4f} of {total} words")


if __name__ == "__main__":
    main()
