from pipeline.sources import SOURCES, remote_boards

FAKE = {
    "id": 42, "name": "Senior Product Manager", "publication_date": "2026-10-10T12:00:00Z",
    "contents": "<p>Own the <b>roadmap</b>.</p>",
    "company": {"name": "Acme"}, "refs": {"landing_page": "https://www.themuse.com/jobs/acme/spm"},
    "locations": [{"name": "Flexible / Remote"}, {"name": "Bangalore, India"}],
}


def test_muse_job_mapping():
    j = remote_boards._muse_job(FAKE)
    assert (j.company, j.title, j.source) == ("Acme", "Senior Product Manager", "themuse")
    assert j.url == "https://www.themuse.com/jobs/acme/spm"
    assert j.location == "Flexible / Remote / Bangalore, India"
    assert j.remote is True
    assert j.posted_at is not None and j.posted_at.year == 2026
    assert "roadmap" in j.description and "<" not in j.description


def test_muse_not_remote_without_flexible_location():
    j = remote_boards._muse_job({**FAKE, "locations": [{"name": "Bangalore, India"}]})
    assert j.remote is False


class FakeSession:
    def __init__(self):
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append(params)
        page = params["page"]
        results = [FAKE] if page == 0 else [{**FAKE, "id": 43, "name": "PM 2"}]
        payload = {"page_count": 2, "results": results}
        return type("R", (), {"json": lambda self: payload})()


def test_themuse_pages_and_dedupes_across_locations(monkeypatch):
    fake = FakeSession()
    monkeypatch.setattr(remote_boards, "session", lambda: fake)
    jobs = remote_boards.themuse({}, [])
    assert len(fake.calls) == 4  # 2 locations x 2 pages
    assert sorted(j.title for j in jobs) == ["PM 2", "Senior Product Manager"]
    assert "themuse" in SOURCES
