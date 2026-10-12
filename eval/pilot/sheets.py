"""The pilot evaluation's spreadsheets: the questions the customer's lawyers write, and the
grading sheet they fill in after the run.

The sheets are in Turkish, for the people who fill them in; the code reads and writes them by
column position, through the headings below, so a renamed heading is an error rather than a
column read as something else.
"""

from dataclasses import dataclass
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.worksheet import Worksheet

YES, NO = "Evet", "Hayır"
FULL, PARTIAL, WRONG, REFUSED = "Tam doğru", "Kısmen doğru", "Yanlış", "Reddedildi"
GRADES = (FULL, PARTIAL, WRONG, REFUSED)
NO_ERROR = "Yok"
CRITICAL = (
    "Süre ya da tarih",
    "Tutar ya da hesap",
    "Taraf, kişi ya da dosya",
    "Esas, karar ya da evrak numarası",
    "Kanun maddesi ya da mevzuat",
    "Sonucun tersine çevrilmesi",
    "Kaynakta olmayan iddia",
)

QUESTION_SHEET = "Sorular"
QUESTION_HEADINGS = (
    "No",
    "Soru",
    "Kısa doğru cevap",
    "Cevabın geçtiği belge (dosya adı)",
    "Arşivde cevabı var mı? (Evet/Hayır)",
    "Bugünkü yöntemle bulma süresi (dakika)",
    "Not",
)
QUESTION_HELP = (
    "Son üç ayda gerçekten aradığınız bilgileri soru olarak yazın: 40-60 soru.",
    "Her soru için kısa doğru cevabı ve cevabın geçtiği belgenin dosya adını yazın.",
    "Arşivde cevabı olmayan 10 soru da ekleyin; onlarda cevap ve belge boş kalır, "
    "üçüncü sütuna Hayır yazın.",
    "10 soruda bilgiyi bugünkü yönteminizle kaç dakikada bulduğunuzu kronometreyle ölçüp yazın.",
    "Soruları sistemi kurduktan sonra verin; sistem sorulara göre ayarlanmaz.",
)

GRADING_SHEET = "Puanlama"
GRADING_HEADINGS = (
    "No",
    "Soru",
    "Beklenen cevap",
    "Beklenen belge",
    "Sistemin cevabı",
    "Gösterilen kaynaklar",
    "Belge ilk 10 kaynakta mı? (otomatik tahmin)",
    "Cevap süresi (saniye)",
    "Bugünkü yöntemle süre (dakika)",
    "Sınıf",
    "Doğru belge ilk 10 kaynakta mı?",
    "Kritik hukuki hata",
    "Not",
)
# The columns the lawyer fills in (1-based, as spreadsheets count).
GRADE_COLUMN, FOUND_COLUMN, CRITICAL_COLUMN = 10, 11, 12
GRADING_HELP = (
    "Her satırda Sınıf sütununu doldurun: Tam doğru (kullanabileceğiniz cevap), Kısmen doğru "
    "(eksik ama yanlış bilgi yok), Yanlış (en az bir yanlış bilgi), Reddedildi (sistem "
    "bulunamadı dedi). Sınıflar ayrı sayılır.",
    "Doğru belge gösterilen ilk 10 kaynak arasında mı? Otomatik tahmini kontrol edip Evet ya da "
    "Hayır yazın.",
    "Cevapta kritik hukuki hata varsa türünü seçin, yoksa Yok bırakın. Kısmen doğru bir cevapta "
    "da kritik hata olabilir.",
)


@dataclass(frozen=True)
class Question:
    number: int
    text: str
    answer: str
    document: str
    answerable: bool
    manual_minutes: float | None


@dataclass(frozen=True)
class Graded:
    question: Question
    system_answer: str
    sources: str
    seconds: float | None
    grade: str
    found: bool | None
    critical: str | None


def _heading_row(sheet: Worksheet, headings: tuple[str, ...]) -> None:
    sheet.append(list(headings))
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        cell.fill = PatternFill("solid", fgColor="E6E6E6")
    sheet.freeze_panes = "A2"


def _help_sheet(book: Workbook, lines: tuple[str, ...]) -> None:
    sheet = book.create_sheet("Nasıl doldurulur")
    sheet.column_dimensions["A"].width = 110
    for line in lines:
        sheet.append([line])
        sheet.cell(sheet.max_row, 1).alignment = Alignment(wrap_text=True)


def _choice(sheet: Worksheet, values: tuple[str, ...], cells: str) -> None:
    rule = DataValidation(type="list", formula1='"' + ",".join(values) + '"', allow_blank=True)
    sheet.add_data_validation(rule)
    rule.add(cells)


def write_question_template(path: Path, rows: int = 70) -> None:
    book = Workbook()
    sheet = book.active
    sheet.title = QUESTION_SHEET
    _heading_row(sheet, QUESTION_HEADINGS)
    for number in range(1, rows + 1):
        sheet.append([number])
    for letter, width in zip("ABCDEFG", (6, 60, 40, 40, 16, 18, 30), strict=True):
        sheet.column_dimensions[letter].width = width
    _choice(sheet, (YES, NO), f"E2:E{rows + 1}")
    _help_sheet(book, QUESTION_HELP)
    book.save(path)


def _sheet(path: Path, name: str, headings: tuple[str, ...]) -> Worksheet:
    sheet = load_workbook(path, data_only=True)[name]
    found = tuple(str(c.value or "").strip() for c in sheet[1][: len(headings)])
    if found != headings:
        raise ValueError(f"{path.name}: the {name} sheet's headings are not the template's")
    return sheet


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _minutes(value: object) -> float | None:
    text = _text(value).replace(",", ".")
    return float(text) if text else None


def read_questions(path: Path) -> list[Question]:
    questions = []
    for row in _sheet(path, QUESTION_SHEET, QUESTION_HEADINGS).iter_rows(
        min_row=2, values_only=True
    ):
        number, text, answer, document, answerable, minutes = (list(row) + [None] * 7)[:6]
        if not _text(text):
            continue
        flag = _text(answerable).casefold()
        if flag not in {YES.casefold(), NO.casefold()}:
            raise ValueError(f"question {number}: write {YES} or {NO} in the third column")
        questions.append(
            Question(
                number=int(number),
                text=_text(text),
                answer=_text(answer),
                document=_text(document),
                answerable=flag == YES.casefold(),
                manual_minutes=_minutes(minutes),
            )
        )
    if len({q.number for q in questions}) != len(questions):
        raise ValueError("two questions share a number")
    return questions


@dataclass(frozen=True)
class Result:
    question: Question
    status: str
    answer: str
    sources: list[str]
    document_in_top10: bool | None
    seconds: float | None


def write_grading(path: Path, results: list[Result]) -> None:
    book = Workbook()
    sheet = book.active
    sheet.title = GRADING_SHEET
    _heading_row(sheet, GRADING_HEADINGS)
    for result in results:
        q = result.question
        guess = (
            None if result.document_in_top10 is None else (YES if result.document_in_top10 else NO)
        )
        sheet.append(
            [
                q.number,
                q.text,
                q.answer if q.answerable else "(arşivde cevabı yok)",
                q.document,
                result.answer or "Belgelerde bulunamadı.",
                "\n".join(result.sources),
                guess,
                result.seconds,
                q.manual_minutes,
                REFUSED if result.status != "answered" else None,
                guess,
                NO_ERROR,
                None,
            ]
        )
        for cell in sheet[sheet.max_row]:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    last = len(results) + 1
    widths = (6, 45, 35, 30, 60, 45, 14, 10, 12, 16, 14, 26, 30)
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[sheet.cell(1, index).column_letter].width = width
    _choice(sheet, GRADES, f"J2:J{last}")
    _choice(sheet, (YES, NO), f"K2:K{last}")
    _choice(sheet, (NO_ERROR, *CRITICAL), f"L2:L{last}")
    _help_sheet(book, GRADING_HELP)
    book.save(path)


def read_grading(path: Path, questions: dict[int, Question]) -> list[Graded]:
    graded = []
    sheet = _sheet(path, GRADING_SHEET, GRADING_HEADINGS)
    for row in sheet.iter_rows(min_row=2, values_only=True):
        cells = list(row) + [None] * len(GRADING_HEADINGS)
        if cells[0] is None:
            continue
        number = int(cells[0])
        grade = _text(cells[GRADE_COLUMN - 1])
        if grade not in GRADES:
            raise ValueError(f"question {number}: the grade must be one of {', '.join(GRADES)}")
        found = _text(cells[FOUND_COLUMN - 1])
        critical = _text(cells[CRITICAL_COLUMN - 1]) or NO_ERROR
        if critical != NO_ERROR and critical not in CRITICAL:
            raise ValueError(f"question {number}: unknown critical error {critical!r}")
        seconds = cells[7]
        graded.append(
            Graded(
                question=questions[number],
                system_answer=_text(cells[4]),
                sources=_text(cells[5]),
                seconds=float(seconds) if isinstance(seconds, (int, float)) else None,
                grade=grade,
                found=None if not found else found == YES,
                critical=None if critical == NO_ERROR else critical,
            )
        )
    return graded
