# How People Use SEC EDGAR: A Survey of Applications for Data-Product Builders (as of October 2026)

EDGAR is used heavily for investment signals, text mining and LLM work, governance and legal research, and regulatory monitoring, but it is still under-used as a real-time source for labor-market and macro measurement and for quote-grounded thematic extraction. Those two gaps are the best openings for a new data product. A Federal Reserve Board team has already shown that 8-K layoff filings track the business cycle and help forecast unemployment.\[1\] Commercial "earnings-themes" tools still mostly rely on earnings-call transcripts, which are not on EDGAR, rather than on the 8-K Item 2.02 press releases and MD&A text that are.

## TL;DR
- **The landscape is large but uneven.** Insider trades (Forms 3/4/5), 13F holdings, 13D activism, XBRL fundamentals and 10-K text signals ("Lazy Prices", Loughran-McDonald sentiment, Hoberg-Phillips industries) are mature and commoditized. Newer structured feeds (XML 13D/G since Dec 2024, expanded N-PX since Aug 2024, cyber 8-K Item 1.05 since Dec 2023) are less exploited.
- **Labor-market uses are the clearest white space.** The Fed's FEDS 2024-020 paper (Crane et al.) built a layoff series from 8-K Item 2.05 plus NLP-screened Items 7.01/8.01, and found that about 25% of layoffs linked to WARN notices appeared in 8-Ks four or more weeks earlier. Headcount is still mostly untagged prose in 10-K Item 1. Human-capital disclosures under Reg S-K 101(c) are inconsistent, which leaves room for extraction products.
- **Quote-grounded theme extraction is feasible and differentiated if built on what EDGAR actually contains.** That means 8-K Item 2.02 Exhibit 99.1 press releases, MD&A, and Item 1A risk factors, accessed through Full-Text Search (from 2001), the submissions API and XBRL APIs. Watch three 2026 changes: the proposed optional semiannual Form 10-S (May 2026), which would thin out quarterly MD&A; the proposed rescission of the climate rule (May 29, 2026); and EDGAR Next filer authentication (mandatory since Sept 15, 2025).

## Summary Table

| Use case | Primary users | EDGAR sources | Access method | Representative examples |
|---|---|---|---|---|
| Fundamental analysis | Buy/sell-side, retail, academics, vendors | 10-K, 10-Q, 20-F, 40-F, XBRL | XBRL companyfacts/companyconcept/frames APIs; Financial Statement (and Notes) Data Sets | Calcbench, Daloopa, FactSet, Bloomberg, Compustat |
| Insider-trading signals | Quants, retail, journalists, academics | Forms 3/4/5, 144 | Daily index, RSS, Form 4 XML | OpenInsider, SecForm4; Cohen-Malloy-Pomorski (JF 2012); Lakonishok-Lee (RFS 2001) |
| 13F holdings, cloning, crowding, common ownership | Hedge funds, allocators, academics, antitrust economists | 13F-HR (XML info table) | Bulk 13F data sets, full index | WhaleWisdom, Fintel, Goldman Hedge Fund Monitor; Azar-Schmalz-Tecu (JF 2018) |
| Activism / beneficial ownership | Event-driven funds, IR/defense advisers, academics | SC 13D/13G (XML since Dec 18, 2024) | Full-text search, XML | Brav-Jiang-Partnoy-Thomas (JF 2008) |
| Earnings releases and guidance | Quants, news vendors, earnings-themes products | 8-K Item 2.02 + Ex. 99.1; Item 7.01 | RSS, submissions API, efts | Bloomberg/Dow Jones, AlphaSense, sec-api.io |
| Text-change and sentiment signals | Quants, academics | 10-K/10-Q full text, Item 1A, MD&A | Bulk archives, EDGAR-CORPUS | Lazy Prices (JF 2020); Loughran-McDonald (JF 2011) |
| Product-market industries | Academics, antitrust economists | 10-K Item 1 | Bulk text | Hoberg-Phillips TNIC (JPE 2016) |
| Financial constraints | Academics, credit analysts | MD&A, 10-K text | Bulk text | Hoberg-Maksimovic (RFS 2015); Bodnaruk-Loughran-McDonald (JFQA 2015) |
| IPOs, SPACs, M&A | ECM/M&A bankers, journalists, academics | S-1/F-1, 424B, DRS (once public), S-4, DEFM14A, SC TO-T, 425 | efts, RSS | Hanley-Hoberg (RFS 2010) |
| Distress and accounting red flags | Credit, short sellers, auditors, academics | 8-K 1.03, 4.01, 4.02; NT 10-K; going-concern text | Item-coded 8-K feeds, efts | Audit Analytics; Apify 8-K monitors |
| Funds/ETFs and proxy votes | Fund analysts, governance researchers, ISS/Glass Lewis clients | N-PORT, N-CEN, N-CSR, 485BPOS, N-PX (XML) | DERA structured data sets | Morningstar; academic N-PX vote studies |
| Private markets | VC trackers, B2B sales, academics | Form D, 1-A/1-K, Form C | Form D data sets, efts | PitchBook/Crunchbase-style ingestion |
| ABS loan-level | Structured-credit investors, Fed/academic researchers | ABS-EE (auto, CMBS, RMBS) | XML exhibits | Auto-ABS credit studies |
| Broker/adviser due diligence | Allocators, compliance | X-17A-5; Form ADV (IAPD, not EDGAR) | EDGAR + IAPD | Operational due diligence |
| LLM benchmarks and corpora | AI labs, academics | 10-K/10-Q/8-K/DEF 14A | Bulk download, edgar-crawler | EDGAR-CORPUS; FinanceBench; FinQA; DocFinQA; FinAgentBench |
| Layoff tracking | Fed economists, journalists, HR/labor analysts | 8-K 2.05, 7.01, 8.01 | efts, item-coded 8-K feeds | Crane et al. FEDS 2024-020; FactFiled "Layoffs 2026" tracker |
| Headcount and human capital | Labor economists, ESG, HR-tech | 10-K Item 1 (Reg S-K 101(c)); dei:EntityNumberOfEmployees (rarely tagged) | Text extraction; XBRL | Bourveau-Chowdhury-Le; Demers et al. (2024); Gibson Dunn surveys |
| Executive turnover | Recruiters, governance, journalists | 8-K 5.02 | Item-coded feeds | Execu-search tools; BoardEx |
| Macro / policy indicators | Fed, IMF, academics | 10-K/10-Q text, XBRL frames, S-1, 8-K | efts, frames API | Crane et al.; Fed AI-buildout note (2026); Caldara et al. TPU (uses calls) |
| Corporate structure / tax | Tax researchers, KYC, journalists | Exhibit 21 | Full-text | Dyreng-Lindsey (JAR 2009) |
| Governance and compensation | Proxy advisers, academics, journalists | DEF 14A, 8-K 5.07, ECD XBRL | efts, XBRL | ExecuComp, ISS, Glass Lewis |
| Contracts | Lawyers, credit academics | Exhibit 10 | efts | Nini-Smith-Sufi (RFS 2012; JFE 2009); Bloomberg Law/Intelligize |
| Comment letters | Practitioners, academics | CORRESP/UPLOAD | efts | Audit Analytics; Intelligize |
| Cyber incidents | Insurers, security vendors, lawyers | 8-K 1.05 / 8.01 / 7.01; 10-K Item 1C | Item feeds | Debevoise, Wilson Sonsini, Greenberg Traurig trackers; Florackis et al. (RFS 2023) |
| EDGAR meta-research | Academics | EDGAR log files | DERA log data sets | Loughran-McDonald (2017); Drake-Roulstone-Thornock (CAR 2015) |

## 1. Investment and Trading Uses

**Fundamental analysis (10-K/10-Q/20-F + XBRL).** This is the foundational use. It serves the buy side, the sell side, retail investors and every data vendor. The SEC's free JSON endpoints on data.sec.gov (submissions, companyfacts, companyconcept, frames) need no API key; they do require a declared User-Agent. The quarterly Financial Statement Data Sets and the richer Financial Statement and Notes data sets serve bulk users. Commercial normalizers (Calcbench, Daloopa, FactSet, Bloomberg, S&P Compustat) sell cleaned, standardized versions. That cleaning is the value they add, because company-specific extension tags and inconsistent tag choices make raw XBRL hard to compare across firms. Kim, Muhn & Nikolaev's "Financial Statement Analysis with Large Language Models" (arXiv 2407.17866, 2024) gave GPT-4 standardized, anonymized balance sheets and income statements. They report the LLM beat analysts at predicting the direction of earnings changes.\[2\] This is a sign that XBRL-derived statements are becoming LLM inputs. **Maturity:** established. **Limitations:** extension tags, restatement handling, and non-GAAP metrics that are not tagged.

**Insider trading (Forms 3/4/5, 144).** Form 4 has been machine-readable XML for years, so OpenInsider, SecForm4 and many screeners repackage it for retail and quant users. The academic anchors are Lakonishok & Lee, "Are Insider Trades Informative?" (RFS 2001, 14(1):79–111), and Cohen, Malloy & Pomorski, "Decoding Inside Information" (JF 2012, 67(3):1009–1043).\[3\]\[4\] Cohen et al. separate "routine" from "opportunistic" insiders, and only opportunistic trades predict returns.\[3\] Form 144 (notice of proposed sales) is now filed electronically and gives a lead indicator of insider selling. **Maturity:** heavily commoditized. The differentiated layer is now 10b5-1 plan context and footnote parsing.

**13F holdings, cloning, crowding, common ownership.** 13F-HR information tables (XML) feed WhaleWisdom, Fintel, AlphaClone-style cloning strategies and Goldman Sachs' Hedge Fund Monitor (crowding and "VIP" lists). The SEC also publishes flattened 13F data sets. Academics use 13F for institutional-ownership controls and for common-ownership work: Azar, Schmalz & Tecu, "Anticompetitive Effects of Common Ownership" (JF 2018, 73(4):1513–1565), used holdings overlap to argue that airline ticket prices rise with common ownership, a claim debated in antitrust policy.\[5\]\[6\] **Limitations:** 45-day lag, long-only U.S.-listed positions, no shorts, and confidential-treatment omissions.

**Activism (SC 13D/13G).** Brav, Jiang, Partnoy & Thomas, "Hedge Fund Activism, Corporate Governance, and Firm Performance" (JF 2008, 63(4):1729–1775), is the canonical 13D event study.\[7\] The 2023 beneficial-ownership amendments cut the initial 13D deadline from 10 calendar days to five business days and require 13D amendments within two business days. Since December 18, 2024, Schedules 13D and 13G must be filed in structured XML.\[8\]\[9\] That makes 13D/G parsing much cheaper and timelier, and it is an under-exploited upgrade.

**Earnings releases and guidance (8-K Item 2.02, Ex. 99.1).** Earnings press releases are furnished as Exhibit 99.1 to 8-K Item 2.02, usually just before the call. Guidance often appears in the release or under Item 7.01. Newswires, quant shops and AI research tools (AlphaSense, Bloomberg, FactSet, sec-api.io) extract headline numbers and guidance from them. **Important limitation:** earnings-call transcripts are generally not on EDGAR. Some firms furnish transcripts or prepared remarks under 7.01/8.01, but coverage is sparse. Most academic "earnings-call" measures, such as the Caldara et al. trade-policy-uncertainty index and Jha-Qian-Weber-Yang's "ChatGPT and Corporate Policies" (NBER WP 32161, 2024), use licensed transcripts (e.g., S&P Global), not EDGAR.\[10\]\[11\]

**Text-change and sentiment signals.** Cohen, Malloy & Nguyen, "Lazy Prices" (JF 2020, 75(3):1371–1415), show that firms whose 10-K/10-Q language changes year over year subsequently underperform.\[12\] A long "non-changers"/short "changers" portfolio earns up to 188 bps/month in alpha, with Item 1A risk-factor changes among the most informative.\[13\] They found no announcement-day reaction, which they read as investor inattention.\[13\]\[14\] Independent 2026 replications on S&P 500 large caps (e.g., a GitHub replication covering 2005–2026 filings) find the headline whole-document effect does not replicate in large caps, though the risk-factor signal points the right way.\[15\] Treat the alpha as decayed and concentrated in smaller, less-covered firms. Loughran & McDonald, "When Is a Liability Not a Liability?" (JF 2011, 66(1):35–65), produced the finance-specific sentiment dictionaries.\[16\] Their Notre Dame SRAF site also distributes cleaned 10-K text, word lists and the file-size readability measure, which they argue beats the Fog index for 10-Ks.

**Risk factors (Item 1A) and cybersecurity risk.** Campbell, Chen, Dhaliwal, Lu & Steele (Review of Accounting Studies 2014, 19(1):396–455) show that mandatory risk-factor disclosures carry information.\[17\] Florackis, Louca, Michaely & Weber, "Cybersecurity Risk" (RFS 2023, 36(1):351–407), build a firm-level cyber-risk measure from 10-K text and find it is priced.\[18\]

**Industries and financial constraints from text.** Hoberg & Phillips, "Text-Based Network Industries and Endogenous Product Differentiation" (JPE 2016, 124(5):1423–1465), build TNIC competitor networks from 10-K Item 1 product descriptions. The data are freely downloadable and widely used, including in competition and merger analysis.\[19\] Constraint measures come from Hoberg & Maksimovic, "Redefining Financial Constraints: A Text-Based Analysis" (RFS 2015, 28(5):1312–1352), using MD&A liquidity text, and from Bodnaruk, Loughran & McDonald, "Using 10-K Text to Gauge Financial Constraints" (JFQA 2015, 50(4):623–646).\[20\]\[21\]

**IPOs, SPACs, M&A.** Hanley & Hoberg, "The Information Content of IPO Prospectuses" (RFS 2010, 23(7):2821–2864), use S-1/424B text to explain IPO pricing.\[22\] ECM desks and journalists watch S-1s, 424B pricing prospectuses and publicly released DRS confidential drafts. Confidential drafts become visible only when the S-1 is made public, which limits their use as a leading indicator. SPAC trackers use S-1, 425, S-4 and DEFM14A filings. M&A analysts mine S-4 and DEFM14A "Background of the Merger" sections, and tender offers appear as SC TO-T.

**Buybacks, dividends, distress and accounting red flags.** Repurchase amounts come from 10-Q/10-K issuer-repurchase tables and XBRL. The 2023 share-repurchase disclosure modernization rule was vacated by the Fifth Circuit in 2023 and never took effect. Distress monitors key on 8-K Item 1.03 (bankruptcy), NT 10-K/NT 10-Q late-filing notices, going-concern language, material weaknesses, Item 4.01 auditor changes and Item 4.02 non-reliance (restatements). Several Apify actors and vendors now sell item-filtered 8-K feeds covering 1.03, 1.05, 2.05, 4.01, 4.02 and 5.02.\[23\]\[24\] Audit Analytics (Ideagen) is the research-grade source for restatements, auditor changes and opinions.

**Funds and ETFs.** N-PORT (monthly portfolio holdings, published quarterly with a lag), N-CEN (annual census of service providers), N-CSR (shareholder reports), 485BPOS (prospectus updates) and N-PX (proxy votes) support fund analytics, ETF holdings research and fee studies. Amended Form N-PX took effect July 1, 2024. It standardizes and XML-structures fund vote records and requires 13F managers to report say-on-pay votes. First filings were due August 31, 2024, covering July 2023–June 2024.\[25\]\[26\] This is a new structured data set on how institutions vote.

**Private markets.** Form D (Reg D offerings), Reg A (1-A, 1-K, 1-SA) and Reg CF (Form C) feed VC/PE trackers, B2B sales "funding trigger" alerts and academic work on private capital formation. **Limitations:** Form D amounts are often "indefinite", there is no valuation data, and filing is frequently late or skipped.

**ABS-EE loan-level data.** Reg AB II asset-level exhibits (auto loans and leases, CMBS, RMBS, debt securities) give loan-by-loan XML. Structured-credit investors and Fed and academic researchers use them, especially for auto credit. Few retail tools touch them.

**Broker-dealer and adviser due diligence.** X-17A-5 FOCUS Part III annual audited reports for broker-dealers are on EDGAR. Form ADV lives on IAPD, not EDGAR. Allocators combine the two for operational due diligence. AI Street's analysis of about 16,000 ADV filings found about 5,800 (just under 40%) mention AI, and 75 of the 100 largest money managers disclosed some AI use.

## 2. Text-Mining, NLP and AI Uses

**Commercial theme extraction and summarization.** AlphaSense (which acquired Sentieo in 2022), Bloomberg, FactSet, Brightwave, Fintool, Daloopa, Calcbench and idaciti offer search, summarization and theme tracking over filings. Most blend EDGAR documents with licensed transcripts and broker research. The pitch for "earnings-themes" is usually transcript-centric. A product that works only from EDGAR primary text (Ex. 99.1, MD&A, 1A, 10-Q Item 2) and returns verbatim, accession-numbered quotes is differentiated on auditability and licensing cost. **This positioning is my inference from product descriptions, not a vendor-confirmed gap.**

**Quote-grounded extraction and RAG.** FinanceBench (Islam et al., 2023, arXiv 2311.11944) is an open-book QA benchmark over public-company filings (10-K, 10-Q, 8-K, earnings releases). Its full set has 10,231 questions and a public 150-question sample. In the original evaluation of 16 model configurations (2,400 hand-reviewed answers), GPT-4-Turbo with a retrieval system incorrectly answered or refused 81% of questions, while long-context configurations did far better. That gap is the core argument for evidence-grounded pipelines. Later benchmarks built from EDGAR include DocFinQA (long-context FinQA), FinQA and TAT-QA (table-text reasoning over financial reports), FinBen/PIXIU (NeurIPS 2024 datasets track) and FinAgentBench (2025). FinAgentBench uses about 3,000 companies' 2023–2024 10-K, 10-Q, 8-K and DEF 14A filings plus transcripts to test agentic retrieval.\[27\] Kim, Muhn & Nikolaev's "Bloated Disclosures" (SSRN 4425527 / arXiv 2306.10224, still a working paper) shows that LLM summaries of MD&A and calls are much shorter, and that the share of "bloat" predicts information frictions.\[28\]\[29\]

**Corpora and tooling.** EDGAR-CORPUS (Loukas et al., ECONLP 2021) packages 10-K items for 1993–2020.\[30\] Its companion edgar-crawler (Loukas et al., WWW 2025 companion) downloads and item-splits filings and was adapted by the Fed's layoff team for 8-Ks.\[1\] Other open-source tools include edgartools, sec-edgar-downloader, python-edgar, secedgar, OpenEDGAR, datamule, the R "edgar" package (SoftwareX 2021), Arelle and py-xbrl for XBRL, and sec-parsers. Commercial APIs include sec-api.io (full-text, item extraction, an MCP server for AI agents) and a growing set of Apify actors. The SEC's own Full-Text Search (efts.sec.gov/LATEST/search-index) covers filings since 2001, including exhibits. It is free and keyless, but its JSON endpoint is undocumented and capped at about 10,000 hits per query.\[31\]\[32\]

**Thematic mention measurement.** Counting AI, DEI, China, remote-work, climate, pandemic and tariff mentions in 10-Ks is now a staple of journalism and consultancy. Recent examples (methodologies vary, so the numbers are not comparable):
- Metal (analysis by software engineer Pablo Rios, reported by CFO Dive): 85% of Fortune 500 10-Ks mention AI, up from 29% in 2022, and total AI mentions across FY2022–2025 filings grew 601%.
- An arXiv study of more than 30,000 10-Ks from over 7,000 firms: more than 50% of companies mention AI, and over 43% mention AI risks.\[33\]
- Context Analytics: 3,545 of 6,258 U.S. 10-Ks filed in 2026 (57%) mention AI.\[34\]
- An EDGAR full-text count by startbusinessbystate.com: 70.7% of 10-Ks filed Jan 1–Sep 27, 2026 contain "artificial intelligence", up from 18.6% in 2023.\[35\]

The spread (57% vs. 71% for 2026) comes from different denominators and phrase rules. It shows the need for transparent, reproducible mention indices, which is a product opportunity. "AI-washing" has also become an SEC enforcement theme.

## 3. Labor-Market and Employment Uses (Extended)

**Layoff tracking via 8-K Item 2.05.** Item 2.05 ("Costs Associated with Exit or Disposal Activities", in force since 2004) requires a filing when a board commits to an exit plan that triggers *material* charges, including severance under ASC 420.\[1\] The best evidence is Crane, Green, Harnish, McClennan, Soto, Vrankovich & Williams, "Tracking Real Time Layoffs with SEC Filings: A Preliminary Investigation" (FEDS 2024-020, Federal Reserve Board).\[1\] Their findings:
- Only 0.38% of 8-Ks in 2022 (258 filings) included Item 2.05.\[1\]
- Layoffs also appear under Items 7.01 and 8.01 (present in about 24% and 22% of 8-Ks). They found these with phrase lists ("reduction in force", "workforce reduction", "eliminate staff positions", "reduce headcount") refined iteratively with BERT embeddings plus XGBoost. These items contribute about 16% of layoff events (roughly 7,000 in total).\[1\]
- A Llama 2 pass found several hundred more but with non-trivial false positives, so the authors excluded them.\[1\]
- Worker counts are parsed from numbers or percentages near layoff words, scaled by lagged Compustat employment.\[1\]
- The series tracks the Great Recession and COVID. It rose less than UI claims in 2020, likely because temporary layoffs carry little severance. It was unusually elevated in 2023: 8-K layoff events were up 145.56% in 2022Q4–2023Q1 and 81.72% in 2023Q2–Q4 versus 2019, while UI claims, JOLTS layoffs and WARN notices were essentially flat.
- Linked to WARN notices (285 matched layoffs), neither source dominates on timing: about 25% appear in 8-Ks four or more weeks before the WARN notice, about 22% in the same week, and about 18% of WARN notices come more than four weeks before the 8-K. Only about 23% of 8-K layoffs would meet WARN filing thresholds.
- In-sample, the series helps forecast unemployment and initial claims.\[1\]

The Fed team did not use the public EDGAR website but the daily feed of all filings through the SEC's dissemination vendor, Attain (Crane et al., fn. 1). Prior accounting work on 2.05 includes Jung et al. (2016) and Laurion (2020), as cited by Crane et al.

**Existing trackers.** FactFiled's "Layoffs 2026" page lists Item 2.05 filings found via EDGAR full-text search, rechecked every few days.\[36\] Apify and other commercial 8-K item feeds expose 2.05 as a filter.\[24\] Layoffs.fyi (tech-focused, media-sourced), TrueUp, and WARN aggregators (e.g., WARNTracker; Quiver Quantitative has offered WARN-notice data, though I could not verify its current product) cover different populations. **I found no maintained, open, research-grade EDGAR layoff panel with worker counts, which is a clear gap.**

**How the sources compare:**
- **EDGAR 8-K:** public companies only, materiality-gated, firm-level, often has a dollar charge and sometimes headcount, filed within four business days (though firms may wait until employees are told).\[1\]
- **WARN:** establishment-level, all ownership types, threshold-based (generally 50+ at a site), state-by-state formats.
- **Layoffs.fyi/TrueUp:** fast, tech-skewed, media-sourced.
- **BLS JOLTS/CES:** comprehensive, survey-based, lagged, not firm-identified.

The best product fuses all four and uses EDGAR for dollar costs and firm identifiers.

**Headcount.** Firms disclose employee counts in 10-K Item 1. An XBRL element exists (dei:EntityNumberOfEmployees), but few filers tag it. Data vendors report that the companyconcept endpoint for it returns nothing for most firms, so headcount must be extracted from text.\[37\]\[38\] Compustat's EMP is the research standard. It is annual, and its timing and definitions are mixed (FTE vs. headcount, global vs. U.S.).

**Human-capital disclosures (Reg S-K 101(c), since Nov 9, 2020).** The principles-based rule requires a description of human-capital resources, including headcount, where material. The evidence:
- Bourveau, Chowdhury & Le ("Human Capital Disclosures") find quantitative metrics were rare before the rule (fewer than 2% of 10-Ks for most categories). Afterwards, disclosure rose mainly in DEI and turnover metrics.\[39\]\[40\]
- As summarized by Georgiev (Emory, 2024), Demers et al. (2024) find, across more than 3,600 firms, that 10-Ks with quantitative HC metrics rose from 40% to 72%, the average number of metrics went from 1 to 2.5 by 2023, and 28% still disclose none.\[41\]
- Gibson Dunn's four-year S&P 500 survey (Dec 2024): diversity-in-hiring disclosure rose to 60% (from 47% in 2021). Quantitative turnover rates, union relations and safety each appear in under 16% of filings.\[42\]

The SEC's Investor Advisory Committee recommended prescriptive HC metrics in September 2023.\[42\] The current Commission's January 2026 directive to review Reg S-K, and its deregulatory agenda, make new mandates unlikely.\[43\] DEI language has also been retreating in 2025–2026 10-Ks, which is itself measurable.

**Labor costs, unions, strikes.** XBRL tags such as LaborAndRelatedExpense, SalariesAndWages and ShareBasedCompensation are tagged only by some filers. Union coverage ("none of our employees are represented by a labor union") is boilerplate in Item 1 and easy to extract. Strikes surface in 8-K 7.01/8.01 and 10-Q risk updates.

**Executive turnover (8-K 5.02).** Officer and director departures and appointments must be filed within four business days. CEO-turnover datasets, executive recruiters and governance analysts mine these (BoardEx and ExecuComp are the curated equivalents). The F5 Item 1.05 8-K in October 2025 also carried a 5.02 director resignation, which shows the value of reading all items in a filing.\[44\]

**Labor shortages and hiring difficulty.** 10-Q/10-K mentions of "labor shortage", "wage inflation" and "difficulty hiring" serve as text-based tightness indicators. I could not confirm a specific published Fed note built from EDGAR (rather than transcripts) for labor shortages. Flag this as unverified.

**Employee plans (11-K).** Form 11-K (401(k) and ESOP annual reports) is now subject to Inline XBRL under the FASB Employee Benefit Plan taxonomy, phased in over three years.\[45\] Plan-level structured data is emerging.

## 4. Macroeconomic, Policy and Nowcasting Uses

- **Fed staff work.** Crane et al. (2024) is the clearest EDGAR-native nowcasting paper. The Fed's July 2026 note "The AI Buildout and the Economy" (Soto, Thieu & Allen) compiles big-tech capex, much of it from filings, alongside BEA and Census data.\[46\] A San Francisco Fed Economic Letter (May 2026) uses earnings-call AI sentiment, not EDGAR, and finds the four hyperscalers drove most AI-positive firms' 2025 investment growth.\[47\]
- **Caldara-Iacoviello et al.** "The Economic Effects of Trade Policy Uncertainty" (JME 2020) uses earnings-call transcripts (about 160,000 calls; firms mentioning TPU rose from 2.8% in 2017 to about 13% later).\[48\]\[49\] It is *not* an EDGAR measure, but the same tariff dictionary ("tariff*", "import dut*", "import barrier*", "trade polic*") applied to 10-K/10-Q text would be a free EDGAR analogue, relevant again after the 2025 tariff shock.\[50\]
- **XBRL frames as macro series.** The frames API returns one value per filer for a concept and period, which allows aggregation of capex, cash, buybacks and inventories across all filers. I found no evidence that BEA uses EDGAR XBRL in official corporate-profits estimates; BEA relies on IRS and QFR data. Treat any such claim as unverified.
- **Pipelines.** S-1 flow and the timing of public DRS releases, plus S-4/DEFM14A/SC TO-T counts, are widely used as sentiment indicators by bankers and journalists.
- **Antitrust and market definition.** Hoberg-Phillips TNIC similarity, Exhibit 21 subsidiary maps, segment disclosures (ASC 280) and customer-concentration disclosures (10% customers; FactSet Revere and Compustat segments) support market definition and supply-chain mapping.
- **Tax havens and corporate structure.** Dyreng & Lindsey (JAR 2009, 47(5):1283–1316) built the canonical Exhibit 21 text search for tax-haven subsidiaries.\[51\] Journalists (ICIJ-style) and KYC vendors reuse Exhibit 21.
- **SEC DERA.** DERA publishes structured data sets (financial statements, 13F, N-PORT, Form D, logs) and economic analyses supporting rulemaking.

## 5. Corporate Governance, Accounting and Legal Uses

- **Compensation and voting:** DEF 14A Summary Compensation Tables (ExecuComp), CEO pay ratio, pay-versus-performance (tagged via the ECD XBRL taxonomy) and say-on-pay results. Vote results are filed under 8-K Item 5.07 within four business days. ISS and Glass Lewis build policies from them. The SEC's May 19, 2026 proposals to simplify filer categories and revise executive-compensation disclosure could change these inputs.
- **Audit and fraud:** Audit Analytics (fees, opinions, restatements, auditor changes), AAER-based fraud-prediction research, and XBRL-based earnings-management and tagging-error studies.
- **Comment letters:** CORRESP (company replies) and UPLOAD (staff letters) are released at least 20 business days after review completion. Practitioners use them to anticipate staff positions; academics study disclosure changes they cause.
- **Contracts:** Exhibit 10 material contracts are the de facto free precedent library for lawyers (Bloomberg Law, Intelligize, Law Insider-style tools) and a research source. Nini, Smith & Sufi's "Creditor Control Rights and Firm Investment Policy" (JFE 2009, 92(3):400–420) and "Creditor Control Rights, Corporate Governance, and Firm Value" (RFS 2012, 25(6):1713–1761) used credit agreements and text-searched covenant violations.\[52\]\[53\]
- **Litigation and KYC:** Item 3 legal proceedings, class-action monitoring, beneficial-ownership checks (13D/G, proxy ownership tables) and related-party transactions (Item 404).
- **Climate:** The March 2024 climate rule was stayed and never took effect. The SEC dropped its defense in March 2025. The Eighth Circuit has held the case in abeyance since September 2025 and denied a motion to lift the abeyance on May 21, 2026.\[54\]\[55\] The SEC proposed rescission on May 29, 2026 (published in the Federal Register on June 3, 2026).\[56\] Climate data now comes from voluntary 10-K risk text and California SB 253/261 regimes (the latter partly enjoined).
- **Cyber:** Item 1.05 has been effective since December 18, 2023, alongside annual 10-K Item 1C governance disclosure. After the SEC staff's May 2024 statement, firms shifted non-material incidents to Item 8.01.\[57\]\[58\] Trackers record the shift:
  - Debevoise: 26 Item 1.05 filers by February 2025.\[58\]
  - Wilson Sonsini: 80 cyber 8-Ks from 54 companies through January 19, 2025, 51% under 1.05 and 43% under 8.01.\[59\]
  - sec-api.io: 31 companies from March 1 to August 18, 2026, only 13 under 1.05.\[60\]
  
  **Any cyber product must therefore scan 1.05, 8.01 and 7.01, not just 1.05.**
- **Conflict minerals (Form SD):** still filed annually. Used by NGOs and supply-chain compliance teams.

## 6. Journalism, Competitive Intelligence, Sales, Education, Regulators

- **Journalism:** Form 4 investigations (WSJ insider-trading series), executive-pay rankings (NYT/Equilar, AP), 13F stories (Bloomberg), and ProPublica's tax and ownership work built on Exhibit 21 and proxies. Reporters lean heavily on Full-Text Search.
- **Competitive intelligence and benchmarking:** segment data, risk-factor and peer-mention analysis, and pricing commentary in MD&A.
- **B2B sales triggers:** Form D (new funding), S-1, 8-K 5.02 (new executives), 1.01 (material contracts) and 2.01 (acquisitions) feed CRM enrichment.
- **Executive recruiting:** 5.02 departures signal open seats.
- **Education:** financial-statement-analysis courses use EDGAR filings as cases. LLM "companion apps" (e.g., the one released with Kim-Muhn-Nikolaev) now support teaching.\[61\]
- **Regulators and rating agencies:** SEC enforcement and Corp Fin review, FINRA, state securities regulators and credit-rating agencies all consume EDGAR. Many large vendors (and the Fed team) take the paid SEC public dissemination feed for timeliness.

## 7. Meta-Uses of EDGAR Itself

- **Log files:** DERA's EDGAR Log File Data Sets cover January 1, 2003–June 30, 2017 and May 19, 2020–June 30, 2025. July 2017–May 2020 is no longer available, and the newer files omit some fields, including full IP information.\[62\]\[63\]
- **Research using the logs:**
  - Loughran & McDonald, "The Use of EDGAR Filings by Investors" (Journal of Behavioral Finance 2017), found the average firm's 10-K was requested only 28.4 times right after filing. Their FOIA request prompted the SEC to publish the logs.\[64\]\[65\]
  - Drake, Roulstone & Thornock, "The Determinants and Consequences of Information Acquisition via EDGAR" (Contemporary Accounting Research 2015), find that EDGAR access improves market efficiency.\[66\]\[67\]
  - Later work uses IP blocks to identify institutions (e.g., Iliev et al. on mutual-fund governance research) and to separate robot traffic from human traffic. The common filter excludes IPs making more than 5 requests per minute or more than 1,000 per day.\[68\]\[69\]
- **XBRL quality** studies document tagging errors and extension overuse.
- **Filing timing** studies examine Friday-evening and holiday filings, NT filings and 8-K deadline compliance.

## EDGAR Data-Access Landscape and 2024–2026 Changes

- **Free official access:**
  - data.sec.gov submissions and XBRL APIs (companyfacts, companyconcept, frames), keyless with a required User-Agent.
  - Nightly bulk submissions.zip and companyfacts.zip.
  - Daily, quarterly and full indexes.
  - RSS feeds.
  - efts Full-Text Search, covering 2001 onward per the SEC FAQ.\[70\]
  - DERA structured data sets: Financial Statement and Notes, 13F, N-PORT, N-CEN, Form D, Reg A, Reg CF and others.
  - The SEC's fair-access policy limits automated traffic to 10 requests per second.
- **EDGAR Next:** enrollment opened March 24, 2025. Compliance became mandatory on September 15, 2025: Login.gov individual credentials, multi-factor authentication, account administrators and filer API tokens. The enrollment window ran to December 19, 2025; after that, unenrolled filers must reapply with a notarized Form ID.\[71\]\[72\]\[73\] This affects filers and filing agents, not public data consumers.
- **Structured-data expansions:** 13D/G XML (December 18, 2024); N-PX XML with manager say-on-pay votes (August 2024 onward); cyber Item 1.05 and the CYD taxonomy for 10-K Item 1C; ECD pay-versus-performance tagging; Inline XBRL filing-fee exhibits (required since July 31, 2025); 11-K Inline XBRL phase-in.\[74\]
- **Pending changes that could reshape data products:**
  - The proposed optional semiannual reporting rule (May 5, 2026, Release S7-2026-15). It would create Form 10-S due 40–45 days after the half-year, in place of three 10-Qs, with 8-K duties unchanged. Comments closed July 6, 2026.\[43\]\[75\]\[76\]\[77\] If adopted, quarterly MD&A and XBRL series would become irregular for electing firms, and 8-K Item 2.02 releases and 7.01 materials would become relatively more important.
  - The May 19, 2026 filer-status and executive-compensation proposals.\[43\]
  - The climate-rule rescission proposal.

## Gaps and Emerging Opportunities

1. **An open, research-grade 8-K layoff panel.** Item 2.05 plus 7.01/8.01, with extracted headcount, percentage, dollar charge, location and verbatim quote, linked to WARN establishments and lagged headcount. The Fed's prototype shows signal; the Llama 2 false-positive problem shows that modern LLMs with quote-grounding and human review could raise recall.
2. **A quarterly headcount and human-capital panel.** Extract Item 1 headcount, union share, turnover and DEI metrics, which XBRL largely lacks, along with 10-Q headcount mentions and restructuring headcount targets. The DEI retreat in 2025–2026 is itself a trackable series.
3. **Quote-grounded earnings themes from EDGAR-native text.** Ex. 99.1 releases, MD&A and Item 1A diffs (Lazy-Prices-style change detection at sentence level) with accession-numbered evidence. This avoids transcript licensing and fits the auditability needs that FinanceBench-type failures expose.
4. **EDGAR-text macro indices.** Tariff, supply-chain, labor-shortage, AI and uncertainty mention rates from 10-K/10-Q/8-K. These are free analogues of transcript-based Fed measures, with transparent denominators to settle the 57%-vs-71% problem.
5. **Newly structured feeds:** 13D/G XML activism alerts, N-PX institution-level vote analytics, multi-item cyber-incident databases, and ABS-EE consumer-credit nowcasts.
6. **Regime-change monitoring:** who elects semiannual reporting, if it is adopted, and how disclosure shifts into 8-Ks.

## Caveats

- Transcripts are not on EDGAR. Many "text" findings in the literature (Caldara et al. TPU, Jha et al., SF Fed AI sentiment) come from licensed call data.
- Item 2.05 is materiality-gated and covers public companies only, so many layoffs (private firms, small cuts, attrition) never appear. Industry mix is skewed: Crane et al. find SIC 737 (computer programming and data processing) and SIC 283 (drugs) accounted for more than 65% of the 2023 increase in 8-K layoffs, and about 11% of public firms are pharmaceutical manufacturers versus 0.03% of all firms.
- Headcount is annual, mostly untagged, and definitions vary.
- XBRL tags are inconsistent across filers.
- AI-mention statistics vary widely by method.
- Kim-Muhn-Nikolaev "Bloated Disclosures" and Jha et al. remain working papers.
- I did not independently verify current product features for OpenInsider, WhaleWisdom, AlphaClone, Quiver Quantitative, Brightwave, Fintool or idaciti. I also did not verify whether BEA uses XBRL, or any EDGAR-based Fed labor-shortage index.
- The required references list is omitted from this version per the output format. Sources are named inline.

## Sources

1. <https://www.federalreserve.gov/econres/feds/files/2024020pap.pdf>
2. [\[PDF\] Financial Statement Analysis with Large Language Models](https://www.semanticscholar.org/paper/Financial-Statement-Analysis-with-Large-Language-Kim-Muhn/77f2e8dc258600dea936c8356770dd0bdc478252)
3. [Decoding Inside Information](https://dash.harvard.edu/entities/publication/73120379-15cc-6bd4-e053-0100007fdf3b)
4. [Are insider trades informative? - Korea Advanced Institute of Science and Technology](https://pure.kaist.ac.kr/en/publications/are-insider-trades-informative/)
5. [Anticompetitive Effects of Common Ownership - AZAR - 2018 - The Journal of Finance - Wiley Online Library](https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12698)
6. [Anticompetitive Effects of Common Ownership](https://www.ecgi.global/publications/paper-publications/anticompetitive-effects-of-common-ownership)
7. [Hedge Fund Activism, Corporate Governance, and Firm Performance - BRAV - 2008 - The Journal of Finance - Wiley Online Library](https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.2008.01373.x)
8. [Reminders: Amended Beneficial Ownership Rules Effective; Upcoming Filing Deadlines](https://www.skadden.com/insights/publications/2024/02/reminders-amended-beneficial-ownership-rules-effective)
9. [SEC Modernizes Beneficial Ownership Reporting on Schedule 13D and 13G with XML format](https://www.toppanmerrill.com/blog/sec-modernizes-beneficial-ownership-reporting-on-schedule-13d-and-13g-with-xml-format/)
10. [Chatgpt and Corporate Policies by Manish Jha, Jialin Qian, Michael Weber, Baozhong Yang :: SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4731070)
11. [The Economic Effects of Trade Policy Uncertainty by Dario Caldara, Matteo Iacoviello, Patrick Molligo, Andrea Prestipino, Andrea Raffo :: SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3473067)
12. [Publication: Lazy Prices](https://dash.harvard.edu/entities/publication/576a041c-19c4-47d8-b28d-2a5ef079f54f)
13. [Lazy Prices: 22% Alpha in 10-Ks Nobody Reads](https://www.quantt.co.uk/resources/lazy-prices-snowflake-cortex-ai)
14. [Lazy Prices by Lauren Cohen, Christopher J. Malloy, Quoc H. Nguyen :: SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1658471)
15. [GitHub - Shardul-Pandit/Lazy-Prices: Lazy Prices" (JF 2020): 10-K text changes as a return signal, built from raw SEC filings. · GitHub](https://github.com/Shardul-Pandit/Lazy-Prices)
16. [Publications](https://sites.nd.edu/tim-loughran/publications/)
17. [The information content of mandatory risk factor disclosures in corporate filings](https://www.semanticscholar.org/paper/The-information-content-of-mandatory-risk-factor-in-Campbell-Chen/1d282e6b954acbddfc1264ef5bbf1682e92a8c8a)
18. [Cybersecurity Risk](https://academic.oup.com/rfs/article-abstract/36/1/351/6585907)
19. [Hoberg and Phillips Data Library](http://hobergphillips.tuck.dartmouth.edu/)
20. [Using 10-K Text to Gauge Financial Constraints by Andriy Bodnaruk, Tim Loughran, Bill McDonald :: SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2331544)
21. [Hoberg and Maksimovic Data Library](https://faculty.marshall.usc.edu/Gerard-Hoberg/MaxDataSite/)
22. [Information Content of IPO Prospectuses](https://academic.oup.com/rfs/article-abstract/23/7/2821/1588747)
23. [SEC 8-K Tracker: Earnings, Exec Changes, M&A, Cyber Events · Apify](https://apify.com/scrapemint/sec-8k-event-tracker)
24. [SEC 8-K Scraper: EDGAR Material Event Alerts by Item · Apify](https://apify.com/openwell-data/sec-8k-event-monitor)
25. [Reminder: New Say-on-Pay Disclosures for Institutional Investment Managers Now Effective](https://foleyhoag.com/news-and-insights/publications/alerts-and-updates/2024/july/reminder-new-say-on-pay-disclosures-for-institutional-investment-managers-now-effective/)
26. [SEC.gov](https://www.sec.gov/resources-small-businesses/small-business-compliance-guides/enhanced-reporting-proxy-votes-registered-management-investment-companies-reporting-executive)
27. [FinAgentBench: A Benchmark Dataset for Agentic Retrieval in Financial Question Answering](https://arxiv.org/pdf/2508.14052)
28. [5757 S. University Ave. Chicago, IL 60637 Main: 773.702.5599 bfi.uchicago.edu](https://smallake.kr/wp-content/uploads/2023/06/BFI_WP_2023-59.pdf)
29. [Bloated Disclosures: Can ChatGPT Help Investors Process Information?](https://ideas.repec.org/p/arx/papers/2306.10224.html)
30. [EDINET-Bench: Evaluating LLMs on Complex Financial ...](https://pub.sakana.ai/edinet-bench/EDINET-Bench.pdf)
31. [SEC EDGAR Full-Text Search API: Every Filing Since 2001 — Edgrapi](https://edgrapi.com/blog/sec-edgar-api-full-text-search)
32. [EDGAR Full-Text Search: Search Inside SEC Filings + EFTS API Guide](https://edgarscout.com/full-text-search/)
33. [Are Companies Taking AI Risks Seriously?A Systematic Analysis of Companies’ AI Risk Disclosures in SEC 10-K forms](https://arxiv.org/html/2508.19313v1)
34. [The Quiet Part: What 10-K Risk Factors Say About AI in 2026 - Context Analytics](https://www.contextanalytics-ai.com/case-studies/the-quiet-part-what-10-k-risk-factors-say-about-ai-in-2026/)
35. [AI in 10-K Filings (2026): 71% of Annual Reports Mention AI](https://startbusinessbystate.com/ai-in-10-k-filings/)
36. [Layoffs 2026: Company List From SEC Filings, Updated](https://factfiled.com/jobs/trackers/layoffs-2026)
37. [SEC EDGAR API: past the filers to 64M records](https://companydata.com/sec-edgar-api/)
38. [Number of Employees: Financial Ratio Definition & Meaning](https://www.geminiq.com/financial-definitions/number-of-employees)
39. [Human Capital Disclosures∗ Thomas Bourveau† Maliha Chowdhury‡ Anthony Le§](https://www.tilburguniversity.edu/sites/default/files/download/ThomasBourveau.pdf)
40. [Human Capital Disclosures∗ Thomas Bourveau† Maliha Chowdhury‡ Anthony Le§](https://uwaterloo.ca/ctr-sustainability-performance-management/sites/default/files/uploads/documents/human-capital-disclosures.pdf)
41. [Human Capital Disclosure & Corporate Governance](https://scholarlycommons.law.emory.edu/cgi/viewcontent.cgi?article=1289&context=faculty-articles)
42. [Four Years of Evolving Form 10-K Human Capital Disclosures - Gibson Dunn](https://www.gibsondunn.com/four-years-of-evolving-form-10-k-human-capital-disclosures/)
43. [FEDERATED HERMES, INC. - Form 10-Q - FY2026](https://www.sec.gov/Archives/edgar/data/0001056288/000105628826000026/fhi-20260630.htm)
44. [F5, INC. - Form 8-K - FY2025](https://www.sec.gov/Archives/edgar/data/1048695/000104869525000149/ffiv-20251015.htm)
45. [Form 11-K Inline XBRL compliance: Key requirements and timing](https://www.toppanmerrill.com/blog/form-11-k-inline-xbrl-compliance-key-requirements-and-timing/)
46. [The Fed - The AI Buildout and the Economy: Publicly Available Data to Assess AI's Impact](https://www.federalreserve.gov/econres/notes/feds-notes/the-ai-buildout-and-the-economy-publicly-available-data-to-assess-ais-impact-20260717.html)
47. [Is Optimism for Artificial Intelligence Boosting Investment? - San Francisco Fed](https://www.frbsf.org/research-and-insights/publications/economic-letter/2026/05/is-optimism-for-artificial-intelligence-boosting-investment/)
48. [The Economic E↵ects of Trade Policy Uncertainty⇤ Dario Caldara](https://www.stern.nyu.edu/sites/default/files/assets/documents/Caldara_Iacoviello_Molligo_Prestipino_Raffo.pdf)
49. [The Economic Eﬀects of Trade Policy Uncertainty ∗](https://clausen.berkeley.edu/wp-content/uploads/2020/01/Economic-Effects-of-Trade-Policy-TPU_PAPER_final.pdf)
50. [1\. Introduction 2. Firm-Level TPU 3. Aggregate TPU 4. DSGE Model 5. Conclusions](https://www.matteoiacoviello.com/research_files/TPU_SLIDES.pdf)
51. [Strategic Subsidiary Disclosure Scott Dyreng Jeffrey L Hoopes](https://www.bauer.uh.edu/departments/accy/research/documents/Dyreng-Strategic-Subsidiary-Disclosure.pdf)
52. [Gregory Nini, PhD](https://www.lebow.drexel.edu/people/gregorynini)
53. [Replication of “Creditor Control Rights, Corporate Governance, and Firm Value”](https://dmurav.com/replications/releases/v2026-09-06/reports/paper-faf236e614ee.pdf)
54. [Chamber of Commerce v. SEC](https://www.uschamber.com/cases/capital-markets-and-corporate-law/sec-climate-disclosure-rule)
55. [CSW INDUSTRIALS, INC. - Form 10-K - FY2026](https://www.sec.gov/Archives/edgar/data/0001624794/000162479426000027/cswi-20260331.htm)
56. [SEC Proposes Rescission of Climate-Related Disclosure Rules - Gibson Dunn](https://www.gibsondunn.com/sec-proposes-rescission-of-climate-related-disclosure-rules/)
57. [SEC Cybersecurity Disclosure Trends: 2025 Update on Corporate Reporting Practices](https://www.gtlaw.com/en/insights/2025/2/sec-cybersecurity-disclosure-trends-2025-update-on-corporate-reporting-practices)
58. [Cyber Disclosure: Statistics from the 8-Ks Filed To Date : TheCorporateCounsel.net Blog](https://www.thecorporatecounsel.net/blog/2025/03/cyber-disclosure-statistics-from-the-8-ks-filed-to-date.html)
59. [Form 8-K Cybersecurity Incident Disclosure Trends](https://connect.societycorpgov.org/blogs/randi-morrison/2025/02/19/form-8-k-cybersecurity-incident-disclosure-trends)
60. [List all cybersecurity incidents in a date range](https://sec-api.io/financial-analysis-prompts/cybersecurity-incident-disclosures)
61. [Financial Statement Analysis with Large Language Models Alex G. Kim1](https://www.bayes.citystgeorges.ac.uk/__data/assets/pdf_file/0009/799794/Alex-Kim_Financial_Statement_Analysis_with_Large_Language_Models__2024_-6.pdf)
62. [SEC.gov](https://www.sec.gov/data-research/sec-markets-data/edgar-log-file-data-sets)
63. [edgar log file data sets](https://www.sec.gov/about/data/edgar-log-file-data-sets)
64. [Loughran 2017](https://www.scribd.com/document/942332650/Loughran-2017)
65. [EDGAR Server Log](https://sraf.nd.edu/data/edgar-server-log/)
66. [Text analysis in financial disclosures](https://arxiv.org/pdf/2101.04480)
67. [The Determinants and Consequences of Information Acquisition via EDGAR](https://www.researchgate.net/publication/270223507_The_Determinants_and_Consequences_of_Information_Acquisition_via_EDGAR)
68. [The Use of EDGAR Filings by Investors](https://www.researchgate.net/publication/316716080_The_Use_of_EDGAR_Filings_by_Investors)
69. [Investors’ Attention to Corporate Governance Peter Iliev Penn State University](https://www.aeaweb.org/conference/2019/preliminary/paper/drZTnSnA)
70. [EDGAR Full-Text Search API: efts.sec.gov Parameters](https://datatooly.xyz/guides/sec-edgar-full-text-search-api/)
71. [Federal Register :: EDGAR Filer Access and Account Management](https://www.federalregister.gov/documents/2024/12/27/2024-30494/edgar-filer-access-and-account-management)
72. [Deadline Approaching: Enroll in EDGAR Next No Later than September 12, 2025 to Avoid Late Filings with the SEC](https://www.dorsey.com/newsresources/publications/client-alerts/2025/9/edgar-next)
73. [EDGAR Next Timeline & Key Deadlines for SEC Filers](https://www.m2compliance.com/edgar-next-timeline.php)
74. [SEC Seal SEC Logo](https://www.edgarfiling.sec.gov/Welcome/EDGARLogin.htm)
75. [Heads Up — SEC Proposes Optional Semiannual Reporting for Public Companies in Lieu of Quarterly Reporting (May 8, 2026)](https://dart.deloitte.com/USDART/home/publications/deloitte/heads-up/2026/sec-proposes-semi-annual-reporting)
76. [Goodbye 10-Q? SEC Proposes Semiannual Reporting Option for Public Companies with New Form 10-S](https://www.jw.com/news/insights-sec-semiannual-reporting-change/)
77. [SEC Proposes Optional Semiannual Reporting Regime: What Companies Should Consider Now](https://www.sidley.com/en/insights/newsupdates/2026/05/sec-proposes-optional-semiannual-reporting-regime-practical-considerations)
