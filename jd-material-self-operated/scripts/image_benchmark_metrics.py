import uuid

def new_attempt_id():
    return uuid.uuid4().hex

def attempt_events(events, attempt, task):
    return [event for event in events if event.get('attempt') == attempt and event.get('task') == task]

def request_outcome(status, starts):
    return 'not-dispatched' if status == 'failed' and (not starts) else status

def next_probe_time(first, now, attempts, retry_after):
    target = max(first + 300, now + retry_after) if not attempts else now + max(600, retry_after)
    return min(first + 1800, target)

def retryable_recovery_result(item):
    if item.get('quotaExhausted') or item.get('authenticationFailed'):
        return False
    return bool(item.get('errorType') == 'ModelTransientError' or item.get('resourceBlocked') or any((response.get('httpStatus') == 429 for response in item.get('responses', []))))

def attempt_totals(attempts):
    if any((item.get('httpStarts', 0) not in (0, 1) or len(item.get('responses', [])) > item.get('httpStarts', 0) for item in attempts)):
        raise ValueError('single-dispatch attempt correlation is inconsistent; reconcile raw events first')
    starts = sum((item.get('httpStarts', 0) for item in attempts))
    failed = sum((item.get('status') == 'failed' and bool(item.get('httpStarts')) for item in attempts))
    return {'httpStarts': starts, 'httpFailures': sum((response.get('httpStatus', 0) >= 400 for item in attempts for response in item.get('responses', []))), 'failedImageAttempts': failed, 'successfulImages': sum((item.get('status') == 'generated' for item in attempts)), 'notDispatched': sum((item.get('status') == 'not-dispatched' for item in attempts)), 'imageAttemptFailureRate': failed / starts if starts else None}
