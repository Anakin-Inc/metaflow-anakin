# metaflow-anakin

A [Metaflow](https://metaflow.org) extension for [Anakin](https://anakin.io), a web data API. Add `@anakin` to a step to scrape pages to markdown or structured JSON, crawl sites, run AI web search, run [Wire](https://anakin.io/docs) actions on supported sites, and manage website monitors.

```bash
pip install metaflow-anakin
```

Requires Metaflow 2.13+ and Python 3.10 to 3.13.

## Quickstart

```python
from metaflow import FlowSpec, anakin, card, current, step


class WebResearchFlow(FlowSpec):
    @step
    def start(self):
        self.pages_to_scrape = ["https://example.com", "https://www.iana.org/help/example-domains"]
        self.next(self.scrape, foreach="pages_to_scrape")

    @card(type="anakin_calls")
    @anakin
    @step
    def scrape(self):
        self.page = current.anakin.scrape_url(self.input)
        self.next(self.join_pages)

    @step
    def join_pages(self, inputs):
        self.pages = [inp.page for inp in inputs]
        self.next(self.end)

    @step
    def end(self):
        for page in self.pages:
            print(page["url"], len(page["markdown"]), "chars")


if __name__ == "__main__":
    WebResearchFlow()
```

```bash
python web_research_flow.py run
```

This works without an API key on a small free per-IP allowance. For everything else, get a key at [anakin.io/dashboard](https://anakin.io/dashboard) (the free tier needs no card) and set `ANAKIN_API_KEY`.

## What the decorator adds

You can call `anakin-sdk` directly inside a step. `@anakin` handles what tends to go wrong when you do that in a flow:

- **Artifacts stay readable.** Methods return plain dicts and lists, so `Flow(...).latest_run.data.pages` works in a notebook without `anakin-sdk` installed.
- **Your API key stays out of the datastore.** The key is read from the environment, can't be a decorator attribute, and `self.client = current.anakin` fails the step instead of saving it.
- **`@retry` won't repeat a write.** `wire_write_action` refuses to run on a re-attempt unless you set `@anakin(allow_write_on_retry=True)`. Read actions retry normally.
- **You can see what each task fetched.** See [Call log and card](#call-log-and-card).
- **`@pypi` steps get the SDK.** See [Remote tasks](#remote-tasks-kubernetes-aws-batch).
- **Payments are refused.** `wire_write_action`, `wire_build` and `browser_task` raise before calling the API for anything that looks like a payment or fund transfer, the same rule as Anakin's MCP server. Set `ANAKIN_ALLOW_FINANCIAL=true` to turn this off.
- **Monitor webhook secrets are redacted** from results, so they aren't stored as artifacts.

## Methods

Call these on `current.anakin` inside a step with `@anakin`.

| Group | Methods |
|---|---|
| Web data | `scrape_url`, `scrape_batch`, `map`, `crawl`, `search`, `agentic_search` |
| Wire site actions | `wire_discover`, `wire_catalog`, `wire_read_action`, `wire_write_action`, `wire_identities`, `wire_login`, `wire_build`, `wire_build_status` |
| Website monitors | `monitor_create`, `monitor_list`, `monitor_changes`, `monitor_control` |
| AI visibility | `ai_visibility_search`, `ai_visibility_sources` |
| Browser | `session_list`, `session_delete`, `browser_task` |

`current.anakin.sdk` is the underlying `anakin.Anakin` client, for anything else. Outside a flow, `from metaflow import AnakinClient` gives you the same methods.

The SDK retries 429 and 5xx responses on its own, so `@retry` is for failures that outlast those retries. Failed calls raise subclasses of `anakin.AnakinError`.

## Options

```python
@anakin(api_key_env="MY_ANAKIN_KEY", allow_write_on_retry=False, base_url=None)
```

| Attribute | Default | Meaning |
|---|---|---|
| `api_key_env` | `ANAKIN_API_KEY` | Environment variable holding the key |
| `allow_write_on_retry` | `False` | Let `wire_write_action` run on a `@retry` re-attempt |
| `base_url` | `None` | Override the API base URL |

You can also attach it from the command line: `python flow.py run --with anakin`.

## Call log and card

Each task's calls are saved to its metadata, with the operation, target, status, time, job id, cache hit and credits. Query strings are removed from URLs, and request parameters and page content aren't logged.

```python
from metaflow import Flow, get_anakin_calls

for task in Flow("WebResearchFlow").latest_run["scrape"]:
    print(get_anakin_calls(task)["calls"])
```

`@card(type="anakin_calls")` shows the same log as a table:

```bash
python web_research_flow.py card view scrape
```

The log is metadata rather than an artifact so that `merge_artifacts` keeps working in joins. Only the first 200 calls per task are kept, and `total` and `dropped` tell you if any were left out.

## Remote tasks (Kubernetes, AWS Batch)

Metaflow's code package carries this extension to remote tasks, but not its dependencies. Without `anakin-sdk` in the task's environment, the step fails with an error that says so.

Use `@pypi`, which gets `anakin-sdk` added for you:

```python
@pypi(python="3.12")
@anakin
@step
def scrape(self): ...
```

```bash
python flow.py --environment=pypi run --with kubernetes
```

Or install `anakin-sdk>=0.2,<0.3` in your image. `anakin-sdk` isn't on conda-forge, so `@conda` steps can't use it.

The key has to reach the task too, because your shell's environment doesn't. Use a secret, not `@environment`, which puts the value in the job spec:

```python
@kubernetes(secrets=["anakin-credentials"])  # a Kubernetes secret with an ANAKIN_API_KEY key
@anakin
@step
def scrape(self): ...
```

```python
@secrets(sources=["my-secret-store-entry"])  # any configured @secrets backend
@anakin
@step
def scrape(self): ...
```

## Development

Metaflow finds extensions from an installed distribution's `top_level.txt`, so install the built wheel, not an editable install, and run `pytest` directly rather than `python -m pytest` (a copy of the source on `sys.path` makes Metaflow refuse to load the extension).

```bash
uv build --wheel --out-dir dist
uv venv && uv pip install dist/*.whl --group test --group lint
.venv/bin/pytest
ANAKIN_LIVE_TESTS=1 .venv/bin/pytest tests/test_live.py  # calls api.anakin.io, no key needed
```

## License

Apache-2.0
