# OCR in October 2026, and what 99% takes

Written 2026-10-03, when OCR became the product's first priority: **99% of words exactly right** on Turkish and English documents first (German, Russian and others later), scanned and born-digital, tables and handwriting included, run on the customer's own hardware. Time per page is not a constraint; a page may take minutes. This document gathers what is known, so the design rests on evidence and is then decided by measurement on our own data ([benchmarks/ocr.md](../benchmarks/ocr.md)), not on leaderboards.

**Method.** Four surveys of primary sources (model cards, repositories, licence files, papers, leaderboards) on 2026-10-03: the open models; what was released in 2026; Turkish OCR and handwriting; the techniques of systems that reach 99%. Figures are as their sources report them: different benchmarks use different metrics, and most are not word accuracy. "Self-reported" means the model's authors measured it. Vendor numbers are marked.

## The target, precisely

- **Word accuracy**: 1 minus the word error rate (edits over the truth's words) after aligning the output with the truth by line or region, so that reading order alone does not count as an error; Unicode NFC on both sides; case-sensitive; Turkish casing where case is folded at all (Python's `lower()` turns "İ" into "i" plus a combining dot and "I" into "i").
- **Identifiers and numbers** (decision and law numbers, dates, amounts, codes) separately, exact match, target 99.5%: one wrong digit is the most harmful error for search and answers.
- **Per stratum**, never pooled: {Turkish, English} × {born-digital, clean scan, degraded scan or photocopy or fax, phone photo, tables, handwriting}.
- **Turkish words are long** (about 6.6 characters with the space, against 4.0 in English handwriting sets), so the same character error rate costs more words: 99% of words needs a character error rate of about 0.15% in Turkish against 0.25% in English if errors are spread out ([Sabancı thesis](https://research.sabanciuniv.edu/id/eprint/47179/); derived).
- **Claiming it** needs enough words: to show the error is below 1% with 95% confidence when the observed error is 0.7%, about 45,000 words (150 pages) per stratum, allowing for errors clustering by page; at 0.5%, about 14,000 words (48 pages). For identifiers, no error in 3,000 shows less than 0.1%. Ground truth must be double-keyed: the error of the truth must be far below 1%.

**Where we are** (Tesseract 5 `tur+eng`, what the product runs today, on the benchmark of [benchmarks/ocr.md](../benchmarks/ocr.md); word accuracy with reading order counted, which understates table and multi-column pages): 90.1% on clean renders, 89.2% on simulated scans, 86.6% on poor ones, about 95% on 3 hand-verified real scans (594 words).

## What the field reports

### Page parsers

The specialised document models of 2026 are small (0.8 to 1.4 billion parameters), permissively licensed, fit a 12 GB GPU at full precision, and lead the main leaderboard, [OmniDocBench v1.6](https://github.com/opendatalab/OmniDocBench) (README of 2026-09-11; overall = text, tables and formulas):

| Model | Size | Licence (weights) | Overall | Text edit distance | Table TEDS | Turkish |
|---|---|---|---|---|---|---|
| TeleOCR | 1.4B | Apache-2.0 | 96.91 | 0.027 | 96.82 | not stated (card: zh, en) |
| OvisOCR2 | 0.85B | Apache-2.0 | 96.47 | 0.027 | 94.58 | not stated |
| PaddleOCR-VL-1.6 | 0.96B | Apache-2.0 | 96.34 | 0.033 | 94.76 | listed (109 languages) |
| MinerU2.5-Pro | 1.2B | Apache-2.0 (toolkit: custom) | 95.75 | 0.036 | 93.42 | zh, en only |
| GLM-OCR | 0.9B | MIT | 95.22 | 0.044 | 92.83 | no (8 languages) |
| Gemini 3 Pro (closed) | | | 92.91 | 0.064 | 89.15 | |

That board is **saturated**: the top models are within 1.5 points, about 12% of its scored blocks carry annotation errors ([PureDocBench](https://arxiv.org/abs/2605.07492)), and on harder sets the order changes and scores fall: 58 models lose 3.3 points on degraded renders and 11.6 on real photographs ([PureDocBench](https://arxiv.org/abs/2605.07492)); the leaders score 55 to 68 on Dr.DocBench (self-reported in the [TeleOCR card](https://huggingface.co/StarDoc-AI/TeleOCR)); on a real-world table set the best parser scores 85 TEDS ([arXiv 2608.09842](https://arxiv.org/abs/2608.09842)); on degraded microfilm the best local model (Qwen3.6-35B-A3B) has a median character error rate of 1.7% but a mean of 9 to 11%, because a few pages fail completely ([arXiv 2607.24077](https://arxiv.org/html/2607.24077v3)). Rankings must come from our own documents.

### Turkish

Turkish is barely covered: none of the leading 2026 specialist cards but PaddleOCR-VL's lists it, and no public benchmark has Turkish scans, photocopies, faxes or photographs.

- [OCRTurk](https://aclanthology.org/2026.sigturk-1.16/) (180 born-digital pages, academic use only): page-level normalised edit distance PaddleOCR-VL 0.08, HunyuanOCR 0.09, olmOCR 2 0.09, DeepSeek-OCR 0.12, Docling 0.13; Turkish-character sensitivity (1 minus the error rate on ç ğ ı ö ş ü and capitals) HunyuanOCR 0.88, PaddleOCR-VL 0.82, olmOCR 2 0.80. Typical errors: "ğ" written as a breve and "g", "İ" read as "Ì", doubled letters dropped ("Kuvvet": "Kuvet"), spaces lost.
- [MORE](https://arxiv.org/pdf/2607.02956) (Turkish subset of 10 digital pages, scored per text block): HunyuanOCR 99.74, dots.ocr 99.55, PaddleOCR-VL 99.16, Qwen3-VL-2B 98.33. The gap with OCRTurk is reading order and skipped blocks, not characters: our metric aligns before it counts.
- A synthetic Turkish benchmark ([IJDAR 2026](https://link.springer.com/article/10.1007/s10032-026-00613-6); 6,600 images, [CC BY 4.0](https://zenodo.org/records/17163025)): GPT-4o character error rate 0.017, Qwen2.5-VL-7B comparable, PaddleOCR 0.239; Turkish letters and blur hurt every model.
- Classical recognisers: PP-OCRv5's server model has no "İ" or "Ğ" in its dictionary; its Latin model and PP-OCRv6 medium have all twelve Turkish letters ([model files](https://huggingface.co/PaddlePaddle/PP-OCRv6_medium_rec)). PP-OCRv5 on 5,198 rendered Turkish pages: 32% word error on clean, 65 to 124% under blur, noise or low resolution ([dataset card](https://huggingface.co/datasets/sfidan42/turkish-ocr-noise-corpus-v2)).
- Vendor tables put Turkish among the weakest Latin-script languages: Chandra 2 84.1% against German 94.8% ([Chandra](https://github.com/datalab-to/chandra/blob/master/FULL_BENCHMARKS.md)).

### Handwriting

- English, best local results: about 7% word error on full IAM pages for specialised models ([ExpertHTR](https://arxiv.org/abs/2609.12705)), about 4% for open vision-language models zero-shot (possibly seen in training; [arXiv 2503.15195](https://arxiv.org/abs/2503.15195)), but 28% under a strict line-level protocol ([OmniHandwritingOCR](https://arxiv.org/abs/2608.18586)). In the wild, the best model (cloud) scores below humans, and large general models (27B to 400B) beat small OCR specialists ([WildHandBench](https://arxiv.org/abs/2608.22959)).
- Turkish: the only real line-level set (73 writers, 2,641 lines; no licence, not downloadable) gives 18.6% word error at best ([Sabancı thesis](https://research.sabanciuniv.edu/id/eprint/47179/)). No model has been evaluated on real modern Turkish handwriting.
- **99% of words on free handwriting is not reachable with local models today**, in either language. It becomes plausible on constrained fields (digits, dates, TC kimlik numbers and IBANs with their checksums, names against master data, block capitals), with two agreeing engines and human review of the rest; a writer's own 16 lines cut errors by a quarter, 256 lines by half ([arXiv 2302.06308](https://arxiv.org/abs/2302.06308)).

### Faithfulness: the risk that decides the design

Vision-language models do not only misread; they write fluent text the image does not support. Under perturbed text, general models lose up to 6.9 points of word error, OCR-specialised ones 0.1 to 3.4, classical engines under 0.8; about 10% of words of 4 to 6 letters are "corrected" ([FaithC4](https://arxiv.org/abs/2607.21617)). Reported failures include invented invoice numbers ([arXiv 2605.22413](https://arxiv.org/abs/2605.22413)), text on blank pages, repetition loops ([olmOCR 2](https://arxiv.org/abs/2510.19817)), spelling normalised and names substituted ([arXiv 2607.24077](https://arxiv.org/html/2607.24077v3)). A classical recogniser (CTC decoding) cannot invent free text: PP-OCRv6 was free of hallucination on 93.2% of a test set against 80.6% for Qwen3-VL-235B (vendor-run, [PP-OCRv6](https://arxiv.org/html/2606.13108v1)). Their errors differ in kind, which is what voting needs.

### How 99% is reached in practice

- **Redundant, different engines, aligned and voted**: progressive alignment of 5 engines cut word error by 25% against the best one, the oracle of all their alternatives by 55% ([Lund et al.](https://scholarsarchive.byu.edu/etd/4024)); a 5-stream vote halved character error in a 2026 study ([arXiv 2607.00250](https://arxiv.org/abs/2607.00250)); three models compared by their mutual edit distance route only the 7% they disagree on to a stronger model ([Consensus Entropy](https://arxiv.org/abs/2504.11101)).
- **Correction that sees the image**: a second engine with the page image brought handwriting from 3.6% to 1.1% character error ([arXiv 2502.20295](https://arxiv.org/abs/2502.20295)) and German directories from 3.67% to 0.84% ([arXiv 2504.00414](https://arxiv.org/abs/2504.00414)). Text-only correction by language models makes agglutinative languages worse: for Finnish, open models raised the error by 19 to 77% ([arXiv 2502.01205](https://arxiv.org/abs/2502.01205)), and Turkish is the same kind of language. Corrections must be limited to words the engines disagree on, and to readings some engine produced.
- **A valid text layer is the best reader of a born-digital page** (table cells 0.980 against 0.929 for the best OCR, [arXiv 2512.10888](https://arxiv.org/abs/2512.10888)), but it must be validated: about 29% of real PDFs needed OCR in FinePDFs, whose classifier for it reached only 0.71 F1 ([FinePDFs](https://huggingfacefw-finepdfsblog.hf.space/)).
- **Abstention**: industrial 99% is 99% on what the system accepts. The 2010 US Census reached 99.56% field accuracy while accepting 86.4% of handwritten fields, the rest keyed by people ([FCSM 2012](https://apps.bea.gov/icsp/fcsm/assets/docs/Paxton_2012FCSM_IV-D.pdf)). Models' own confidence is poorly calibrated (verbalised confidence AUROC 0.54 to 0.74); combined signals (agreement between engines, image quality, layout, validation rules) reach 0.90 to 0.99 and let 49 to 72% of fields through at the target error ([arXiv 2609.20110](https://arxiv.org/abs/2609.20110)).
- **Images**: at least 300 dpi (by the height of capitals), deskew, local inversion of white-on-dark cells (Tesseract needs dark on light), no binarisation for neural engines (it raised their errors), dewarping for photographs (it halves their error but leaves them far above 1%: photographs need re-capture or review; [arXiv 2505.21975](https://arxiv.org/abs/2505.21975)). Each step is kept only where it lowers the error on its stratum.

## Licences

Commercial on-premises use needs the weights' licence to allow it, not only the code's.

- **Clean** (Apache-2.0 or MIT): PaddleOCR-VL 1.5 and 1.6, PP-OCRv6, TeleOCR, OvisOCR2, GLM-OCR, MinerU2.5-Pro weights, dots.mocr, DeepSeek-OCR 2, Unlimited-OCR, Qianfan-OCR, LightOnOCR-2, olmOCR 2, Qwen3.5, Qwen3.6, Qwen3.8-27B, Qwen3-VL, Gemma 4, Tesseract, docTR, Kraken.
- **Excluded**: Chandra 2 and Surya 2 (modified OpenRAIL-M, free only under USD 2M or 5M of revenue; Chandra also bars competing use), HunyuanOCR (excludes the EU, the UK and South Korea), jina-ocr-v1 (non-commercial), Youtu-Parsing (not for the EU), Nanonets-OCR2-3B, MonkeyOCR-pro-3B, Dolphin-v2 and everything else built on Qwen2.5-VL-3B (research licence), models with no licence on their card (Logics-Parsing, TrOCR handwritten), Mistral OCR 4 (closed).
- **Review before use**: the MinerU toolkit (Apache-2.0 plus thresholds and mandatory attribution since 2026-04-17); NVIDIA's Open Model License.
- **Evaluation data** is often non-commercial (OmniDocBench, OCRTurk, IAM, FUNSD, XFUND): at most for internal reference, never for training.

## Candidates to measure

| Role | Candidates | Why |
|---|---|---|
| Page parser (layout, reading order, tables) | PaddleOCR-VL-1.6 with PP-DocLayout; TeleOCR; OvisOCR2; dots.mocr; MinerU2.5-Pro (tables) | best permissive parsers; only PaddleOCR-VL lists Turkish, the rest must prove it |
| Classical readers (cannot invent text; character confidences) | PP-OCRv6 medium (Turkish letters, not PP-OCRv5 server); Tesseract 5 `tur` (today's, fine-tunable) | voters and guards against invented text |
| Strong second reader for hard regions | Qwen3.5-9B or Qwen3-VL-8B (8-bit on 12 GB); Qwen3.6-35B-A3B (experts on the CPU); Qwen3.8-27B (24 GB or more) | best on degraded pages and handwriting; highest risk of rewriting, so never alone |
| Text layer of born-digital PDFs | PDFium (today's) with per-page validation | the best reader when it is sound |

Inference: vLLM 0.30 and llama.cpp support nearly all of them; at full precision or 8 bits (no study shows 4 bits harmless for OCR). The production mini PC (Radeon 680M, Vulkan) runs llama.cpp only, and its vision path had a fixed but recent quality bug (llama.cpp #20081).

## Data for measuring

- **Usable**: our corpus (97 public documents, the truth from their own text layers; printed and scanned again for real degradations, the truth is exact and nobody has trained on it); Turkish synthetic sets ([IJDAR set](https://zenodo.org/records/17163025) CC BY 4.0, [Werea enterprise v2](https://huggingface.co/datasets/Werea-co/werea-tr-doc-ocr-enterprise-v2) Apache-2.0 with 12 document types × clean, scan and photo, [TR-DocVQA-Synth](https://huggingface.co/datasets/Ethosoft/TR-DocVQA-Synth) CC BY 4.0); [olmOCR-Bench](https://huggingface.co/datasets/allenai/olmOCR-bench) (ODC-BY, English, with tests for text that must not appear); tables from PubTabNet and FinTabNet (CDLA-Permissive); handwriting from [GNHK](https://github.com/GoodNotes/GNHK-dataset) (CC BY 4.0, phone photographs) and Bentham (CC BY 4.0).
- **To build**: Turkish scans, photocopies, faxes and photographs with exact truth (print the corpus, degrade it physically); Turkish handwriting (consented collection, double-keyed). No public set covers either.

## The design this points to (a hypothesis, decided by measurement)

1. **Route each page**: validate the text layer (garbled encodings, missing Unicode maps, agreement with an OCR of the rendered page); a sound layer is read, a doubtful one becomes one voter.
2. **Prepare the image**: 300 dpi or more, orientation, deskew, local inversion; dewarping and shadow removal for photographs; every step justified on its stratum; the original kept beside it.
3. **Layout first**: regions, reading order, tables, then recognition per region at native resolution.
4. **Read each region several times, differently**: a page parser, a classical recogniser, and for hard regions a large model; align them per line and vote.
5. **Resolve disagreements by looking again**: re-read the crop at a higher resolution or in variants; a model may choose among the engines' readings or abstain, never write a new one; numbers and identifiers change only when two engines agree.
6. **Validate**: dates, checksums (TC kimlik, IBAN), totals; Turkish spelling as a flag (Zemberek), never as an automatic correction.
7. **Know what it does not know**: calibrated confidence from agreement, image quality and validation; words below the threshold marked as uncertain (in search, answers and the viewer) and offered for review; accuracy reported on accepted words together with the share accepted.

## Plan

1. **Measurement before models**: word accuracy, identifier accuracy, Turkish-character sensitivity, table TEDS, invented-text and skipped-line rates, worst decile, per stratum, with confidence intervals; the strata built from the data above.
2. **Single engines** on the test machine (RTX 4070, 12 GB): every candidate above, each measured per stratum, with its time per page; then the same on the production mini PC for what runs there.
3. **Combinations**: voting, re-reading, validation, abstention; each stage kept only for what it measurably adds.
4. **The product**: the chosen pipeline in the ingestion jobs, with progress and time estimates on the documents page (OCR will take minutes per page) and uncertain words marked.

## Sources

The surveys' full notes with every figure and link were kept with the session; the figures above link their primary sources. Main ones: [OmniDocBench](https://github.com/opendatalab/OmniDocBench), [PureDocBench](https://arxiv.org/abs/2605.07492), [OCRTurk](https://aclanthology.org/2026.sigturk-1.16/), [MORE](https://arxiv.org/pdf/2607.02956), [PaddleOCR-VL-1.6](https://arxiv.org/pdf/2606.03264), [PP-OCRv6](https://arxiv.org/html/2606.13108v1), [FaithC4](https://arxiv.org/abs/2607.21617), [degraded documents and hallucination types](https://arxiv.org/html/2607.24077v3), [OmniHandwritingOCR](https://arxiv.org/abs/2608.18586), [WildHandBench](https://arxiv.org/abs/2608.22959), [OCR-D evaluation spec](https://ocr-d.de/en/spec/ocrd_eval), [Unicode SpecialCasing](https://www.unicode.org/Public/UCD/latest/ucd/SpecialCasing.txt), [Census 2010 data capture](https://apps.bea.gov/icsp/fcsm/assets/docs/Paxton_2012FCSM_IV-D.pdf), [llama.cpp multimodal](https://github.com/ggml-org/llama.cpp/blob/master/docs/multimodal.md).
