from weatherbot.parser import parse_bucket, parse_city, parse_market


def test_parse_city_nyc():
    assert parse_city("Will NYC high temperature be above 70F?") == "nyc"


def test_parse_bucket_above():
    bucket = parse_bucket("Will NYC high temperature be above 70F?")
    assert bucket is not None
    assert bucket.metric == "max"
    assert bucket.operator == "above"
    assert bucket.contains(71)
    assert not bucket.contains(70)


def test_parse_bucket_between_from_group_title():
    bucket = parse_bucket("What will the low temperature be in Chicago?", "30-34")
    assert bucket is not None
    assert bucket.metric == "min"
    assert bucket.operator == "between"
    assert bucket.contains(32)
    assert not bucket.contains(35)


def test_parse_hong_kong_celsius_bucket():
    bucket = parse_bucket("Will the highest temperature in Hong Kong be 25°C on May 4?", "25°C")
    assert bucket is not None
    assert bucket.metric == "max"
    assert bucket.unit == "C"
    assert bucket.operator == "integer_degree"
    assert bucket.contains(25.4)
    assert not bucket.contains(26.0)


def test_parse_hong_kong_celsius_or_higher():
    bucket = parse_bucket("Will the highest temperature in Hong Kong be 26°C or higher on May 4?", "26°C or higher")
    assert bucket is not None
    assert bucket.unit == "C"
    assert bucket.metric == "max"
    assert bucket.operator == "at_or_above"
    assert bucket.contains(26.0)
    assert not bucket.contains(25.9)


def test_parse_low_temperature_or_higher_stays_min():
    bucket = parse_bucket("Will the lowest temperature in Hong Kong be 25°C or higher on May 4?", "25°C or higher")
    assert bucket is not None
    assert bucket.metric == "min"
    assert bucket.operator == "at_or_above"


def test_parse_market_temperature():
    raw = {
        "id": "1",
        "question": "Will NYC high temperature be above 70F on May 5?",
        "slug": "nyc-high-above-70",
        "outcomes": "[\"Yes\", \"No\"]",
        "outcomePrices": "[\"0.42\", \"0.58\"]",
        "endDateIso": "2026-05-05",
        "liquidityNum": 1000,
        "volumeNum": 5000,
        "spread": 0.02,
    }
    market = parse_market(raw)
    assert market is not None
    assert market.city == "nyc"
    assert market.yes_price == 0.42


def test_parse_market_hong_kong_temperature():
    raw = {
        "id": "2137348",
        "question": "Will the highest temperature in Hong Kong be 25°C on May 4?",
        "slug": "highest-temperature-in-hong-kong-on-may-4-2026-25c",
        "groupItemTitle": "25°C",
        "outcomes": "[\"Yes\", \"No\"]",
        "outcomePrices": "[\"0.38\", \"0.62\"]",
        "endDateIso": "2026-05-04",
        "liquidityNum": 1000,
        "volumeNum": 5000,
        "spread": 0.04,
    }
    market = parse_market(raw)
    assert market is not None
    assert market.city == "hong kong"
    assert market.bucket.unit == "C"
    assert market.bucket.contains(25.7)
