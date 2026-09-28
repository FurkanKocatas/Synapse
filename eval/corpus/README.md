# Synapse evaluation corpus (manifest)

This folder describes a corpus of 100 publicly available Turkish documents used to evaluate Synapse, an on-prem document RAG assistant for Turkish municipalities, law firms and healthcare organizations. It holds only the manifest (`manifest.csv`); no document bodies were downloaded. Each row gives a direct file URL, a landing page, and metadata collected on 2026-09-28.

## Composition

| Sector | PDF | DOCX | DOC | XLSX | PPTX | Total |
|---|---:|---:|---:|---:|---:|---:|
| Municipal | 31 | 3 | 0 | 5 | 2 | 41 |
| Legal | 24 | 5 | 2 | 0 | 1 | 32 |
| Health | 21 | 1 | 1 | 3 | 1 | 27 |
| **Total** | **76** | **9** | **3** | **8** | **4** | **100** |

Scanned status (PDF only):

| is_scanned | Count |
|---|---:|
| yes (confirmed by viewing the text layer) | 12 |
| no | 60 |
| unknown | 4 |

The 12 scanned PDFs are 7 municipal (Karabük, Bilecik, Serdivan council decisions and reports; Karabük and Bolu encümen decisions), 2 legal (Danıştay İçtihadı Birleştirme decisions from 1970 and 1972) and 3 health (Sağlık Bakanlığı genelgeleri 2021/3, 2022/7, 2024/11 annex). One PPTX also has an unknown status for embedded images.

- Total size (sum of HEAD `Content-Length`): 315,564,645 bytes (about 316 MB, 301 MiB). Every row has a size.
- Approximate page count: about 4,300 pages over the 82 rows with a numeric estimate. Most page counts are estimates, not measured.
- Personal data flag: 55 `none`, 43 `public officials`, 2 `unknown`.
- Municipal sources come from 28 municipalities (metropolitan and district, all regions), plus one ministry guide.

### Content by sector

- **Municipal (41):** 10 meclis kararları (including numbered decisions such as "2026/16", three of which adopt regulations), 4 encümen kararları, 3 municipal regulations as DOCX, 5 faaliyet raporları, 4 stratejik planlar (2025 to 2029), 2 budget or performance program PDFs, 5 XLSX budget and tariff tables (Ankara BB, İBB), 2 PPTX presentations, 4 imar plan notları or plan açıklama raporları, and the ministry guide on council meeting procedure.
- **Legal (32):** 13 laws from mevzuat.gov.tr (5393, 5216, 6698, 4734, 4735, 1136, 6098, 5846, 3194, 4982, 5018, 2577, 6100), Belediye Meclisi Çalışma Yönetmeliği (.doc), high court decisions (Anayasa Mahkemesi and Yargıtay İBBGK decisions from Resmî Gazete, Danıştay İBK decisions), KVKK guides, Board principle decisions and a DOCX privacy notice, bar association AI guides (TBB, Ankara Barosu), the 2025/2026 attorney minimum fee comparison table, 4 Adalet Bakanlığı mediation templates (DOCX) and 1 KVKK/GDPR PPTX.
- **Health (27):** 3 health laws and 2 regulations from mevzuat.gov.tr (1593, 3359, 1219, Kişisel Sağlık Verileri Hakkında Yönetmelik, Hasta Hakları Yönetmeliği), SKS Hastane 6.1 set with its XLSX version, SKS ADSH, SKS indicator guide, infection control programs and guides, COVID-19 guides, hypertension and type 1 diabetes guides, TİTCK guidelines, TİTCK XLSX lists (reference-priced drugs, biocidal products), the TİTCK adverse reaction form (DOCX), a Ministry training PPTX, Sağlık İstatistikleri Yıllığı 2024 and 3 scanned genelgeler.

## Selection criteria

1. Publicly posted by an official source: a municipality website, a ministry, a court, KVKK, TİTCK, the official legislation portal (mevzuat.gov.tr) or Resmî Gazete. Bar associations and one chamber of commerce are the only non-government publishers.
2. The direct file URL answered an HTTP HEAD request with status 200 and a document content type (PDF, DOCX, DOC, XLSX, PPTX) on 2026-09-28. Sizes come from that response.
3. Features that stress a RAG pipeline: large and multi-page tables (budgets, strategic plans, statistics yearbook, SKS sets), numbered identifiers ("2025/35 sayılı", E./K. numbers, article and fıkra references, genelge numbers), scanned pages that need OCR, near-duplicate documents (two versions of one template, related laws such as 4734 and 4735), old Turkish orthography (1593, 1219) and heavy amendment footnotes.
4. A spread of dates (1930 to 2026), with most municipal items from 2024 to 2026.
5. Format mix targets: at least 10 scanned PDFs, 8 DOCX, 6 XLSX and 3 PPTX. All targets are met.

## Copyright basis

Turkish Law No. 5846 on Intellectual and Artistic Works (Fikir ve Sanat Eserleri Kanunu, FSEK), Article 31 ("Mevzuat ve içtihatlar"), provides that officially published or announced laws, regulations (tüzük, yönetmelik), communiqués (tebliğ), circulars (genelge) and judicial decisions (kazai kararlar) may be freely reproduced, distributed, adapted and used in any way. The wording was checked against the consolidated text of the law (the mevzuat.gov.tr PDF of 5846 is itself row doc-049 in the manifest).

Scope of that basis in this corpus:

- **Clearly covered:** laws and regulations from mevzuat.gov.tr, Resmî Gazete court decisions, Danıştay İBK decisions, Sağlık Bakanlığı genelgeleri, KVKK Board principle decisions, and municipal council decisions that adopt or publish regulations.
- **Not clearly covered:** faaliyet raporları, stratejik planlar, budget tables, imar plan reports, clinical guidelines, SKS books, TİTCK guidelines, KVKK guides, bar association guides, templates and presentations. These are publicly posted institutional publications, not texts listed in Article 31, and may carry the publisher's copyright. The manifest marks them "internal evaluation use only". Keep any copies inside the evaluation environment and do not redistribute them.
- Municipal council and encümen decisions are administrative decisions, not judicial ones. Treating them as within Article 31 is a reasonable reading but not settled.

## Exclusions

- Any document that names private individuals together with identifiers (T.C. kimlik no, address, parcel ownership linked to a named person) or contains health records. An encümen decision and a 1984 Danıştay decision were rejected on this basis.
- Documents whose URL failed HEAD or returned HTML instead of a file (see Known gaps).
- Legacy PowerPoint (.ppt) files.
- Public officials' names in signed documents (mayors, council members, judges, guideline authors) are accepted and flagged `public officials`.

## Known gaps and caveats

- **Page counts:** most are estimates. 18 rows have no numeric count (XLSX workbooks and some Resmî Gazete files).
- **Scanned status:** set by viewing a PDF's text layer where possible. 4 large PDFs (over 10 MB) are marked `unknown`. PDFs marked `no` without viewing (most mevzuat.gov.tr files) are born-digital, but this was not confirmed file by file.
- **DOC vs DOCX:** mevzuat.gov.tr serves older regulations only as legacy `.doc` (application/msword), so 3 rows are DOC, not DOCX.
- **Mirrored source:** the TBB AI guide URL is a news-site CDN mirror (hukukihaber.net) because barobirlik.org.tr returned HTTP 402. Replace it with the TBB original when one can be reached.
- **Non-legal publisher:** the KVKK/GDPR PPTX is from Deniz Ticaret Odası, and it and the Polatlı Belediyesi PPTX have personal data status `unknown`. Review both before ingestion.
- **Unconfirmed landing pages:** about 18 municipal rows point to a homepage or listing page that was not confirmed to link the file. The usefulness column says so for each.
- **Balance:** there are 4 encümen decisions (target 5). All scanned health items are genelgeler, with no scanned clinical guideline. XLSX files are all municipal or health; the İBB XLSX tables are small (about 10 KB each).
- **Failed candidates (excluded):** 3 Anayasa Mahkemesi normkararlarbilgibankasi PDFs (404), an İstanbul Barosu PDF (410), a COVID-19 adult treatment PDF (returned HTML), Mersin and Bursa files (404), Mezitli and Erdemli reports (404), and Bayrampaşa and Bolu download links (returned HTML).
- **Volatility:** municipal and ministry URLs (for example dosyamerkez `Eklenti` IDs) change often. Re-run HEAD checks before each download, and record the `Last-Modified` or a checksum when documents are fetched.
