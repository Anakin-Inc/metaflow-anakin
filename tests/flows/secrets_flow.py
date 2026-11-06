import os

from metaflow import FlowSpec, anakin, current, secrets, step


class SecretsFlow(FlowSpec):
    """The key comes from a real @secrets decorator, applied outside and inside @anakin."""

    @secrets(
        sources=[
            {"type": "inline", "id": "k", "options": {"env_vars": {"KEY_A": "ask_" + "2" * 64}}}
        ]
    )
    @anakin(api_key_env="KEY_A", base_url=os.environ["FAKE_ANAKIN_URL"])
    @step
    def start(self):
        self.page = current.anakin.scrape_url("https://outer.test")
        self.next(self.inner)

    @anakin(api_key_env="KEY_B", base_url=os.environ["FAKE_ANAKIN_URL"])
    @secrets(
        sources=[
            {"type": "inline", "id": "k", "options": {"env_vars": {"KEY_B": "ask_" + "3" * 64}}}
        ]
    )
    @step
    def inner(self):
        self.page = current.anakin.scrape_url("https://inner.test")
        self.next(self.end)

    @step
    def end(self):
        pass


if __name__ == "__main__":
    SecretsFlow()
