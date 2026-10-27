"""The model clients. Both have the same tiny interface:  client.chat(messages) -> str

* OllamaClient - the real thing: a local open-source model served by Ollama on this machine.
* MockClient   - a scripted stand-in that is NOT a language model. It lets the API and the tests run on a computer
                 without a model. Its answers are labelled meta.backend = "mock", so it can never be mistaken for a model.
"""
from __future__ import annotations

import json
import os
import re

import requests

from .prompt import WORDS

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")


class OllamaClient:
    name = "ollama"

    def __init__(self, url: str = OLLAMA_URL, model: str = OLLAMA_MODEL, timeout: int = 120):
        self.url, self.model, self.timeout = url.rstrip("/"), model, timeout

    def chat(self, messages: list[dict]) -> str:
        options = {"temperature": 0.2, "num_predict": 400}            # low temperature = steadier answers
        if os.environ.get("OLLAMA_NUM_GPU"):                           # set OLLAMA_NUM_GPU=0 to force the CPU
            options["num_gpu"] = int(os.environ["OLLAMA_NUM_GPU"])
        r = requests.post(f"{self.url}/api/chat", timeout=self.timeout,
                          json={"model": self.model, "messages": messages, "stream": False, "format": "json",
                                "options": options})
        r.raise_for_status()
        return r.json()["message"]["content"]


class MockClient:
    name = "mock"
    model = "mock-template-writer"

    def chat(self, messages: list[dict]) -> str:
        user = messages[-1]["content"]
        snap = json.loads(re.search(r"SNAPSHOT:\n(\{.*\})", user).group(1))      # the snapshot is inside the prompt
        tone = re.search(r"Suggested tone: (\w+)", user).group(1)
        facts = re.findall(r"^- (\w+_7d: .*)$", user, flags=re.M)
        if facts:
            metric = facts[0].split("_7d")[0]
            went = "rose" if "(+" in facts[0] else "fell"
            insight = f"Your {WORDS[metric]} {went} compared with your usual level this week. Small steady habits add up."
            evidence = facts[:2]
        else:
            insight = "Your week looks close to your usual level. Nicely consistent."
            evidence = [f"app_streak_days: {snap['app']['streak_days']}"]
        return json.dumps({
            "member_id": snap["member_id"], "insight": insight, "evidence": evidence,
            "actions": ["Take a 10 minute walk after one meal on three days.",
                        "Pick a regular bedtime and keep it for the next few nights."],
            "tone": tone, "safety_flag": False,
        })


def get_client(backend: str | None = None):
    backend = backend or os.environ.get("LLM_BACKEND", "ollama")
    if backend == "mock":
        return MockClient()
    if backend == "ollama":
        return OllamaClient()
    raise ValueError(f"unknown LLM_BACKEND: {backend}")
