# Changelog

## 0.1.0 (unreleased)

First release.

- `@anakin` step decorator: gives a step an Anakin client as `current.anakin`, on `anakin-sdk`
  0.2, with one method per Anakin capability (23 in all): scrape, batch scrape, map, crawl,
  search, agentic search, Wire discovery, catalog, read/write actions, identities, login and
  builds, website monitors, AI visibility, browser sessions and AI browser tasks.
- Results are plain dicts and lists, so artifacts can be read back without `anakin-sdk`.
- Each task's API calls are saved to task metadata. Read them with `get_anakin_calls(task)`
  or show them with `@card(type="anakin_calls")`.
- Steps with `@pypi` get `anakin-sdk` added to their packages.
- `wire_write_action` refuses to run on a `@retry` re-attempt unless you allow it, and the
  client refuses to be stored as an artifact, which would persist the API key.
