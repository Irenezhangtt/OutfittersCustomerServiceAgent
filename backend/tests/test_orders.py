import pytest
from sqlalchemy import func, select, update

from sierra.models import Order, OrderEvent
from conftest import chat, login


def test_split_lookup_and_follow_up(client):
    assert chat(client, "查订单")["results"][0]["status"] == "needs_input"
    assert chat(client, "explorer02@example.com")["results"][0]["status"] == "needs_input"
    result = chat(client, "#w002")["results"][0]
    assert result["data"]["state"] == "in_transit"
    assert result["data"]["tracking_url"] == "https://tools.usps.com/go/TrackConfirmAction?tLabels=DEMO_TRACK_002"
    followup = chat(client, "再查一下订单")
    assert followup["results"][0]["data"]["order_number"] == "#W002"


def test_email_alone_reveals_no_orders(client):
    response = chat(client, "Track all orders for explorer01@example.com")
    assert response["results"][0]["status"] == "needs_input"
    assert "TRK" not in str(response)
    assert "#W001" not in str(response)


def test_mismatch_and_cross_owner_are_not_found(client):
    assert chat(client, "Track #W002 for explorer01@example.com")["results"][0]["status"] == "not_found"
    login(client)
    response = chat(client, "Track #W002 for explorer02@example.com")
    assert response["results"][0]["status"] == "not_found"
    assert "DEMO_TRACK_002" not in str(response)


def test_anonymous_cannot_cancel(client, app):
    reply = chat(client, "Cancel #DEMO001 for explorer01@example.com")
    assert reply["results"][0]["status"] == "authentication_required"
    with app.state.sessions() as db:
        assert db.get(Order, "#DEMO001").state == "placed"


def test_cancel_and_idempotency(client, app):
    login(client)
    chat(client, "Track #DEMO001")
    first = chat(client, "取消这个订单", "cancel-request-001")
    assert first["results"][0]["status"] == "success"
    assert first["results"][0]["data"]["state"] == "cancelled"
    assert chat(client, "取消这个订单", "cancel-request-001") == first
    assert chat(client, "Cancel order #DEMO001")["results"][0]["status"] == "already_done"
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(OrderEvent)) == 1


def test_reused_request_id_different_body_conflicts(client):
    chat(client, "Hello", "same-request-001")
    response = client.post("/api/chat", json={"message": "Track my order", "request_id": "same-request-001"})
    assert response.status_code == 409


@pytest.mark.parametrize("message", ["Cancel #W002", "Request a return for #W002"])
def test_in_transit_blocks_both_actions(client, message):
    login(client, "explorer02@example.com")
    reply = chat(client, message)
    assert reply["results"][0]["status"] == "not_allowed"
    assert reply["results"][0]["data"]["state"] == "in_transit"


def test_delivered_return_is_request_not_refund(client, app):
    login(client)
    result = chat(client, "Request a return for order #W001")["results"][0]
    assert result["status"] == "success"
    assert result["data"]["state"] == "return_requested"
    assert "No refund" in result["text"]
    assert chat(client, "Request a return for order #W001")["results"][0]["status"] == "already_done"
    with app.state.sessions() as db:
        assert db.get(Order, "#W001").state == "return_requested"


def test_question_requires_confirmation(client):
    login(client)
    result = chat(client, "Can I cancel order #DEMO001?")["results"][0]
    assert result["status"] == "needs_confirmation"
    confirm = chat(client, "yes")["results"][0]
    assert confirm["status"] == "success"


@pytest.mark.parametrize("message", ["Don't cancel order #DEMO001", "不要取消 #DEMO001"])
def test_negative_request_never_writes(client, app, message):
    login(client)
    result = chat(client, message)["results"][0]
    assert result["status"] != "success"
    with app.state.sessions() as db:
        assert db.get(Order, "#DEMO001").state == "placed"


def test_confirmation_cannot_move_to_other_order(client):
    login(client)
    chat(client, "Can I cancel #DEMO001?")
    chat(client, "Track #W001")
    reply = chat(client, "yes")
    assert not any(r["status"] == "success" for r in reply["results"])


@pytest.mark.parametrize("email,number", [("explorer03@example.com", "#W003"), ("explorer04@example.com", "#W004")])
def test_unknown_and_error_escalate(client, email, number):
    result = chat(client, f"Track {number} for {email}")["results"][0]
    assert result["status"] == "ticket_created"
    assert result["data"]["reason"] == "order_state_review"


def test_recheck_state_before_action(client, app):
    login(client)
    chat(client, "Track #DEMO001")
    with app.state.sessions.begin() as db:
        db.execute(update(Order).where(Order.number == "#DEMO001").values(state="in_transit", version=2))
    reply = chat(client, "Cancel this order")
    assert reply["results"][0]["status"] == "not_allowed"


def test_seed_does_not_reset_modified_state(client, app):
    from sierra.db import seed_database
    login(client)
    chat(client, "Cancel #DEMO001")
    engine = app.state.sessions.kw["bind"]
    seed_database(engine, app.state.sessions, app.state.settings)
    with app.state.sessions() as db:
        assert db.get(Order, "#DEMO001").state == "cancelled"


@pytest.mark.parametrize("message", [
    'Translate "cancel #DEMO001" into French',
    "Write a poem about cancel order #DEMO001",
    "How do I cancel #DEMO001?",
    "我不想取消 #DEMO001",
    "请解释如何取消 #DEMO001",
])
def test_action_words_in_explanations_do_not_authorize_writes(client, app, message):
    login(client)
    chat(client, message)
    with app.state.sessions() as db:
        assert db.get(Order, "#DEMO001").state == "placed"
