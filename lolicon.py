import os
import json
import time
import traceback
import asyncio
import aiohttp
import io
import random
import datetime
from PIL import Image
from hoshino import R
from .config import get_config

quota_limit_time = datetime.datetime.now()

API_TIMEOUT = aiohttp.ClientTimeout(total=15)
DOWNLOAD_TIMEOUT = aiohttp.ClientTimeout(total=60)

class SetuApiError(Exception):
    '''api请求失败/配额受限/下载全失败, 与"搜索无结果"相区分'''
    pass

SUB_DIRS = ('lolicon', 'lolicon_r18')

# 图库容量扫描缓存, 60秒内不重复扫描
_usage_cache = {'ts': 0.0, 'total': 0, 'detail': {}}

def scan_warehouse():
    now = time.time()
    if now - _usage_cache['ts'] < 60:
        return
    detail = {}
    total = 0
    for sub in SUB_DIRS:
        size = 0
        count = 0
        res = R.img('setu_mix/' + sub)
        if os.path.exists(res.path):
            for root, _, files in os.walk(res.path):
                for fn in files:
                    try:
                        size += os.path.getsize(os.path.join(root, fn))
                        count += 1
                    except OSError:
                        pass
        detail[sub] = {'count': count // 2, 'bytes': size}
        total += size
    _usage_cache['ts'] = now
    _usage_cache['detail'] = detail
    _usage_cache['total'] = total

def warehouse_usage_bytes():
    scan_warehouse()
    return _usage_cache['total']

def warehouse_full():
    limit_mb = get_config('base', 'max_size_mb')
    if not limit_mb or limit_mb <= 0:
        return True
    return warehouse_usage_bytes() >= limit_mb * 1024 * 1024

def evict_warehouse():
    # 滚动缓存: 图库满时按最旧优先整对(jpg+json)删除, 腾出约一批抓图的余量
    limit_mb = get_config('base', 'max_size_mb')
    if not limit_mb or limit_mb <= 0:
        return False
    limit_bytes = limit_mb * 1024 * 1024
    target = max(limit_bytes - 20 * 1024 * 1024, 0)
    pairs = {}
    for sub in SUB_DIRS:
        res = R.img('setu_mix/' + sub)
        if not os.path.exists(res.path):
            continue
        for fn in os.listdir(res.path):
            stem, ext = os.path.splitext(fn)
            if ext not in ('.jpg', '.json') or not stem.isdigit():
                continue
            p = os.path.join(res.path, fn)
            try:
                st = os.stat(p)
            except OSError:
                continue
            ent = pairs.setdefault((sub, stem), {'paths': [], 'size': 0, 'time': st.st_mtime})
            ent['paths'].append(p)
            ent['size'] += st.st_size
            ent['time'] = min(ent['time'], st.st_mtime)
    entries = sorted(pairs.values(), key=lambda e: e['time'])
    total = warehouse_usage_bytes()
    removed = 0
    for e in entries:
        if total <= target:
            break
        ok = True
        for p in e['paths']:
            try:
                os.remove(p)
            except OSError:
                ok = False
        if ok:
            total -= e['size']
            removed += 1
    print('setu_mix 图库已满, 已清理最旧图片', removed, '张')
    _usage_cache['ts'] = 0
    return warehouse_usage_bytes() <= limit_bytes

def lolicon_warehouse_state():
    scan_warehouse()
    return _usage_cache['detail'], _usage_cache['total']

def generate_image_struct():
    return {
        'id': 0,
        'url': '',
        'title': '',
        'author': '',
        'tags': [],
        'r18': False,
        'data': None,
        'native': False,
    }

native_info = {}
native_r18_info = {}

def load_native_info(sub_dir):
    info = {}
    path = f'setu_mix/' + sub_dir
    res = R.img(path)
    if not os.path.exists(res.path):
        return info
    fnlist =  os.listdir(res.path)

    for fn in fnlist:
        s = fn.split('.')
        if len(s) != 2 or s[1] != 'json' or not s[0].isdigit():
            continue
        uid = int(s[0])
        try:
            with open(res.path + '/' + fn, encoding='utf8') as f:
                d = json.load(f)
                d['tags'].append(d['title'])
                d['tags'].append(d['author'])
                info[uid] = ','.join(d['tags'])
        except:
            pass
    print('read', len(info), 'setu from', sub_dir)
    return info

#获取随机色图
async def query_setu(r18 = 0, keyword=None):
    global quota_limit_time
    image_list = []
    if datetime.datetime.now() < quota_limit_time:
        raise SetuApiError(f'lolicon api 已达调用额度上限, 稍后自动恢复')
    if get_config('lolicon', 'mode') == 2 and warehouse_full():
        if not evict_warehouse():
            raise SetuApiError('图库已满且无法腾出空间, 已停止api抓图')

    url = 'https://api.lolicon.app/setu'
    params = {
        'r18': r18,
        'num': 10,
        }
    if keyword:
        params['keyword'] = keyword
    if get_config('lolicon', 'use_thumb'):
        params['size1200'] = 'true'
    if get_config('lolicon', 'pixiv_direct'):
        params['proxy'] = 'disable'

    try:
        async with aiohttp.ClientSession(timeout=API_TIMEOUT) as session:
            async with session.get(url, params=params) as resp:
                data = await resp.json(content_type='application/json')
    except Exception as e:
        raise SetuApiError(f'lolicon api 请求失败: {e!r}') from None
    if 'code' not in data:
        raise SetuApiError('lolicon api 返回数据无效')
    if data['code'] != 0:
        if data['code'] == 429:
            ttl = data.get('quota_min_ttl') or 600
            quota_limit_time = datetime.datetime.now() + datetime.timedelta(seconds=ttl)
            raise SetuApiError(f'lolicon api 已达调用额度上限, 约{ttl // 60}分钟后恢复')
        raise SetuApiError(f'lolicon api error {data["code"]}: {data.get("msg", "")}')
    for item in data['data']:
        image = generate_image_struct()
        image['id'] = item['pid']
        image['title'] = item['title']
        image['url'] = item['url']
        image['tags'] = item['tags']
        image['r18'] = item['r18']
        image['author'] = item['author']
        image_list.append(image)
    return image_list

def _pil_to_jpeg(data):
    # PIL 解码大图是重CPU操作, 只能放线程池, 避免阻塞事件循环拖住整个bot
    byte_stream = io.BytesIO(data)
    roiImg = Image.open(byte_stream)
    if roiImg.mode != 'RGB':
        roiImg = roiImg.convert('RGB')
    imgByteArr = io.BytesIO()
    roiImg.save(imgByteArr, format='JPEG')
    return imgByteArr.getvalue()

async def _to_jpeg(data):
    return await asyncio.get_event_loop().run_in_executor(None, _pil_to_jpeg, data)

async def download_image(url: str):
    print('lolicon downloading image', url)
    try:
        async with aiohttp.ClientSession(timeout=DOWNLOAD_TIMEOUT) as session:
            async with session.get(url) as resp:
                data = await resp.read()
                return await _to_jpeg(data)
    except :
        print('download image failed')
        #traceback.print_exc()
    return None

async def download_pixiv_image(url: str, id):
    print('lolicon downloading pixiv image', url)
    headers = {
        'referer': f'https://www.pixiv.net/member_illust.php?mode=medium&illust_id={id}'
        }
    try:
        async with aiohttp.ClientSession(timeout=DOWNLOAD_TIMEOUT, headers=headers) as session:
            async with session.get(url, proxy=get_config('lolicon', 'pixiv_proxy')) as resp:
                data = await resp.read()
                return await _to_jpeg(data)
    except :
        print('download image failed')
        #traceback.print_exc()
    return None

def save_image(image):
    path = f'setu_mix/lolicon/{image["id"]}'
    if image['r18']:
        path = f'setu_mix/lolicon_r18/{image["id"]}'

    res = R.img(path + '.jpg')
    with open(res.path, 'wb') as f:
        f.write(image['data'])

    res = R.img(path + '.json')
    info = {
        'title': image['title'],
        'author': image['author'],
        'url': image['url'],
        'tags': image['tags'],
    }
    with open(res.path, 'w', encoding='utf8') as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
    _usage_cache['ts'] = 0

async def get_setu_online(num, r18 = 0, keyword = None):
    image_list = await query_setu(r18 = r18, keyword = keyword)
    valid_list = []
    had_result = len(image_list) > 0

    while len(image_list) > 0:
        image = image_list.pop(random.randint(0, len(image_list) - 1))
        #检查本地是否存在该图片
        path = f'setu_mix/lolicon/{image["id"]}.jpg'
        if image['r18']:
            path = f'setu_mix/lolicon_r18/{image["id"]}.jpg'
        res = R.img(path)
        if os.path.exists(res.path):
            with open(res.path, 'rb') as f:
                image['data'] = f.read()
                image['native'] = True
        else:
            if get_config('lolicon', 'pixiv_direct'):
                image['data'] = await download_pixiv_image(image['url'], image['id'])
            else:
                image['data'] = await download_image(image['url'])
            image['native'] = False
            if image['data'] and get_config('lolicon', 'mode') == 2:
                save_image(image)
        if image['data']:
            valid_list.append(image)
        if len(valid_list) >= num:
            break
    if had_result and len(valid_list) == 0:
        raise SetuApiError('图片下载失败')
    return valid_list

def get_setu_native(r18 = 0, uid = 0):
    image = generate_image_struct()

    path = f'setu_mix/lolicon'
    if r18 == 1:
        path = f'setu_mix/lolicon_r18'
    elif r18 == 2:
        if random.randint(1, 100) > 50:
            path = f'setu_mix/lolicon_r18'
    res = R.img(path)
    if not os.path.exists(res.path):
        return image

    if uid == 0:
        fn = random.choice(os.listdir(res.path))
        if fn.split('.')[0].isdigit():
            uid = int(fn.split('.')[0])

    if not uid:
        return image

    image['id'] = int(uid)
    image['native'] = True

    path += f'/{uid}'
    res = R.img(path)
    try:
        with open(res.path + '.jpg', 'rb') as f:
            image['data'] = f.read()
        with open(res.path + '.json', encoding='utf8') as f:
            d = json.load(f)
            if 'title' in d:
                image['title'] = d['title']
            if 'author' in d:
                image['author'] = d['author']
    except:
        pass

    return image

def search_setu_native(keyword, r18, num):
    result_list = []
    if r18 == 0 or r18 == 2:
        for k, v in native_info.items():
            if v.find(keyword) >= 0:
                result_list.append({
                    'uid': k,
                    'r18': 0,
                })
    if r18 == 1 or r18 == 2:
        for k, v in native_r18_info.items():
            if v.find(keyword) >= 0:
                result_list.append({
                    'uid': k,
                    'r18': 1,
                })
    if len(result_list) > num:
        result_list = random.sample(result_list, num)
    image_list = []
    for result in result_list:
        image = get_setu_native(result['r18'], result['uid'])
        if image['data']:
            image_list.append(image)
    return image_list

# r18: 0 正常 1 r18 2 混合
async def lolicon_get_setu(r18):
    if get_config('lolicon', 'mode') >= 2:
        return get_setu_native(r18)
    elif get_config('lolicon', 'mode') == 1:
        try:
            image_list = await get_setu_online(1, r18)
        except SetuApiError as e:
            print('get setu failed:', e)
            return None
        if len(image_list) > 0:
            return image_list[0]
        else:
            return None
    else:
        return None

# r18: 0 正常 1 r18 2 混合
async def lolicon_search_setu(keyword, r18, num):
    if get_config('lolicon', 'mode') == 1 or get_config('lolicon', 'mode') == 2:
        return await get_setu_online(num, r18, keyword)
    elif get_config('lolicon', 'mode') == 3: #离线模式
        return search_setu_native(keyword, r18, num)
    else:
        return None

async def lolicon_fetch_process():
    errors = []
    if get_config('lolicon', 'mode') == 2:
        print('fetch lolicon setu')
        try:
            await get_setu_online(10, 0)
        except SetuApiError as e:
            print('fetch lolicon setu failed:', e)
            errors.append(f'普通图库: {e}')
        if get_config('lolicon', 'r18'):
            print('fetch lolicon r18 setu')
            try:
                await get_setu_online(10, 1)
            except SetuApiError as e:
                print('fetch lolicon r18 setu failed:', e)
                errors.append(f'r18图库: {e}')
    return errors

def lolicon_init():
    global native_info
    global native_r18_info
    if get_config('lolicon', 'mode') == 3:
        native_info = load_native_info('lolicon')
        native_r18_info = load_native_info('lolicon_r18')
