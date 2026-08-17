# Stacks

Docker Compose applications running in my homelab.

Each directory represents an individual application stack managed through Portainer.

## Structure

```text
stacks/
├── jellyfin/
│   └── compose.yml
├── kuma/
│   └── compose.yml
├── vikunja/
│   └── compose.yml
├── open-webui/
│   └── compose.yml
└── ...
```

Each stack is intentionally kept separate so applications can be deployed, updated, and managed independently.

## GitOps

Stack definitions are stored in GitHub and deployed through Portainer.

```text
GitHub
   ↓
Portainer GitOps
   ↓
Docker
```

Changes to stack files can trigger automatic redeployment through the homelab webhook dispatcher.

For example:

```text
stacks/jellyfin/compose.yml
```

is associated with Jellyfin's Portainer stack.

A commit changing multiple stack directories can trigger multiple deployments:

```text
stacks/jellyfin/...
stacks/kuma/...
stacks/vikunja/...
```

→ Jellyfin, Kuma, and Vikunja are all updated.

## Philosophy

Stacks are managed as code whenever possible.

The repository describes what should be running; Portainer and Docker handle running it.

This makes the homelab easier to rebuild, migrate, understand, and experiment with over time.
