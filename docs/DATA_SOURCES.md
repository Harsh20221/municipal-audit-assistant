# Where public example documents can be found

Use documents you are allowed to download. Register a file you already have with
`python -m data_sources.register_document`. This project does not crawl or download
these sites.

## Property tax

Municipal property-tax assessments, bills, and receipts are published by each
city corporation, not by one national form.

- [data.gov.in](https://www.data.gov.in/) lists open datasets from Indian government
  departments. Search for property tax or municipal finance.
- [india.gov.in](https://www.india.gov.in/) links to state and city government sites.
  From a city corporation's official site, open its property-tax or citizen-services
  section.

Download a digital PDF (one you can select text in). A scanned image of a bill
cannot be read by this assistant.

## Works projects

Tender notices, work orders, and progress reports are public procurement records.

- [Central Public Procurement Portal](https://eprocure.gov.in/eprocure/app) publishes
  tender and award notices.
- [Government eProcurement System of India](https://etenders.gov.in/) publishes
  state and central tenders.
- City public-works or municipal-engineering pages, linked from the corporation
  site, sometimes publish work orders and monthly progress.

## What to store

Keep the publisher, the page URL, the date you retrieved the file, and whether
it contains personal data. Hand labels go in `data/gold/gold_labels.csv`. Put the
PDF at `data/real/<sha256>.pdf` if you want the Tier A check to score it.
