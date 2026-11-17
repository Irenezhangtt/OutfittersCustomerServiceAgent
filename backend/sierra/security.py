import hashlib
import re
import secrets
import threading
import time
from collections import OrderedDict

from fastapi import HTTPException

COOKIE_NAME = "sierra_session"


def new_token():
    return secrets.token_urlsafe(32)


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def is_injection(message):
    patterns = [
        r"ignore\s+(?:all\s+)?(?:previous|prior|system|above)\s+(?:instructions|prompts|rules)",
        r"(?:reveal|print|show|repeat|dump).{0,25}(?:system prompt|secret key|api key|all customers|all orders)",
        r"(?:忽略|绕过|无视).{0,16}(?:指令|规则|提示词|system)",
        r"(?:泄露|输出|打印|显示|告诉我).{0,16}(?:系统提示词|密钥|所有客户|其他客户|全部订单)",
        r"(?:<\|system\|>|\[INST\]|</?system>|developer\s+message:)",
    ]
    return any(re.search(p, message, re.I | re.S) for p in patterns)


class RateLimiter:
    """Bounded process-local abuse protection; use an edge limiter for multi-worker production."""

    def __init__(self, limit=40, window=60, capacity=10000):
        self.limit, self.window, self.capacity = limit, window, capacity
        self.entries = OrderedDict()
        self.lock = threading.Lock()

    def check(self, key):
        now = time.monotonic()
        with self.lock:
            start, count = self.entries.pop(key, (now, 0))
            if now - start >= self.window:
                start, count = now, 0
            self.entries[key] = (start, count + 1)
            if len(self.entries) > self.capacity:
                self.entries.popitem(last=False)
            if count >= self.limit:
                raise HTTPException(429, "Too many requests. Please wait a minute.", headers={"Retry-After": "60"})
