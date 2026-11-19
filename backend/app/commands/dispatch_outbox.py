"""Independent dispatcher; safe to run alongside Beat (SKIP LOCKED claims)."""
import logging
import signal
import threading

from app.config import load_settings
from app.logging_config import configure_logging
from app.modules.async_execution.tasks_core import dispatch_outbox_once


def main():
    settings = load_settings()
    configure_logging(settings.log_level)
    stopping = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stopping.set())
    while not stopping.is_set():
        try:
            result = dispatch_outbox_once(settings)
            logging.getLogger(__name__).info('outbox.dispatch', extra={'dispatched_count': len(result['dispatched']), 'failed_count': len(result['failed'])})
        except Exception as exc:
            logging.getLogger(__name__).error('outbox.unavailable', extra={'error_type': type(exc).__name__})
        stopping.wait(5)


if __name__ == '__main__':
    main()
