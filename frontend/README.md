# TantSaakshi frontend

The React source in this folder builds the page served by FastAPI at `/app`.

```powershell
cd frontend
npm install
npm run build
```

The build writes `app.html` and its hashed assets into `backend/static/`. For local frontend work, run `npm run dev`; API requests proxy to the backend on `127.0.0.1:8000`.
