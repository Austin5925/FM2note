# FM2note 共享转录缓存 (cache_sidecar)

可选的 FastAPI + SQLite sidecar，配合 fm2note 客户端实现"两人订阅同一批播客时谁先转完另一方零成本拿现成 .md"。

## 部署

### 1. 把 server/ 拷到服务器
```bash
scp server/cache_sidecar.py server/__init__.py \
    server/Dockerfile.cache server/docker-compose.cache.yaml \
    <host>:/root/fm2note-cache/server/
```

### 2. 生成 token 并启动
```bash
ssh <host>
mkdir -p /root/fm2note-cache/server
TOKEN=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
echo "$TOKEN" > /root/.fm2note-cache-token
chmod 600 /root/.fm2note-cache-token

cd /root/fm2note-cache/server
SHARED_CACHE_TOKEN=$TOKEN docker compose -f docker-compose.cache.yaml up -d --build
```

容器会在 `127.0.0.1:8765` 暴露 HTTP（仅 localhost，必须走反代加 TLS）。

### 3. nginx 反代（示例）
追加到现有 server block：
```nginx
location /fm2note-cache/ {
    proxy_pass http://127.0.0.1:8765/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    client_max_body_size 6m;
    proxy_read_timeout 60s;
}
```
`nginx -t && systemctl reload nginx`

### 4. 验证
```bash
curl https://your-host.com/fm2note-cache/healthz
# {"ok":true,"version":"1.4.16"}

curl -H "Authorization: Bearer $TOKEN" https://your-host.com/fm2note-cache/cache/nonexistent
# {"ok":false,"error":"not found"}  (HTTP 404 with body)
```

### 5. 每个客户端 `.env` 加：
```
export SHARED_CACHE_URL=https://your-host.com/fm2note-cache
export SHARED_CACHE_TOKEN=<the same token>
```

重启 fm2note 后，pipeline 会在每集开始前 GET /cache/{guid}，命中就跳过 ASR+摘要+渲染，直接 write_note；每集 write_note 后 fire-and-forget POST /cache/{guid} 上传。

## 协议

| 端点 | 方法 | 鉴权 | 返回 |
|---|---|---|---|
| `/healthz` | GET | 无 | `{"ok": true, "version": "..."}` |
| `/cache/{guid}` | GET | Bearer | 200 `{ok, guid, content, uploader_fp, updated_at}` / 404 `{ok: false, error}` |
| `/cache/{guid}` | POST | Bearer | upsert · last-write-wins · 200 `{ok, guid, updated_at}` |

## 安全

- Bearer token 用 `hmac.compare_digest` 避免 timing leak（v1.4.16 audit fix #2）
- 单 aiosqlite 连接 GET/POST 都走 `db_lock` 防止并发 interleave（v1.5.4 audit fix）
- HTTP middleware 校验 Content-Length 在 FastAPI buffer 前 reject 超大 body（v1.4.16 Codex #6）
- guid 长度 ≤ 256
- 单次 upload ≤ 5MB
- 启动时缺 token 直接拒跑（v1.4.16 design）
- 没有 enumeration endpoint —— 攻击者拿到 token 也无法列出已上传的 guid

## 当前已知部署

| Host | URL | Deployed | 备注 |
|---|---|---|---|
| macroclaw.app | https://macroclaw.app/fm2note-cache | 2026-05-25 (v1.5.4) | server-side 详细记录见 `/root/fm2note-cache/README.md` |

## 客户端集成位置

| 文件 | 行 | 作用 |
|---|---|---|
| `src/shared_cache.py` | 全文件 | client + URL 编码 + 5s timeout + swallow-all 错误 |
| `src/episode_processor.py` | 143 | `from_config` 调 `SharedCacheClient.from_env()` |
| `src/episode_processor.py` | 166-170 | cache-hit short-circuit 入口 |
| `src/episode_processor.py` | 221-222 | upload-after-write |
| `src/episode_processor.py` | 260-307 | `_handle_cache_hit` 含 idempotent guard（笔记已存在不重写） |

## 故障排查

- **没命中**：检查 client side `SharedCacheClient.from_env()` 返回 None? → env vars 没设
- **总是 401**：token 不匹配（chmod 600 之后 cat 重新核对）
- **upload 失败**：5s timeout 太短？大 .md 可能受影响 → 改 `_TIMEOUT_SEC` 或 server 反代 `proxy_read_timeout`
- **两人都改了同一 guid**：last-write-wins，不会报错；guid 是 RSS 标准里的"该 episode 的全局唯一 id"，两人 feed 拿到的 guid 应该完全相同
