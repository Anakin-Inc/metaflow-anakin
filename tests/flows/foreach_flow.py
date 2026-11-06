import os

from metaflow import FlowSpec, anakin, card, current, step


class ForeachFlow(FlowSpec):
    """A foreach whose join calls merge_artifacts with no exclude list."""

    @step
    def start(self):
        self.pages_to_scrape = ["https://a.test/x?token=SECRET", "https://b.test/y"]
        self.next(self.scrape, foreach="pages_to_scrape")

    @card(type="anakin_calls")
    @anakin(base_url=os.environ["FAKE_ANAKIN_URL"])
    @step
    def scrape(self):
        self.page = current.anakin.scrape_url(self.input)
        self.next(self.join_pages)

    @step
    def join_pages(self, inputs):
        self.pages = [inp.page for inp in inputs]
        self.merge_artifacts(inputs, exclude=["page"])
        self.next(self.end)

    @step
    def end(self):
        pass


if __name__ == "__main__":
    ForeachFlow()
