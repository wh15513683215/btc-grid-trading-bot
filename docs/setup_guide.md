# 配置指南：加密货币网格交易系统

> 适用版本：Python 3.11 + Binance (Testnet / 实盘)

---

## 目录

1. [获取 Binance API Key](#1-获取-binance-api-key)
2. [配置 .env 文件](#2-配置-env-文件)
3. [调整 config.yaml](#3-调整-configyaml)
4. [验证连接](#4-验证连接)
5. [切换实盘模式](#5-切换实盘模式)
6. [常见问题](#6-常见问题)

---

## 1. 获取 Binance API Key

### 1-A：Testnet（推荐先用）

1. 浏览器打开 **https://testnet.binance.vision/**
2. 点击右上角 **"Log In with GitHub"** 授权登录
3. 登录后点击 **"Generate HMAC_SHA256 Key"**
4. 填写一个备注名（如 `grid-bot`），点击 **Generate**
5. 页面会显示：
   - `API Key`：以 `vm...` 开头的长字符串
   - `Secret Key`：**只显示一次**，立刻复制保存

> Testnet 账户自动充值测试资金，不涉及真实资产，适合调试。

### 1-B：实盘（Binance 正式账号）

1. 登录 **https://www.binance.com** → 右上角头像 → **API 管理**
2. 点击 **创建 API** → 选择 **"系统生成"** → 填写标签名
3. 完成邮箱/手机/谷歌验证
4. 在权限设置中：
   - **勾选** "启用现货及杠杆交易"
   - **不要勾选** 提币权限（安全原则）
   - IP 限制：建议绑定你的服务器/本机 IP（可选但推荐）
5. 复制 `API Key` 与 `Secret Key`（Secret 只显示一次）

---

## 2. 配置 .env 文件

在项目根目录创建 `.env` 文件（已有 `.env.example` 作为模板）：

```bash
cp .env.example .env
```

用编辑器打开 `.env`，填入你的密钥：

```dotenv
BINANCE_API_KEY=粘贴你的_API_Key_在这里
BINANCE_API_SECRET=粘贴你的_Secret_Key_在这里
```

**注意事项：**
- `.env` 已在 `.gitignore` 中（请确认），**绝对不能提交到 Git**
- 密钥两侧不要加引号，不要有多余空格
- 如果文件不存在会导致启动时 `KeyError`

---

## 3. 调整 config.yaml

文件路径：`config/config.yaml`

### 3-A：Exchange 区块

```yaml
exchange:
  name: binance
  api_key: "${BINANCE_API_KEY}"      # 保持不变，从 .env 读取
  api_secret: "${BINANCE_API_SECRET}" # 保持不变，从 .env 读取
  testnet: true                       # Testnet 用 true；实盘改为 false
  rate_limit_ms: 200                  # 请求间隔，建议 ≥ 200ms
```

### 3-B：Grid 策略区块

根据你要交易的标的和行情调整：

```yaml
grid:
  symbol: "BTC/USDT"          # 交易对，如 ETH/USDT
  upper_price: 70000.0         # 网格上边界（当前价格以上 10-20%）
  lower_price: 60000.0         # 网格下边界（当前价格以下 10-20%）
  grid_count: 20               # 网格数量（建议 10-50）
  investment_amount: 10000.0   # 投入 USDT 总金额
  grid_type: arithmetic        # arithmetic（等差）或 geometric（等比）
  take_profit_price: null      # 选填：超过此价格清仓
  stop_loss_price: null        # 选填：低于此价格清仓
```

**参数建议：**

| 参数 | 保守 | 激进 |
|------|------|------|
| `grid_count` | 10 | 50 |
| 价格区间宽度 | 当前价 ±5% | 当前价 ±20% |
| `investment_amount` | 1000 USDT | 随意 |
| `grid_type` | arithmetic | geometric |

### 3-C：Risk 风控区块

```yaml
risk:
  max_position_pct: 0.95    # 最大仓位占比（95%），留 5% 防止余额不足
  stop_loss_pct: 0.08       # 单次价格跌幅止损线（8%）
  daily_loss_limit: 500.0   # 每日最大亏损 USDT（超出自动停机）
  max_open_orders: 50       # 最大挂单数，不超过 grid_count
  max_drawdown_pct: 0.20    # 最大回撤 20% 触发停机
```

---

## 4. 验证连接

### 4-A：运行连接测试

```bash
python3.11 -m pytest tests/ -v -k "exchange"
```

### 4-B：快速手动验证

```bash
python3.11 -c "
import asyncio, os
from dotenv import load_dotenv
load_dotenv()
from src.exchange.binance_client import BinanceClient
from src.core.config import load_config

config = load_config('config/config.yaml')

async def test():
    client = BinanceClient(config.exchange)
    await client.connect()
    balance = await client.fetch_balance()
    print('连接成功，USDT 余额:', balance.get('USDT', {}).get('free', 0))
    await client.disconnect()

asyncio.run(test())
"
```

成功输出示例：
```
连接成功，USDT 余额: 10000.0
```

### 4-C：运行回测验证策略

```bash
python3.11 -m src.cli.main backtest \
  --symbol BTC/USDT \
  --start 2024-01-01 \
  --end 2024-12-31
```

---

## 5. 切换实盘模式

确认以下所有检查项后再切换：

- [ ] 回测结果满意（夏普率 > 1，最大回撤 < 20%）
- [ ] Testnet 试运行 ≥ 48 小时无异常
- [ ] `.env` 已替换为正式账号的 API Key
- [ ] `config.yaml` 中 `testnet: false`
- [ ] 风控参数已根据实际资金调整
- [ ] 日志目录 `logs/` 可写

切换命令：

```bash
# 先用 dry-run 模式（不真实下单）验证
python3.11 -m src.cli.main trade --dry-run

# 确认无误后去掉 --dry-run 正式启动
python3.11 -m src.cli.main trade
```

---

## 6. 常见问题

| 错误信息 | 原因 | 解决方案 |
|----------|------|----------|
| `AuthenticationError` | API Key 错误或 Secret 有空格 | 重新检查 `.env`，确认无多余字符 |
| `Invalid API-key, IP, or permissions` | IP 未绑定或权限不足 | Binance 后台检查 IP 白名单和权限 |
| `Timestamp for this request is outside` | 本机时间与 Binance 服务器偏差 >1s | 同步系统时间：`sudo sntp -sS time.apple.com` |
| `InsufficientFunds` | 账户余额不足 | Testnet 刷新余额；实盘充值 |
| `KeyError: BINANCE_API_KEY` | `.env` 文件未创建或未加载 | 确认根目录存在 `.env` 且 `load_dotenv()` 被调用 |
| `RateLimitExceeded` | 请求频率过高 | 增大 `rate_limit_ms`（如改为 500） |

---

*最后更新：2026-04-10*
