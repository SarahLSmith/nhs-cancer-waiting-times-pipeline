# Working rules for this project

These rules apply to every person and every AI agent working in this repository.

## Git and reviews
- Never commit to `main`. Work on a feature branch.
- Open a pull request for Sarah to review manually before anything reaches `main`.
- Commit only when Sarah asks.

## Changes
- No structural or code changes without prior approval.
- Suggestions go in text first. They become code only after approval.
- If anything is unclear, ask before acting.

## Data
- Raw NHS files and the local database are never committed (`landing/`, `warehouse/` are git-ignored).
- Only the small summary outputs the dashboard reads may be committed.
- No sensitive information in the repository, in commit messages, or in shared outputs.
- Every ICB mapping decision is recorded in `docs/decisions.md` with its source.

## Code
- Python 3.11+, formatted with **black** (`python -m black .`) before every commit.
- Every public function has a docstring written for a non-specialist reader.
- Tests must pass (`python -m pytest`) and `python -m pipeline` must finish with every check passing before a pull request is opened.
- Settings belong in `config/sources.yml`, not in code.

## Agents
- The Reviewer role checks a change against these rules before a pull request is opened.
- Agents never merge pull requests.
