"""Anakin (https://anakin.io) step decorator and client for Metaflow.

This package must stay importable without `anakin-sdk`: Metaflow imports every
installed extension on `import metaflow`, including inside remote tasks whose
image may not have the SDK. A top-level `import anakin` here would break all of
Metaflow there, so the SDK is only imported when a step uses it.
"""
