# Services

Infrastructure services used to support my homelab.

Services in this directory are generally tools for automation, management, networking, or infrastructure rather than individual applications.

## Current Services

### Webhook Dispatcher

Small FastAPI service connecting GitHub to Portainer.

```text
GitHub
  ↓
Cloudflare Tunnel
  ↓
Webhook Dispatcher
  ↓
Portainer
```

Dispatcher examines changed repository paths and determines which Docker stacks need to be redeployed.

For example:

```text
stacks/jellyfin/compose.yml
```

triggers Jellyfin, while a change to an unrelated stack does not.

## Why It Exists

GitHub limits repositories to 20 webhooks.

Instead of creating one webhook for every Docker stack, this project uses one repository webhook and a small routing service.

```text
             GitHub
                │
        1 repository webhook
                │
                ▼
           Dispatcher
                |
                ▼
    Various Docker Containers
```

This allows the number of Docker stacks to grow without creating additional GitHub webhooks.

## Approach

Services in this directory are intended to be:

- Small
- Reproducible
- Containerized
- Source-controlled
- Independently deployable

Secrets and environment-specific configuration are kept outside the repository.
