from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select

from sierra.models import Coupon
from conftest import chat, login


@pytest.mark.parametrize("hour,minute,expected", [(7, 59, "outside_window"), (8, 0, "issued"), (9, 59, "issued"), (10, 0, "outside_window")])
def test_claim_boundaries(client, app, hour, minute, expected):
    login(client)
    app.state.clock = lambda: datetime(2026, 11, 17, hour, minute, tzinfo=ZoneInfo("America/Los_Angeles")).astimezone(timezone.utc)
    reply = chat(client, "I want to claim the Early Risers Promotion")
    assert reply["results"][0]["status"] == expected


@pytest.mark.parametrize("month,utc_hour", [(7, 15), (11, 16)])
def test_daylight_saving(client, app, month, utc_hour):
    login(client)
    app.state.clock = lambda: datetime(2026, month, 17, utc_hour, 15, tzinfo=timezone.utc)
    assert chat(client, "领取早鸟优惠")["results"][0]["status"] == "issued"


def test_requires_authentication(client):
    assert chat(client, "领取早鸟优惠")["results"][0]["status"] == "authentication_required"


def test_information_is_not_a_claim(client, app):
    login(client)
    assert chat(client, "Tell me about the early risers discount")["results"][0]["status"] == "information"
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(Coupon)) == 0


def test_duplicate_claim_and_outside_window_retrieval(client, app):
    login(client)
    first = chat(client, "领取早鸟优惠")["results"][0]
    app.state.clock = lambda: datetime(2026, 11, 17, 23, 0, tzinfo=timezone.utc)
    second = chat(client, "领取早鸟优惠")["results"][0]
    assert second["status"] == "existing"
    assert second["data"]["code"] == first["data"]["code"]
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(Coupon)) == 1


def test_distinct_customers_have_distinct_codes(client):
    login(client)
    john = chat(client, "领取早鸟优惠")["results"][0]["data"]["code"]
    login(client, "explorer02@example.com")
    jane = chat(client, "领取早鸟优惠")["results"][0]["data"]["code"]
    assert john != jane


def test_negative_claim_is_not_issued(client, app):
    login(client)
    assert chat(client, "Don't claim the Early Risers discount")["results"][0]["status"] == "information"
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(Coupon)) == 0
