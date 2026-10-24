import hoshino
import asyncio
import json
import os
import traceback
from datetime import datetime, timedelta
from .base import get_setu, search_setu, fetch_process
from .lolicon import lolicon_warehouse_state, warehouse_full, SetuApiError
from .config import get_config, get_group_config, set_group_config, set_config

HELP_MSG = '''色图/来n张色图 : 随机获取1张/n张色图
搜[n张]色图 keyword : 搜索指定关键字的色图,附带数量可以获取多张'''
sv = hoshino.Service('涩涩-在线', bundle='pcr娱乐', help_=HELP_MSG)

#设置limiter
tlmt = hoshino.util.DailyNumberLimiter(get_config('base', 'daily_max'))
flmt = hoshino.util.FreqLimiter(get_config('base', 'freq_limit'))

LIMIT_FILE = os.path.join(os.path.dirname(__file__), 'limit_data.json')

def _limiter_day():
    # 与 DailyNumberLimiter.check 的口径一致: (北京时间 - 5小时).day
    return (datetime.utcnow() + timedelta(hours=3)).day

def load_limit_data():
    try:
        with open(LIMIT_FILE, encoding='utf8') as f:
            d = json.load(f)
        if d.get('day') != _limiter_day():
            return
        tlmt.today = d.get('day')
        for k, v in d.get('count', {}).items():
            tlmt.count[int(k)] = v
        for k, v in d.get('freq', {}).items():
            flmt.next_time[int(k)] = v
        print('setu_mix 已恢复限流数据:', len(d.get('count', {})), 'users')
    except:
        pass

def save_limit_data():
    try:
        d = {
            'day': tlmt.today,
            'count': {str(k): v for k, v in tlmt.count.items()},
            'freq': {str(k): v for k, v in flmt.next_time.items()},
        }
        tmp = LIMIT_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf8') as f:
            json.dump(d, f)
        os.replace(tmp, LIMIT_FILE)
    except:
        traceback.print_exc()

load_limit_data()

def _bot_nickname():
    nick = getattr(hoshino.config, 'NICKNAME', None)
    if isinstance(nick, (list, tuple)) and nick:
        return str(nick[0])
    if isinstance(nick, str) and nick:
        return nick
    return '我'

def check_lmt(uid, num):
    if uid in hoshino.config.SUPERUSERS:
        return 0, ''
    if not tlmt.check(uid):
        return 1, f"您今天已经冲过{get_config('base', 'daily_max')}次了哦！{_bot_nickname()}不喜欢涩涩的家伙。"
    if num > 1 and (get_config('base', 'daily_max') - tlmt.get_num(uid)) < num:
            return 1, f"今天只许再冲{get_config('base', 'daily_max') - tlmt.get_num(uid)}次了哦,请节制!"
    if not flmt.check(uid):
        return 1, f'您冲的太快了,请等待{round(flmt.left_time(uid))}秒!'
    flmt.start_cd(uid)
    save_limit_data()
    return 0, ''

@sv.on_prefix('setu')
async def send_setu(bot, ev):
    uid = ev['user_id']
    gid = ev['group_id']
    is_su = hoshino.priv.check_priv(ev, hoshino.priv.SUPERUSER)
    is_admin = is_su or hoshino.priv.check_priv(ev, hoshino.priv.ADMIN)
    args = ev.message.extract_plain_text().split()

    msg = ''
    if not is_admin:
        msg = '需要群管理员权限'
    elif len(args) == 0:
        msg = 'invalid parameter'
    elif args[0] == 'set' and len(args) >= 3: #setu set module on [group]
        if is_su and len(args) >= 4 and args[3].isdigit():
            gid = int(args[3]) #指定群号仅限超级用户, 管理员只能管理本群
        key = None
        value = False
        if args[1] == 'lolicon':
            key = 'lolicon'
        elif args[1] == 'lolicon_r18':
            key = 'lolicon_r18'
        elif args[1] == 'withdraw':
            key = 'withdraw'
        elif args[1] == 'maxsize':
            key = 'maxsize'
        if args[2] == 'on' or args[2] == 'true':
            value = True
        elif args[2] == 'off' or args[2] == 'false':
            value = False
        elif args[2].isdigit():
            value = int(args[2])
        if key:
            if key == 'maxsize':
                if not is_su:
                    msg = 'maxsize 需要超级用户权限'
                elif args[2].isdigit():
                    set_config('base', 'max_size_mb', int(args[2]))
                    msg = f'图库容量上限已设为 {args[2]} MB'
                    if int(args[2]) <= 0:
                        msg += '（已停止api抓图）'
                else:
                    msg = 'invalid parameter, maxsize需要为整数MB'
            elif key == 'withdraw' and value == 10: #一键r18
                set_group_config(gid, key, value)
                set_group_config(gid, 'lolicon_r18', True)
                msg = f'{gid}已一键设置r18'
            elif key == 'withdraw' and value == 0:
                set_group_config(gid, key, value)
                set_group_config(gid, 'lolicon_r18', False)
                msg = f'{gid}已一键禁用r18'
            else:
                set_group_config(gid, key, value)
                msg = f'{gid} : {key} = {value}'
        else:
            msg = 'invalid parameter'
    elif args[0] == 'get':
        if is_su and len(args) >= 2 and args[1].isdigit():
            gid = int(args[1])
        msg = f'group {gid} :'
        msg += f'\nwithdraw : {get_group_config(gid, "withdraw")}'
        msg += f'\nlolicon : {get_group_config(gid, "lolicon")}'
        msg += f'\nlolicon_r18 : {get_group_config(gid, "lolicon_r18")}'
    elif args[0] == 'fetch':
        if get_config('lolicon', 'mode') != 2:
            msg = '当前lolicon不在mode 2, 无需抓取'
        else:
            await bot.send(ev, 'start fetch mission')
            errors = await fetch_process()
            if errors:
                msg = 'fetch 部分失败:\n' + '\n'.join(errors)
            else:
                msg = 'fetch mission complete'
    elif args[0] == 'warehouse':
        detail, total = lolicon_warehouse_state()
        limit_mb = get_config('base', 'max_size_mb')
        msg = 'warehouse:'
        for k, v in detail.items():
            msg += f'\n{k} : {v["count"]}张 / {v["bytes"]/1024/1024:.1f}MB'
        msg += f'\ntotal : {total/1024/1024:.1f}MB / 上限 {limit_mb}MB'
        msg += '\n状态: ' + ('已满, 已停止api抓图' if warehouse_full() else '未满')
    else:
        msg = 'invalid parameter'
    await bot.send(ev, msg)

@sv.on_rex(r'^不够[涩瑟色]|^再来[点张份]|^[涩瑟色]图$|^[再]?来?(\d*)?[份点张]([涩色瑟]图)')
async def send_random_setu(bot, ev):
    num = 1
    match = ev['match']
    try:
        num = int(match.group(1))
    except:
        pass
    if num > 5:
        num = 5
        await bot.send(ev, '一次不能太贪心哦！')
    uid = ev['user_id']
    gid = ev['group_id']
    result, msg = check_lmt(uid, num)
    if result != 0:
        await bot.send(ev, msg)
        return

    result_list = []
    for _ in range(num):
        msg = await get_setu(gid)
        if msg == None:
            await bot.send(ev, '无可用模块')
            return
        try:
            result_list.append(await bot.send(ev, msg))
        except:
            print('图片发送失败')
        await asyncio.sleep(1)

    if not result_list:
        await bot.send(ev, '图片发送失败, 请稍后再试')
        return
    tlmt.increase(uid, len(result_list))
    save_limit_data()

    second = get_group_config(gid, "withdraw")
    if second and second > 0:
        await asyncio.sleep(second)
        for result in result_list:
            try:
                await bot.delete_msg(self_id=ev['self_id'], message_id=result['message_id'])
            except:
                print('撤回失败')
            await asyncio.sleep(1)

@sv.on_rex(r'^搜[索]?(\d*)[份张]*(.*?)[涩瑟色]图(.*)')
async def send_search_setu(bot, ev):
    uid = ev['user_id']
    gid = ev['group_id']

    keyword = ev['match'].group(2) or ev['match'].group(3)
    if not keyword:
        await bot.send(ev, '需要提供关键字')
        return
    keyword = keyword.strip()
    num = ev['match'].group(1)
    if num:
        num = int(num.strip())
    else:
        num = 1
    result, msg = check_lmt(uid, num)
    if result != 0:
        await bot.send(ev, msg)
        return

    await bot.send(ev, '正在搜索...')
    try:
        msg_list = await search_setu(gid, keyword, num)
    except SetuApiError as e:
        await bot.send(ev, f'[CQ:reply,id={ev["message_id"]}]{e}')
        return
    except Exception:
        traceback.print_exc()
        await bot.send(ev, f'[CQ:reply,id={ev["message_id"]}]搜索失败, 请稍后重试')
        return
    if msg_list is None:
        await bot.send(ev, '无可用模块')
        return
    if len(msg_list) == 0:
        await bot.send(ev, '无结果')
        return
    result_list = []
    for msg in msg_list:
        try:
            result_list.append(await bot.send(ev, msg))
        except:
            print('图片发送失败')
        await asyncio.sleep(1)
    if not result_list:
        await bot.send(ev, f'[CQ:reply,id={ev["message_id"]}]图片发送失败, 请稍后再试')
        return
    tlmt.increase(uid, len(result_list))
    save_limit_data()
    second = get_group_config(gid, "withdraw")
    if second and second > 0:
        await asyncio.sleep(second)
        for result in result_list:
            try:
                await bot.delete_msg(self_id=ev['self_id'], message_id=result['message_id'])
            except:
                print('撤回失败')
            await asyncio.sleep(1)

@sv.scheduled_job('interval', minutes=30)
async def job():
    await fetch_process()
