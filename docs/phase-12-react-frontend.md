# Phase 12: React frontend

Phase 12 adds a responsive React/Vite interface named **CourseLens AI**. Students can validate and upload a PDF directly to private S3 through the presigned form, monitor processing, select indexed sources, ask grounded questions, inspect citations, and launch study tools.

The browser contains no AWS credentials. It knows only the API Gateway URL; upload authorization and all Bedrock/OpenSearch access remain server-side. PDF type and 10 MiB size are checked in the browser for fast feedback and checked again by the backend as the security boundary.

## Run locally

```bash
cd frontend
cp .env.example .env.local
# Replace the placeholder API endpoint in .env.local
npm install
npm run dev
```

Use `npm run build` for a production bundle. API Gateway CORS must use the exact frontend origin (normally `http://localhost:5173` during local development).
