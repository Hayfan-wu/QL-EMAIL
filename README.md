# QL-EMAIL - 网易邮箱大师自动签到

基于 API 直调的网易邮箱大师（MailMaster）自动化脚本，支持**青龙面板定时运行** + **QQ 机器人交互控制** + **产物自动记录查询**。

> 单文件 `mail_auto.py` 入口，与 QL-DX 模式一致。  
> 用户**只需配置青龙面板三项参数**，其余由 QQ 机器人自动完成。

## 功能

| 功能 | 说明 |
|------|------|
| 手机号+验证码登录 | QQ机器人交互式登录，自动获取所有配置 |
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

## 快速开始

### 1. 部署到服务器

```bash
cd /opt
git clone https://github.com/Hayfan-wu/QL-EMAIL.git
cd QL-EMAIL
cp .env.example .env
```

### 2. 配置青龙面板参数

编辑 `.env` 文件，只需填写三项：

```env
QL_URL=http://127.0.0.1:5700
QL_CLIENT_ID=你的ClientID
QL_CLIENT_SECRET=你的ClientSecret
```

### 3. 通过 QQ 机器人登录

在 QQ 群发送：

```
大师登录
```

然后按提示输入手机号 → 接收验证码 → 输入验证码 → 自动完成所有配置。

**整个过程自动完成：**
- 发送短信验证码
- 验证码登录获取 mastersess / masterfp
- 自动提取 tokenList / emailList
- 保存配置到 .env
- 自动提交到青龙面板环境变量

## QQ 机器人命令

| 命令 | 功能 |
|------|------|
| `大师登录` | 手机号+验证码登录，自动获取所有配置 |
| `大师状态` | 查看配置状态和有效性 |
| `大师查询` | 查看最近一次执行结果 |
| `大师执行` | 执行全部任务 |
| `大师签到` | 仅执行签到 |
| `大师开启/关闭 签到/任务/广告` | 功能开关 |
| `大师配置 <COOKIE>` | 手动设置 MASTER_COOKIE（备选方案） |
| `签到` / `积分` | 快捷命令 |

## 青龙面板

定时任务命令：`task mail_auto.py`

建议定时：`30 8 * * *`（每天 8:30）

## 项目结构

```
QL-EMAIL/
├── mail_auto.py           # 唯一入口（青龙定时任务用这个）
├── login_api.py           # 登录API模块（短信验证码登录+自动反推配置）
├── .env                   # 环境变量（git不追踪）
├── .env.example           # 环境变量模板
├── result.json            # 产物记录（自动生成）
├── bot_plugins/           # QQ机器人插件
│   ├── __init__.py         # 插件包初始化
│   └── mail_plugin.py     # 交互逻辑（登录+命令）
└── requirements.txt       # Python 依赖
```

## 登录API端点说明

默认使用网易通行证 Web 登录接口。如果登录失败，说明需要抓包获取 MailMaster App 的实际登录端点。

抓包步骤：
1. 手机安装抓包工具（Stream / Proxyman / Charles）
2. 打开 MailMaster App，进行手机号+验证码登录
3. 抓包分析登录流程中的网络请求
4. 在 `.env` 中覆盖端点：

```env
MASTER_SEND_SMS_URL=https://实际发送验证码端点
MASTER_VERIFY_LOGIN_URL=https://实际验证登录端点
```

## 依赖

```
pip install requests certifi
```

## 注意事项

- 大师号的 `mastersess` 有有效期，过期后需重新登录
- 部分任务（集赞墙、标记待办、归档邮件）需 App 内操作，无法自动完成
- 用户只需配置 `QL_CLIENT_ID` 和 `QL_CLIENT_SECRET`，其余自动管理
