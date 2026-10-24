"""
Unit tests for the WebhookDispatcher, retries, and Dead-Letter Queue (DLQ).
"""

from relianthook.dispatcher import WebhookDispatcher
from relianthook.models import DeliveryStatus, WebhookEvent


def test_dispatcher_successful_delivery():
    """Verify HTTP 200 marks event as DELIVERED."""
    def mock_transport(url, headers, body):
        assert "X-Webhook-Signature" in headers
        return 200, '{"ok": true}'

    dispatcher = WebhookDispatcher(transport=mock_transport)
    event = WebhookEvent(
        event_id="evt_succ_1",
        destination_url="https://merchant.com/webhook",
        event_type="payment.success",
        payload='{"amount": 1000}',
        secret_key="whsec_123",
    )

    attempt = dispatcher.dispatch(event)
    assert attempt.is_success is True
    assert event.status == DeliveryStatus.DELIVERED
    assert len(event.attempts) == 1
    dispatcher.shutdown()


def test_dispatcher_retry_and_dlq_escalation():
    """Verify HTTP 500 triggers retry and escalates to Dead-Letter Queue on max retries."""
    def failing_transport(url, headers, body):
        return 500, "Internal Server Error"

    dispatcher = WebhookDispatcher(transport=failing_transport, base_backoff_sec=0.01)
    event = WebhookEvent(
        event_id="evt_fail_1",
        destination_url="https://broken.merchant.com/webhook",
        event_type="payment.success",
        payload='{"amount": 1000}',
        secret_key="whsec_123",
        max_retries=3,
    )

    # Attempt 1
    dispatcher.dispatch(event)
    assert event.status == DeliveryStatus.FAILED_RETRYING
    assert event.retry_count == 1

    # Attempt 2
    dispatcher.dispatch(event)
    assert event.status == DeliveryStatus.FAILED_RETRYING
    assert event.retry_count == 2

    # Attempt 3 (Hits max_retries: escalates to DEAD_LETTER)
    dispatcher.dispatch(event)
    assert event.status == DeliveryStatus.DEAD_LETTER
    assert event.retry_count == 3

    # Event must be present in DLQ
    dlq_events = dispatcher.get_dlq_events()
    assert len(dlq_events) == 1
    assert dlq_events[0].event_id == "evt_fail_1"

    # Replay from DLQ with recovery
    def recovered_transport(url, headers, body):
        return 200, '{"recovered": true}'

    dispatcher.transport = recovered_transport
    replay_attempt = dispatcher.replay_dlq_event("evt_fail_1")
    assert replay_attempt.is_success is True
    assert event.status == DeliveryStatus.DELIVERED
    assert len(dispatcher.get_dlq_events()) == 0
    dispatcher.shutdown()
