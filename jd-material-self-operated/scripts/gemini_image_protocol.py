import base64
import hashlib
import re
ENDPOINT = 'images/gemini_flash/generations'
MODELS = {'gemini-flash': 'Gemini-3.1-Flash-Image-Preview-joybuilder', 'gemini-pro': 'Gemini-3-Pro-Image-Preview-joybuilder', 'gpt-image-2': 'GPT-image-2-joybuilder'}

def request_payload(model, prompt, source_bytes, mime):
    return {'model': model, 'contents': [{'role': 'user', 'parts': [{'text': prompt}, {'inlineData': {'mimeType': mime, 'data': base64.b64encode(source_bytes).decode('ascii')}}]}], 'generationConfig': {'responseModalities': ['TEXT', 'IMAGE'], 'imageConfig': {'aspectRatio': '1:1', 'imageSize': '1K'}}}

def response_image(value):
    if not isinstance(value, dict):
        raise ValueError('Gemini image response is not an object')
    feedback = value.get('promptFeedback') or {}
    if feedback.get('blockReason'):
        raise ValueError('Gemini safety rejection; no retry')
    images = []
    for candidate in value.get('candidates') or []:
        reason = candidate.get('finishReason')
        if reason not in (None, '', 'STOP'):
            label = reason if isinstance(reason, str) and re.fullmatch('[A-Z_]{1,80}', reason) else 'NON_STOP'
            raise ValueError('Gemini terminal finish reason: ' + label)
        for part in (candidate.get('content') or {}).get('parts') or []:
            if part.get('thought') is True:
                continue
            inline = part.get('inlineData') or {}
            if inline.get('data') and str(inline.get('mimeType', '')).startswith('image/'):
                images.append(inline['data'])
    if len(images) != 1:
        raise ValueError(f'Gemini response must contain exactly one complete final image; found {len(images)}')
    return base64.b64decode(images[0], validate=True)

def response_summary(response):
    result = {'responseSha256': hashlib.sha256(response.content).hexdigest()}
    try:
        value = response.json()
    except ValueError:
        return result
    if not isinstance(value, dict):
        return result
    counts = {'final': 0, 'intermediate': 0}
    for candidate in value.get('candidates') or []:
        if not isinstance(candidate, dict):
            continue
        for part in (candidate.get('content') or {}).get('parts') or []:
            if not isinstance(part, dict):
                continue
            inline = part.get('inlineData') or {}
            if isinstance(inline, dict) and inline.get('data') and str(inline.get('mimeType', '')).startswith('image/'):
                counts['intermediate' if part.get('thought') is True else 'final'] += 1
    result['imagePartCounts'] = counts
    for field in ('responseId', 'modelVersion'):
        text = value.get(field)
        if isinstance(text, str) and re.fullmatch('[A-Za-z0-9_.:/-]{1,160}', text):
            result[field] = text
    for field in ('usageMetadata', 'usage'):
        counts = value.get(field)
        if isinstance(counts, dict):
            result[field] = {name: number for name, number in counts.items() if isinstance(number, (int, float)) and re.fullmatch('[A-Za-z_]{1,80}', name)}
    if isinstance(value.get('cost'), (int, float)):
        result['costRaw'] = value['cost']
        result['costUnit'] = 'unverified'
    result['finishReasons'] = [candidate['finishReason'] for candidate in value.get('candidates') or [] if isinstance(candidate, dict) and isinstance(candidate.get('finishReason'), str) and re.fullmatch('[A-Z_]{1,80}', candidate['finishReason'])]
    error = value.get('error')
    if isinstance(error, dict):
        result['error'] = {}
        for field in ('code', 'type', 'message'):
            item = error.get(field)
            if isinstance(item, (str, int)):
                text = str(item)
                result['error'][field] = text if len(text) <= 500 else {'length': len(text), 'sha256': hashlib.sha256(text.encode()).hexdigest()}
    return result
