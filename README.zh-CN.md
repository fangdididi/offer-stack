# Offer Stack 优惠叠加精算

[English](README.md) | **中文**

一个智能体技能：当商家同时甩出优惠券、满减档位、组合价、支付立减、返现和积分时，帮你算清楚"真正想买的东西最少要付多少钱"。它会找出最省且合规的叠加方式，指出哪些券是陷阱，判断凑单值不值，并在付款前把真实结算价和计算结果对一遍。

适用于任何超市、外卖平台或网店。它只做规划，从不下单、不付款。

## 为什么需要它

优惠之间会互相影响。一张小券可能挡住一个更大的组合价；"满 60"的门槛可能按单品打折后的金额算；为了够档加购一件 9.90 的东西，可能省钱，也可能白花钱；"原价"可能上周刚被调高。这些都是组合爆炸式的算术，人和大模型都经常算错。所以 Offer Stack 让智能体负责收集信息和解释结果，让一个小脚本以"分"为单位穷举并完成所有运算，最终以结算页为准。

## 功能

- **五层模型**，按固定顺序生效：单品优惠、订单满减、运费、支付方式立减、事后价值（返现和积分）。
- **穷举搜索**：最多 12 项有效优惠和 6 件可选商品，支持同组互斥、独占券、封顶、限用件数和最低消费。
- **诚实凑单**：只有标为 `maybe`（近期反正会买）的商品才能用来凑单，而且总会单独给出"不凑单"的节省金额。
- **券体检**：给出 `USE`、`SKIP`、`TRAP`、`DEAD`、`OUT` 结论，对比面额、实际节省和机会成本。
- **价格锚点检查**：有 30 天最低价时，按最低价衡量真实折扣。
- **结算价核对**：结算页金额不一致时，指出最可能没生效的那项优惠。
- **单品实付分摊**：用于退款估算和拼单公平分账。
- 过期、未开始、渠道不符、条款未核实的优惠一律剔除并注明原因，绝不猜测。
- 单个 Python 文件，只用标准库，附 40 个测试。

## 安装

技能就是这个文件夹本身：`SKILL.md`（英文）、`SKILL.zh-CN.md`（中文）和 `scripts/stackcalc.py`。

**Claude Code**

```bash
git clone https://github.com/fangdididi/offer-stack.git ~/.claude/skills/offer-stack
```

**Codex CLI**

```bash
git clone https://github.com/fangdididi/offer-stack.git ~/.codex/skills/offer-stack
```

**Cursor**：克隆到项目的 `.cursor/skills/offer-stack`，或在项目规则里引用 `SKILL.md`。

**其他智能体**：把文件夹放到智能体能读取的位置，告诉它遇到购物优惠问题时按 `SKILL.md` 操作。脚本需要 Python 3.8 及以上。

## 用法

直接用自然语言问智能体：

> 我在 App 里买咖啡、燕麦和两瓶燕麦奶。手上有满 80 减 12、满 60 减 6、咖啡 7 折、咖啡 + 燕麦组合价 45，还有钱包立减。该怎么用？

智能体会写一份清单文件（参见 [`examples/weekly-shop.json`](examples/weekly-shop.json)），然后运行：

```bash
python3 scripts/stackcalc.py best  basket.json --top 3     # 最省的几个方案
python3 scripts/stackcalc.py audit basket.json             # 每张券的结论
python3 scripts/stackcalc.py quote basket.json --plan T60,C30,WALLET --paid 57.40   # 与结算页核对
python3 scripts/stackcalc.py shares basket.json --plan T60,C30,WALLET               # 退款 / 分账分摊
```

任何命令加 `--json` 即输出机器可读结果。结算价不一致时，`quote` 以退出码 2 结束。

## 示例

```text
$ python3 scripts/stackcalc.py audit examples/weekly-shop.json
best plan uses: C30, CB, T80, WALLET
  USE   T80: nominal 12.00, real alone 12.00, opportunity cost 0.00
  SKIP  T60: nominal 6.00, real alone 6.00, opportunity cost 2.68
  USE   C30: nominal 12.60, real alone 12.60, opportunity cost 0.00
  SKIP  PAIR: nominal 12.00, real alone 12.00, opportunity cost 0.58
  USE   WALLET: nominal 5.00, real alone 5.00, opportunity cost 0.00
  USE   CB: nominal 2.43, real alone 1.94, opportunity cost 0.00
  OUT   OLD: expired 2026-10-20
  OUT   WEB: channel app not in ['web']
```

这里总体最优方案加了可选的绿茶，够到满 80 减 12。`best` 同时会给出不凑单的方案：今天付 57.40，比原价 81.00 省 23.60。组合价本身能用，但会挡住咖啡 7 折券，所以不用。

## 清单文件速览

```json
{
  "settings": {"today": "2026-10-24", "channel": "app", "threshold_base": "after_item",
               "cashback_haircut": 0.8, "point_value": 0.01, "maybe_credit": 0.8,
               "shipping_fee": 6, "free_shipping_over": 59},
  "items":  [{"id": "coffee", "price": 42, "want": "need", "low_30d": 36}],
  "offers": [{"id": "T80", "type": "threshold", "min_spend": 80, "value": 12, "group": "store"}]
}
```

优惠类型：`bundle`（组合价）、`item_price`（单品改价）、`percent`（单品折扣）、`amount_off`（单品立减）、`threshold`（满减）、`order_percent`（整单折扣）、`payment`（支付立减）、`cashback`（返现，`percent` 按比例或 `value` 固定金额）、`points`（积分）。可选字段：`applies_to`、`slots`、`price`、`min_spend`、`cap`、`max_units`、`group`、`exclusive`、`starts`、`expires`、`channels`、`verified`。

## 文件结构

```text
offer-stack/
├── SKILL.md               # 技能说明（英文）
├── SKILL.zh-CN.md         # 技能说明（中文）
├── README.md
├── README.zh-CN.md
├── LICENSE
├── scripts/
│   └── stackcalc.py       # best / audit / quote / shares
├── examples/
│   └── weekly-shop.json
└── tests/
    └── test_stackcalc.py  # python3 -m unittest discover -s tests
```

## 许可证

MIT © fangdididi
