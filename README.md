# QL-EMAIL - 网易邮箱大师自动签到

基于 API 直调的网易邮箱大师（MailMaster）自动化脚本，支持**青龙面板定时运行** + **QQ 机器人交互控制** + **产物自动记录查询**。

> 单文件 `mail_auto.py` 入口，与 QL-DX 模式一致。

## 功能

| 功能 | 说明 |
|------|------|
| 每日签到 | 自动签到，支持补签 |
| 积分查询 | 实时查询积分余额和即将过期积分 |
| 任务领取 | 自动领取所有可领取的任务奖励 |
| 互动任务 | 小红书点赞等互动任务 |
| 功能体验 | AI总结、AI润色、邮件翻译等新功能体验 |
| 每日任务 | 查看邮件、归档、标记待办、规划计划 |
| 广告任务 | 每日3次观看广告领取积分 |
| 集赞墙 | 进度查询 |
| 礼品列表 | 查询可兑换礼品 |
| 产物记录 | 每次执行自动记录，可随时查询 |

## 配置

### 获取认证信息

1. 手机安装 MailMaster App 并登录大师号
2. 使用抓包工具（Charles/Proxyman/Stream）抓取 `dashi.163.com` 的请求
3. 提取：
   - 请求头 `mastersess`
   - 请求头 `masterfp`
   - 请求体 `tokenList` 数组
   - 请求体 `emailList` 数组

### 环境变量

```env
# 推荐方式: 一条配置
MASTER_COOKIE=mastersess:::masterfp:::M_INFO:::token1&token2:::email1@163.com

# 或分开配置
MASTER_MASTERSESS=你的mastersess
MASTER_MASTERFP=你的masterfp
MASTER_TOKENS=token1&token2
MASTER_EMAILS=email1@163.com
```

多账号用换行分隔（每行一个 MASTER_COOKIE）。

## 依赖

```
pip install requests certifi
```

## 青龙面板

定时任务命令：`task mail_auto.py`

建议定时：`30 8 * * *`（每天 8:30）

## QQ 机器人

配合 [QL-Bot](https://github.com/Hayfan-wu/QL-Bot) 使用，自动扫描 `/opt/QL-EMAIL/bot_plugins/` 加载插件。

| 命令 | 功能 |
|------|------|
| `大师菜单` | 帮助菜单 |
| `大师登录` | 多轮引导设置认证信息，自动提交青龙 |
| `大师配置` | 直接配置 MASTER_COOKIE 字符串 |
| `大师状态` | 查看配置状态 |
| `大师查询` | 查看最近一次执行结果 |
| `大师执行` | 执行全部任务 |
| `大师签到` | 仅执行签到 |
| `大师开启/关闭 签到/任务/广告` | 功能开关 |

## 项目结构

```
QL-EMAIL/
├── mail_auto.py           # 唯一入口（青龙定时任务用这个）
├── .env                   # 环境变量（git不追踪）
├── .env.example           # 环境变量模板
├── result.json            # 产物记录（自动生成）
├── bot_plugins/           # QQ机器人插件
│   └── mail_plugin.py     # 交互逻辑
└── requirements.txt       # Python 依赖
```

## 注意事项

- 大师号的 `mastersess` 有有效期，过期后需重新抓包
- 部分任务（集赞墙、标记待办、归档邮件）需 App 内操作，无法自动完成
- 获取方式：抓包 MailMaster App 请求 `dashi.163.com`
