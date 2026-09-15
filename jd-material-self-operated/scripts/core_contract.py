from collections.abc import Iterator
from dataclasses import fields, is_dataclass
import math


COMMON_FUNCTIONS = (
    'jd_material_agent.selling_point_prompts', 'jd_material_agent.short_title_prompts',
    'jd_material_agent._shared_image_rules', 'jd_material_agent.image_prompt',
)
FUNCTIONS = {
    'jd-material-pop': (*COMMON_FUNCTIONS, 'jd_material_agent._jobs_from_rows', 'jd_material_agent.build_material_binding_requests'),
    'jd-material-self-operated': (*COMMON_FUNCTIONS, 'jd_material_agent.reconcile_self_operated_segment',
        'direct_binding.build_material_binding_requests', 'direct_binding.build_self_operated_binding_requests',
        'direct_binding.build_self_operated_short_title_requests'),
}
TYPE_NAMES = ('SourceRow', 'SpuJob', 'PreparedSource', 'SelfOperatedDiscoveryResult')
SECRET_FIELDS = {'api_key', 'apikey', 'authorization', 'cookie', 'cookies', 'me_token', 'access_token', 'password', 'jd_llm_api_key'}


def encode(value, depth=0):
    if depth > 48:
        raise ValueError('CORE_INVALID_INPUT')
    nested = lambda item: encode(item, depth + 1)
    if value is None or type(value) in (str, bool, int):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if is_dataclass(value) and type(value).__name__ in TYPE_NAMES:
        return {'type': type(value).__name__, 'fields': {field.name: nested(getattr(value, field.name)) for field in fields(value)}}
    if isinstance(value, dict):
        if any(not isinstance(key, (str, int)) or str(key).lower() in SECRET_FIELDS for key in value):
            raise ValueError('CORE_INVALID_INPUT')
        return {'type': 'dict', 'items': [[key, nested(item)] for key, item in value.items()]}
    if isinstance(value, (list, tuple, set, Iterator)):
        kind = 'tuple' if isinstance(value, tuple) else 'set' if isinstance(value, set) else 'list'
        return {'type': kind, 'items': [nested(item) for item in value]}
    raise ValueError('CORE_INVALID_INPUT')


def decode(value, registry, depth=0):
    if depth > 48:
        raise ValueError('CORE_INVALID_INPUT')
    nested = lambda item: decode(item, registry, depth + 1)
    if value is None or type(value) in (str, bool, int):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if not isinstance(value, dict):
        raise ValueError('CORE_INVALID_INPUT')
    kind = value.get('type')
    if kind in TYPE_NAMES and set(value) == {'type', 'fields'}:
        cls = registry.get(kind)
        source = value['fields']
        if cls is None or not isinstance(source, dict) or set(source) != {field.name for field in fields(cls)}:
            raise ValueError('CORE_INVALID_INPUT')
        return cls(**{key: nested(item) for key, item in source.items()})
    if set(value) != {'type', 'items'} or not isinstance(value['items'], list):
        raise ValueError('CORE_INVALID_INPUT')
    items = value['items']
    if kind == 'dict':
        result = {}
        for pair in items:
            if not isinstance(pair, list) or len(pair) != 2 or not isinstance(pair[0], (str, int)) or pair[0] in result or str(pair[0]).lower() in SECRET_FIELDS:
                raise ValueError('CORE_INVALID_INPUT')
            result[pair[0]] = nested(pair[1])
        return result
    values = [nested(item) for item in items]
    if kind == 'tuple':
        return tuple(values)
    if kind == 'list':
        return values
    if kind == 'set':
        return set(values)
    raise ValueError('CORE_INVALID_INPUT')
