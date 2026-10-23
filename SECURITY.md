# Security policy

## Reporting a vulnerability

Please do not open a public issue for security problems. Report them privately through
[GitHub Security Advisories](https://github.com/emersonmrd/auto-send/security/advisories/new).

Include what you found, how to reproduce it and the version or commit affected. You should get an
answer within a few days. Fixes go into the next release, and the advisory is published after it ships.

## Scope

Auto-Send is self-hosted and meant to run on a trusted machine or network. Reports are most useful
when they concern:

- leaking a bot token to logs, API responses or the frontend;
- path traversal or unsafe handling of uploaded media;
- server-side request forgery through inline button URLs or chat resolution;
- injection in messages sent to Telegram;
- supply-chain issues in the dependencies, container images or the Windows package.

## Supported versions

Only the latest release receives fixes.
