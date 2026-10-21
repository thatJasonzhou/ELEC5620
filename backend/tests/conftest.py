"""Shared test configuration."""

import os


# Tests must stay deterministic even when a developer enables the live LLM in
# the local .env file.
os.environ["PLANNER_LLM_MODE"] = "mock"
