# Auto-Send frontend

Next.js dashboard for Auto-Send. See the [project README](../README.md) for setup and
[`AGENTS.md`](../AGENTS.md) for the engineering rules.

```bash
npm ci
npm run dev            # http://localhost:3000, API from NEXT_PUBLIC_API_URL (default http://localhost:8000)
npm run lint
npm run build
npx playwright test    # E2E against a mocked API
npm run test:real-app  # E2E against the real backend
```
