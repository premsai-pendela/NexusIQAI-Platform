# NexusIQ Web — the product frontend

Next.js 16 + TypeScript frontend for the NexusIQ multi-agent backend.
Warm-editorial design system (`~/Dev/NexusIQ-migration/DESIGN.md` lineage);
three pages: Welcome (`/`), How it works (`/how`), Ask Nexus (`/ask`).

Nothing rendered here is invented: stats come from `GET /api/v1/meta`,
answers stream live over `POST /api/v1/query/stream`, evidence and the
trace timeline come from the enriched answer payload and `GET /api/v1/trace/{id}`.
When the backend is offline the UI says so — it never fakes an answer.

## Run

```bash
# backend (repo root, needs .env)
uvicorn api.main:app --port 8000

# frontend
cd web
npm ci
npm run dev            # http://localhost:3000
```

Point at a remote backend with `NEXT_PUBLIC_API_BASE=https://api.example.com npm run dev`.
Optional `NEXT_PUBLIC_API_KEY` sends `X-API-Key` (public, rate-limited demo key only).
