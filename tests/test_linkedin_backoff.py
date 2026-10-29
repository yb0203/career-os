from pipeline.sources import india


class Resp:
    def __init__(self, status, text=""):
        self.status_code, self.text = status, text


def card(n):
    return (f'<a class="base-card__full-link" href="https://in.linkedin.com/jobs/view/{n}"></a>')


def test_linkedin_retries_after_429_and_raises_only_when_empty(monkeypatch):
    sleeps = []
    monkeypatch.setattr(india.time, "sleep", lambda s: sleeps.append(s))

    class S429Then200:
        n = 0
        def get(self, *a, **k):
            S429Then200.n += 1
            return Resp(429) if S429Then200.n <= 2 else Resp(200, "")
    monkeypatch.setattr(india, "session", lambda: S429Then200())
    try:
        india.linkedin({"locations": ["Bengaluru"], "pages": 1, "retries": 3, "backoff_seconds": 1}, ["product manager"])
    except RuntimeError:
        pass   # empty result after recovery raises: nothing fetched
    assert S429Then200.n >= 3 and len(sleeps) >= 3   # it waited and retried instead of giving up at the first 429

    class AlwaysBlocked:
        def get(self, *a, **k):
            return Resp(429)
    monkeypatch.setattr(india, "session", lambda: AlwaysBlocked())
    try:
        india.linkedin({"locations": ["Bengaluru"], "pages": 1, "retries": 1, "backoff_seconds": 1}, ["product manager"])
        raised = False
    except RuntimeError:
        raised = True
    assert raised
