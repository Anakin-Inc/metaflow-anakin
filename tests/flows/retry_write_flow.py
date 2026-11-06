import os

from metaflow import FlowSpec, anakin, current, retry, step


class RetryWriteFlow(FlowSpec):
    """First attempt fails after its write; the retry must refuse to write again."""

    @retry(times=1, minutes_between_retries=0)
    @anakin(base_url=os.environ["FAKE_ANAKIN_URL"])
    @step
    def start(self):
        if current.retry_count == 0:
            raise RuntimeError("step failed after the write")
        current.anakin.wire_write_action("some_form_submit", params={"a": 1})
        self.next(self.end)

    @step
    def end(self):
        pass


if __name__ == "__main__":
    RetryWriteFlow()
