# Security and deployment boundary

Mock mode is the default and needs no external credentials. Tracked files never contain API keys. Docker loads existing ignored Nexora provider env files when present, then project-local ignored `.env` / `.env.local` overrides. Provider secrets remain backend-only and are never exposed through snapshots, responses, reports, screenshots, or frontend variables.

The Compose deployment binds services to loopback, separates edge and internal data networks, applies `no-new-privileges`, runs the backend as an unprivileged user, and publishes no PostgreSQL interface beyond loopback. The supplied database password is explicitly development-only and must be replaced before any shared environment.
