# Invoice Processing Pipeline

An event-driven invoice processing pipeline on Google Cloud Platform that automatically extracts structured data from invoice emails using Gemini AI.

## Live Demo

🖥️ **Dashboard:** https://dashboard-frontend-290164040879.us-central1.run.app

📧 **To test:** Send an invoice PDF to `invoices.processor.aishasartaj@gmail.com` — it will appear on the dashboard within ~60 seconds, fully extracted by Gemini AI.

## Architecture

Gmail → Cloud Run Parser → GCS → Pub/Sub → Cloud Run Worker → Gemini AI → PostgreSQL → Dashboard

## Services

- **email-parser** — receives Gmail push notifications, fetches emails, uploads attachments to GCS, publishes Pub/Sub events
- **invoice-worker** — downloads PDFs from GCS, classifies and extracts invoice fields using Gemini 2.5 Flash, writes to PostgreSQL
- **dashboard-api** — read-only Flask API serving invoice data from PostgreSQL
- **dashboard-frontend** — live dashboard showing processed invoices, totals and confidence scores

## Stack

- **Google Cloud Run** — parser, worker, dashboard API and frontend
- **Cloud SQL (PostgreSQL)** — structured invoice data storage
- **Cloud Pub/Sub** — decoupled event queue between parser and worker
- **Cloud Storage** — raw PDF attachment archive (7-year retention)
- **Secret Manager** — all credentials stored securely, nothing in code
- **Vertex AI (Gemini 2.5 Flash)** — invoice classification and field extraction
- **Python, Flask** — backend services
- **Gmail API** — push notifications via watch()

## How It Works

1. A vendor sends an invoice email with PDF attachment to the processor inbox
2. Gmail push notification triggers the email-parser Cloud Run service
3. Parser downloads the PDF and uploads it to Cloud Storage
4. Parser publishes an event to Pub/Sub with the file location
5. invoice-worker picks up the event and downloads the PDF
6. Gemini 2.5 Flash classifies the document and extracts: vendor, invoice number, date, total amount
7. Extracted data is written to PostgreSQL
8. Dashboard updates automatically within 30 seconds

## Repo Structure

    email-parser/        Cloud Run parser service
    invoice-worker/      Cloud Run worker service with Gemini
    dashboard-api/       Flask read API for dashboard
    dashboard-frontend/  Static HTML/CSS/JS dashboard