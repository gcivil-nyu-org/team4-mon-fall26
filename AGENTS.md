# Instructions for coding agents

PlayNYU is a Django app (Django templates, no JavaScript framework) deployed on AWS Elastic Beanstalk.

## UI work

Read [docs/DESIGN.md](docs/DESIGN.md) before creating or changing any template, CSS or page. It is the design system for the whole app: stack and pinned CDN versions, tokens, components with markup, page recipes, and a PR checklist. Follow it exactly. If you need something it doesn't cover, add it to docs/DESIGN.md in the same PR.

## Working agreements

The full workflow is in [docs/WORKFLOW.md](docs/WORKFLOW.md); the short version:


- Every page extends `templates/base.html`. Don't add another layout.
- Branch from `testing` and open pull requests against `testing`. `main` only receives tested merges from `testing`.
- Before opening a PR, run what CI runs: `flake8 .`, `coverage run manage.py test`, `coverage report --fail-under=80`. Format code with black.

All shared docs are listed in the [README](README.md#docs).
