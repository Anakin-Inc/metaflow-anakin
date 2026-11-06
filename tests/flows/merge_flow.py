import os

from metaflow import FlowSpec, anakin, current, step


class MergeFlow(FlowSpec):
    """Branches that make different calls must not conflict in merge_artifacts."""

    @step
    def start(self):
        self.next(self.left, self.right)

    @anakin(base_url=os.environ["FAKE_ANAKIN_URL"])
    @step
    def left(self):
        self.left_page = current.anakin.scrape_url("https://left.test")
        self.next(self.join_branches)

    @anakin(base_url=os.environ["FAKE_ANAKIN_URL"])
    @step
    def right(self):
        self.right_page = current.anakin.scrape_url("https://right.test")
        self.next(self.join_branches)

    @step
    def join_branches(self, inputs):
        self.merge_artifacts(inputs)
        self.next(self.end)

    @step
    def end(self):
        pass


if __name__ == "__main__":
    MergeFlow()
