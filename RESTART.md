# Hướng dẫn khởi động lại hệ thống

## Yêu cầu trước khi bắt đầu

- Docker Desktop đang chạy (kiểm tra icon ở system tray — cá voi xanh)
- Mở PowerShell, di chuyển vào thư mục backend:

```powershell
cd F:\PROJECTS\tinchineu\backend
```

---

## 1. Khởi động

```powershell
docker compose -f docker-compose.quicktunnel.yml --env-file .env.quicktunnel up -d
```

> Lần đầu sau khi cài đặt hoặc có thay đổi code: thêm `--build` vào cuối lệnh.

---

## 2. Lấy URL public mới

URL thay đổi mỗi lần khởi động lại. Chạy lệnh sau để lấy:

```powershell
docker compose -f docker-compose.quicktunnel.yml --env-file .env.quicktunnel logs cloudflared | Select-String "trycloudflare"
```

Kết quả sẽ có dạng:
```
https://abc-def-ghi.trycloudflare.com
```

---

## 3. Kiểm tra trạng thái

```powershell
docker compose -f docker-compose.quicktunnel.yml --env-file .env.quicktunnel ps
```

Tất cả container phải ở trạng thái `running`. Riêng `neu-postgres-qt` cần thêm `(healthy)`.

---

## 4. Xem log khi có lỗi

```powershell
# Tất cả services
docker compose -f docker-compose.quicktunnel.yml --env-file .env.quicktunnel logs --tail=50

# Từng service
docker compose -f docker-compose.quicktunnel.yml --env-file .env.quicktunnel logs api --tail=50
docker compose -f docker-compose.quicktunnel.yml --env-file .env.quicktunnel logs worker --tail=50
docker compose -f docker-compose.quicktunnel.yml --env-file .env.quicktunnel logs cloudflared --tail=50
```

---

## 5. Dừng hệ thống

```powershell
docker compose -f docker-compose.quicktunnel.yml --env-file .env.quicktunnel down
```

> Dữ liệu database được giữ nguyên. Chỉ dùng `down -v` nếu muốn xóa toàn bộ dữ liệu.

---

## Backup database

```powershell
.\deploy\home\backup-db.ps1 -ComposeFile docker-compose.quicktunnel.yml -EnvFile .env.quicktunnel
```

File backup được lưu vào thư mục `backups\`.
