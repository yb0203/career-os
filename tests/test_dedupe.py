from pipeline.dedupe import canon_key, find_duplicates, norm_title


def test_same_job_different_spelling_collapses():
    assert canon_key("Branch International Inc.", "Associate Product Manager") == canon_key("Branch International", "Associate Product Manager")
    assert canon_key("Zepto", "Product Manager (m/f/d)") == canon_key("Zepto Pvt. Ltd.", "Product Manager (Remote)")
    assert norm_title("Product Manager - Bengaluru") == norm_title("Product Manager")
    assert norm_title("Sr. Product Manager") == norm_title("Senior Product Manager")


def test_different_roles_stay_distinct():
    assert canon_key("Satispay", "Product Manager - Credit") != canon_key("Satispay", "Product Manager - Investments")
    assert canon_key("GitLab", "Backend Engineer (Python)") != canon_key("GitLab", "Backend Engineer (Ruby)")
    assert canon_key("X", "Product Manager") != canon_key("X", "Senior Product Manager")
    assert canon_key("X", "Product Manager I") != canon_key("X", "Product Manager II")


def test_find_duplicates_keeps_the_applied_direct_row():
    rows = [dict(Company="A Inc.", Role="Product Manager", Status="New", Source="linkedin", **{"First seen": "2026-10-20"}),
            dict(Company="A", Role="Product Manager (Remote)", Status="Applied", Source="greenhouse", **{"First seen": "2026-10-22"}),
            dict(Company="B", Role="Product Manager", Status="New", Source="lever", **{"First seen": "2026-10-20"})]
    (keeper, dups), = find_duplicates(rows)
    assert keeper["Status"] == "Applied" and [d["Source"] for d in dups] == ["linkedin"]


def test_plan_updates_marks_only_extra_copies():
    from pipeline.dedupe import plan_updates
    rows = [dict(ID="1", Company="A", Role="Product Manager", Status="Applied", Source="greenhouse", Notes="x", **{"First seen": "1"}),
            dict(ID="2", Company="A Inc", Role="Product Manager", Status="Applied", Source="manual", Notes="", **{"First seen": "2"}),
            dict(ID="3", Company="A", Role="Product Manager - Remote", Status="New", Source="linkedin", Notes="", **{"First seen": "3"}),
            dict(ID="4", Company="B", Role="Product Manager", Status="New", Source="lever", Notes="", **{"First seen": "1"})]
    plan = plan_updates(rows)
    assert set(plan) == {"2", "3"} and plan["2"][0] == "Skip" and "Duplicate of A / Product Manager" in plan["3"][1]


def test_workday_listing_filter():
    from pipeline.fetchers.workday import parse_listing
    ok = parse_listing("mastercard.wd1", "CorporateCareers", {"title": "Senior Product Manager", "locationsText": "Gurgaon, India",
                       "externalPath": "/job/Gurgaon/PM_R-1", "postedOn": "Posted Today"})
    assert ok and ok["url"] == "https://mastercard.wd1.myworkdayjobs.com/CorporateCareers/job/Gurgaon/PM_R-1"
    assert parse_listing("x.wd1", "S", {"title": "Product Manager", "locationsText": "Dallas, TX", "externalPath": "/job/a"}) is None
    assert parse_listing("x.wd1", "S", {"title": "Software Engineer", "locationsText": "Bengaluru", "externalPath": "/job/a"}) is None
