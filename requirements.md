# Technical Requirements Specification

## PDF Financial Statement Extraction and Excel Consolidation System

## 1. Purpose

This document defines the technical requirements for a system that extracts consolidated financial statements from company annual reports and quarterly reports in PDF format, normalizes the data, validates financial logic, and consolidates the extracted information into standardized Excel workbooks.

The system must support both initial generation from a set of PDF reports and incremental updates when new reports become available.

---

## 2. Scope

### 2.1 In Scope

The system shall:

1. Process only PDF files.
2. Support multiple companies, with each company managed in a separate folder.
3. Extract consolidated financial statements from annual reports and quarterly reports.
4. Consolidate annual and quarterly financial statement data into one Excel file per company.
5. Normalize all monetary amounts to millions while preserving the original currency.
6. Merge line items across years and quarters using the union of all extracted items.
7. Preserve financial statement hierarchy and indentation where possible.
8. Validate financial logic where feasible.
9. Highlight validation results in Excel.
10. Generate separate source tracking and warning files.
11. Support both:

* initial workbook generation; and
* incremental updates based on newly added reports.

### 2.2 Out of Scope

The system shall not:

1. Process HTML, Word, Excel, image-only files outside PDF containers, or web pages.
2. Perform foreign exchange conversion.
3. Manually standardize every financial statement line item into a fixed accounting taxonomy.
4. Reprocess all historical reports during incremental updates unless explicitly required.
5. Extract non-consolidated financial statements unless consolidated statements are unavailable and a warning is generated.

---

## 3. Input Requirements

### 3.1 File Format

The system shall accept only PDF files.

PDFs may include:

1. Text-based PDFs where text can be directly extracted.
2. Scanned PDFs requiring OCR.
3. Mixed PDFs containing both embedded text and scanned pages.

The system shall detect whether OCR is required on a page-by-page or document-level basis.

### 3.2 Report Language

All input reports are expected to be in English.

The system does not need to support non-English reports.

### 3.3 Folder Structure

The system shall support multiple companies. Each company shall have a separate folder.

Expected folder structure:

```text
Company A/
  Financial_Statements/
    Report 1.pdf
    Report 2.pdf
    Report 3.pdf
  final_excel/
```

Input PDFs shall be stored under:

```text
Financial_Statements/
```

Generated output files shall be stored under:

```text
final_excel/
```

### 3.4 Company-Level Processing

Each company shall produce its own output files.

Reports from different companies shall not be merged into the same Excel workbook.

---

## 4. Financial Statements to Extract

For each PDF report, the system shall extract the following consolidated financial statements where available:

1. Consolidated Statement of Financial Position / Consolidated Balance Sheet
2. Consolidated Statement of Profit or Loss / Consolidated Income Statement
3. Consolidated Statement of Cash Flows
4. Consolidated Statement of Comprehensive Income, if available

The system shall prioritize consolidated statements over parent-company-only or standalone statements.

If a consolidated statement cannot be found, the system shall generate a warning.

---

## 5. Annual and Quarterly Report Handling

### 5.1 Annual Reports

Annual report data shall be identified by fiscal year.

Annual periods shall be displayed from oldest to newest, from left to right.

Example:

```text
2022 | 2023 | 2024
```

### 5.2 Quarterly Reports

Quarterly report data shall represent single-quarter data only.

The system shall not extract year-to-date data such as:

```text
Six months ended
Nine months ended
Year-to-date
```

unless single-quarter data is unavailable. If only year-to-date data is available, the system shall generate a warning.

Quarterly periods shall be displayed from oldest to newest, from left to right.

Quarterly column labels shall use the following format:

```text
Q1 2024
Q2 2024
Q3 2024
Q4 2024
```

---

## 6. Excel Workbook Output

### 6.1 Main Output Workbook

For each company, the system shall generate one main Excel workbook named:

```text
CompanyName_financial_statements_final.xlsx
```

This workbook shall contain the consolidated annual and quarterly financial statements.

### 6.2 Required Sheets

The workbook shall contain the following sheets:

```text
Balance Sheet
Income Statement
Cash Flow & Comprehensive Income
```

### 6.3 Sheet Layout

For each financial statement sheet:

1. Annual data shall be placed on the left side.
2. Quarterly data shall be placed on the right side.
3. One blank column shall separate annual data and quarterly data.
4. Annual columns shall be sorted from oldest year to newest year.
5. Quarterly columns shall be sorted from oldest quarter to newest quarter.

Example layout:

```text
Line Item | 2022 | 2023 | 2024 | [Blank Column] | Q1 2024 | Q2 2024 | Q3 2024
```

### 6.4 Cash Flow and Comprehensive Income Sheet

The `Cash Flow & Comprehensive Income` sheet shall contain:

1. Consolidated Statement of Cash Flows at the top.
2. Consolidated Statement of Comprehensive Income below the cash flow statement, if available.

Both sections shall follow the same annual-left, quarterly-right layout.

---

## 7. Currency and Unit Normalization

### 7.1 Currency

The system shall preserve the original currency used in the reports.

The system shall not perform FX conversion.

Examples:

```text
USD remains USD
HKD remains HKD
JPY remains JPY
```

### 7.2 Unit

All annual and quarterly amounts shall be converted to millions.

Examples:

```text
USD thousands → USD millions
HKD millions → HKD millions
JPY billions → JPY millions
```

Conversion rules:

```text
Thousands to millions: divide by 1,000
Millions to millions: no change
Billions to millions: multiply by 1,000
```

### 7.3 Unit Detection

The system shall detect the stated currency and unit from the relevant financial statement header, table title, footnote, or surrounding text.

Examples:

```text
US$ in thousands
HK$ million
RMB millions
JPY billions
```

### 7.4 Inconsistent Units Within One Report

Although unlikely, the system shall detect if different financial statements within the same report use different units.

If detected, the system shall:

1. Continue extraction.
2. Convert each table to millions independently.
3. Generate a warning in the warning file.
4. Record the original unit and converted unit in the source tracking file.

### 7.5 Inconsistent Currencies Across Reports

If different reports for the same company use different currencies, the system shall:

1. Continue extraction.
2. Not perform FX conversion.
3. Generate a critical warning.
4. Clearly mark the top of the relevant Excel sheets with:

```text
Multiple currencies detected
```

The workbook shall still be generated.

---

## 8. Line Item Merging Rules

### 8.1 Union of Line Items

When consolidating multiple periods, the system shall use the union of all line items.

If a line item exists in one period but not another, the missing period shall be left blank.

Example:

```text
Line Item                    2023       2024
Cash and cash equivalents    100        120
Restricted cash              50
```

### 8.2 Matching Similar Line Items

The system may merge line items with slightly different names only when they are clearly the same item.

Examples of mergeable line items:

```text
Cash and cash equivalents
Cash & cash equivalents
```

```text
Trade receivables
Trade and other receivables
```

The second example should only be merged if the surrounding context confirms that the items are equivalent.

### 8.3 Name Preservation

When line items are merged, the system shall keep the line item name from the latest available report.

Example:

```text
2023 name: Cash & cash equivalents
2024 name: Cash and cash equivalents
Final name: Cash and cash equivalents
```

### 8.4 Non-Mergeable Items

If two line items are similar but not clearly equivalent, they shall remain separate.

The system should avoid aggressive matching that may incorrectly merge distinct accounting items.

### 8.5 Line Item Order

The default line item order shall follow the latest available annual or quarterly report.

Items that exist only in earlier periods shall be inserted in the closest logical position where possible.

If no reliable position can be inferred, they shall be appended within the relevant statement section.

### 8.6 Hierarchy and Indentation

The system shall preserve the original financial statement hierarchy where possible.

Example:

```text
Current assets
    Cash and cash equivalents
    Trade receivables
    Inventories
Total current assets
```

Indentation shall be reflected in Excel formatting.

---

## 9. Excel Formatting Requirements

### 9.1 Top-of-Sheet Metadata

Each sheet shall display currency and unit information at the top.

Example:

```text
Currency: USD
Unit: millions
```

If multiple currencies are detected:

```text
Currency: Multiple currencies detected
Unit: millions
```

### 9.2 General Formatting

The system shall apply a standardized Excel format:

1. Freeze the top title rows.
2. Freeze the first column containing line item names.
3. Use bold formatting for table headers.
4. Use bold formatting for subtotal and total rows.
5. Preserve indentation for financial statement hierarchy.
6. Apply consistent column widths.
7. Apply thousands separators for numbers.
8. Display negative numbers using parentheses.
9. Use one blank column between annual and quarterly data.
10. Use clear section headers for cash flow and comprehensive income.

### 9.3 Number Format

Recommended number format:

```text
#,##0;(#,##0);-
```

Decimals may be retained only if required after unit conversion.

---

## 10. Financial Logic Validation

### 10.1 Validation Scope

The system shall validate all financial logic that can be reasonably checked from the extracted data.

Examples include:

1. Total current assets equals the sum of current asset components.
2. Total assets equals total current assets plus total non-current assets.
3. Total current liabilities equals the sum of current liability components.
4. Total liabilities equals current liabilities plus non-current liabilities.
5. Total equity equals the sum of equity components.
6. Total liabilities and equity equals total liabilities plus total equity.
7. Gross profit equals revenue minus cost of sales, where applicable.
8. Operating profit equals gross profit minus operating expenses, where applicable.
9. Profit before tax equals operating profit plus or minus finance and other items, where applicable.
10. Net profit equals profit before tax minus income tax expense, where applicable.
11. Ending cash equals beginning cash plus net cash flow movements, where applicable.

### 10.2 Validation Tolerance

Validation tolerance shall be zero.

The calculated result must exactly equal the reported value after unit conversion.

### 10.3 Validation Formatting

For cells that can be validated:

1. If validation passes, the reported cell shall be highlighted in green.
2. If validation fails, the reported cell shall be highlighted in red.
3. Cells that cannot be validated shall have no validation color.

### 10.4 Validation Failures

For failed validations, the system shall record the issue in the warning file.

Each validation warning should include:

```text
Company name
Source report
Statement type
Period
Line item
Reported value
Calculated value
Difference
Validation rule
```

---

## 11. Incremental Update Requirements

The system shall support two operating modes.

---

### 11.1 Mode 1: Initialization

Initialization mode shall process all PDF reports under a company’s `Financial_Statements/` folder and generate a new consolidated Excel workbook.

Initialization mode shall:

1. Read all available PDF reports.
2. Classify each report as annual or quarterly.
3. Extract the required consolidated statements.
4. Normalize monetary values to millions.
5. Merge line items across periods.
6. Generate the final Excel workbook.
7. Generate the source tracking file.
8. Generate the warning file.
9. Apply validation checks and Excel formatting.

---

### 11.2 Mode 2: Incremental Update

Incremental update mode shall update an existing final Excel workbook using one or more newly added PDF reports.

Incremental update mode shall:

1. Read only the newly provided PDF reports.
2. Extract financial statement data from the new reports.
3. Normalize monetary values to millions.
4. Merge new data into the existing workbook.
5. Add new periods if they do not already exist.
6. Add new line items if they do not already exist.
7. Preserve existing historical data.
8. Avoid reprocessing all historical PDFs.
9. Update the source tracking file.
10. Update the warning file.

### 11.3 Incremental Update Conflict Handling

If the incoming report contains data for a line item and period that already exists in the workbook, the system shall compare the values.

If the existing value and new value are identical:

```text
No new column is needed.
```

If the existing value and new value conflict:

```text
A new conflict column shall be inserted to the right of the existing period column.
```

Conflict column naming format:

```text
2024 Conflict - ReportName.pdf
Q1 2024 Conflict - ReportName.pdf
```

The conflicting value from the new report shall be written into the conflict column.

The conflict shall also be recorded in the warning file.

---

## 12. Source Tracking File

### 12.1 File Name

For each company, the system shall generate a separate source tracking file:

```text
CompanyName_source_tracking.xlsx
```

### 12.2 Required Fields

The source tracking file shall include, at minimum:

```text
Company Name
Source PDF File Name
Report Type
Fiscal Year
Fiscal Quarter
Statement Type
Extracted Page Number
Original Currency
Original Unit
Converted Unit
Extraction Timestamp
OCR Used
Warnings
```

### 12.3 Report Type Values

Allowed report type values:

```text
Annual
Quarterly
```

### 12.4 Statement Type Values

Allowed statement type values:

```text
Balance Sheet
Income Statement
Cash Flow Statement
Comprehensive Income Statement
```

---

## 13. Warning File

### 13.1 File Name

For each company, the system shall generate a separate warning file:

```text
CompanyName_extraction_warnings.xlsx
```

### 13.2 Warning Severity

Warnings shall be classified by severity:

```text
Info
Warning
Critical
```

### 13.3 Examples of Warning Conditions

The system shall generate warnings for situations including but not limited to:

1. Consolidated statement not found.
2. Comprehensive income statement not found.
3. OCR was required.
4. OCR confidence is low.
5. Table extraction confidence is low.
6. Single-quarter data not found.
7. Only year-to-date data found.
8. Unit inconsistency within the same report.
9. Currency inconsistency across reports from the same company.
10. Possible but uncertain line item match.
11. Validation failure.
12. Duplicate report period detected.
13. Conflict detected during incremental update.

### 13.4 Required Warning Fields

The warning file shall include:

```text
Company Name
Source PDF File Name
Severity
Statement Type
Period
Page Number
Issue Type
Issue Description
Suggested Action
Timestamp
```

---

## 14. PDF Extraction Requirements

### 14.1 Statement Detection

The system shall identify statement pages using keywords and layout context.

Examples of statement title keywords:

```text
Consolidated Statement of Financial Position
Consolidated Balance Sheet
Consolidated Statement of Profit or Loss
Consolidated Income Statement
Consolidated Statement of Comprehensive Income
Consolidated Statement of Cash Flows
```

The system shall avoid extracting:

```text
Parent company statement
Company-only statement
Notes to financial statements
Segment tables
Management discussion tables
Non-GAAP summary tables
```

unless no consolidated statement exists and a warning is generated.

### 14.2 OCR Handling

For scanned PDFs, the system shall apply OCR before table extraction.

The source tracking file shall record whether OCR was used.

If OCR confidence is low, the system shall generate a warning.

### 14.3 Table Extraction

The system shall extract:

```text
Line item names
Period columns
Reported amounts
Currency
Unit
Table hierarchy
Page number
```

The system shall handle common PDF table issues, including:

1. Multi-line line item names.
2. Wrapped text.
3. Negative numbers shown in parentheses.
4. Dashes representing zero or missing values.
5. Footnote markers.
6. Indented line items.
7. Multi-page financial statements.

---

## 15. Data Normalization Rules

### 15.1 Negative Numbers

Numbers shown in parentheses shall be treated as negative values.

Example:

```text
(1,234) → -1234
```

### 15.2 Dashes

Dashes shall be handled according to context.

Recommended treatment:

```text
- or — in numeric cells → blank or zero depending on the report convention
```

If the report clearly uses dashes to mean zero, convert to zero.

If ambiguous, leave blank and generate a low-severity warning.

### 15.3 Footnote Markers

Footnote markers attached to numbers or line items shall be removed during numeric extraction.

Example:

```text
1,234(a) → 1234
Cash and cash equivalents1 → Cash and cash equivalents
```

### 15.4 Duplicated Columns

If a report presents both current and comparative periods, the system shall extract the relevant period according to the report type.

For annual reports, extract annual fiscal year columns.

For quarterly reports, extract single-quarter data only.

---

## 16. Acceptance Criteria

The system shall be considered acceptable if it satisfies the following criteria.

### 16.1 Input and Classification

1. The system accepts PDF files only.
2. The system processes each company folder independently.
3. The system correctly classifies reports as annual or quarterly.
4. The system correctly identifies fiscal years and fiscal quarters.

### 16.2 Extraction

1. The system extracts the required consolidated financial statements where available.
2. The system prioritizes consolidated statements.
3. The system handles both text-based and scanned PDFs.
4. The system records page-level source information.

### 16.3 Excel Output

1. One main Excel workbook is generated per company.
2. Annual data appears on the left.
3. Quarterly data appears on the right.
4. Annual and quarterly sections are separated by one blank column.
5. Annual periods are sorted from oldest to newest.
6. Quarterly periods are sorted from oldest to newest.
7. Cash flow and comprehensive income are placed in the same sheet, with comprehensive income below cash flow.
8. Currency and unit are displayed at the top of each sheet.

### 16.4 Unit Normalization

1. All amounts are converted to millions.
2. Currency is preserved.
3. No FX conversion is performed.
4. Unit and currency inconsistencies are detected and recorded.

### 16.5 Line Item Consolidation

1. The final workbook contains the union of all line items.
2. Missing values for unavailable periods remain blank.
3. Clearly equivalent line items are merged.
4. Merged line items use the latest available name.
5. Hierarchy and indentation are preserved where possible.
6. Default ordering follows the latest available report.

### 16.6 Validation

1. All feasible subtotal and total checks are performed.
2. Validation tolerance is zero.
3. Passing cells are highlighted green.
4. Failing cells are highlighted red.
5. Non-checkable cells remain uncolored.
6. Validation failures are recorded in the warning file.

### 16.7 Incremental Update

1. New reports can be added to an existing workbook.
2. New periods are added as new columns.
3. New line items are added as new rows.
4. Existing historical data is preserved.
5. Conflicting values are placed in conflict columns.
6. Conflict columns follow the agreed naming convention.
7. Incremental updates do not require reprocessing all historical reports.

---

## 17. Output Files

For each company, the system shall generate the following files under `final_excel/`:

```text
CompanyName_financial_statements_final.xlsx
CompanyName_source_tracking.xlsx
CompanyName_extraction_warnings.xlsx
```

---

## 18. Recommended Processing Workflow

### 18.1 Initialization Workflow

```text
1. Scan company folder.
2. Identify all PDF reports under Financial_Statements/.
3. Classify each report as annual or quarterly.
4. Detect fiscal year or fiscal quarter.
5. Locate consolidated financial statement pages.
6. Apply OCR where required.
7. Extract tables.
8. Normalize numbers, currency, and unit.
9. Convert all values to millions.
10. Merge line items across periods.
11. Generate Excel workbook.
12. Run validation checks.
13. Apply formatting and validation coloring.
14. Generate source tracking file.
15. Generate warning file.
```

### 18.2 Incremental Update Workflow

```text
1. Load existing final Excel workbook.
2. Read newly added PDF report or reports.
3. Classify new reports.
4. Extract required consolidated financial statements.
5. Normalize and convert values to millions.
6. Compare new data against existing workbook.
7. Add new periods where needed.
8. Add new line items where needed.
9. Insert conflict columns where conflicting values are found.
10. Update source tracking file.
11. Update warning file.
12. Re-run validation for affected new data only.
13. Save updated workbook.
```

---

## 19. Key Implementation Notes

1. The extraction logic should be conservative. It is better to generate a warning than to silently merge or overwrite uncertain data.
2. Line item matching should combine text similarity with statement context, section hierarchy, and neighboring line items.
3. Incremental update mode should not modify historical values unless a conflict column is explicitly created.
4. Validation logic should only be applied where the required component lines can be clearly identified.
5. OCR output should be auditable through source tracking and warnings.
6. The system should preserve traceability from every extracted number back to the source PDF and page number, even though this traceability is stored in a separate file rather than the main Excel workbook.
