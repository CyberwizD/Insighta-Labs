# Contributing

## Branches

- Use focused branch names such as `feat/auth-pkce`, `fix/cli-refresh`, or `chore/docs`.

## Commits

- Use conventional commits with scope.
- Examples:
  - `feat(auth): add refresh token rotation`
  - `fix(cli): retry request after access token refresh`
  - `docs(readme): describe csrf protection`

## Pull Requests

- Open a pull request before merging to `main`.
- Make sure CI passes before requesting review.
- Keep PRs scoped to one concern where possible.

## Local Checks

Run these before opening a PR:

```bash
py -3 -m py_compile app\config.py app\database.py app\ids.py app\models.py app\auth.py app\http_runtime.py app\profiles.py app\main.py cli.py run.py
```
