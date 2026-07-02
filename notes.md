# 2026-06-25
## Project Status

**Telemetry to BI** is currently in an exploratory portfolio-build phase. The core goal is to turn raw transit-style telemetry data into clean, business-intelligence-ready outputs that can support reporting, dashboards, and operational analysis.

At this stage, the project has focused on building a local data-processing pipeline that exports route/day telemetry into structured Excel-compatible reports. The pipeline includes metadata handling, summary tables, and formatting logic intended to make the output usable in tools such as Excel, Power BI, Google Sheets, or other BI platforms.

Current work has included:

* Building a Python-based export script for route/day telemetry analysis
* Generating `.xlsx` outputs with formatted tables and workbook metadata
* Debugging compatibility issues between generated Excel files, Excel Online, and Power BI
* Investigating whether the problem is caused by file formatting, BI tool behavior, VM environment issues, or Microsoft-side ingestion quirks
* Exploring alternative BI/reporting paths after Power BI Desktop and Excel Online proved unreliable in the current environment
* Reframing the project toward practical automation/reporting use cases, especially Google Sheets automation and lightweight BI deliverables

The current blocker is not the telemetry-processing logic itself, but the downstream BI tooling path. Power BI can initially preview and transform the data, but fails or hangs when applying changes. Excel Online has also shown unexpected failures opening or creating workbooks, even with clean test files. Because of this, the project is being steered away from a Power BI-dependent workflow for now and toward more robust, portable reporting outputs.

Near-term priorities are:

1. Stabilize the export format so outputs are consistently accepted by common spreadsheet tools.
2. Add simple, demonstrable analytics such as per-route summaries, daily aggregates, time-on-task metrics, and anomaly flags.
3. Produce portfolio-friendly sample reports that show operational value without requiring a fragile BI setup.
4. Evaluate Google Sheets, Looker Studio, lightweight web dashboards, or static HTML reports as practical alternatives.
5. Package the project as an “Automated Quality / Operations Report Generator” style demo for Upwork and portfolio use.

The project is not yet a finished BI dashboard product. It is currently best understood as a telemetry-to-reporting pipeline under active development, with the processing layer taking shape and the presentation layer still being selected.

# 2026-06-28
## Architecture Update: Reporting Delivery Layer

The Telemetry to BI project has evolved from a traditional desktop BI workflow into a cloud-based reporting automation pipeline. Rather than centering the final deliverable around a locally maintained Power BI or Excel environment, the project now focuses on automated report generation using Google Workspace services.

The underlying analytics pipeline remains unchanged. The Python application queries InfluxDB for route telemetry, parses the raw CSV output, standardizes identifiers and timestamps, derives operational features such as service date, hour, weekday, operating period, suspicious coordinates, and record classifications, and produces a collection of summary datasets using pandas.

The primary architectural change is the reporting layer. Instead of generating local spreadsheet artifacts for manual consumption, the pipeline now publishes results directly to Google Sheets, creating a cloud-hosted workbook that can be shared, distributed, and regenerated automatically.

Current workflow:

```text
Local InfluxDB data
→ Python extraction pipeline
→ pandas cleaning and transformation
→ Google OAuth authentication
→ Google Drive workbook creation
→ multi-tab reporting output
```

Each execution produces a workbook in Google Drive containing multiple reporting tabs, including:

* Daily Summary
* Hourly Summary
* Stop Summary
* Weekday Summary
* Operational Period Summary
* Metadata
* Raw Data

This transition moves the project beyond simple local analysis and toward a reusable office automation pattern: operational data in, business-ready reporting artifact out.

A significant portion of the recent work involved hardening the supporting infrastructure.

On the data side, the local InfluxDB environment was standardized to ensure reliable execution. Because the Docker configuration relies on relative volume mappings, the container must be launched from the correct project context (`wimbac-influx-copy`) to guarantee consistent access to persistent telemetry storage. Establishing a repeatable startup process restored stable query execution and improved overall reproducibility.

On the reporting side, several Google authentication strategies were evaluated. Service accounts successfully authenticated with the Google Sheets API and remain an excellent option for shared resources, existing spreadsheets, and organizational environments. However, because this project is designed to generate new reporting artifacts within a personal Google Drive environment, OAuth authentication using a personal Google account proved to be the more appropriate architecture.

The application now uses a standard OAuth flow:

* `client_secret.json` defines the OAuth application credentials.
* A one-time browser authorization grants access to the user's Google account.
* `token.json` stores and reuses the resulting access credentials for subsequent runs.

Conceptually:

```text
Service account:
  Best for bots, shared resources, existing sheets, and Workspace environments

OAuth personal account:
  Best for generating and managing new artifacts within a personal Google Drive
```

For Telemetry to BI, OAuth aligns naturally with the project's reporting model because each execution should be capable of producing a fresh, independently shareable workbook.

### Current milestone

```text
InfluxDB → Python analytics → Google Sheets workbook
```

The project now demonstrates a complete end-to-end automation workflow:

1. Extract operational telemetry.
2. Transform and summarize the data.
3. Publish a business-facing reporting artifact automatically.

This represents a strong portfolio example of practical office automation and operational reporting.

### Planned next steps

```text
1. Stabilize and refactor the Google Sheets publishing layer.
2. Add a README/dashboard worksheet as the workbook landing page.
3. Improve workbook presentation with formatting, frozen headers, and sizing.
4. Add manager-facing insight tabs such as "Top Bottlenecks."
5. Explore charts, Google Docs report generation, PDF export, and scheduled execution.
```

### Project summary

> Telemetry to BI extracts route telemetry from InfluxDB, transforms it into route, time, and stop-level operational summaries, and publishes the results as a multi-tab Google Sheets workbook.

This architecture reflects a common business automation pattern: transforming messy operational data into a clean, shareable reporting artifact that can be regenerated on demand.

# 2026-07-02
This update refactors Telemetry to BI from a single working script into a more maintainable extract-transform-publish pipeline. The Python code is being split into focused modules for querying InfluxDB, cleaning telemetry data, generating route summaries, and publishing outputs to either local Excel/CSV artifacts or Google Sheets. The goal is to make the project easier to understand, extend, and present as a reusable office automation/analytics workflow.

The Google Sheets publisher now creates a shareable workbook with summary tabs for daily, hourly, stop-level, weekday, and operational-period analysis. To keep the workbook reliable at larger data volumes, the full raw telemetry export stays in local CSV artifacts while Sheets receives a capped raw sample and the analysis summaries. This keeps Google Sheets focused on reviewable business-facing outputs instead of trying to act as the full data warehouse.
