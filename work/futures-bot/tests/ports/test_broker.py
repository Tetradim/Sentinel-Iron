from datetime import datetime, timezone

import pytest

from futures_bot.ports.broker import (
    BrokerCancellationError,
    BrokerOrderUpdate,
    BrokerOrderUpdateType,
    BrokerSubmissionError,
)


def test_broker_submission_error_exposes_reason_and_error_code():
    error = BrokerSubmissionError(
        reason="exchange rejected order",
        broker_error_code="EXCHANGE_REJECT",
    )

    assert str(error) == "exchange rejected order"
    assert error.reason == "exchange rejected order"
    assert error.broker_error_code == "EXCHANGE_REJECT"


def test_broker_submission_error_requires_reason():
    with pytest.raises(ValueError, match="reason is required"):
        BrokerSubmissionError(reason="")


def test_broker_cancellation_error_exposes_reason_and_error_code():
    error = BrokerCancellationError(
        reason="broker rejected cancel",
        broker_error_code="TOO_LATE_TO_CANCEL",
    )

    assert str(error) == "broker rejected cancel"
    assert error.reason == "broker rejected cancel"
    assert error.broker_error_code == "TOO_LATE_TO_CANCEL"


def test_broker_cancellation_error_requires_reason():
    with pytest.raises(ValueError, match="reason is required"):
        BrokerCancellationError(reason="")


def test_broker_order_update_requires_positive_fill_quantity_for_fills():
    with pytest.raises(ValueError, match="fill_quantity must be positive for fill updates"):
        BrokerOrderUpdate(
            account_id="acct-1",
            client_order_id="order-1",
            broker_order_id="broker-123",
            instrument_id="ES-202609-CME",
            update_type=BrokerOrderUpdateType.FILL,
            timestamp=datetime(2026, 6, 28, 14, 31, tzinfo=timezone.utc),
        )


def test_broker_order_update_requires_reject_reason_for_rejections():
    with pytest.raises(ValueError, match="reject_reason is required for rejected updates"):
        BrokerOrderUpdate(
            account_id="acct-1",
            client_order_id="order-1",
            broker_order_id="broker-123",
            instrument_id="ES-202609-CME",
            update_type=BrokerOrderUpdateType.REJECTED,
            timestamp=datetime(2026, 6, 28, 14, 31, tzinfo=timezone.utc),
        )
