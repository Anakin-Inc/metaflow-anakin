"""`AnakinClient`: the Anakin web data API, returning plain JSON-serializable data.

Every method returns dicts and lists, never SDK models. A pickled SDK model would
need `anakin-sdk` wherever the artifact is read back, such as in a notebook.

All methods except `browser_task` delegate to `anakin-sdk`, which handles request
bodies, retries on 429/5xx and job polling. `browser_task` calls `POST /ai/evaluate`
directly because the SDK doesn't wrap that endpoint yet.

- Scrape and search: `scrape_url`, `scrape_batch`, `map`, `crawl`, `search`, `agentic_search`
- Wire: `wire_discover`, `wire_catalog`, `wire_read_action`, `wire_write_action`,
  `wire_identities`, `wire_login`, `wire_build`, `wire_build_status`
- Website monitoring: `monitor_create`, `monitor_list`, `monitor_changes`, `monitor_control`
- AI visibility: `ai_visibility_search`, `ai_visibility_sources`
- Browser: `session_list`, `session_delete`, `browser_task`
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from ._policy import financial_block_reason
from .calls import MAX_LOGGED_CALLS, safe_url, short_text

if TYPE_CHECKING:
    from anakin import Anakin
    from pydantic import BaseModel

DEFAULT_BASE_URL = "https://api.anakin.io/v1"
_MONITOR_ACTIONS = ("pause", "resume", "run_now", "delete")
_MAX_ERROR_CHARS = 300


def _dump(value: BaseModel) -> dict[str, Any]:
    return value.model_dump(mode="json")


def _dump_all(values: Sequence[BaseModel]) -> list[dict[str, Any]]:
    return [_dump(v) for v in values]


def _refuse_if_financial(text: str) -> None:
    blocked = financial_block_reason(text)
    if blocked:
        raise ValueError(blocked)


class AnakinClient:
    """Scrape, crawl, search and run Wire site actions with Anakin from a Metaflow step.

    Inside a step, use the instance `@anakin` provides as `current.anakin`. Outside a
    step (a notebook, a script), create one yourself with `AnakinClient()`.

    Args:
        api_key: Anakin API key (`ask_...`). Get one at https://anakin.io/dashboard;
            the free tier needs no card. Defaults to the `ANAKIN_API_KEY` environment
            variable. Without a key only `scrape_url`, `wire_discover` and
            `wire_catalog` work, on a small free per-IP allowance.
        api_key_env: Read the key from this environment variable instead.
        base_url: Override the API base URL.
        retry_count: The current `@retry` attempt. `@anakin` sets this.
        allow_write_on_retry: Let `wire_write_action` run when `retry_count` > 0.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        api_key_env: str = "ANAKIN_API_KEY",
        base_url: str | None = None,
        retry_count: int = 0,
        allow_write_on_retry: bool = False,
    ) -> None:
        self._api_key = api_key
        self._api_key_env = api_key_env
        self._base_url = base_url
        self._retry_count = retry_count
        self._allow_write_on_retry = allow_write_on_retry
        self._sdk: Anakin | None = None
        self._calls: list[dict[str, Any]] = []
        self._total_calls = 0

    def __reduce__(self) -> Any:
        # `self.client = current.anakin` would otherwise store the key in the datastore.
        raise TypeError(
            "AnakinClient can't be stored as an artifact because it holds your API key. "
            "Store its results instead, and call current.anakin again in each step."
        )

    def __repr__(self) -> str:
        return "AnakinClient(calls=%d)" % self._total_calls

    def _key(self) -> str | None:
        # Read late so @secrets can set the variable after this object is created.
        return self._api_key or os.environ.get(self._api_key_env)

    @property
    def sdk(self) -> Anakin:
        """The underlying `anakin.Anakin` client, for anything not wrapped here.

        Calls made through it aren't in the call log, and its models aren't plain
        data: call `.model_dump(mode="json")` before assigning them to `self`.
        """
        if self._sdk is None:
            from anakin import Anakin

            if self._base_url:
                self._sdk = Anakin(api_key=self._key(), base_url=self._base_url)
            else:
                self._sdk = Anakin(api_key=self._key())
        return self._sdk

    def close(self) -> None:
        """Release the HTTP connection pool. `@anakin` calls this when the step ends."""
        if self._sdk is not None:
            self._sdk.close()
            self._sdk = None

    @property
    def call_log(self) -> dict[str, Any]:
        """The calls made so far: `calls`, `total` and `dropped`.

        Same shape as `metaflow.get_anakin_calls(task)`.
        """
        return {
            "calls": list(self._calls),
            "total": self._total_calls,
            "dropped": self._total_calls - len(self._calls),
        }

    @contextmanager
    def _track(self, op: str, target: str | None = None) -> Iterator[dict[str, Any]]:
        entry: dict[str, Any] = {"op": op, "target": target, "status": "ok"}
        started = time.monotonic()
        try:
            yield entry
        except Exception as exc:
            entry["status"] = "error"
            entry["error"] = f"{type(exc).__name__}: {str(exc)[:_MAX_ERROR_CHARS]}"
            raise
        finally:
            entry["duration_ms"] = round((time.monotonic() - started) * 1000)
            self._total_calls += 1
            if len(self._calls) < MAX_LOGGED_CALLS:
                self._calls.append(entry)

    # ─── Scrape and search ──────────────────────────────────────────────────

    def scrape_url(
        self,
        url: str,
        *,
        country: str = "us",
        use_browser: bool = False,
        generate_json: bool = False,
        output_schema: dict[str, Any] | None = None,
        formats: list[str] | None = None,
        force_fresh: bool = False,
        session_id: str | None = None,
        session_name: str | None = None,
    ) -> dict[str, Any]:
        """Scrape one URL to markdown, optionally extracting structured JSON with AI.

        Works without an API key on a small free per-IP allowance.

        Args:
            url: The URL to scrape.
            country: Proxy country code, e.g. "us", "gb", "de".
            use_browser: Render with a headless browser. Use for JavaScript-heavy pages.
            generate_json: Extract structured JSON from the page with AI.
            output_schema: JSON Schema for the extracted JSON (implies AI extraction).
            formats: Output formats, any of "markdown" (default), "html",
                "cleaned_html", "screenshot", "links".
            force_fresh: Skip the cache and fetch the page again.
            session_id: Saved browser session to scrape as a logged-in user.
            session_name: Saved browser session name (alternative to `session_id`).

        Returns:
            The scraped document: `id`, `url`, `status`, `markdown`, `generated_json`
            and the other fields of `anakin.models.Document`.
        """
        with self._track("scrape_url", safe_url(url)) as entry:
            document = self.sdk.scrape(
                url,
                formats=tuple(formats or ("markdown",)),  # type: ignore[arg-type]
                country=country,
                use_browser=use_browser,
                generate_json=generate_json,
                output_schema=output_schema,
                force_fresh=force_fresh,
                session_id=session_id,
                session_name=session_name,
            )
            entry.update(job_id=document.id, cached=document.cached)
            return _dump(document)

    def scrape_batch(
        self,
        urls: Sequence[str],
        *,
        country: str = "us",
        use_browser: bool = False,
        generate_json: bool = False,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Scrape several URLs as one job. Needs an API key.

        For per-URL retries and artifacts, use a Metaflow `foreach` with `scrape_url`.

        Args:
            urls: The URLs to scrape.
            country: Proxy country code.
            use_browser: Render each page with a headless browser.
            generate_json: Extract structured JSON from each page with AI.
            session_id: Saved browser session to scrape as a logged-in user.

        Returns:
            `id`, `status`, `urls` and `results`, one entry per URL.
        """
        with self._track("scrape_batch", "%d url(s)" % len(urls)) as entry:
            result = self.sdk.scrape_batch(
                urls,
                country=country,
                use_browser=use_browser,
                generate_json=generate_json,
                session_id=session_id,
            )
            entry.update(job_id=result.id)
            return _dump(result)

    def map(
        self,
        url: str,
        *,
        limit: int = 100,
        depth: int = 2,
        limit_per_level: int = 100,
        include_subdomains: bool = False,
        include_external_links: bool = False,
        search: str | None = None,
        use_browser: bool = False,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Discover the URLs on a site (sitemap plus link traversal).

        Useful to build the list a `foreach` scrapes.

        Args:
            url: Starting URL, usually a homepage or section root.
            limit: Maximum URLs to return (max 5000).
            depth: Link hops to follow from `url` (max 5).
            limit_per_level: Maximum URLs collected per depth level.
            include_subdomains: Include URLs on subdomains of the starting host.
            include_external_links: Also collect (but don't follow) external links.
            search: Only return URLs whose path or title matches this keyword.
            use_browser: Render with a headless browser. Needed for SPAs.
            session_id: Saved browser session to map as a logged-in user.

        Returns:
            `id`, `url`, `links`, `total_links`, `external_links`,
            `total_external_links`, `duration_ms`.
        """
        with self._track("map", safe_url(url)) as entry:
            result = self.sdk.map(
                url,
                limit=limit,
                depth=depth,
                limit_per_level=limit_per_level,
                include_subdomains=include_subdomains,
                include_external_links=include_external_links,
                search=search,
                use_browser=use_browser,
                session_id=session_id,
            )
            entry.update(job_id=result.id)
            return _dump(result)

    def crawl(
        self,
        url: str,
        *,
        max_pages: int = 10,
        depth: int = 1,
        include_patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
        country: str = "us",
        use_browser: bool = False,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Fetch markdown for many pages of a site in one job.

        Args:
            url: Starting URL.
            max_pages: Maximum pages fetched.
            depth: Link hops to follow from `url`.
            include_patterns: Only fetch URLs matching at least one of these patterns.
            exclude_patterns: Skip URLs matching any of these patterns.
            country: Proxy country code.
            use_browser: Render each page with a headless browser.
            session_id: Saved browser session to crawl as a logged-in user.

        Returns:
            `id`, `url`, `total_pages`, `completed_pages` and `pages`, each with `url`,
            `status`, `markdown` and `error`.
        """
        with self._track("crawl", safe_url(url)) as entry:
            result = self.sdk.crawl(
                url,
                max_pages=max_pages,
                depth=depth,
                include_patterns=include_patterns or (),
                exclude_patterns=exclude_patterns or (),
                country=country,
                use_browser=use_browser,
                session_id=session_id,
            )
            entry.update(job_id=result.id)
            return _dump(result)

    def search(self, prompt: str, *, limit: int = 5) -> dict[str, Any]:
        """AI web search with citations. Synchronous.

        Args:
            prompt: The search query or question.
            limit: Maximum results (max 20).

        Returns:
            `id` and `results`, each with `url`, `title`, `snippet` and `date`.
        """
        with self._track("search", short_text(prompt)) as entry:
            result = self.sdk.search(prompt, limit=limit)
            entry.update(job_id=result.id)
            return _dump(result)

    def agentic_search(
        self,
        prompt: str,
        *,
        use_browser: bool = True,
        schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Multi-step research: search, scrape the cited pages, return a structured answer.

        Takes minutes rather than seconds. Use `search` for quick lookups.

        Args:
            prompt: The research question (max 8 KB).
            use_browser: Scrape citations with a headless browser.
            schema: Optional JSON Schema (max 50 KB) for `structured_data`.

        Returns:
            `id`, `status` and `generated_json` with `summary`, `structured_data`
            and `data_schema`.
        """
        with self._track("agentic_search", short_text(prompt)) as entry:
            result = self.sdk.agentic_search(prompt, use_browser=use_browser, schema=schema)
            entry.update(job_id=result.id)
            return _dump(result)

    # ─── Wire ───────────────────────────────────────────────────────────────

    def wire_discover(
        self,
        q: str,
        *,
        catalog: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Find Wire actions for a task described in plain language.

        Works without an API key.

        Args:
            q: What you want to do, e.g. "top phones on walmart".
            catalog: Restrict to one site's catalog slug, e.g. "amazon".
            limit: Maximum candidate actions to return.

        Returns:
            Ranked actions, each with `action_id`, `catalog_slug`, `params` and
            `credits` (plus `mode` and auth details when called with an API key).
            Pass an `action_id` to `wire_read_action` or `wire_write_action`.
        """
        with self._track("wire_discover", short_text(q)):
            return _dump_all(self.sdk.wire.discover(q, catalog=catalog, limit=limit))

    def wire_catalog(self, *, slug: str | None = None) -> dict[str, Any] | list[dict[str, Any]]:
        """Browse the Wire catalog: every supported site, or one site's actions.

        Works without an API key.

        Args:
            slug: Site to inspect, e.g. "walmart". Omit to list every site.

        Returns:
            Without `slug`, a list of sites with their action counts. With `slug`,
            that site's actions (parameter schema, mode, auth mode, credit cost) and
            its login fields if it needs credentials.
        """
        with self._track("wire_catalog", slug):
            wire = self.sdk.wire
            if slug:
                return _dump(wire.catalog(slug))
            return _dump_all(wire.catalogs())

    def _run_wire(
        self,
        op: str,
        action_id: str,
        params: dict[str, Any] | None,
        credential_id: str | None,
        identity_id: str | None,
    ) -> dict[str, Any]:
        with self._track(op, action_id) as entry:
            result = self.sdk.wire.run(
                action_id, params or {}, credential_id=credential_id, identity_id=identity_id
            )
            entry.update(job_id=result.job_id, credits_used=result.credits_used)
            return _dump(result)

    def wire_read_action(
        self,
        action_id: str,
        *,
        params: dict[str, Any] | None = None,
        credential_id: str | None = None,
        identity_id: str | None = None,
    ) -> dict[str, Any]:
        """Run a Wire read action, which extracts data without changing anything on the site.

        For actions that change state, use `wire_write_action`.

        Args:
            action_id: The action to run, from `wire_discover` or `wire_catalog`.
            params: The action's parameters, as described by discovery.
            credential_id: Needed when the action's `auth_mode` is "required". Get one
                from `wire_identities` or `wire_login`.
            identity_id: Alternative to `credential_id`: run as this saved identity.

        Returns:
            `job_id`, `status`, `data`, `credits_used`, `execution_ms` and `error`.
        """
        return self._run_wire("wire_read_action", action_id, params, credential_id, identity_id)

    def wire_write_action(
        self,
        action_id: str,
        *,
        params: dict[str, Any] | None = None,
        credential_id: str | None = None,
        identity_id: str | None = None,
    ) -> dict[str, Any]:
        """Run a Wire write action: submit a form, add to cart, post content, update settings.

        Raises `ValueError` before calling the API if this is a `@retry` re-attempt
        (a repeated write can duplicate it; set `@anakin(allow_write_on_retry=True)` to
        allow it) or if it looks like a payment or fund transfer.

        Args:
            action_id: The action to run, from `wire_discover` or `wire_catalog`.
            params: The action's parameters, as described by discovery.
            credential_id: Needed when the action's `auth_mode` is "required".
            identity_id: Alternative to `credential_id`: run as this saved identity.

        Returns:
            Same shape as `wire_read_action`.
        """
        if self._retry_count > 0 and not self._allow_write_on_retry:
            raise ValueError(
                "Not running Wire write action %s: this is @retry attempt %d, and repeating a "
                "write can duplicate it. Check the site, then use "
                "@anakin(allow_write_on_retry=True) if repeating it is safe."
                % (action_id, self._retry_count)
            )
        resolved_params = params or {}
        _refuse_if_financial(f"{action_id} {resolved_params}")
        return self._run_wire(
            "wire_write_action", action_id, resolved_params, credential_id, identity_id
        )

    def wire_identities(self, *, catalog_id: str | None = None) -> list[dict[str, Any]]:
        """List your saved Wire identities (site accounts) and their credentials.

        Args:
            catalog_id: Only identities for this catalog.

        Returns:
            Identities, each with `credentials`; every credential's `id` can be passed
            as `credential_id` to the Wire action methods.
        """
        with self._track("wire_identities", catalog_id):
            return _dump_all(self.sdk.wire.identities(catalog_id=catalog_id))

    def wire_login(
        self,
        catalog_slug: str,
        *,
        params: dict[str, Any] | None = None,
        identity_name: str | None = None,
        source_id: str | None = None,
        source_ref: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Sign in to a site that needs credentials and get a `credential_id`.

        Anakin stores the encrypted session, never the password. Read the password
        from `@secrets`; don't put it in a `Parameter` or on `self`, because Metaflow
        stores both as artifacts.

        Args:
            catalog_slug: The site to sign in to.
            params: The login fields listed in `wire_catalog(slug=...)`'s
                `login_input_schema`, e.g. `{"email": ..., "password": ...}`.
            identity_name: Name for the identity.
            source_id: 1Password identity source, instead of `params`.
            source_ref: 1Password item locator (`vault_id`, `item_id`, `fields`), used
                with `source_id`.

        Returns:
            The login result, including the new `credential_id`.
        """
        with self._track("wire_login", catalog_slug):  # never log params
            return _dump(
                self.sdk.wire.login(
                    catalog_slug,
                    params,
                    identity_name=identity_name,
                    source_id=source_id,
                    source_ref=source_ref,
                )
            )

    def wire_build(
        self,
        website_url: str,
        goal: str,
        *,
        catalog_id: str | None = None,
        visibility: str = "private",
        force: bool = False,
    ) -> dict[str, Any]:
        """Ask Anakin to build a new Wire action for a site that isn't in the catalog.

        Builds run asynchronously: this returns the pending build request. Check on it
        with `wire_build_status`. Charges credits up front, refunded if the build fails.
        Run `wire_discover` first to make sure no action exists. Refuses payment or
        fund-transfer goals (raises `ValueError`).

        Args:
            website_url: The site to build an action for.
            goal: What the action should do or extract. Be specific.
            catalog_id: Attach to an existing catalog instead of creating one.
            visibility: "private" (default) or "public".
            force: Build even if similar actions already exist for the domain.

        Returns:
            The build request: `id`, `status` and related fields.
        """
        _refuse_if_financial(f"{goal} {website_url}")
        with self._track("wire_build", safe_url(website_url)) as entry:
            build = self.sdk.wire.build(
                website_url, goal, catalog_id=catalog_id, visibility=visibility, force=force
            )
            entry.update(job_id=build.id)
            return _dump(build)

    def wire_build_status(self, build_id: str) -> dict[str, Any]:
        """Check a Wire build request started with `wire_build`.

        Args:
            build_id: The `id` returned by `wire_build`.

        Returns:
            The build's `status` and, once published, its `action_id`.
        """
        with self._track("wire_build_status", build_id):
            return _dump(self.sdk.wire.get_build(build_id))

    # ─── Website monitoring ─────────────────────────────────────────────────

    def monitor_create(
        self,
        url: str,
        interval_minutes: int,
        *,
        scope: str = "page",
        watch_mode: str = "full_page",
        watch_format: str = "markdown",
        output_schema: dict[str, Any] | None = None,
        ai_mode: bool = False,
        ai_goal: str | None = None,
        use_browser: bool = False,
        country: str = "us",
        session_id: str | None = None,
        is_active: bool = True,
        expires_at: str | None = None,
        alert_webhook_url: str | None = None,
        alert_emails: str | None = None,
        max_pages: int | None = None,
        max_depth: int | None = None,
        include_patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
        wire_action_id: str | None = None,
        wire_catalog_slug: str | None = None,
        wire_credential_id: str | None = None,
        wire_params: dict[str, Any] | None = None,
        wire_watch_paths: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a scheduled website monitor.

        Checks `url` every `interval_minutes` (minimum 15) and records a change when the
        content differs, optionally alerting a webhook or email. `scope="page"` watches
        one URL, `"site"` crawls the site and tracks pages added, removed and changed,
        and `"wire"` runs a Wire action each check and diffs its JSON.
        `watch_mode="specific_data"` tracks only the fields in `output_schema` (prices,
        stock, status). `ai_mode` filters out trivial changes and summarizes real ones.
        See https://anakin.io/pricing for the credit cost per check and the
        active-monitor limit on each plan.

        Monitors run on Anakin's side, so a step that calls this creates a new one on
        each run: guard it, or create the monitor once outside the flow.

        Args:
            url: The URL to watch (the root URL for site scope).
            interval_minutes: Minutes between checks. Minimum 15.
            scope: "page", "site" or "wire".
            watch_mode: "full_page" or "specific_data".
            watch_format: Compared format in full_page mode: "markdown", "html" or
                "cleaned_html".
            output_schema: JSON Schema of the fields to track. Required for
                `watch_mode="specific_data"`.
            ai_mode: Filter out trivial changes with AI.
            ai_goal: Which changes count as meaningful (used with `ai_mode`).
            use_browser: Check with a headless browser.
            country: Proxy country code.
            session_id: Saved browser session for login-protected pages.
            is_active: Start checking immediately.
            expires_at: End date (ISO 8601 or `YYYY-MM-DD`); the monitor pauses then.
            alert_webhook_url: Webhook that receives signed change alerts.
            alert_emails: Comma-separated email recipients for change alerts.
            max_pages: Site scope: maximum pages per run.
            max_depth: Site scope: crawl depth (1-5).
            include_patterns: Site scope: patterns or URLs to track.
            exclude_patterns: Site scope: patterns to skip.
            wire_action_id: Wire scope (required there): the action to run each check.
            wire_catalog_slug: Wire scope: the action's catalog slug.
            wire_credential_id: Wire scope: credential for actions that need auth.
            wire_params: Wire scope: parameters for the action.
            wire_watch_paths: Wire scope: JSON paths to diff instead of the whole result.

        Returns:
            The new monitor's configuration and status. The webhook signing secret is
            redacted; read it in the Anakin dashboard.
        """
        from . import _http

        options: dict[str, Any] = {
            "scope": scope,
            "watch_mode": watch_mode,
            "watch_format": watch_format,
            "ai_mode": ai_mode,
            "use_browser": use_browser,
            "country": country,
            "is_active": is_active,
        }
        optional: dict[str, Any] = {
            "output_schema": output_schema,
            "ai_goal": ai_goal,
            "session_id": session_id,
            "expires_at": expires_at,
            "alert_webhook_url": alert_webhook_url,
            "alert_emails": alert_emails,
            "max_pages": max_pages,
            "max_depth": max_depth,
            "include_patterns": include_patterns,
            "exclude_patterns": exclude_patterns,
            "wire_action_id": wire_action_id,
            "wire_catalog_slug": wire_catalog_slug,
            "wire_credential_id": wire_credential_id,
            "wire_params": wire_params,
            "wire_watch_paths": wire_watch_paths,
        }
        options.update({k: v for k, v in optional.items() if v is not None})

        with self._track("monitor_create", safe_url(url)) as entry:
            monitor = self.sdk.monitors.create(url, interval_minutes, **options)
            entry.update(job_id=monitor.id)
            return _http.redact_secrets(_dump(monitor))  # type: ignore[no-any-return]

    def monitor_list(
        self, *, monitor_id: str | None = None
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """List your website monitors, or fetch one monitor's configuration.

        Args:
            monitor_id: Return only this monitor.

        Returns:
            A list of monitors, or one monitor when `monitor_id` is set, with webhook
            signing secrets redacted.
        """
        from . import _http

        with self._track("monitor_list", monitor_id):
            monitors = self.sdk.monitors
            if monitor_id:
                return _http.redact_secrets(_dump(monitors.get(monitor_id)))  # type: ignore[no-any-return]
            return _http.redact_secrets(_dump_all(monitors.list()))  # type: ignore[no-any-return]

    def monitor_changes(self, monitor_id: str) -> list[dict[str, Any]]:
        """Get the changes a monitor has detected, newest first.

        Args:
            monitor_id: The monitor's `id`.

        Returns:
            One entry per detected change, with its diff and (when `ai_mode` is on) the
            AI summary.
        """
        with self._track("monitor_changes", monitor_id):
            return _dump_all(self.sdk.monitors.changes(monitor_id))

    def monitor_control(self, monitor_id: str, action: str) -> dict[str, Any] | None:
        """Pause, resume, run, or delete a monitor.

        Args:
            monitor_id: The monitor's `id`.
            action: "pause", "resume", "run_now" (an immediate check, billed like a
                scheduled one) or "delete" (removes the monitor and its history).

        Returns:
            The updated monitor for pause/resume, the queued run for run_now, and None
            for delete.
        """
        if action not in _MONITOR_ACTIONS:
            raise ValueError(
                "Unknown monitor action {!r}: use one of {}.".format(
                    action, ", ".join(_MONITOR_ACTIONS)
                )
            )
        from . import _http

        with self._track(f"monitor_control:{action}", monitor_id):
            monitors = self.sdk.monitors
            if action == "delete":
                monitors.delete(monitor_id)
                return None
            if action == "pause":
                result: BaseModel = monitors.pause(monitor_id)
            elif action == "resume":
                result = monitors.resume(monitor_id)
            else:
                result = monitors.run_now(monitor_id)
            return _http.redact_secrets(_dump(result))  # type: ignore[no-any-return]

    # ─── AI visibility ──────────────────────────────────────────────────────

    def ai_visibility_sources(self) -> list[dict[str, Any]]:
        """List the AI answer engines `ai_visibility_search` can query.

        Returns:
            Each engine's slug (pass these as `sources`) and display name.
        """
        with self._track("ai_visibility_sources"):
            return _dump_all(self.sdk.ai_visibility.sources())

    def ai_visibility_search(
        self,
        query: str,
        *,
        sources: list[str] | None = None,
        country: str = "us",
        include_full_content: bool = False,
    ) -> dict[str, Any]:
        """Ask several AI answer engines (ChatGPT, Gemini, Google AI Overview, ...) one question.

        Useful for checking how a brand or topic shows up in AI answers, per country.
        Billed per engine that answers; failed engines are free. A search where some
        engines failed is returned, not raised.

        Args:
            query: The question (max 2000 characters).
            sources: Engine slugs from `ai_visibility_sources`. Omit for all.
            country: Two-letter country code for the search location.
            include_full_content: Keep each engine's full answer text. Off by default;
                summaries and the cross-engine synthesis are always returned.

        Returns:
            `search_id`, `status`, `country`, `synthesis` and one `results` entry per engine.
        """
        with self._track("ai_visibility_search", short_text(query)):
            result = _dump(self.sdk.ai_visibility.search(query, sources=sources, country=country))
        if not include_full_content:
            result["results"] = [
                {k: v for k, v in r.items() if k != "full_content"}
                for r in result.get("results", [])
            ]
        return result

    # ─── Browser sessions and AI browser tasks ──────────────────────────────

    def session_list(self, *, domain: str | None = None) -> list[dict[str, Any]]:
        """List saved browser sessions (logged-in states you created in the Anakin dashboard).

        Pass a session's `id` as `session_id` to `scrape_url`, `crawl`, `monitor_create`
        or `browser_task` to run as that logged-in user.

        Args:
            domain: Only sessions for this domain, e.g. "amazon.com".

        Returns:
            Sessions with `id`, `name`, `website_domain` and `is_active`.
        """
        with self._track("session_list", domain):
            return _dump_all(self.sdk.sessions.list(domain=domain))

    def session_delete(self, session_id: str) -> None:
        """Permanently delete a saved browser session and its encrypted login data.

        Anything that uses this session loses its logged-in access.

        Args:
            session_id: The session's `id`, from `session_list`.
        """
        with self._track("session_delete", session_id):
            self.sdk.sessions.delete(session_id)

    def browser_task(
        self,
        prompt: str,
        *,
        url: str | None = None,
        session_id: str | None = None,
        max_steps: int | None = None,
        timeout_ms: int | None = None,
        output_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run a task described in plain language in a cloud browser driven by an AI agent.

        The agent navigates, clicks, types and extracts. Use it for multi-step flows
        `scrape_url` can't do and no Wire action covers (Wire actions are faster and
        cheaper, so try `wire_discover` first). Runs are capped at about 330 seconds
        server-side. For logged-in tasks pass `session_id`; never put passwords in
        `prompt`. Refuses payment or fund-transfer tasks (raises `ValueError`).

        Args:
            prompt: What to do and what to return.
            url: Start here. Omit to let the agent follow URLs in the prompt.
            session_id: Saved browser session to run as a logged-in user.
            max_steps: Maximum agent steps.
            timeout_ms: Task timeout in milliseconds.
            output_schema: JSON Schema the returned `result` should follow.

        Returns:
            `success`, `result`, `steps_taken`, `iterations`, `cached`, `duration_ms`
            and `run_id`.

        Raises:
            RuntimeError: If the task fails or times out.
        """
        _refuse_if_financial("{} {}".format(prompt, url or ""))

        key = self._key()
        if not key:
            raise ValueError(
                "browser_task needs an Anakin API key: set the "
                f"{self._api_key_env} environment variable."
            )

        import httpx

        from . import _http

        body: dict[str, Any] = {"prompt": prompt, "async": True}
        optional = {
            "url": url,
            "session_id": session_id,
            "max_steps": max_steps,
            "timeout_ms": timeout_ms,
            "output_schema": output_schema,
        }
        body.update({k: v for k, v in optional.items() if v is not None})

        with (
            self._track("browser_task", short_text(prompt)) as entry,
            httpx.Client(
                base_url=self._base_url or DEFAULT_BASE_URL,
                headers={"X-API-Key": key},
                timeout=60.0,
            ) as http_client,
        ):
            accepted = _http.request(http_client, "POST", "/ai/evaluate", json=body)
            workflow_id = accepted.get("workflow_id")
            if not workflow_id:
                resolved = accepted
            else:
                job = _http.poll(
                    http_client,
                    f"/ai/jobs/{workflow_id}",
                    is_terminal=lambda b: b.get("status") in {"completed", "failed", "timed_out"},
                )
                if job.get("status") in {"failed", "timed_out"}:
                    # The reason is in `error`, or in the nested result's text.
                    nested = job.get("result")
                    reason = job.get("error") or (isinstance(nested, dict) and nested.get("result"))
                    raise RuntimeError(f"Browser task {job.get('status')}: {reason or 'unknown'}")
                resolved = job.get("result") or job
            entry.update(job_id=resolved.get("run_id"), cached=resolved.get("cached"))

        steps = resolved.get("steps")
        return {
            "success": resolved.get("success"),
            "result": resolved.get("result"),
            "steps_taken": len(steps) if isinstance(steps, list) else None,
            "iterations": resolved.get("iterations"),
            "cached": resolved.get("cached"),
            "duration_ms": resolved.get("duration_ms"),
            "run_id": resolved.get("run_id"),
        }
