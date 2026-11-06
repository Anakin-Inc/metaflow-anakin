import os

from metaflow import FlowSpec, anakin, current, step


class StoreClientFlow(FlowSpec):
    """Storing the client as an artifact must fail rather than persist the API key."""

    @anakin(base_url=os.environ["FAKE_ANAKIN_URL"])
    @step
    def start(self):
        self.client = current.anakin
        self.next(self.end)

    @step
    def end(self):
        pass


if __name__ == "__main__":
    StoreClientFlow()
