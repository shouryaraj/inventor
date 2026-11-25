from inventor.verify import quote_in_text

TEXT = """I’ve tried three “smart” greenhouse controllers. None of them alert you when a sensor
stops reporting — I ended up writing a cron job that emails me if the reading is stale."""


def test_exact_and_normalised_quotes_pass():
    assert quote_in_text("I ended up writing a cron job that emails me", TEXT) == (True, None)
    # Case, whitespace, curly quotes and wrapping quotation marks are ignored.
    assert quote_in_text('"i\'ve tried three "smart" greenhouse   controllers"', TEXT)[0]
    assert quote_in_text("None of them alert you when a sensor stops reporting - I ended up", TEXT)[0]


def test_ellipsis_parts_must_appear_in_order():
    assert quote_in_text("None of them alert you ... writing a cron job", TEXT)[0]
    assert quote_in_text("writing a cron job … None of them alert you", TEXT) == (False, "quote_not_found")


def test_fabricated_or_trivial_quotes_fail():
    assert quote_in_text("None of them support Zigbee sensors out of the box", TEXT) == (False, "quote_not_found")
    assert quote_in_text("cron job", TEXT) == (False, "quote_too_short")
    assert quote_in_text("None of them ... a", TEXT) == (False, "quote_too_short")
