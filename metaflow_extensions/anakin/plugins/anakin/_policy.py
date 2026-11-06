"""Guard against payment and fund-transfer requests.

Same rule Anakin's MCP server applies to its write tools: `wire_write_action`,
`wire_build` and `browser_task` refuse anything that looks like it completes
a payment or moves money (pay, checkout, purchase, place order, buy now,
wire transfer, remit, payout, charge card). Benign writes such as "add to
cart" or "submit a form" pass, and read actions are never checked.
"""

from __future__ import annotations

import os
import re

_FINANCIAL_PATTERN = re.compile(
    r"\b(payments?|pay\s?now|checkout|purchase|place\s?order|buy\s?now|"
    r"wire\s?transfer|remit(?:tance)?|payout|charge\s?card|transfer\s?funds)\b",
    re.IGNORECASE,
)


def financial_block_reason(text: str) -> str | None:
    """Return a human-readable refusal reason if `text` looks like a payment
    or fund-transfer request, else `None`.

    `text` is typically an action id + serialized params, or a goal/prompt +
    URL. Set the `ANAKIN_ALLOW_FINANCIAL=true` environment variable to
    disable this guard.
    """
    if os.environ.get("ANAKIN_ALLOW_FINANCIAL") == "true":
        return None

    # `\b` doesn't break on `_`/`-`, so "amazon_checkout" must become "amazon
    # checkout" for `\bcheckout\b` to match snake_case/kebab-case action ids.
    haystack = re.sub(r"[_-]+", " ", text)
    if _FINANCIAL_PATTERN.search(haystack):
        return (
            "metaflow-anakin does not run payments or fund transfers, so this "
            "action was not run. Use a read action to look up information, or "
            "complete the payment directly on the site. Set "
            "ANAKIN_ALLOW_FINANCIAL=true to turn this check off."
        )
    return None
