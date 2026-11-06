"""The `@anakin` step decorator."""

from __future__ import annotations

import json
import os
from typing import Any

from metaflow import current
from metaflow.decorators import StepDecorator
from metaflow.exception import MetaflowException

from .calls import METADATA_FIELD, METADATA_TYPE
from .client import AnakinClient

# What `@pypi` steps get when they don't pin anakin-sdk themselves. `@pypi` takes
# an exact version; keep this inside the range in pyproject.toml.
PYPI_SDK_VERSION = "0.2.0"
_SDK_PACKAGE = "anakin-sdk"


class AnakinMissingSDK(MetaflowException):
    headline = "anakin-sdk is not installed in this task's environment"


class AnakinDecorator(StepDecorator):
    """Gives a step an Anakin client as `current.anakin`.

    Results come back as plain dicts and lists, so they can be stored as
    artifacts and read back from a notebook that doesn't have `anakin-sdk`.
    Every call is logged to the task's metadata: read it with
    `metaflow.get_anakin_calls(task)` or render it with `@card(type="anakin_calls")`.

    The API key is read from the environment at the first call, so it can come
    from `@secrets`, `@kubernetes(secrets=...)` or your shell. Without a key, only
    `scrape_url`, `wire_discover` and `wire_catalog` work (small free allowance per IP).

    Steps with `@pypi` get `anakin-sdk` added to their packages. With a plain container
    image, install it yourself. It isn't on conda-forge, so `@conda` steps can't use it, and
    neither can steps with no `@pypi` under `--environment=pypi` (they get `@conda` only).

    Parameters
    ----------
    api_key_env : str, default "ANAKIN_API_KEY"
        Environment variable holding the API key. The key itself isn't accepted
        as an attribute because decorator attributes are part of the flow's source.
    base_url : str, optional, default None
        Override the API base URL.
    allow_write_on_retry : bool, default False
        Let `wire_write_action` run on a `@retry` re-attempt. Off because a
        write that failed part-way may already have taken effect, and repeating it
        can duplicate it.
    """

    name = "anakin"
    defaults = {  # noqa: RUF012
        "api_key_env": "ANAKIN_API_KEY",
        "base_url": None,
        "allow_write_on_retry": False,
    }

    def step_init(
        self,
        flow: Any,
        graph: Any,
        step_name: str,
        decorators: Any,
        environment: Any,
        flow_datastore: Any,
        logger: Any,
    ) -> None:
        pinned_by_flow = any(
            _SDK_PACKAGE in deco.attributes["packages"]
            for deco in flow._flow_decorators.get("pypi_base", [])
        )
        if pinned_by_flow:
            return
        for deco in decorators:
            if deco.name == "pypi" and _SDK_PACKAGE not in deco.attributes["packages"]:
                # A new dict: the default value is shared by every @pypi in the flow.
                deco.attributes["packages"] = {
                    **deco.attributes["packages"],
                    _SDK_PACKAGE: PYPI_SDK_VERSION,
                }

    def task_pre_step(
        self,
        step_name: str,
        task_datastore: Any,
        metadata: Any,
        run_id: str,
        task_id: str,
        flow: Any,
        graph: Any,
        retry_count: int,
        max_user_code_retries: int,
        ubf_context: Any,
        inputs: Any,
    ) -> None:
        try:
            import anakin  # noqa: F401
        except ImportError as exc:
            raise AnakinMissingSDK(
                f"@anakin on step '{step_name}' needs anakin-sdk. Use @pypi (it is added for "
                "you), or install it in the image with: pip install 'anakin-sdk>=0.2,<0.3'. "
                f"Original error: {exc}"
            ) from exc

        self._task = (metadata, run_id, step_name, task_id, retry_count)
        self._client: AnakinClient | None = AnakinClient(
            api_key=os.environ.get(self.attributes["api_key_env"]),
            api_key_env=self.attributes["api_key_env"],
            base_url=self.attributes["base_url"],
            retry_count=retry_count,
            allow_write_on_retry=bool(self.attributes["allow_write_on_retry"]),
        )
        current._update_env({"anakin": self._client})

    def task_post_step(
        self,
        step_name: str,
        flow: Any,
        graph: Any,
        retry_count: int,
        max_user_code_retries: int,
    ) -> None:
        self._save_calls()

    def task_exception(
        self,
        exception: BaseException,
        step_name: str,
        flow: Any,
        graph: Any,
        retry_count: int,
        max_user_code_retries: int,
    ) -> None:
        self._save_calls()

    def _save_calls(self) -> None:
        """Write the call log to task metadata. A failure here never fails the step."""
        client = getattr(self, "_client", None)
        if client is None:
            return
        self._client = None
        client.close()

        metadata, run_id, step_name, task_id, retry_count = self._task
        from metaflow.metadata_provider import MetaDatum

        try:
            metadata.register_metadata(
                run_id,
                step_name,
                task_id,
                [
                    MetaDatum(
                        field=METADATA_FIELD,
                        value=json.dumps(client.call_log),
                        type=METADATA_TYPE,
                        tags=["attempt_id:%d" % retry_count],
                    )
                ],
            )
        except Exception as exc:
            print(f"@anakin: could not save the call log: {exc}")
