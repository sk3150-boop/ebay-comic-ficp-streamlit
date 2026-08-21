# eBay Manga CSV FICP Assistant: Oracle Always Free deployment

## What this deployment creates

- One Oracle Always Free Ubuntu ARM VM running the Streamlit app and PostgreSQL in Docker Compose.
- A local-only port `127.0.0.1:8501`; it is not exposed directly to the Internet.
- A separately configured Cloudflare named Tunnel for HTTPS and a fixed hostname.

The application starts `comic_ficp_streamlit_app.py` explicitly. It creates a new authentication database: old user accounts, stored API keys, and login cookies cannot be restored after the expired VPS was removed.

## Do not deploy the dirty local source folder

Deploy from this clean Git checkout at commit `93ff8a0` or from the corresponding GitHub `main` branch. Do not copy the mixed camera/apparel changes from `C:\Users\sk315\OneDrive\ドキュメント\新画像精査ツール`.

## 1. Create the Oracle VM

In Oracle Cloud Console, create an Always Free eligible Ubuntu VM using `VM.Standard.A1.Flex`, with at most 2 OCPUs and 12 GB RAM in total across the tenancy. Keep the boot volume within the Always Free allocation. Add only an SSH public key; do not share the private key or console credentials with Codex.

Open no inbound application port. SSH port 22 may be restricted to the operator's IP in the security list. Cloudflare Tunnel uses outbound connections.

## 2. Install Docker and prepare the application

On the VM, clone the repository and enter it:

```bash
git clone https://github.com/sk3150-boop/ebay-comic-ficp-streamlit.git /opt/comic-ficp
cd /opt/comic-ficp
sudo apt-get update
sudo apt-get install -y ca-certificates curl git docker.io docker-compose-v2
sudo usermod -aG docker "$USER"
```

Start a fresh SSH session after the group change. Create the non-versioned environment file locally on the VM:

```bash
cp deploy/oracle/.env.example deploy/oracle/.env
chmod 600 deploy/oracle/.env
openssl rand -base64 36
openssl rand -base64 48
```

Put the first generated value in `POSTGRES_PASSWORD` and the second in `COMIC_FICP_KEY_ENCRYPTION_SECRET`. Save the encryption secret in the operator's password manager; without it, encrypted user API keys in a future restored database cannot be read. Do not put either value in Git, logs, or chat.

Build and start the application:

```bash
docker compose --env-file deploy/oracle/.env -f deploy/oracle/compose.yaml up -d --build
docker compose --env-file deploy/oracle/.env -f deploy/oracle/compose.yaml ps
curl -fsS http://127.0.0.1:8501/_stcore/health
```

The expected health response is `ok`.

## 3. Configure a fixed HTTPS URL

1. Add a domain you already own to Cloudflare's free plan.
2. In Cloudflare Dashboard, create a remotely managed Tunnel named `comic-ficp`.
3. Install `cloudflared` on the Oracle VM using Cloudflare's current Ubuntu instructions.
4. Add a published application route such as `manga.example.com` to `http://localhost:8501`.
5. Install the Cloudflare service so it starts after VM reboots.

Do not use a `trycloudflare.com` Quick Tunnel for this deployment: its URL is temporary and not supported for production use.

## 4. Verify safely

1. Confirm `/_stcore/health` via the public hostname returns `ok`.
2. Open the public app in a private browser window.
3. Register a new test account and verify login/logout plus remembered-login behavior.
4. Add a test API key only if the operator accepts the provider charge, then remove it after verification.
5. Run a one-row CSV test before using actual listing data.

## Backups

Run the following after meaningful account/settings changes and copy the resulting encrypted backup off the VM:

```bash
sh deploy/oracle/backup-db.sh
```

The database dump is sensitive because it contains password hashes and encrypted API-key blobs. Keep it outside the repository and retain the matching `COMIC_FICP_KEY_ENCRYPTION_SECRET` in the password manager.
