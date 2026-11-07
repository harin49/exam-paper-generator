# Development and releases

## Try edits without pushing

Add the marketplace from your clone instead of GitHub:

```
/plugin marketplace add /path/to/exam-paper-generator
```

The plugin's files are then read straight from the repo, so an edit takes effect after
`/reload-plugins` or in the next session, with no version change.

## Run the tests

From the repo root:

```bash
pip3 install -r requirements-dev.txt
```

```bash
python3 -m unittest discover tests
```

`requirements-dev.txt` adds pypdf, which the PDF-content tests need; they are skipped without it. The
tests use fixed data in `tests/test_data/` (a small 21-mark paper, plus a 50-mark spec for the
blueprint generator), never `examples/` or generated papers.

## Release a change

Claude Code copies a new version of the plugin only when the `version` in
`plugins/exam-papers/.claude-plugin/plugin.json` changes. To release: commit the change, raise the
version (for example `0.4.0` to `0.5.0`), and push to `main`.

## Update an installed plugin

- **Desktop app or Cowork:** **Check for updates** on the marketplace (**Sync automatically** does it
  for you).
- **Claude Code:**

  ```
  /plugin marketplace update exam-paper-generator
  ```

  ```bash
  claude plugin update exam-papers@exam-paper-generator
  ```

A session already open keeps the version it started with; a new session, or `/reload-plugins`, loads
the new one.
