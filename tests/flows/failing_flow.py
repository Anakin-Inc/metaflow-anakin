import os

from metaflow import FlowSpec, anakin, current, step


class FailingFlow(FlowSpec):
    """The call log is kept when the API call fails the step."""

    @anakin(base_url=os.environ["FAKE_ANAKIN_URL"])
    @step
    def start(self):
        current.anakin.scrape_url("https://fail.test")
        self.next(self.end)

    @step
    def end(self):
        pass


if __name__ == "__main__":
    FailingFlow()
