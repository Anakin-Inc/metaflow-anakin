import os

from metaflow import FlowSpec, anakin, current, step


class SecretLateFlow(FlowSpec):
    """A key set after the client is created (as @secrets can) is still used."""

    @anakin(api_key_env="MY_KEY", base_url=os.environ["FAKE_ANAKIN_URL"])
    @step
    def start(self):
        os.environ["MY_KEY"] = "ask_" + "1" * 64
        self.page = current.anakin.scrape_url("https://late.test")
        self.next(self.end)

    @step
    def end(self):
        pass


if __name__ == "__main__":
    SecretLateFlow()
