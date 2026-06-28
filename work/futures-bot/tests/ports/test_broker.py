import pytest

from futures_bot.ports.broker import BrokerSubmissionError


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
