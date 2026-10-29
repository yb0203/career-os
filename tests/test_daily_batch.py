from pipeline.daily_batch import candidates, select, to_values, HEADER


def row(company, role, tier="Strong", status="New", loc="Bengaluru", score=50, url="https://boards.greenhouse.io/x/jobs/1", i="1"):
    return dict(Company=company, Role=role, Tier=tier, Status=status, Location=loc, Score=score, URL=url, ID=i,
                Notes="", Source="greenhouse", Why="", Open="Yes")


def eu(company, role, visa="sponsor", remote="No", fam="Product", status="New", i="e1"):
    return dict(Company=company, Role=role, Family=fam, Status=status, **{"Visa/Relocation": visa}, Remote=remote,
                Country="Netherlands", **{"Apply method": "Direct (no login)", "Apply link": "https://x"}, Why="asks ~2 yrs",
                Score=60, ID=i, Open="Yes")


def test_done_roles_are_dropped_and_foreign_included():
    openings = [row("A", "Product Manager", i="a"), row("B", "Product Manager", status="Applied", i="b"),
                row("B", "Product Manager", i="b2")]
    c = candidates(openings, [eu("C", "Product Manager"), eu("D", "Backend Engineer", fam="Engineering", i="e2")], set())
    names = {(x["company"], x["region"]) for x in c}
    assert ("A", "India") in names and ("C", "Foreign") in names
    assert not any(x["company"] == "B" for x in c)          # same company+role already Applied
    assert not any(x["company"] == "D" for x in c)          # engineering role is skipped


def test_select_puts_strong_first_caps_foreign_and_one_role_per_company():
    cands = candidates([row(f"S{i}", "Product Manager", tier="Strong", i=str(i)) for i in range(10)]
                       + [row(f"M{i}", "Product Manager", tier="Medium", i=f"m{i}") for i in range(30)]
                       + [row("S0", "Associate Product Manager", tier="Strong", i="dup")],
                       [eu(f"F{i}", "Product Manager", i=f"f{i}") for i in range(10)], set())
    batch = select(cands, total=30, max_foreign=3)
    assert len(batch) == 30
    assert sum(c["tier"] == "Strong" for c in batch) >= 8
    assert sum(c["region"] == "Foreign" for c in batch) <= 3
    assert len({c["company"] for c in batch}) == len(batch)
    tiers = [c["tier"] for c in batch]
    assert tiers == sorted(tiers, key=lambda t: {"Strong": 0, "Medium": 1, "Exploratory": 2}[t])
    assert to_values(batch)[0] == HEADER and len(to_values(batch)) == 31


def test_min_years_and_retiering_by_real_years():
    from pipeline.daily_batch import min_years, enrich_years
    assert min_years("We want 3+ years of experience in product management") == 3
    assert min_years("5-8 years of product experience") == 5
    assert min_years("Founded 12 years ago, a fun place to work") is None
    c = [dict(tier="Strong", region="India", company="X", role="PM", location="", years=6, route="Claude · fill",
              lane="", visa="", link="", score=1, id="1")]
    enrich_years(c)
    assert c[0]["tier"] == "Medium"
