# Changelog

All notable changes to this project are documented here. The format is
loosely based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## Unreleased

### Fixed
- `get_repos` paginated without bound — a user with thousands of repos
  could chew through GitHub's rate-limit quota on the first cache miss.
  Added a `max_repos` cap (default 600, ~7 GitHub requests worst case).
- `get_repos` defaulted to GitHub's `type=all`, which leaks private
  repos visible to the supplied `GITHUB_TOKEN`. Now defaults to
  `type=owner` so the analyzer only returns repos the user owns on
  their personal account.