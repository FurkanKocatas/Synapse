"""The pilot evaluation's metrics against the thresholds agreed before the test, and the report.

    uv run --directory backend python ../eval/pilot/report.py QUESTIONS.xlsx GRADING.xlsx \\
        [--thresholds thresholds.json] [--out report.md]

Every class is counted on its own (README.md, "Grading"); a critical legal error counts
whatever the class of its answer. The report lists every critical error with its question,
answer and sources, then every question.
"""

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path

from sheets import FULL, PARTIAL, REFUSED, WRONG, Graded, read_grading, read_questions

# The thresholds proposed in the evaluation plan; the ones agreed with the customer before the
# test replace them (--thresholds), and are not changed afterwards.
THRESHOLDS = {
    "found": 0.85,
    "full": 0.65,
    "usable": 0.80,
    "wrong": 0.10,
    "refused": 0.10,
    "unanswerable_refused": 0.90,
    "critical_per_50": 1,
    "unsupported": 0,
    "time_gain": 0.50,
}
UNSUPPORTED = "Kaynakta olmayan iddia"
# The grading sheet holds one source per line.
LINE = "\n"


@dataclass(frozen=True)
class Line:
    label: str
    value: str
    target: str
    passed: bool | None


def _share(part: int, whole: int) -> float:
    return part / whole if whole else 0.0


def _percent(value: float) -> str:
    return f"%{value * 100:.0f}".replace(".", ",")


def metrics(rows: list[Graded], thresholds: dict[str, float]) -> list[Line]:
    answerable = [r for r in rows if r.question.answerable]
    unanswerable = [r for r in rows if not r.question.answerable]
    count = len(answerable)

    def share_of(grade: str) -> float:
        return _share(sum(r.grade == grade for r in answerable), count)

    full, partial = share_of(FULL), share_of(PARTIAL)
    wrong, refused = share_of(WRONG), share_of(REFUSED)
    found = _share(sum(bool(r.found) for r in answerable), count)
    held = _share(sum(r.grade == REFUSED for r in unanswerable), len(unanswerable))
    critical = sum(r.critical is not None for r in rows)
    allowed = math.floor(len(rows) / 50 * thresholds["critical_per_50"])
    unsupported = sum(r.critical == UNSUPPORTED for r in rows)
    timed = [r for r in rows if r.question.manual_minutes and r.seconds is not None]
    manual = sum((r.question.manual_minutes or 0) * 60 for r in timed)
    gain = 1 - sum(r.seconds or 0 for r in timed) / manual if manual else None
    t = thresholds
    return [
        Line(
            "Doğru belge ilk 10 kaynakta",
            _percent(found),
            f"en az {_percent(t['found'])}",
            found >= t["found"],
        ),
        Line("Tam doğru cevap", _percent(full), f"en az {_percent(t['full'])}", full >= t["full"]),
        Line(
            "Tam ya da kısmen doğru cevap",
            _percent(full + partial),
            f"en az {_percent(t['usable'])}",
            full + partial >= t["usable"],
        ),
        Line(
            "Yanlış cevap", _percent(wrong), f"en çok {_percent(t['wrong'])}", wrong <= t["wrong"]
        ),
        Line(
            "Cevabı olan sorulardan reddedilen",
            _percent(refused),
            f"en çok {_percent(t['refused'])}",
            refused <= t["refused"],
        ),
        Line(
            "Cevabı olmayan sorulardan reddedilen",
            _percent(held),
            f"en az {_percent(t['unanswerable_refused'])}",
            held >= t["unanswerable_refused"],
        ),
        Line(
            "Kritik hukuki hata", str(critical), f"hedef 0, en çok {allowed}", critical <= allowed
        ),
        Line(
            "Kaynakta olmayan iddia",
            str(unsupported),
            f"en çok {int(t['unsupported'])}",
            unsupported <= t["unsupported"],
        ),
        Line(
            "Bulma süresinde kazanç",
            "ölçülmedi" if gain is None else _percent(gain),
            f"en az {_percent(t['time_gain'])}",
            None if gain is None else gain >= t["time_gain"],
        ),
    ]


def _cell(text: str) -> str:
    return " ".join(text.replace("|", "/").split()) or "-"


def render(rows: list[Graded], lines: list[Line]) -> str:
    answerable = sum(r.question.answerable for r in rows)
    out = [
        "# Değerlendirme sonucu",
        "",
        f"{len(rows)} soru: {answerable} sorunun cevabı arşivde var, "
        f"{len(rows) - answerable} sorunun yok. Puanlamayı müşterinin avukatı yaptı.",
        "",
        "| Ölçü | Sonuç | Eşik | Durum |",
        "|---|---|---|---|",
    ]
    status = {True: "geçti", False: "geçmedi", None: "-"}
    out += [f"| {x.label} | {x.value} | {x.target} | {status[x.passed]} |" for x in lines]
    counts = {
        g: sum(r.grade == g for r in rows if r.question.answerable)
        for g in (FULL, PARTIAL, WRONG, REFUSED)
    }
    out += [
        "",
        "Cevabı olan sorularda sınıflar: " + ", ".join(f"{g} {n}" for g, n in counts.items()) + ".",
    ]
    critical = [r for r in rows if r.critical]
    out += ["", "## Kritik hukuki hatalar", ""]
    if not critical:
        out.append("Yok.")
    for r in critical:
        out += [
            f"**Soru {r.question.number}** ({r.critical}): {r.question.text}",
            "",
            f"- Sistemin cevabı: {_cell(r.system_answer)}",
            f"- Beklenen cevap: {_cell(r.question.answer)}",
            f"- Gösterilen kaynaklar: {_cell(r.sources.replace(LINE, '; '))}",
            "",
        ]
    out += [
        "## Bütün sorular",
        "",
        "| No | Soru | Sınıf | Belge ilk 10'da | Kritik hata | Süre (sn) |",
        "|---|---|---|---|---|---|",
    ]
    for r in sorted(rows, key=lambda r: r.question.number):
        found = "-" if r.found is None else ("evet" if r.found else "hayır")
        seconds = "-" if r.seconds is None else f"{r.seconds:.0f}"
        out.append(
            f"| {r.question.number} | {_cell(r.question.text)} | {r.grade} | {found} | "
            f"{r.critical or '-'} | {seconds} |"
        )
    out += ["", "İç testlerin (benchmark) sonuçları bu raporun parçası değildir.", ""]
    return "\n".join(out)


def main() -> None:
    options = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    options.add_argument("questions", type=Path)
    options.add_argument("grading", type=Path)
    options.add_argument("--thresholds", type=Path)
    options.add_argument("--out", type=Path, default=Path("report.md"))
    args = options.parse_args()
    thresholds = dict(THRESHOLDS)
    if args.thresholds:
        thresholds |= json.loads(args.thresholds.read_text(encoding="utf-8"))
    questions = {q.number: q for q in read_questions(args.questions)}
    rows = read_grading(args.grading, questions)
    lines = metrics(rows, thresholds)
    args.out.write_text(render(rows, lines), encoding="utf-8")
    for line in lines:
        print(f"{line.label}: {line.value} ({line.target})")
    print(f"report: {args.out}")


if __name__ == "__main__":
    main()
