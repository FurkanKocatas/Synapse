# 01 - Market Research: Synapse in Turkey

Status: research draft, 2026-09-28. All URLs accessed 2026-09-28 unless another date is given.

Legend used throughout:

- **[V]** verified: taken from an official or primary source, or from at least one reputable secondary source quoting it.
- **[S]** secondary: from a vendor blog, reseller or news aggregator; plausible but not confirmed at the primary source.
- **[E]** estimate: my own calculation or judgement, with the basis stated.

Exchange rate used for conversions: 1 USD = 45.80 TRY (TCMB rate at the close on Friday 26 Sep 2026, per [Mynet Finans](https://finans.mynet.com/haber/detay/doviz/26-eylul-2026-dolar-bugun-kac-tl-serbest-piyasa-dolar-kuru-dolar-tl-gunluk-sinirli-yukselis-haftalik-yukselis/577072/) and [HaberGo](https://www.habergo.com.tr/haber/dolar-tl-cuma-kapanisinda-nasil-oldu-tcmb-ve-serbest-piyasa-son-kurlar)) [S].

---

## 1. Market size and adoption

### 1.1 Adoption statistics

| Indicator | Value | Source |
|---|---|---|
| Turkish enterprises (10+ employees) that use any AI technology, 2025 | 7.5% (2.7% in 2021) | TÜİK AI Statistics 2025, published 1 Oct 2025, reported by [ANKA](https://ankahaber.net/haber/detay/tuik_2025_yilinda_girisimlerin_yuzde_75i_yapay_zeka_teknolojilerini_kullandi_264437) [V] |
| Same, by size: 10-49 / 50-249 / 250+ employees | 6.6% / 9.6% / 24.1% | same [V] |
| EU enterprises (10+) that use AI, 2025 | 20.0% (13.5% in 2024) | [Eurostat, 11 Dec 2025](https://ec.europa.eu/eurostat/web/products-eurostat-news/w/ddn-20251211-2) [V] |
| Barriers named by Turkish non-adopters | lack of expertise 74.2%, cost 67.4%, legal uncertainty 62.4% | TÜİK via ANKA [V] |
| Individuals (16-74) using generative AI, 2025 | 19.2%; 36.1% of university graduates; 33.8% of users use it for work | TÜİK via [TRT Haber, 1 Oct 2025](https://www.trthaber.com/haber/gundem/turkiyede-uretken-yapay-zeka-kullandigini-beyan-edenlerin-orani-yuzde-192-921422.html) [V] |
| SMEs as a share of all enterprises, 2024 | 99.6%, about 3.93 million SMEs; 68.5% of employment | [TÜİK KOBİ İstatistikleri 2024](https://data.tuik.gov.tr/Bulten/Index?p=Kucuk-ve-Orta-Buyuklukteki-Girisim-Istatistikleri-2024-54054) [V] |

Reading: Turkish enterprise AI adoption is roughly one third of the EU level, while employee (shadow) use of consumer generative AI is already common. The three stated barriers (expertise, cost, legal uncertainty) are exactly what a packaged, on-premise, KVKK-aware product addresses. [E]

### 1.2 Addressable segments (counts)

| Segment | Count | Source |
|---|---|---|
| Municipalities | about 1,390 to 1,404 in total: 30 metropolitan, 519 metropolitan district, 51 provincial, about 400 non-metro district, about 400 belde | Ministry of Interior figures via [Milliyet](https://www.milliyet.com.tr/egitim/turkiyede-toplam-kac-ilce-var-2026-ilce-belediyesi-sayisi-6336199) and [Hamle Gazetesi](https://www.hamlegazetesi.com/haber/turkiyede_1401_belediye_var-22469.html) [S] |
| Lawyers | 206,678 registered (31 Dec 2025), 67,463 in Istanbul | TBB figures via [Hukuki Haber](https://www.hukukihaber.net/turkiyede-206-bin-678-avukat-var-istanbul-barosuna-kayitli-avukat-sayisi-ise-67-bin-463) [V] |
| Hospitals | 1,562 in 2024: 941 Ministry of Health, 69 university, 552 private | Sağlık İstatistikleri Yıllığı 2024 bulletin, [PDF](https://ohsad.org/wp-content/uploads/2025/10/Saglik-Istatistikleri-2024-Yilligi-Haber-Bulteni.pdf) [V] |
| SMEs 10-249 employees | TÜİK does not split the 3.93 M by size in the headline; the vast majority are micro firms | [E] |

Rough serviceable market, first 3 years [E]:

- Municipalities: realistic targets are the 519 + 400 district municipalities and the 51 provincial ones. Metropolitan ones usually build or buy larger platforms.
- Law firms: firms with 5+ lawyers are the buyers of a server product; solo lawyers buy SaaS (İçtihad AI and similar). The count of 5+ lawyer firms is not published; assume a low thousands figure, mostly in Istanbul, Ankara and İzmir.
- Healthcare: 552 private hospitals plus private medical centers and dialysis/imaging chains. Public hospitals buy through Ministry of Health central structures and are hard to reach.

### 1.3 Policy programs that create demand

- **Türkiye Yapay Zekâ Eylem Planı 2026-2030**: announced 13 Jun 2026, made binding by Presidential Circular 2026/9 in the Resmî Gazete of 18 Aug 2026 (no. 33344). It asks for at least 2% of public investment budgets for AI projects, positions public institutions as "first users and reference customers" of domestic solutions, and introduces "AI vouchers" for SMEs. [Türkiye Yapay Zeka İnisiyatifi](https://turkiye.ai/turkiye-yapay-zeka-eylem-plani-aciklandi/), [Memurlar.net](https://www.memurlar.net/haber/1175670/turkiye-yapay-zeka-eylem-plani-genelgesi-resmi-gazete-de.html) [S; RG number from secondary sources]
- The earlier **Ulusal Yapay Zekâ Stratejisi 2024-2025 Eylem Planı** (71 actions, coordinated by CBDDO) prioritized Turkish LLMs and public sector pilots. [CBDDO](https://cbddo.gov.tr/duyurular/6846/ulusal-yapay-zeka-stratejisi-2024-2025-eylem-plani-yayimlandi) [V]
- Municipal capacity building: Marmara Belediyeler Birliği "Yapay Zekâ 101" program, a TÜBİTAK-funded "BEYAZ" project that will produce municipal AI maturity levels and guides, and UNDP + TBB training. [Marmara Belediyeler Birliği](https://www.marmara.gov.tr/tr/yerel-yonetimler-icin-yapay-zeka-101-basliyor), [SDÜ](https://w3.sdu.edu.tr/haber/12069/sduden-belediye-hizmetlerini-iyilestirme-ve-yeni-politikalar-gelistirmede-yapay-zeka-kullanimi-projesi) [S]
- The Ministry of Interior's **e-Belediye Bilgi Sistemi** aims to move municipal core software onto a common, cloud-based system. A document assistant must integrate with it rather than compete with it. [S, via turkiye.gov.tr/İLBANK search results]

---

## 2. Competitors

### 2.1 Comparison table

Prices are list prices where published. TRY conversions at 45.80 and exclude VAT.

| Product | Deployment | Price | Turkish quality | On-prem | Main weaknesses for Synapse's targets |
|---|---|---|---|---|---|
| Microsoft 365 Copilot | SaaS (Microsoft cloud) | Enterprise $30/user/month (~1,374 TRY); Copilot Business $21 (~962 TRY), promo $18 for <300 users until 30 Sep 2026; needs an M365 base licence [S: [microsoftistanbul.com](https://microsoftistanbul.com/blog/microsoft-365-copilot-lisans-fiyat-satin-alma-turkiye-2026), [Microsoft TR](https://www.microsoft.com/tr-tr/microsoft-365-copilot/pricing)] | Good [E] | No | Turkey is not among the 15 countries that get in-country Copilot processing ([Microsoft, 4 Nov 2025](https://www.microsoft.com/en-us/copilot/blog/2025/11/04/microsoft-offers-in-country-data-processing-to-15-countries-to-strengthen-sovereign-controls-for-microsoft-365-copilot/)) [V], so public critical data is excluded; the cost stacks on top of M365; value depends on data being in SharePoint |
| ChatGPT Business (ex Team) / Enterprise | SaaS | Business $20/user/month annual, $25 monthly, 2 seat minimum; Premium seats $100 annual; Enterprise by quote [S: [Elephas](https://elephas.app/resources/chatgpt-business-pricing), [justinmckelvey.com](https://justinmckelvey.com/blog/chatgpt-business-pricing)] | Very good [E] | No | Data leaves Turkey, so KVKK Art. 9 transfer mechanism needed; no per-document ACL over local file shares; not acceptable for public critical data |
| Google Workspace with Gemini | SaaS | Gemini bundled into Workspace since 2025; Business Standard around $14 to $18/user/month depending on source [S: [Google](https://workspace.google.com/pricing), [eesel](https://www.eesel.ai/blog/gemini-workspace-pricing)] | Good [E] | No | Requires moving to Workspace; low Workspace share in Turkish public sector [E]; the Turkcell + Google Cloud Turkey region may weaken the data residency argument later ([Turkcell](https://www.turkcell.com.tr/blog/turkiyenin-dijital-donusumundeki-tarihi-adim-turkcell-ve-google-cloud-isbirliginin-analizi)) [S] |
| Glean | SaaS (some VPC options) | Not published; reported $45-50/user/month base plus about $15 AI add-on, 100 seat minimum, about $60k/year minimum ACV [S: [Coworker](https://coworker.ai/blog/glean-pricing), [Workativ](https://workativ.com/hr/blog/glean-pricing)] | Unknown/probably OK [E] | No | Priced far above Turkish SMB and municipal budgets; no Turkish presence |
| Onyx (ex Danswer) | Self-host (CE, MIT) or cloud | CE free; Cloud Business $20/user/month; Enterprise (SSO, permission sync, white label) by quote [S: [Onyx review](https://www.teamazing.com/blog/onyx-ai-enterprise-review-2026/), [WZ-IT](https://wz-it.com/en/blog/onyx-self-hosted-installation/)] | Depends on the model used [E] | Yes | Document permission sync is paid EE; heavy stack (Vespa etc.); English-first UI; no Turkish support or partner |
| AnythingLLM | Desktop, self-host (MIT), cloud | Self-host free; cloud $50 and $99/month [S: [useanything.com](https://useanything.com/pricing)] | Depends on model | Yes | Workspace-level rather than document-level permissions [E]; limited audit trail; aimed at individuals and small teams |
| Open WebUI | Self-host | Free; since v0.6.6 (Apr 2025) branding must stay above 50 users unless an enterprise licence is bought [V: [docs](https://docs.openwebui.com/license/)] | Depends on model | Yes | Chat front end first, RAG second; no document ACL model; branding clause blocks white-label resale |
| Dify | Self-host, cloud | Cloud $59 and $159/workspace/month; self-host under a modified Apache 2.0 that forbids multi-tenant operation without written permission and forbids removing the logo [V: [LICENSE](https://github.com/langgenius/dify/blob/main/LICENSE), [DEV](https://dev.to/beton/dify-pricing-teardown-2026-42g5)] | Depends on model | Yes | App/workflow builder, not an end-user knowledge product; licence blocks SaaS resale |
| RAGFlow | Self-host (Apache 2.0) | Free | Depends on model | Yes | Needs 16 GB minimum, 32 GB recommended for the stack alone before an LLM ([GitHub](https://github.com/infiniflow/ragflow)) [V]; no enterprise permissions |
| PrivateGPT / Zylon | Self-host (PrivateGPT OSS), Zylon commercial on-prem | Zylon by quote, flat fee [S: [Zylon](https://www.zylon.ai/)] | Depends on model | Yes | OSS is an API layer, not a product; Zylon has no Turkish presence |
| Kotaemon | Self-host | Free | Depends on model | Yes | Effectively dormant, last release May 2025 [S: [Onyx insights](https://onyx.app/insights/self-hosted-rag)] |
| LibreChat | Self-host (MIT) | Free | Depends on model | Yes | Acquired by ClickHouse late 2025 [S]; strong auth (SAML/LDAP) but basic RAG and no connectors |
| HAVELSAN MAIN | On-prem, public/defence | Not published | Native Turkish (9B own model) [S] | Yes | Sold to central government and defence; used for CİMER application evaluation ([HAVELSAN](https://www.havelsan.com/tr/urunler/main-kurumsal-yapay-zeka-platformu), [Para Dergi](https://www.paradergi.com.tr/girisimcilik/2024/02/22/main-havelsandan-turkce-yapay-zeka-platformu)); not priced or packaged for district municipalities or SMBs |
| CBOT | On-prem or cloud | Not published | Good | Yes | Citizen-facing conversational agent (İBB "İstanbul Senin" runs it on-prem, [CBOT](https://www.cbot.ai/municipality-services/)) [S]; not an internal document knowledge base |
| SESTEK Knovvu Copilot | On-prem or private cloud | Not published | Good (own ASR/NLU) | Yes | Contact-center focus, enterprise price level ([SESTEK](https://www.sestek.com/knovvu-copilot)) [S] |
| Local integrators (DeepZeka, C3T and many agencies) | Custom on-prem projects | Project based | Varies | Yes | Custom work, not a product; slow and expensive to replicate ([DeepZeka](https://www.deepzeka.com/), [C3T](https://c3t.com.tr/)) [S] |
| Legal SaaS: İçtihad AI | SaaS (EU servers) | 2,699 / 5,499 / 9,999 TRY per month (site on 28 Sep 2026) [V: [ictihad.ai](https://ictihad.ai/)] | Native | No | Hosted in the EU, which is a transfer abroad for client data; strength is the case law corpus, not the firm's own files |
| Legal SaaS: Lexpera (LEXI AI, beta) | SaaS | Annual 34,200 / 43,800 / 48,000 TRY, VAT incl. [V: [Lexpera](https://www.lexpera.com.tr/uyelik-destek/paketler-ucretler)] | Native | No | Research database first; LEXI document assistant is beta ([Lexpera LEXI](https://www.lexpera.com.tr/ayrintilar/lexi)) |
| Legal SaaS: DavaHukuk, LexChat, JustLaw, OveK and others | SaaS | Subscription or credits | Native | No | Crowded, case law centric, cloud only ([DavaHukuk](https://davahukuk.com/), [LexChat](https://lexchat.ai/)) [S] |
| UYAP (Ministry of Justice) | Government portal | Free | Native | n/a | Added an AI chat assistant and, in 2026, AI summarization of case files in the lawyer portal ([Adalet Bakanlığı](https://basin.adalet.gov.tr/yargida-yapay-zek-destekli-yeni-donem)) [S]; this commoditizes "summarize my UYAP file" |

### 2.2 Turkish LLM landscape (relevant for the local model)

- **Kumru** (VNGRS): 7.4B model trained from scratch for Turkish, positioned for on-prem document Q&A; vendor claims it beats much larger open models on Turkish tasks [S: [DonanımHaber](https://www.donanimhaber.com/ilk-turkce-buyuk-dil-modeli-kumru-llm-tanitildi--197149)]. Licence terms for commercial redistribution were not verified.
- **T3 AI** (T3 Vakfı + Baykar): beta since Jul 2025; described as open source, but no weights download was found [S: [AA](https://www.aa.com.tr/tr/bilim-teknoloji/turkce-buyuk-dil-modeli-t3-ai-beta-surumuyle-yayinda/3628200)].
- Open multilingual models (Qwen3 family, Gemma 3/4) are the realistic default for a CPU box; no reliable public Turkish RAG benchmark on CPU was found. **We must build our own Turkish eval set.** [E]

### 2.3 Where the gap is [E]

Global SaaS tools are strong but cannot touch data the buyer is not allowed to send abroad. Open-source tools are free but are toolkits: no Turkish UI, weak document-level ACL and audit, no local support, and in two cases (Open WebUI, Dify) licences restrict white-label or multi-tenant resale. Turkish players are either (a) large enterprise/defence vendors (HAVELSAN, SESTEK, CBOT) or (b) cloud legal research SaaS. **No one sells a fixed-price, Turkish-first, on-premise document assistant with per-document permissions and audit logs sized for a district municipality, a 10-lawyer firm or a private clinic.**

---

## 3. Regulation and procurement

### 3.1 KVKK (Law 6698) after the 2024 amendment

- Law 7499 (RG 12 Mar 2024, in force 1 Jun 2024) rewrote Art. 6 (special category data) and Art. 9 (transfer abroad) [V: [Erdem & Erdem](https://www.erdem-erdem.av.tr/bilgi-bankasi/kisisel-verilerin-korunmasi-kanununda-neler-degisti), [KVKK](https://www.kvkk.gov.tr/Icerik/2053/Yurtdisina-Aktarim)].
- Transfer abroad now works through (1) an adequacy decision (none issued as of the sources found), (2) appropriate safeguards, mainly the **Board's standard contract**, which must be notified to KVKK within **5 business days** of signature (Board decision 2024/959 of 4 Jun 2024; online notification module since Board decision 2024/1793), or (3) narrow occasional derogations. Implementing regulation: RG 10 Jul 2024, no. 32598 [V: [KVKK SCC notice](https://www.kvkk.gov.tr/Icerik/8043/Standart-Sozlesme-Bildirim-Modulu-Hakkinda-Kamuoyu-Duyurusu), [KVKK transfer guide](https://www.kvkk.gov.tr/Icerik/8142/Kisisel-Verilerin-Yurt-Disina-Aktarilmasi-Rehberi)].
- **Practical effect:** every SaaS LLM call with personal data in the prompt (OpenAI, Anthropic, Google, Azure outside Turkey) is a transfer abroad needing an SCC and notification. Many SMBs do not do this. An on-prem product removes the question; an "external API" mode must be opt-in, logged, and ideally apply PII masking first. [E]
- KVKK published "**Üretken Yapay Zekâ ve Kişisel Verilerin Korunması Rehberi (15 Soruda)**" on 24 Nov 2025 and a separate guide on generative AI tools in the workplace [V: [KVKK](https://www.kvkk.gov.tr/Icerik/8547/uretken-yapay-zeka-ve-kisisel-verilerin-korunmasi-rehberi-15-soruda), [KVKK workplace guide](https://www.kvkk.gov.tr/Icerik/8674/is-yerlerinde-uretken-yapay-zeka-araclarinin-kullanimi)]. These are useful sales collateral.
- **Health data** remains special category. After 7499, explicit consent is no longer the only basis; processing is allowed by persons under confidentiality duty for medical purposes (Art. 6/3), and the Kişisel Sağlık Verileri Yönetmeliği was aligned to this. Re-using treatment data for a new purpose (for example model training) needs its own legal basis [S: [Ozay Law](https://ozay.av.tr/publication/6698-sayili-kisisel-verilerin-korunmasi-kanunu-nda-yapilan-degisikliklerin-degerlendirilmesi), [Hanyaloğlu & Acar](https://www.hanyaloglu-acar.av.tr/malpraktis-tazminat/saglikta-yapay-zeka-hukuki-cerceve)]. Synapse must never train on customer data by default.
- **No AI law yet.** Several bills were filed in 2024-2025 and a TBMM research commission report (Mar 2026) recommends an AI authority; nothing enacted as of the sources [S: [NPartners](https://npartners.com.tr/tr/turkiyede-2026-yapay-zeka-kanunu-tbmmye-sunulan-uc-kanun-teklifinin-detayli-karsilastirilmasi)]. Design for EU AI Act style transparency (source citations, logs, human review) to be ready.

### 3.2 Cumhurbaşkanlığı Bilgi ve İletişim Güvenliği Rehberi

Published by CBDDO in 2020 under Circular 2019/12; binding for public institutions and critical infrastructure [V: [CBDDO PDF](https://cbddo.gov.tr/SharedFolderServer/Genel/File/bg_rehber.pdf)]. Key points for Synapse:

- Critical data (population, health, communication, genetic, biometric) must be stored in Turkey.
- Public institution data may not be stored in cloud services except the institution's own systems or domestic providers under institutional control.
- Critical data should sit on networks isolated from the internet, with access control and tamper-resistant logs.

For a municipality this means: on-prem or Turkish-hosted only, an **offline/air-gapped install path**, no telemetry by default, and append-only audit logs. The Guide's asset groups and security levels (3 levels) are what municipal IT uses in technical specifications; mapping Synapse to them is a cheap, high-value sales document. [E]

### 3.3 Public procurement (4734) for municipalities

| Limit (1 Feb 2026 to 31 Jan 2027, excl. VAT) | Amount | Source |
|---|---|---|
| Doğrudan temin 22/d, administrations within metropolitan municipality borders | 1,021,827 TRY | [Teko Hukuk](https://tekohukuk.com.tr/dogrudan-temin-limiti/), [KİK 2026 table](https://dosyalar.kik.gov.tr/yardim/dokumanlar/2026_Esik_Degerler_Parasal_Limitler_Karsilastirma.pdf) [V] |
| Doğrudan temin 22/d, other administrations | 340,391 TRY | same [V] |
| Pazarlık 21/f (goods and services) | 3,406,508 TRY | [İhale Metrik](https://ihalemetrik.com/kaynaklar/blog/esik-degerler-2026) [S] |
| Update rule | yearly on 1 Feb by Yİ-ÜFE; +27.67% for 2026 | [Mevzuat Takip](https://mevzuattakip.com.tr/haber/kamu-ihalelerinde-esik-degerler-ve-parasal-limitler-27-67-artirildi) [S] |

Implications [E]:

- **The 22/d limit is the single most important pricing constraint.** A district municipality inside a metropolitan area can buy up to about 1.02 M TRY without a tender; a non-metro district or belde about 340k TRY. Splitting a need into parts to stay under the limit is prohibited (4734 Art. 12), so the package must be priced as one sensible unit below the limit.
- Above that, 21/f pazarlık up to about 3.4 M TRY is still fast.
- **Yerli malı belgesi:** software can obtain it (minimum 51% domestic content); in tenders up to 15% price advantage for domestic goods, mandatory for products on the KİK medium/high-tech list, which includes software products. New Yerli Malı Tebliği (SGM-2024/10) in force from 1 Jan 2026, amended by SGM-2025/4 [S: [KİK list](https://www.kik.gov.tr/Duyuru/173/orta_ve_yuksek_teknolojili_sanayi_urunleri_listesi.html), [Taxia](https://taxia.com.tr/blog-202510-guncellenen-yerli-mali-tebligi-resmi-gazetede-yayimlandi-693)]. It is issued via the chamber of commerce/industry (TOBB system) and needs a company. Worth obtaining in year 1.
- **Kamu Bilişim / Yazılım Yetki Belgesi:** Regulation of 29 Jun 2022 (Ministry of Industry and Technology). The software authorization is required only for software development, integration or maintenance **service** tenders above 10 times the 4734 Art. 13(b)(2) limit, and needs TS EN ISO/IEC 27001 plus SPICE Level 2 or CMMI Level 3 [S: [Certby](https://www.certby.com/kamu-ihalelerinde-yazilim-yetki-belgesi-ve-sizma-testi-yetki-belgesi-zorunlulugu/), [AA](https://www.aa.com.tr/tr/ekonomi/kamu-bilisim-hizmetleri-alimlarinda-yetkilendirme-donemi/2625385)]. That puts the threshold in the tens of millions of TRY, so it is **not** relevant to Synapse's first sales. [E]
- **ISO 27001:** cannot be demanded as a general qualification criterion in service tenders, but municipalities and hospitals frequently ask for it in technical specifications or supplier questionnaires [S: [kilichukuk.org](https://www.kilichukuk.org/Sozluk/isoiec-27001-bilgi-guvenligi-yonetim-sistemi-belgesi)]. Plan for it in year 2. TSE service certificates are not a standard requirement for this category. [E]
- For health buyers the typical questions are KVKK compliance, data location, HBYS integration and a signed data processing agreement (veri işleyen sözleşmesi). [E]

---

## 4. Sector needs, pains, and realistic use cases

### 4.1 Municipalities

Documents: meclis and encümen kararları (thousands per year per municipality), yönetmelikler/yönergeler, imar plan notes, ihale files, personnel rules, Sayıştay reports, KİK decisions, internal circulars, CİMER and Beyaz Masa answers.

Pains: institutional memory lives in scanned PDFs and in a few senior staff; new staff cannot find precedent decisions; the same citizen question is answered inconsistently; answer deadlines. CİMER alone received 5.525 M applications in 2025 nationally with an 11 day average processing time [V: [İletişim Başkanlığı](https://www.iletisim.gov.tr/turkce/duyurular/detay/cimer-2025te-55-milyon-basvuru-aldi)].

Competitive note: citizen-facing chatbots already exist (CBOT at İBB, Otelbot at Nevşehir, [Nevşehir Kent Haber](https://www.nevsehirkenthaber.com/haber/28327915/nevsehir-belediyesinde-yapay-zeka-donemi)) and legislation Q&A tools for municipal staff are appearing ([yzmevzuat.com](https://yzmevzuat.com/), not verified in detail). Synapse's angle is the **internal** archive of the municipality itself.

### 4.2 Law firms

Documents: the firm's own dilekçe archive, contracts, opinions, client correspondence, UYAP downloads (UDF format), internal templates.

Pains and constraints: Attorney secrecy (Avukatlık Kanunu Art. 36). The TBB guide "Avukatlar İçin Yapay Zekâ Kullanımı Tavsiye Rehberi" advises against sending non-anonymized client information, special category data, case and enforcement file content, evidence and trade secrets to public AI systems or systems with weak contractual guarantees; professional responsibility cannot be delegated to AI [S: [Hukuki Haber](https://www.hukukihaber.net/tbbden-avukatlar-icin-yapay-zeka-kullanimi-tavsiye-rehberi), [TBB](https://www.barobirlik.org.tr/Haberler/tbb-avukatlikta-yapay-zeka-kullanimina-iliskin-tavsiye-rehberini-yayimladi-86648)]. Ankara Barosu published its own guide v1.0 ([PDF](https://ankarabarosu.org.tr/serve/file/bc4de0be-b5fa-11ef-8f94-000c29c9dfce/yapay_zeka_araclarnn_kullanm_rehberi_X1.pdf)) [S]. This is the strongest argument for on-prem in the legal segment.

Competitive note: public case law search (içtihat) is a crowded cloud market (İçtihad AI, Lexpera, DavaHukuk, LexChat) and UYAP itself now summarizes case files. **Synapse should not compete on public case law**; it should make the firm's private archive searchable and let lawyers use a legal SaaS for public case law. Integration target: TBB's own office system büroTeK ([burotek.av.tr](https://www.burotek.av.tr/)) and common office software (KolayOfis, Avukat Bulut) [S].

### 4.3 Healthcare

Documents: clinical guidelines, SOPs and quality documents (SKS: Sağlıkta Kalite Standartları), infection control procedures, drug protocols, JCI files, HR and training material.

Constraints: patient data is special category; clinical decision support that influences diagnosis or treatment can be a medical device, creating liability and regulatory exposure [S: Hanyaloğlu & Acar above]. **Position Synapse as a staff knowledge tool for procedures and quality documents, explicitly not clinical decision support**, and keep patient records out of scope in version 1.

### 4.4 Which use cases work on CPU hardware [E]

Basis: a Ryzen 5 3600 class CPU with dual-channel DDR4 (about 50 GB/s) typically produces about 6-10 tokens/s for a 7-8B model at Q4 and around 12 tok/s for a 3-4B model; prompt processing (reading retrieved context) is the real bottleneck, roughly tens of tokens per second, so a 3,000-token context can take 30-90 s before the first word [E, consistent with [llama.cpp CPU discussion](https://github.com/ggml-org/llama.cpp/discussions/3167) and [PromptQuorum](https://www.promptquorum.com/local-llms/best-cpu-only-llm)]. We must measure this on real hardware.

| Use case | CPU-only fit | Notes |
|---|---|---|
| Semantic + keyword search over documents with cited passages | Excellent | Embedding at index time, BM25 + vector at query time; no LLM needed to be useful |
| Short answer with 2-4 cited chunks, 1-5 concurrent users | Acceptable | Keep context under about 1,500 tokens, stream the answer, 3-4B model |
| Summarize one short decision or procedure | Acceptable, queued | Background job, notify when ready |
| Long document summaries, contract comparison, drafting dilekçe | Poor | GPU tier or opt-in external API |
| OCR of scanned archives | Slow but OK as a batch | Nightly indexing; measure pages/hour |
| 20+ concurrent chat users | Not viable | GPU tier or external API |

---

## 5. Pricing and packaging recommendation

### 5.1 Reference prices buyers will compare against

| Reference | Per user per year, TRY (excl. VAT) |
|---|---|
| Copilot Business ($21) | ~11,540 |
| ChatGPT Business annual ($20) | ~10,990 |
| İçtihad AI Standart (2,699/month, VAT treatment not stated) | ~32,400 |
| Lexpera Standart (34,200 VAT incl.) | ~28,500 |

So a 10-user law firm already pays or is quoted about 110k-330k TRY per year for cloud AI tools. [E]

### 5.2 Hardware prices (Turkey, September 2026)

A global DRAM shortage has pushed memory prices up sharply; 2x16 GB DDR4 reportedly went from 3,299 TRY (Apr 2025) to 16,999 TRY, and SK Hynix expects tight supply until 2028 [S: [Hürriyet](https://www.hurriyet.com.tr/galeri-ram-fiyatlari-neden-yukseldi-tekrar-dusecek-mi-yuzde-300e-yakin-yukselis-piyasayi-karistirdi-43059487), [Technopat, 21 Sep 2026](https://www.technopat.net/2026/09/21/acer-ram-krizi-pc-fiyatlari-icin-tarih-verdi/)].

| Component | Price (TRY, VAT incl.) | Source |
|---|---|---|
| AMD Ryzen 5 5600 (current AM4 successor to the 3600) | from 6,099 (20 Sep 2026) | [Akakçe](https://www.akakce.com/islemci/en-ucuz-amd-ryzen-5-5600-alti-cekirdek-3-50-ghz-fiyati,1782415463.html) [V] |
| 16 GB DDR4-3200 (single module) | from 5,699 (27 Sep 2026) | [Akakçe](https://www.akakce.com/ram/en-ucuz-kingston-fury-beast-16-gb-3200-mhz-ddr4-cl16-kf432c16bb-16-fiyati,1359419327.html) [V] |
| RTX 5060 Ti 16 GB | about 50,400 to 57,700 (13 Sep 2026) | [Cimri](https://www.cimri.com/ekran-kartlari/en-ucuz-msi-geforce-rtx-5060-ti-gaming-oc-16gb-gddr7-ekran-karti-fiyatlari,2456316214) [S] |
| RTX 4060 Ti 16 GB | only stale 2025 listings (about 27-28k); treat as unavailable | [Cimri](https://www.cimri.com/ekran-kartlari/geforce-rtx-4060-ti-ekran-karti) [S] |
| Used RTX 3090 24 GB | global used market about $1,000-1,450 (about 46k-66k TRY); Turkish second-hand prices not verified | [BestValueGPU](https://bestvaluegpu.com/history/new-and-used-rtx-3090-price-history-and-specs/) [S] |

Bill of materials [E]:

| Tier | Spec | Estimated cost (TRY, VAT incl.) |
|---|---|---|
| CPU box | Ryzen 5 5600, 32 GB DDR4, 1 TB NVMe, B550, case, PSU | 35,000-45,000 |
| GPU box | as above plus RTX 5060 Ti 16 GB, 750 W PSU, 64 GB RAM | 100,000-125,000 |
| Server grade (municipal IT preference) | 1U/tower server from HPE/Dell/Lenovo via distributor | 150,000+ (not researched) |

Hardware quotes should be valid for about 7-15 days because of memory prices. Do not hold stock. Resell through a local distributor and quote the hardware separately with a small margin; the value is in the licence and support. [E]

### 5.3 Recommended packages [E]

| Package | Target | Contents | Price (TRY, excl. VAT) |
|---|---|---|---|
| **Büro** | law firm, clinic, small office, up to 15 users | software licence, 1 server, email support, updates | Subscription 75,000-110,000 per year; or perpetual 180,000-240,000 + 20% annual maintenance |
| **Kurum** | SMB or hospital department, up to 75 users | as above + SSO/LDAP, priority support, 2 remote training sessions | Subscription 180,000-300,000 per year |
| **Belediye S** | non-metro district or belde | appliance (CPU box) + perpetual licence + install + training + 1 year support | 290,000-330,000 total, under the 340,391 limit |
| **Belediye M** | district inside a metropolitan area | appliance (GPU box) + perpetual licence + archive OCR/indexing service + 1 year support | 700,000-950,000 total, under the 1,021,827 limit |
| Renewals | all perpetual customers | updates + support | 15-20% of licence per year |
| SaaS (later) | micro offices | Turkish-hosted, per user | 600-900 per user per month |

Reasoning:

- Public buyers prefer a one-time, fixed amount with a clear "mal alımı" item (appliance + licence) that fits 22/d; annual subscriptions create budget and multi-year commitment questions. Private buyers prefer annual subscription with low entry cost.
- Price per server (with a user cap) rather than strictly per user: municipal and hospital staff counts are large but occasional users; per-user pricing blocks adoption.
- Stay below Copilot/ChatGPT per-seat cost at 10+ users, while being the only on-prem option.
- Set prices in TRY but index annually (Yİ-ÜFE or a USD-linked clause for private customers), because hardware and API costs follow USD.

---

## 6. Go-to-market

### 6.1 Channels

| Channel | Why | First step |
|---|---|---|
| Direct, pilot customers first | References matter most in public and legal sales; district municipalities inside metropolitan areas can use the 1.02 M TRY 22/d limit | 3 free pilots with a signed success criterion, then paid references |
| Municipal software vendors and system integrators | They already hold maintenance contracts and procurement relationships with districts | Reseller agreement with 20-30% margin; white-label allowed |
| Municipal unions (TBB, Marmara Belediyeler Birliği, regional unions) | Run trainings (Yapay Zekâ 101) and are trusted by municipal IT | Offer a free session on "KVKK-compliant internal AI" with a live demo |
| Bar associations (Ankara, İzmir, Istanbul and others) | Their AI guides push lawyers towards private, controlled systems | Continuing education seminars; member discount |
| Healthcare: private hospital groups, quality managers (SKS) | Quality documents are a clear, low-risk use case | Pilot with one private hospital's quality department |
| Hardware distributors | Appliance fulfilment | Arrange drop-ship; no inventory |

### 6.2 Funding (later)

- **TÜBİTAK 1512 BiGG**: individuals can apply in stage 1 before founding a company; a company must be established to receive stage 2 funding. Reported stage 2 grant 900,000 TRY [S, amount not verified at the primary source for 2026: [TÜBİTAK](https://tubitak.gov.tr/en/funds/sanayi/ulusal-destek-programlari/1512-entrepreneurship-support-program)]. Eligibility is tied to university degree status.
- **TÜBİTAK 1507** (SME R&D start) and **1501**: the second 2026 calls are open [V: [TÜBİTAK](https://tubitak.gov.tr/tr/duyuru/1501-sanayi-ar-ge-destek-programi-ve-1507-kobi-ar-ge-baslangic-destek-programi-2026-yili-2-cagrilari-acildi)].
- **KOSGEB Ar-Ge, Ür-Ge ve İnovasyon Destek Programı** [V: [KOSGEB](https://www.kosgeb.gov.tr/site/tr/genel/destekdetay/7664/arge-urge-ve-inovasyon-destek-programi)].
- The 2026-2030 Action Plan's SME "AI vouchers" could subsidize customers' purchases once implemented; watch for the implementing call. [S]
- A teknopark company brings tax advantages. [E]

### 6.3 Differentiators vs competitors

1. **Runs on a 35-45k TRY box, offline.** No other packaged product targets CPU-only, 16-32 GB hardware.
2. **Per-document permissions and an append-only audit log** as core features, mapped to KVKK, the BİG Rehberi and TBB guidance. In Onyx these are paid EE features; in most OSS tools they do not exist.
3. **Turkish-first**: Turkish UI, Turkish morphology in search (stemming and deasciification), Turkish OCR, UDF and scanned-PDF handling, Turkish date and number formats.
4. **Procurement-ready packaging**: a fixed-price item under 22/d, a yerli malı belgesi, KVKK documentation pack (VERBİS inputs, data processing agreement template, information security mapping).
5. **Local support in Turkish**, with an on-site install option.
6. **Honest scope**: cited answers from the customer's own documents; no claim to replace case law databases or clinical decision support.

---

## 7. Name check: "Synapse"

| Existing use | Relevance |
|---|---|
| Azure Synapse Analytics (Microsoft) | Active product, no retirement date; Microsoft steers new investment to Fabric [S: [Flexera](https://www.flexera.com/blog/finops/azure-synapse-vs-fabric/)]. Same buyer (IT), confusion in search results |
| Matrix Synapse / Synapse Pro (Element) | Self-hosted server software, commercially licensed Pro edition [V: [Element](https://element.io/en/server-suite/synapse-pro)]. Same "on-prem server" buyer persona |
| Fujifilm Synapse | Healthcare IT/PACS platform sold in Turkey since 1999 [V: [Fujifilm TR](https://www.fujifilm.com/tr/tr/healthcare/healthcare-it)]. **Direct conflict in the healthcare vertical** |
| Razer Synapse | Well-known consumer software |
| US registrations for SYNAPSE in software classes | Several live and dead marks, e.g. Company 3 / Method Inc. [S: [Justia](https://trademarks.justia.com/873/87/synapse-87387273.html)] |
| "Sinaps" in Turkey | Common Turkish word; Sinaps Teknoloji is a Turkish web/mobile company [V: [sinaps.com](https://www.sinaps.com/tr)] |

TÜRKPATENT: the public search ([turkpatent.gov.tr/arastirma-yap](https://www.turkpatent.gov.tr/arastirma-yap)) could not be queried from this environment; **Nice classes 9 and 42 were not verified.** [E]

**Risk assessment: high.** The word is generic in the tech sector, SEO for "Synapse" is dominated by Microsoft and Matrix, and Fujifilm Synapse conflicts in a target vertical. A TÜRKPATENT filing may face opposition or a similarity refusal, and a Turkish reading ("sinaps") is descriptive. Recommendation: keep "Synapse" as an internal code name; before any public use, run a TÜRKPATENT search in classes 9 and 42 and choose a distinctive, Turkish-pronounceable name with a free `.com.tr` domain.

---

## Key takeaways for product design

- **CPU-first means retrieval-first.** Useful search with cited passages must work with no LLM at all; the LLM is an optional layer on top. Keep prompts under about 1,500 tokens on CPU, stream output, and queue long jobs. Measure first-token latency on a real Ryzen 5 3600 / 5600 box before promising anything.
- **Pluggable model backends**: local llama.cpp-class runtime (3-4B default on CPU, 7-14B on GPU tier), and an opt-in external API provider. External calls must be off by default, logged per request, per-collection controllable, and preceded by PII masking, because every call is a KVKK Art. 9 transfer abroad.
- **Per-document ACL enforced inside retrieval** (filter before ranking, never after), with groups/roles and inheritance from folders. This is a headline feature, not an add-on.
- **Append-only, tamper-evident audit log** of logins, queries, retrieved document IDs, answers and exports, with retention settings and export for the customer's KVKK officer. Required by the BİG Rehberi mindset and by law firm confidentiality.
- **Fully offline install and update path** (signed offline bundles, no telemetry by default, no calls home for licence checks). Licence validation must work air-gapped.
- **Turkish text pipeline is a core component**: Turkish-aware tokenization/stemming for keyword search, diacritic-insensitive matching (ı/i, ş/s), Turkish OCR for scanned decisions, UDF (UYAP) import, DOCX/PDF/scanned TIFF. Build a Turkish evaluation set per vertical (meclis kararları, dilekçe, SOPs) from day one.
- **Always cite sources and allow "I don't know."** Answers without a supporting passage should be refused; this aligns with TBB's "human remains responsible" principle and future AI law.
- **Never train on customer data** and state it in the contract; no cross-customer data in the SaaS version (strict tenant isolation, per-tenant encryption keys).
- **Licence and packaging hooks in the code**: user caps per server, feature flags per package (SSO/LDAP, GPU features, external API), white-label support for resellers. Avoid depending on components whose licences forbid white-label or multi-tenant use (Open WebUI branding clause, Dify multi-tenant clause); prefer MIT/Apache-2.0 dependencies and check model licences (Kumru, Qwen, Gemma) for redistribution in an appliance.
- **Hardware-agnostic appliance image**: the same image must run on a 35k TRY mini PC and on a municipal rack server; RAM prices are volatile, so the software must degrade gracefully at 16 GB.
- **Scope out clinical decision support and public case law** in version 1: internal procedures and the customer's own archive only. This avoids medical device exposure and a crowded legal SaaS market.
- **Integration surface to plan for**: LDAP/Active Directory, file shares (SMB), e-Belediye / EBYS exports, büroTeK or other law office software exports, simple REST API. Connectors should be read-only by default.
- **Procurement documents are part of the product**: KVKK pack, BİG Rehberi control mapping, installation and hardening guide, yerli malı belgesi. Plan ISO 27001 for year 2.
