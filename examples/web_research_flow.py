"""Scrape a list of pages in parallel and collect them into one artifact.

export ANAKIN_API_KEY=ask_...   # optional for scraping: a small keyless allowance exists
python examples/web_research_flow.py run
python examples/web_research_flow.py card view join_pages/<run>/<task>  # after the run
"""

from metaflow import FlowSpec, Parameter, anakin, card, current, step


class WebResearchFlow(FlowSpec):
    urls = Parameter(
        "urls",
        help="Comma-separated URLs to scrape",
        default="https://example.com,https://www.iana.org/help/example-domains",
    )

    @step
    def start(self):
        self.pages_to_scrape = [url.strip() for url in self.urls.split(",")]
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
            print(page["url"], len(page["markdown"] or ""), "chars")


if __name__ == "__main__":
    WebResearchFlow()
