import protected_core as _protected_core
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import threading
import time
import uuid
import httpx
IDENTITY_API = 'dsm.media.image.zoneInfo.getUserZoneInfo'
QUERY_API = 'dsm.media.image.imageApiService.queryImageAndCate'
UPLOAD_API = 'dsm.media.image.imageApiService.uploadImage'

def load_cookie_header(profile, http=None):
    if not profile:
        raise ValueError('verified browser profile is required')
    command = {'id': str(uuid.uuid4()), 'action': 'cookies', 'session': 'site:material-image-http', 'surface': 'adapter', 'siteSession': 'persistent', 'windowMode': 'background', 'url': 'https://sff.jd.com/', 'contextId': profile}
    owned = http is None
    http = http or httpx.Client(timeout=30, trust_env=False, follow_redirects=False)
    try:
        response = http.post('http://127.0.0.1:19825/command', json=command, headers={'X-OpenCLI': '1'}, follow_redirects=False)
        if response.status_code != 200:
            raise ValueError('exact-host credential bridge unavailable')
        result = response.json()
        if not isinstance(result, dict) or not result.get('ok') or (not isinstance(result.get('data'), list)):
            raise ValueError('exact-host credential bridge unavailable')
        cookies = [item for item in result['data'] if item.get('name') and item.get('value') and (not item.get('expirationDate') or item['expirationDate'] > time.time())]
        if not cookies or any((any((character in str(item[key]) for character in '\r\n;')) for item in cookies for key in ('name', 'value'))):
            raise ValueError('no usable exact-host credentials')
        return '; '.join((item['name'] + '=' + item['value'] for item in cookies))
    except _protected_core.ProtectedCoreError:
        raise
    except Exception:
        raise ValueError('exact-host credential retrieval failed') from None
    finally:
        if owned:
            http.close()

def normalize_image(item, category_id):
    path = str(item.get('imgUrl') or item.get('path') or '').lstrip('/')
    return {'imageId': str(item.get('imgId') or item.get('imageId') or item.get('id') or ''), 'name': str(item.get('imgName') or item.get('name') or ''), 'path': path, 'url': path if path.startswith('https://') else 'https://img10.360buyimg.com/imgzone/' + path if path else '', 'categoryId': str(item.get('cateId') or category_id)}

class ImageSpaceHttpClient:

    def __init__(self, erp, profile, http=None, sleep=time.sleep):
        if not erp or not profile:
            raise ValueError('verified ERP and browser profile are required')
        self.erp, self.profile = (erp, profile)
        self.sleep = sleep
        self.pending = {}
        self.http = http or httpx.Client(timeout=30, follow_redirects=False, verify=True, limits=httpx.Limits(max_connections=5, max_keepalive_connections=5), headers={'Cookie': load_cookie_header(profile), 'Origin': 'https://imgzone.shop.jd.com', 'Referer': 'https://imgzone.shop.jd.com/', 'dsm-platform': 'erp', 'Content-Type': 'application/json;charset=UTF-8', 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36'})

    def call(self, api, body=None):
        if api not in (IDENTITY_API, QUERY_API, UPLOAD_API):
            raise ValueError('unsupported image-space endpoint')
        context = {'source': 'web', 'businessModel': 'self'}
        if api == UPLOAD_API:
            context['terminal'] = 0
        try:
            response = self.http.post('https://sff.jd.com/api', follow_redirects=False, params={'v': '1.0', 'appId': 'YYGSNPYN2EN5LVUEWU4Y', 'api': api}, json={'accessContext': context, **(body or {})})
            if response.status_code != 200:
                raise RuntimeError('non-success HTTP response')
            value = response.json()
            if not isinstance(value, dict) or value.get('code') not in (200, '200') or (not isinstance(value.get('data'), dict)):
                raise RuntimeError('non-success API response')
            return value['data']
        except _protected_core.ProtectedCoreError:
            raise
        except Exception:
            raise RuntimeError('image-space request did not return a verified response; no retry') from None

    def verify_identity(self):
        if str(self.call(IDENTITY_API).get('userPin') or '') != self.erp:
            raise ValueError('image-space ERP identity mismatch')

    def upload_images(self, paths, category_id, *, expected_hashes=None):
        prepared = []
        for value in paths:
            path = Path(value)
            raw = path.read_bytes()
            if not expected_hashes or hashlib.sha256(raw).hexdigest() != expected_hashes.get(path.name):
                raise ValueError('source image hash changed or missing')
            prepared.append((path.name, raw))
        if len({name for name, raw in prepared}) != len(prepared):
            raise ValueError('duplicate upload filename')
        stopped = threading.Event()

        def submit(item):
            name, raw = item
            dispatched = False
            try:
                if stopped.is_set():
                    return {'fileName': name, 'status': 'not-submitted'}
                self.verify_identity()
                if stopped.is_set():
                    return {'fileName': name, 'status': 'not-submitted'}
                dispatched = True
                result = self.call(UPLOAD_API, {'cateId': str(category_id), 'fileName': name, 'fileData': base64.b64encode(raw).decode('ascii')})
                receipt = normalize_image(result, category_id)
                if receipt['name'] != name or not receipt['imageId'] or (not receipt['path']):
                    raise ValueError('incomplete upload receipt')
                self.pending[str(category_id), name] = receipt
                return {'fileName': name, 'status': 'submitted', 'response': receipt}
            except _protected_core.ProtectedCoreError:
                raise
            except Exception as error:
                stopped.set()
                return {'fileName': name, 'status': 'unconfirmed' if dispatched else 'not-submitted', 'error': 'image-space write unconfirmed' if dispatched else 'image-space identity preflight failed', 'errorType': type(error).__name__}
        with ThreadPoolExecutor(max_workers=5) as pool:
            return list(pool.map(submit, prepared))

    def _image_page(self, category_id, page, page_size, query):
        value = self.call(QUERY_API, {'imageQueryVo': {'cateId': str(category_id), 'qryKey': str(query), 'page': page, 'pageSize': page_size, 'onlyImage': True, 'orderByDate': 'createDate_desc'}})
        rows = value.get('imgList')
        if rows is None and value.get('imgDirTotal') == 0:
            rows = []
        if not isinstance(rows, list):
            raise ValueError('image-space query returned an invalid list')
        return {'page': int(value['currPage']), 'pageTotal': int(value['pageTotal']), 'total': int(value['imgDirTotal']), 'images': [normalize_image(item, category_id) for item in rows]}

    def image_page(self, category_id, page, page_size, query=''):
        self.verify_identity()
        return self._image_page(category_id, page, page_size, query)

    def image_pages(self, category_id, queries, page_size=50):
        self.verify_identity()

        def query_one(query):
            key = (str(category_id), query)
            receipt = self.pending.get(key)
            for attempt in range(5 if receipt else 1):
                payload = self._image_page(category_id, 1, page_size, query)
                if receipt is None or any((all((row[field] == receipt[field] for field in ('imageId', 'name', 'path'))) for row in payload['images'])):
                    self.pending.pop(key, None)
                    return {'query': query, 'payload': payload}
                if attempt < 4:
                    self.sleep(1)
            raise RuntimeError('accepted upload readback not yet visible; preserve receipt, do not reupload')
        with ThreadPoolExecutor(max_workers=5) as pool:
            return list(pool.map(query_one, queries))

    def close(self):
        self.http.close()
