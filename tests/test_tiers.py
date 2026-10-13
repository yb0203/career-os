from pipeline.tiers import classify, fill_tiers


def test_core_roles_by_seniority_location_and_years():
    assert classify("Associate Product Manager", "Bengaluru", "2+ yrs asked") == "Strong"
    assert classify("AI Product Manager", "Remote, India") == "Strong"
    assert classify("Product Manager", "Gurugram, Haryana") == "Medium"
    assert classify("Senior Product Manager", "Bangalore", "5+ yrs asked") == "Medium"
    assert classify("Product Manager", "Bengaluru", "8+ yrs asked") == "Exploratory"
    assert classify("Principal Product Manager", "Bengaluru") == "Exploratory"
    assert classify("Founder's Office - Generalist", "Bengaluru") == "Strong"


def test_adjacent_roles_are_exploratory():
    assert classify("Revenue Operations Specialist", "Bengaluru") == "Exploratory"
    assert classify("AI Solutions Engineer", "Bengaluru") == "Exploratory"


def test_fill_tiers_only_touches_untiered_new_rows():
    rows = [{"ID": "a", "Status": "New", "Tier": "", "Role": "Product Manager", "Location": "Bengaluru"},
            {"ID": "b", "Status": "New", "Tier": "Medium", "Role": "Product Manager", "Location": "Bengaluru"},
            {"ID": "c", "Status": "Applied", "Tier": "", "Role": "Product Manager", "Location": "Bengaluru"}]
    assert fill_tiers(rows) == {"a": "Strong"}
