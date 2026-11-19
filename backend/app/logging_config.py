import logging
import json
import re
from datetime import datetime, timezone

from app.services.audit_service import mask


def safe_text(value):
    value = re.sub(r'(?i)(https?|rediss?|amqps?|postgresql(?:\+psycopg)?)://[^\s/@]+:[^\s/@]+@', r'\1://***@', str(value))
    value = re.sub(r'(?i)(bearer\s+)[^\s,;]+', r'\1***', value)
    return re.sub(r'''(?i)((?:password|secret|api[_-]?key|access_token|refresh_token|authorization|x-amz-(?:signature|credential|security-token))["']?\s*[:=]\s*)(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\s,;&]+)''', r'\1***', value)[:1000]


class JsonFormatter(logging.Formatter):
    def format(self, record):
        item = {'time': datetime.now(timezone.utc).isoformat(), 'level': record.levelname, 'logger': record.name, 'event': safe_text(record.getMessage())}
        for key in ['request_id','method','path','status','duration_ms','job_id','job_type','resource_id','error_type','dispatched_count','failed_count']:
            if hasattr(record, key):
                value = getattr(record, key)
                item[key] = safe_text(value) if isinstance(value,str) else value
        if record.exc_info:
            item['error_type'] = record.exc_info[0].__name__
        return json.dumps(mask(item), ensure_ascii=False, default=str)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)
    # The middleware already logs route templates and timings. Uvicorn's
    # default access handler would also emit raw URLs, including query tokens.
    logging.getLogger('uvicorn.access').disabled = True
    for name in ['uvicorn','uvicorn.error']:
        logger = logging.getLogger(name)
        logger.handlers = [handler]
        logger.propagate = False
        logger.setLevel(level)
