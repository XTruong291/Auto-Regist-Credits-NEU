# Home Production Deployment

This deployment runs the NEU registration stack on a Windows machine through Docker Desktop and publishes it with Cloudflare Tunnel.

## Requirements

- Docker Desktop with WSL2 backend.
- A Cloudflare account and a domain configured in Cloudflare.
- A Cloudflare Tunnel token.
- Windows sleep/hibernate disabled while the service must stay online.

## Setup

Copy the example env file:

```powershell
Copy-Item .env.home.example .env.home
```

Edit `.env.home`:

```text
POSTGRES_PASSWORD=...
CLOUDFLARE_TUNNEL_TOKEN=...
```

Create the backup folder:

```powershell
mkdir backups
```

Start:

```powershell
docker compose -f docker-compose.home.yml --env-file .env.home up -d --build
```

Logs:

```powershell
docker compose -f docker-compose.home.yml --env-file .env.home logs api --tail=100
docker compose -f docker-compose.home.yml --env-file .env.home logs worker --tail=100
docker compose -f docker-compose.home.yml --env-file .env.home logs cloudflared --tail=100
```

Stop:

```powershell
docker compose -f docker-compose.home.yml --env-file .env.home down
```

## Backup

Run from the backend folder:

```powershell
.\deploy\home\backup-db.ps1
```

Backups are written to `.\backups`.

## Cloudflare Tunnel

In Cloudflare Zero Trust:

- Create a tunnel.
- Use the generated tunnel token in `.env.home`.
- Add a public hostname such as `neu.example.com`.
- Point the service to `http://proxy:80`.

Cloudflared runs inside Docker, so `proxy` is resolved by the Docker network.

---

## Phương án miễn phí: Quick Tunnel (không cần domain)

Dùng `docker-compose.quicktunnel.yml` — không cần tài khoản Cloudflare, không cần domain.

**Nhược điểm:** URL ngẫu nhiên, thay đổi mỗi khi restart cloudflared.

Setup:

```powershell
Copy-Item .env.quicktunnel.example .env.quicktunnel
```

Điền `POSTGRES_PASSWORD` vào `.env.quicktunnel`, sau đó chạy:

```powershell
docker compose -f docker-compose.quicktunnel.yml --env-file .env.quicktunnel up -d --build
```

Lấy URL công khai từ log:

```powershell
docker compose -f docker-compose.quicktunnel.yml --env-file .env.quicktunnel logs cloudflared
```

Tìm dòng có dạng:
```
Your quick Tunnel has been created! Visit it at (it may take some time to be reachable):
https://abc-def-ghi.trycloudflare.com
```

Dừng:

```powershell
docker compose -f docker-compose.quicktunnel.yml --env-file .env.quicktunnel down
```
