# Corpus Documentation

Source: FAST-NUCES public website (`nu.edu.pk`) · Documents: 6 · Total Pages: 224

This document maps all seven required corpus properties defined in Section 2 of Assignment 02 to demonstrate that every RAG failure mode is reachable and testable in RAHBAR.

## Required Properties Mapping

| # | Required property | Document(s) that provide it | Failure mode it makes reachable | Evidence and implementation notes |
|---|---|---|---|---|
| 1 | At least 6 documents, 40 pages in total, all public | All 6 documents in `corpus/raw/` (see table below) | None; sets realistic scale | Total 6 PDF documents totaling 224 pages verified by checksums in `corpus/MANIFEST.md`. |
| 2 | Two versions of one policy | `undergraduate-academic-rules-aug-2023.pdf` vs `academic-rules-handbook-jun-2026.pdf` | E: Outdated source; retriever faithfully returns the wrong year | The 2023 undergraduate policy is marked `doc_version: "2023-08"`, `superseded: true`. The 2026 handbook is marked `doc_version: "2026-06"`, `superseded: false`. Without metadata filtering on `superseded`, semantic retrieval confuses old rules (such as repealed grade replacement rules) with current ones. |
| 3 | Scanned, image-only PDF with no text layer | `faculty-entrepreneurship-and-technical-start-ups-policy.pdf` | A: Bad extraction; missing text layer | Font inspection with `pdffonts` returns an empty font list; naive text extraction yields 0 characters. The document requires optical character recognition (OCR) via pytesseract / tesseract-ocr to recover text, or an honest documented extraction boundary. |
| 4 | A table with real information | `annual-report-2019-20.pdf` | A: Bad extraction; table columns come out jumbled | Pages 14–22 contain multi-column statistical tables for faculty headcount, PhD faculty per campus, graduate statistics, and research publications. Naive text dumping merges rows across columns, destroying numerical meaning. |
| 5 | Long definitions | `student-handbook-jun-2026.pdf` | B: Poor chunks; fixed-size chunker cuts context in half | Sections on the Student Code of Conduct, Academic Integrity, and the Generative AI Policy contain dense multi-part definitions spanning 450+ tokens. Fixed-token chunkers split sentences mid-clause, losing key qualifiers. |
| 6 | A deliberately absent topic | Hostel Accommodation, Mess, and Curfew Rules | Abstention (Section 3.4); testing honest refusal | We deliberately excluded `Transport and Hostel Facilities.pdf`. The Student Handbook merely mentions hostels exist as a campus amenity, but provides zero rules for allotment or curfew. The system must abstain (`answered_from_context: false`). |
| 7 | Exact-term content | `academic-rules-handbook-jun-2026.pdf`, `prospectus-2026-academic-rules-and-regulations.pdf` | Embeddings blur exact numeric thresholds and clause IDs | Specific terms include: clause numbers ("Clause 1.21", "Clause 5.4"), CGPA thresholds ("2.00" for warning, "1.70" for probation), degree codes ("BSCS", "BSEE"), and per-credit fees. Dense embedding vectors map these closely to unrelated rules, motivating precise retrieval and filtering. |

---

## Detailed Inventory of Documents

### 1. Undergraduate Academic Rules (Aug 2023)
- **File:** `undergraduate-academic-rules-aug-2023.pdf`
- **Pages:** 52
- **Version:** `2023-08` (`superseded: true`)
- **Role:** Represents the legacy policy. Clause numbering, probation rules, and course repeat policies differ from the 2026 handbook. Serves to verify that query-time metadata filtering prevents quoting obsolete university regulations.

### 2. Academic Rules Handbook (Jun 2026)
- **File:** `academic-rules-handbook-jun-2026.pdf`
- **Pages:** 53
- **Version:** `2026-06` (`superseded: false`)
- **Role:** Represents current binding academic regulations. Numbered clauses specify attendance (Clause 1.21, 80% requirement) and academic warning (Clause 5.4, CGPA < 2.00).

### 3. Prospectus 2026 - Academic Rules and Regulations
- **File:** `prospectus-2026-academic-rules-and-regulations.pdf`
- **Pages:** 5
- **Version:** `2026` (`superseded: false`)
- **Role:** Condensed summary published for incoming students. While covering identical concepts to the handbook, it uses alternative numbering (e.g., Attendance is Clause 1 rather than 1.21), exposing how exact terms differ across document formats.

### 4. Student Handbook (Jun 2026)
- **File:** `student-handbook-jun-2026.pdf`
- **Pages:** 62
- **Version:** `2026-06` (`superseded: false`)
- **Role:** Contains expansive definitions for student disciplinary procedures and the Generative AI policy with multi-tiered subclauses. Used to evaluate structure-aware chunking vs fixed-size chunking.

### 5. Annual Report 2019-20
- **File:** `annual-report-2019-20.pdf`
- **Pages:** 40
- **Version:** `2019-20` (`superseded: false`)
- **Role:** Provides complex multi-column tabular data on campus metrics (Islamabad, Lahore, Karachi, Peshawar, Chiniot-Faisalabad), student enrollments, faculty profiles, and research publication counts.

### 6. Faculty Entrepreneurship and Technical Start-ups Policy
- **File:** `faculty-entrepreneurship-and-technical-start-ups-policy.pdf`
- **Pages:** 12
- **Version:** `2022-05` (`superseded: false`)
- **Role:** Scanned image-only policy. `pdffonts` returns no fonts; plain text extraction yields empty pages. Exercises the OCR pipeline (tesseract / pdf2image) and demonstrates handling of documents lacking native PDF font glyphs.

---

## Deliberately Absent Topic and Abstention Strategy

The university website hosts documents regarding campus transportation routes, vehicle parking permits, and hostel accommodation allocations. We intentionally excluded `Transport and Hostel Facilities.pdf` from the indexed corpus. 

While students frequently search for hostel admission deadlines, hostel room fees, mess charges, and curfew hours, the corpus contains no authoritative text answering these questions. In RAHBAR's query pipeline, these queries trigger the relevance floor check: because retrieved passage similarity scores fall below the minimum relevance threshold (0.65), the system declines honestly (`answered_from_context: false`, `confidence: "low"`), preventing fabricated hallucinations.
