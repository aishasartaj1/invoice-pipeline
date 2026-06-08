# Invoice Processing Pipeline

An event-driven invoice processing pipeline on Google Cloud Platform that automatically extracts structured data from invoice emails using Gemini AI — with built-in confidence scoring and human review routing.

## Live Demo

Dashboard: https://dashboard-frontend-290164040879.us-central1.run.app

To test: Send an invoice PDF to invoices.processor.aishasartaj@gmail.com
It will appear on the dashboard within ~60 seconds, fully extracted by Gemini AI.

## Architecture

```
Vendor Email
     |
     v
Gmail Inbox (invoices.processor.aishasartaj@gmail.com)
     |
     | Push notification (Gmail Watch API)
     v
email-parser (Cloud Run)
     |-- Downloads PDF attachment
     |-- Uploads to Cloud Storage
     |-- Inserts row into raw_emails (PostgreSQL)
     |-- Publishes event to attachment-events (Pub/Sub)
     |
     v
invoice-worker (Cloud Run)
     |-- Downloads PDF from Cloud Storage
     |-- Extracts text (pypdf)
     |
     |-- Gemini 2.5 Flash: Classify
     |       < 50% confidence → SKIPPED (not an invoice)
     |
     |-- Gemini 2.5 Flash: Extract fields
     |       vendor, invoice number, date, total amount, currency
     |
     |-- Confidence routing:
     |       >= 85% → status: processed (auto)
     |       < 85%  → status: review → published to invoice-review-queue
     |
     |-- Writes to invoices table (PostgreSQL)
     |
     v
dashboard-api (Cloud Run)
     |-- GET /api/invoices
     |-- GET /api/stats
     |
     v
dashboard-frontend (Cloud Run)
     |-- Live dashboard auto-refreshing every 30s
     |-- Stats: total invoices, total value, avg confidence, needs review
     |-- Invoice table: vendor, amount, date, status, confidence bar
```

## Services

- **email-parser** — Flask service triggered by Gmail push notifications. Fetches emails, uploads PDF attachments to GCS, inserts raw_emails rows, publishes Pub/Sub events. Tracks last processed Gmail history ID in PostgreSQL to avoid missed or duplicate messages.

- **invoice-worker** — Flask service triggered by Pub/Sub push. Downloads PDFs from GCS, extracts text with pypdf, runs two-stage Gemini classification and extraction. Routes low-confidence invoices to a human review queue.

- **dashboard-api** — Lightweight read-only Flask API. Reads from PostgreSQL and serves invoice data and aggregated stats to the frontend.

- **dashboard-frontend** — Static dashboard served via nginx. Auto-refreshes every 30 seconds. Shows real-time invoice processing results.

## Confidence & Review System

Gemini extraction returns a confidence score (0.0 to 1.0) for each invoice:

| Confidence | Action |
|---|---|
| < 0.50 | Document skipped — not classified as an invoice |
| 0.50 to 0.84 | Flagged as needs review — published to invoice-review-queue topic |
| >= 0.85 | Auto-processed — written directly to invoices table |

The threshold is configurable via the CONFIDENCE_THRESHOLD environment variable (default: 0.85).

## Stack

- **Google Cloud Run** — all four services, scales to zero when idle
- **Cloud SQL PostgreSQL 15** — raw_emails, invoices, processing_jobs, pipeline_metrics, gmail_state tables
- **Cloud Pub/Sub** — attachment-events (parser to worker), invoice-review-queue (low confidence), invoice-dead-letter (failed after 5 attempts)
- **Cloud Storage** — raw PDF archive with 7-year retention policy
- **Secret Manager** — all credentials stored securely, nothing hardcoded in code or env vars
- **Vertex AI (Gemini 2.5 Flash)** — document classification and structured field extraction
- **Gmail API** — push notifications via watch(), history ID state tracked in DB
- **Python 3.12, Flask, gunicorn** — backend services
- **nginx** — frontend static file serving

## Database Schema

- **raw_emails** — one row per email received (gmail_message_id, sender, subject, gcs_folder)
- **invoices** — one row per processed attachment (inv_number, from_vendor, inv_date, grand_total, confidence, status)
- **processing_jobs** — tracks GCS path processing status (processing, processed, review, failed, skipped)
- **pipeline_metrics** — outcome logging per attachment (confidence, null_field_count, pre_filter_reason)
- **gmail_state** — stores last processed Gmail history ID to ensure no emails are missed

## Repo Structure

    email-parser/        Cloud Run parser service
    invoice-worker/      Cloud Run worker service with Gemini AI
    dashboard-api/       Flask read-only API for dashboard
    dashboard-frontend/  Static HTML/CSS/JS dashboard (nginx)