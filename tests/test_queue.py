from pipeline.queue import build, who

LOGIN = {"Baker Tilly"}


def row(**kw):
    base = {"Company": "Acme", "Role": "PM", "Status": "New", "Source": "linkedin", "URL": "https://linkedin.com/x",
            "Notes": "", "Tier": "", "Score": "70", "ID": "id1", "Location": "Bengaluru"}
    return {**base, **kw}


def test_who_routes_by_source_and_link():
    assert who(row(Source="instahyre"), LOGIN)[0] == "Yashvi · Instahyre"
    assert who(row(Source="cutshort"), LOGIN)[0] == "Yashvi · Cutshort"
    assert who(row(Company="Baker Tilly"), LOGIN)[0] == "Yashvi · login"
    assert who(row(URL="https://x.wd5.myworkdayjobs.com/job/1"), LOGIN)[0] == "Yashvi · login"
    assert who(row(Notes="LinkedIn-only, unverified"), LOGIN)[0] == "Decide"
    assert who(row(URL="https://jobs.lever.co/acme/1"), LOGIN) == ("Claude · fill", "https://jobs.lever.co/acme/1")
    # a direct ATS link found in Notes beats the job-board URL
    assert who(row(Notes="Ashby https://jobs.ashbyhq.com/acme/9 open"), LOGIN) == ("Claude · fill", "https://jobs.ashbyhq.com/acme/9")
    assert who(row(), LOGIN)[0] == "Claude · verify+fill"


def test_build_skips_done_rows_and_ranks_by_tier_then_score():
    rows = [row(ID="a", Tier="Medium", Score="90"), row(ID="b", Tier="Strong", Score="60"),
            row(ID="c", Tier="Strong", Score="80"), row(ID="d", Status="Applied", Tier="Strong"),
            row(ID="e", Status="Skip")]
    out = build(rows, LOGIN)
    assert out[0][0] == "#"
    assert [r[-1] for r in out[1:]] == ["c", "b", "a"]
