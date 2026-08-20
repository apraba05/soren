"""Seed corpus of raw invoice text.

Each blob is what you would get out of a PDF text layer for an outside-counsel
invoice: inconsistent spacing, different vendor templates, and one deliberately
bad OCR pass. Nothing here is pre-parsed - the extraction chain has to earn it.
"""

SEED_INVOICES = [
    {
        "id": "INV-2291",
        "file": "wexler_cole_july.pdf",
        "text": """WEXLER & COLE LLP
1 Battery Park Plaza, New York, NY 10004

                            INVOICE

Invoice No:       WC-2291
Invoice Date:     2026-07-31
Client Matter:    MAT-1042 / Acme Robotics v. Nordic Systems
Billing Period:   July 2026

PROFESSIONAL SERVICES
  L120  Analysis/Strategy          6.5 hrs @ $410.00      2,665.00
  L210  Pleadings                  2.0 hrs @ $410.00        820.00

DISBURSEMENTS
  E106  Online research                                      94.00

                     TOTAL DUE (USD)                    $3,579.00

Payment due within 30 days per outside counsel guidelines.""",
    },
    {
        "id": "INV-2292",
        "file": "bramwell_hastings_q3.pdf",
        "text": """Bramwell Hastings LLP
Statement of Account

Matter ID ......... MAT-2287
Matter Name ....... Series C Financing
Invoice ........... BH-88104
Date .............. 2026-08-03

  Partner   J. Bramwell     11.0 hrs   $875/hr      9,625.00
  Associate  R. Okafor      14.5 hrs   $520/hr      7,540.00
  Paralegal  D. Ruiz         6.0 hrs   $210/hr      1,260.00

  Subtotal                                         18,425.00
  Less negotiated discount (8%)                    -1,474.00

  AMOUNT PAYABLE USD                              16,951.00""",
    },
    {
        "id": "INV-2293",
        "file": "ridgeline_ediscovery_aug.pdf",
        "text": """RIDGELINE eDISCOVERY INC.
Data processing & hosting services

Bill To: Legal Operations
Matter: MAT-1042
Invoice #: RE-40219   Date: 2026-08-05

  Processing, 412 GB @ $9.50/GB ................ 3,914.00
  Hosting, 1.2 TB, monthly ....................... 480.00

  TOTAL DUE: $4,394.00

Terms: Net 45.""",
    },
    {
        "id": "INV-2294",
        "file": "tanaka_ip_partners_aug.pdf",
        "text": """TANAKA IP PARTNERS
Intellectual Property Counsel | Tokyo * Palo Alto

INVOICE TIP-7731                     Issued 2026-08-06
Matter Reference: MAT-1042

  Claim chart preparation      8.0 hrs @ $560.00     4,480.00
  Prior art review             3.5 hrs @ $560.00     1,960.00
  E110 Out-of-town travel (airfare, business)          2,180.00

  TOTAL AMOUNT DUE (USD)                            $8,620.00""",
    },
    {
        "id": "INV-2295",
        "file": "orion_court_reporting.pdf",
        "text": """ORION COURT REPORTING
Certified transcripts and videography

Invoice OCR-1188 | 2026-08-07 | Matter MAT-3310

  Deposition transcript, 214 pages @ $4.15 ......... 888.10
  Rough draft, same day ............................ 165.00
  Videographer, 4 hrs @ $95.00 ..................... 380.00

  TOTAL DUE (USD) $1,433.10""",
    },
    {
        "id": "INV-2296",
        "file": "vector_legal_staffing.pdf",
        "text": """VECTOR LEGAL STAFFING
Contract attorney placement

INVOICE VLS-5540
DATE 2026-08-08
MATTER MAT-4455 (EU Data Privacy Audit)

  Contract review, 6 reviewers x 38 hrs @ $72/hr .... 16,416.00
  Project management fee ............................. 1,800.00

  TOTAL 18,216.00 USD""",
    },
    {
        "id": "INV-2297",
        "file": "delacroix_boone_scan.pdf",
        "text": """DELACROIX & B00NE
       -- scanned copy, fax quality --

Invoice  DB-0 9 12          Date  2026/08/09
Matter   MA T-  ????

  Corporate governance advice     4.0 hr5   1,840.OO
  Board minute drafting           2.5 hrs     1,150.00

  T0TAL  DUE     $  2,99O.00

(margin note, handwritten) confirm matter w/ K. Adeyemi""",
    },
    {
        "id": "INV-2298",
        "file": "wexler_cole_aug_supplemental.pdf",
        "text": """WEXLER & COLE LLP

                            INVOICE

Invoice No:       WC-2314
Invoice Date:     2026-08-10
Client Matter:    MAT-3310 / Hollis Employment Arbitration

PROFESSIONAL SERVICES
  L390  Other discovery            3.0 hrs @ $410.00      1,230.00
  A101  Plan and prepare (admin)   1.5 hrs @ $410.00        615.00
  L440  Other trial preparation    2.0 hrs @ $410.00        820.00

                     TOTAL DUE (USD)                    $2,665.00""",
    },
    {
        "id": "INV-2299",
        "file": "halcyon_trial_graphics.pdf",
        "text": """HALCYON TRIAL GRAPHICS
Demonstratives & courtroom presentation

Invoice HTG-2077  //  2026-08-11  //  Matter MAT-1042

  Animation storyboard, 3 scenes .................. 6,300.00
  Exhibit board printing, 22 boards ............... 1,540.00
  Rush surcharge .................................... 900.00

  TOTAL DUE (USD) $8,740.00""",
    },
    {
        "id": "INV-2300",
        "file": "bramwell_hastings_diligence.pdf",
        "text": """Bramwell Hastings LLP
Statement of Account

Matter ID ......... MAT-5001
Matter Name ....... Project Ferrous / M&A Diligence
Invoice ........... BH-88266
Date .............. 2026-08-12

  Partner   J. Bramwell      4.0 hrs   $875/hr      3,500.00
  Associate  L. Vance        2.5 hrs   $520/hr      1,300.00

  AMOUNT PAYABLE USD                                4,800.00""",
    },
    {
        "id": "INV-2301",
        "file": "tanaka_ip_partners_filing.pdf",
        "text": """TANAKA IP PARTNERS

INVOICE TIP-7802                     Issued 2026-08-13
Matter Reference: MAT-1042

  Office action response       2.0 hrs @ $560.00     1,120.00
  USPTO filing fee                                      800.00

  TOTAL AMOUNT DUE (USD)                            $1,920.00""",
    },
    {
        "id": "INV-2302",
        "file": "orion_court_reporting_2.pdf",
        "text": """ORION COURT REPORTING

Invoice OCR-1204 | 2026-08-14 | Matter MAT-3310

  Deposition transcript, 96 pages @ $4.15 .......... 398.40
  Exhibit scanning ................................. 120.00

  TOTAL DUE (USD) $518.40""",
    },
    {
        "id": "INV-2303",
        "file": "delacroix_boone_aug.pdf",
        "text": """DELACROIX & BOONE
Corporate & Governance

Invoice DB-0944            Date 2026-08-15
Matter MAT-5001 / Project Ferrous

  Diligence memo             9.0 hrs @ $455.00      4,095.00
  Signing checklist          2.0 hrs @ $455.00        910.00

  TOTAL DUE     $5,005.00""",
    },
    {
        "id": "INV-2304",
        "file": "wexler_cole_privacy.pdf",
        "text": """WEXLER & COLE LLP

                            INVOICE

Invoice No:       WC-2330
Invoice Date:     2026-08-16
Client Matter:    MAT-4455 / EU Data Privacy Audit

PROFESSIONAL SERVICES
  L110  Fact investigation        5.0 hrs @ $410.00      2,050.00
  L120  Analysis/Strategy         2.0 hrs @ $410.00        820.00

                     TOTAL DUE (USD)                    $2,870.00""",
    },
]

# The first five run through the pipeline at boot so the console is never empty.
PRESEED_IDS = ["INV-2291", "INV-2292", "INV-2293", "INV-2294", "INV-2295"]

BY_ID = {inv["id"]: inv for inv in SEED_INVOICES}
