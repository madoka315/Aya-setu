# Aya-setu

基于HoshinoBot v2的涩图插件, 从 [lolicon.app](https://lolicon.app/) 获取图片.

本项目地址 https://github.com/madoka315/Aya-setu

本插件基于 https://github.com/zyujs/setu_mix 修改: 移除了已失效的 acggov(acgmx) 图源及排行榜功能、卡片涩图功能和 apikey 配置, 新增了图库容量上限与限流持久化.

## 注意事项

- 本插件图片存放位置为 `RES_DIR/setu_mix` , 使用前请保证HoshinoBot的 `RES_DIR` 已经正确配置.
- 刚开始使用插件时本地仓库为空, 会导致无法发送随机图片, 可以在安装配置完毕后使用 `setu fetch` 命令手动抓取一批图片.
- `lolicon` / `lolicon_r18` 两个图库目录共享一个容量上限( `max_size_mb` , 默认500MB). 图库达到上限后进入滚动缓存: 抓图前按最旧优先淘汰旧图腾出空间, 本地发送不受影响. 可用 `setu set maxsize 数值` 调整, 设为0表示完全停止抓图(不会清空现有图库).
- 每日次数/冷却限流数据持久化在插件目录的 `limit_data.json` , 重启不丢失; 每日计数每天凌晨5点(北京时间)自动清零.

## 安装方法

1. 在HoshinoBot的插件目录modules下clone本项目
1. 将本插件目录下的配置文件模板 `config.template.json` 复制为 `config.json` , 按需修改(无需apikey)
1. 在 `config/__bot__.py`的模块列表里加入 `setu_mix`
1. 重启HoshinoBot

## 配置说明

- `base.daily_max` : 每人每日获取上限
- `base.freq_limit` : 每人操作冷却秒数
- `base.max_size_mb` : 图库容量上限(MB), lolicon与r18共享, 达到(>=)后停止api抓图; 0表示停止抓图
- `lolicon.mode` : 0=关闭, 1=在线(不使用本地仓库), 2=在线(使用本地仓库), 3=离线(仅使用本地仓库)
- `lolicon.r18` : 定时抓图时是否同时抓取r18图库
- `lolicon.use_thumb` : 是否使用压缩图(size1200)
- `lolicon.pixiv_direct` : 是否直连pixiv下载(需网络条件), 否则使用api返回的代理地址
- `lolicon.pixiv_proxy` : 直连pixiv时使用的代理

## 指令说明

- `涩图` : 随机获取1张图片
- `来n张涩图` : 随机获取n张图片(单次最多5张)
- `搜涩图 keyword` : 搜索指定关键字的图片
- `搜n张涩图 keyword` : 搜索n张指定关键字的图片

### 以下指令群管理员及以上可用(群主同样算管理员, 仅限群聊; 超级用户可跨群操作)

- `setu set 模块 设置值 [群号]` : 修改本群的设置(超级用户可用[群号]指定其他群), 以下为设置项 - 取值 - 说明:
  - `lolicon` : `on / off` 是否开启lolicon图源
  - `lolicon_r18` : `on / off` 是否开启r18图源
  - `withdraw` : `n` 发出的图片在n秒后撤回,设置为0表示不撤回. 如果撤回功能异常, 请关闭bot宿主程序的分片发送功能. 另外本部署有一个约定: `setu set withdraw 10` 会同时开启r18图源(一键R18), `setu set withdraw 0` 会同时关闭r18图源
  - `maxsize` : `n` 全局图库容量上限(MB), 写入config.json持久化. **仅超级用户可用**(影响全局存储)
- `setu get [群号]` : 查看本群或指定群的图源开启状态
- `setu fetch` :  手动从api拉取一批图片存入本地仓库(插件每半小时会自动拉取一次; 图库已满时不再抓取)
- `setu warehouse` : 查询本地仓库图片数量、容量与上限

## 开源

本插件以AGPL-v3协议开源
