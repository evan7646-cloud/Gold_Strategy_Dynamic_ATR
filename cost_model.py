"""Pepperstone Razor 帳戶交易成本模型 (共用於 gold_adaptive_strategy.py 與 run_4yr_backtest.py)。

點差與佣金數值來源: Pepperstone 官網公告
  https://pepperstone.com/en/ways-to-trade/pricing/
  - Razor 帳戶 XAUUSD 原始點差「從 0.08 點起」
  - Razor 帳戶佣金「每手單邊 $3.50」→ 來回(開倉+平倉)= $7.00/lot
  - 換算為點數 (1 lot = 100 oz): $7.00 / 100 = 0.07 點/來回 (以 1.0 units 為基準)

隔夜利息 (swap) 數值來源: 無官方公告數值。
  Pepperstone 官網 (同上連結) 明確聲明：
  "You can find our latest swap rates on our trading platforms.
   These are indicative rates and are subject to change based upon market volatility."
  → 官方不提供固定隔夜利息表，只能在交易平台即時查詢，且會隨市場波動調整。
  以下 swap_long / swap_short 為「保守估計區間」，非 Pepperstone 官方公告數值，
  僅用於情境敏感度測試 (best / typical / stress)。多單與空單皆視為成本 (負值)，
  不假設空單能穩定賺取正隔夜利息（舊版程式曾假設空單 +0.27/日為收入，過於樂觀，此處移除該假設）。

停損滑價 (slippage) 說明:
  本回測以「4H K棒收盤判斷訊號、下一根開盤價成交」的模型本身已隱含跨棒跳空風險
  (next_open 取自真實歷史資料，已包含真實跳空)，但無法反映「棒內價格瞬間穿越停損價」
  時，真實 MT5 停損單可能提前觸發、以更差價格成交的滑價。此處以當下 ATR 的固定比例
  做保守滑價估計，同樣非官方數值，僅供情境測試。
"""

COST_SCENARIOS = {
    'razor_best': {
        'spread': 0.08,        # Pepperstone 官網公告 Razor 原始點差下限
        'commission_rt': 0.07,  # $3.50/lot/邊 來回換算
        'swap_long': -0.30,     # 保守估計 (非官方)
        'swap_short': -0.05,    # 保守估計 (非官方)
    },
    'razor_typical': {
        'spread': 0.15,
        'commission_rt': 0.07,
        'swap_long': -0.50,
        'swap_short': -0.15,
    },
    'razor_stress': {
        'spread': 0.60,         # 新聞行情/低流動性時段點差顯著放大
        'commission_rt': 0.07,
        'swap_long': -0.70,
        'swap_short': -0.30,
    },
}

SLIPPAGE_ATR_FACTOR = {
    'razor_best': 0.02,
    'razor_typical': 0.05,
    'razor_stress': 0.15,
}

STOP_EXIT_REASONS = ('Stop Loss Exit', 'Pyramid Stop Loss')

DEFAULT_SCENARIO = 'razor_typical'


def trade_cost_points(is_long, holding_days, exit_reason, atr, scenario=DEFAULT_SCENARIO):
    """回傳單一交易應從價差損益中扣除的總成本 (正值), 單位: 點/1.0 units。

    包含：點差 + 來回佣金 + 持倉天數 x 隔夜利息 + (停損出場時)ATR比例滑價。
    """
    c = COST_SCENARIOS[scenario]
    swap_rate = c['swap_long'] if is_long else c['swap_short']  # 負值 = 成本
    cost = c['spread'] + c['commission_rt'] + (-swap_rate) * max(holding_days, 0)
    if exit_reason in STOP_EXIT_REASONS:
        atr_val = atr if (atr is not None and atr == atr) else 0.0  # atr == atr 排除 NaN
        cost += SLIPPAGE_ATR_FACTOR[scenario] * atr_val
    return cost
