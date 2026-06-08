# Invoice Processing Pipeline

An event-driven invoice processing pipeline on Google Cloud Platform.

## Architecture

Gmail → Cloud Run Parser → GCS → Pub/Sub → Cloud Run Worker → Gemini AI → PostgreSQL

## Services

- **email-parser** — receives Gmail push notifications, uploads attachments to GCS
- **invoice-worker** — classifies and extracts invoice fields using Gemini 2.5 Flash

## Stack

- Google Cloud Run, Cloud SQL (PostgreSQL), Pub/Sub, Secret Manager, GCS
- Vertex AI (Gemini 2.5 Flash)
- Python, Flask