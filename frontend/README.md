# Iudicium — Modern Web UI

The Next.js front end for Iudicium's modern web UI. It talks to the root-level FastAPI backend (`backend.py`) over REST, submits case searches as background jobs, and polls for progress and results. See the [project README](../README.md) for the full system overview, including the alternate classic UI.

## Prerequisites

* Node.js 20 or later
* The backend running locally (`uvicorn backend:app --reload --port 8000` from the project root — see the project README's [Running the Application](../README.md#running-the-application) section)

## Getting Started

Install dependencies:

```bash
npm install
```

Point the front end at the backend. Create `frontend/.env.local`:

```text
NEXT_PUBLIC_API_URL=http://localhost:8000
```

Start the development server:

```bash
npm run dev
```

Open `http://localhost:3000` in a browser. The page auto-updates as `app/page.tsx` is edited.

## Project Structure

```text
frontend/
├── app/
│   ├── page.tsx      # main search UI: form state, job polling, results
│   └── layout.tsx     # root layout
├── lib/
│   └── api.ts           # typed client for the backend's REST API
├── public/                # static assets
└── package.json
```

## Available Scripts

| Command | Purpose |
| --- | --- |
| `npm run dev` | Start the development server |
| `npm run build` | Build a production bundle |
| `npm run start` | Serve the production build |
| `npm run lint` | Run ESLint |

## Notes

* This UI uses `NEXT_PUBLIC_API_URL` for every API call (see `lib/api.ts`); without it, requests will fail.
* This front end does not include the AI assistant chat or live WebSocket log streaming found in the classic UI — it polls job status over REST instead. For that functionality, run the classic UI described in the project README.
