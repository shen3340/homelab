# Ollama Gateway

Failover gateway for local Ollama hosts.

## Architecture

Open WebUI
↓
ollama-gateway
↓
primary Ollama
↓ failure
backup Ollama
↓ unavailable
Wake-on-LAN
↓
backup Ollama

## Hosts

Primary:

192.168.50.50:11434

Backup:

192.168.50.115:11434

## Networks

Gateway uses the external Docker network:

ai-net

## Configuration

Copy:

.env.example

to:

.env

Do not commit `.env`.

## Local testing

Build:

docker compose build

Start:

docker compose up -d

Gateway test:

curl http://localhost:11435/health

Backend test:

curl http://localhost:11435/backend

Ollama models:

curl http://localhost:11435/api/tags

## Failover testing

### Primary

Verify primary is online:

curl http://localhost:11435/api/tags

Expected models should match primary.

### Backup

Stop primary Ollama.

Run:

curl http://localhost:11435/api/tags

Gateway should use backup.

### Wake-on-LAN

Hibernate backup.

Stop primary.

Run:

curl http://localhost:11435/api/tags

Gateway should:

1. Detect primary failure.
2. Detect backup failure.
3. Send WoL.
4. Wait for backup.
5. Poll /api/tags.
6. Forward request.

## Open WebUI

Do not change Open WebUI until gateway testing succeeds.

After testing, configure Open WebUI to use:

http://ollama-gateway:11434

## Security

Gateway is intended for internal Docker/LAN use.

Do not expose Ollama or gateway through:

- Cloudflare
- public DNS
- public reverse proxy
- Internet
