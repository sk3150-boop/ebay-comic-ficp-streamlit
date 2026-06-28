# VPS deploy

This app can run on a Linux VPS with Docker Compose.

Required environment variables:

```bash
POSTGRES_PASSWORD=<random database password>
COMIC_FICP_KEY_ENCRYPTION_SECRET=<long random encryption secret>
COMIC_FICP_PUBLIC_PORT=8501
```

Start:

```bash
docker compose -f docker-compose.vps.yml up -d --build
```

Check:

```bash
docker compose -f docker-compose.vps.yml ps
curl -fsS http://127.0.0.1:8501/_stcore/health
```

In public mode, users must create an account before using the CSV tool.
AI API keys are encrypted in the PostgreSQL database.
