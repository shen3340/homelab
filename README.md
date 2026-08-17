# Homelab

Personal self-hosted infrastructure running on a Synology NAS.

This repository contains Docker Compose configurations and infrastructure services used to run my homelab. GitHub acts as source control, while Portainer handles deployment.

## Architecture

```text
GitHub
  │
  ├── Docker Compose
  └── Infrastructure code
          │
          ▼
      Portainer
          │
          ▼
    Docker on Synology
```

External webhook-driven deployments use:

```text
GitHub
  │
  ▼
Cloudflare Tunnel
  │
  ▼
Webhook Dispatcher
  │
  ▼
Portainer
  │
  ▼
Affected Docker Stack
```

A single GitHub webhook is used for the repository. Dispatcher determines which stacks changed based on repository paths, then tells Portainer to redeploy only those stacks.

## Repository

```text
homelab/
├── services/
│   └── webhook-dispatcher/
│
└── stacks/
    └── ...
```

### `services/`

Infrastructure services that support homelab automation and management.

### `stacks/`

Individual applications running as Docker Compose stacks.

## Infrastructure

Current infrastructure includes services for:

- Media
- Monitoring
- AI / local LLMs
- Knowledge management
- Authentication
- Home automation
- Password management
- Networking
- Infrastructure automation

The homelab is designed around self-hosting, automation, reproducibility, and minimizing externally exposed services.

## Networking

External access is handled through Cloudflare Tunnel.

Administrative access uses Tailscale.

Docker services communicate over dedicated internal networks rather than exposing every service directly to the internet.

## GitOps

Infrastructure changes are made through Git.

```text
Edit
  ↓
Commit
  ↓
Push
  ↓
GitHub
  ↓
Portainer
  ↓
Docker
```

The goal is for infrastructure to be understandable from its code rather than relying on undocumented manual changes.

---

This repository is primarily a record of my homelab and an ongoing experiment in self-hosted infrastructure, automation, and local computing.
