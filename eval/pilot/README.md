# Pilot evaluation

A blind test on a customer's own documents: the evidence a commercial claim can rest on. Everything else in `eval/` is a test we built ourselves; numbers from it are never presented as the product's performance on a customer's archive.

## Principles

- **Blind.** The customer's lawyers write the questions and hand them over after the installation. The system is not tuned to them.
- **Thresholds agreed before the test** and not changed afterwards.
- **The customer grades.** We do not take part in grading.
- **The documents stay in the office.** The system runs there, offline, on a release tagged for the test and not changed until it ends.
- **Every raw result is reported**, failures included.

Real customer documents enter the system only once every item of the security checklist is met.

## Steps

1. **Scope.** The customer picks 200 to 1,000 documents, keeping their real share of scanned and digital ones.
2. **Questions.** The lawyers write 40 to 60 things they actually looked for in the last three months, each with a short answer and the file it stands in, and 10 questions the archive has no answer to. For 10 questions they time how long finding the answer takes them today. The sheet comes from `template.py`.
3. **Run.** `run.py` asks every question through the installed system, each in a conversation of its own, and writes `results.csv` (answer, sources, time) and `grading.xlsx`. The customer can run it.
4. **Grading.** The customer's lawyer puts every answer in one of four classes, counted separately and never merged:
   - **Tam doğru** (fully right): an answer the lawyer can use;
   - **Kısmen doğru** (partly right): incomplete, but nothing wrong in it;
   - **Yanlış** (wrong): at least one wrong statement;
   - **Reddedildi** (refused): the system said it found nothing.

   A **critical legal error** is marked on its own, whatever the answer's class (a partly right answer can hold one): a wrong period or date, amount or calculation, party, person or file, case or document number, article of law or legislation, a reversed outcome, or a claim not in the sources presented as if it were. The lawyer also marks whether the right document is among the first ten sources (`run.py` guesses it from the file name).
5. **Report.** `report.py` computes the measures against the agreed thresholds and writes the report: every critical error with its question, answer and sources, then every question.
6. **OCR.** Ten random scanned pages are typed by hand and the word accuracy measured (eval/ocr/ measures word accuracy).

## Proposed thresholds

| Measure | Threshold |
|---|---|
| Right document among the first ten sources | at least 85% |
| Fully right | at least 65% |
| Fully or partly right | at least 80% |
| Wrong | at most 10% |
| Answerable questions refused | at most 10% |
| Unanswerable questions refused | at least 90% |
| Critical legal errors | target 0; more than one in 50 questions fails the test |
| Claims not in the sources | 0 |
| Time saved finding the answer | at least 50% |

The agreed ones go in a JSON file (`--thresholds`) with the keys of `report.THRESHOLDS`.

## Running it

```bash
uv run --directory backend python ../eval/pilot/template.py questions.xlsx
uv run --directory backend python ../eval/pilot/run.py questions.xlsx --base http://127.0.0.1:8080 \
  --email EVALUATOR --password-file FILE --out pilot-run
uv run --directory backend python ../eval/pilot/report.py questions.xlsx pilot-run/grading.xlsx \
  --thresholds thresholds.json --out pilot-run/report.md
uv run --directory backend pytest ../eval/pilot -q
```

The sheets are in Turkish, for the people who fill them in. The account `run.py` signs in with must be able to read every document of the test and must not need a second factor.
