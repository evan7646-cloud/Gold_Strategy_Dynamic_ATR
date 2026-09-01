"""實驗性腳本：測試 ATR / ADX 作為趨勢性過濾條件 (不影響正式回測檔案)。

【測試對象】
  ADX (Average Directional Index)：Wilder 標準演算法，衡量「趨勢強度」(不含方向)。
       經典用法為 ADX < 20 視為盤整、> 25 視為趨勢成形。MT5 內建 iADX，易於移植至 EA。
  ATR 擴張比 (atr_ratio = ATR / ATR 的 N 期均值)：衡量波動度正在擴張或收縮。
       > 1 代表波動度高於近期平均，通常伴隨行情啟動；< 1 代表波動度萎縮，常見於盤整末端。
  ATR 佔價格比 (atr_pct = ATR / close)：波動度的絕對水準，避免因金價由 2000 漲到 4400 而失真。

【比較基準】
  baseline    : 現行邏輯 close > ma30 且 close > 前一根 close
  +d2         : 現行邏輯 + 二次微分過濾 (d2 > -0.01)，前次實驗驗證有效者
  各過濾單獨使用，以及與 d2 疊加，觀察是否帶來額外增益。
"""

import numpy as np
import pandas as pd

from experiment_chop_filter import full_metrics
from experiment_derivative_filter import load_dataset, add_derivatives, simulate

DATASETS = {
    '短期(EA同網格)': 'pepperstone_xauusd_4h.csv',
    '長期(原生4H)': 'pepperstone_xauusd_4h_long.csv',
}


def wilder_smooth(series, period):
    """Wilder 平滑 (RMA)：MT5 內建 ADX/ATR 所使用的平滑方式。"""
    return series.ewm(alpha=1.0 / period, adjust=False).mean()


def add_adx(df, period=14):
    """標準 Wilder ADX，回傳 adx / plus_di / minus_di。"""
    d = df.copy()
    high, low, close = d['high'], d['low'], d['close']
    prev_close, prev_high, prev_low = close.shift(1), high.shift(1), low.shift(1)

    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    up_move = high - prev_high
    down_move = prev_low - low
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    atr_w = wilder_smooth(tr, period)
    plus_di = 100.0 * wilder_smooth(pd.Series(plus_dm, index=d.index), period) / atr_w
    minus_di = 100.0 * wilder_smooth(pd.Series(minus_dm, index=d.index), period) / atr_w
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    d['adx'] = wilder_smooth(dx.fillna(0), period)
    d['plus_di'] = plus_di
    d['minus_di'] = minus_di
    return d


def add_atr_features(df, ma_period=50):
    d = df.copy()
    d['atr_ratio'] = d['atr14_4h'] / d['atr14_4h'].rolling(ma_period).mean()  # 波動度擴張比
    d['atr_pct'] = d['atr14_4h'] / d['close']  # 波動度佔價格比
    return d


def prepare(path, n_deriv=3):
    df = add_derivatives(load_dataset(path), n=n_deriv)
    df = add_adx(df, 14)
    df = add_atr_features(df, 50)
    return df.dropna().reset_index(drop=True)


def build(df, use_d2=False, adx_min=None, atr_ratio_min=None, atr_pct_min=None, th2=0.010):
    """在現行訊號之上疊加各種過濾條件，回傳 is_long_sig 布林陣列。"""
    c = df['close'].to_numpy(); ma = df['ma30_4h'].to_numpy(); dy = df['dy_raw'].to_numpy()
    sig = (c > ma) & (dy > 0)
    if use_d2:
        sig &= df['d2'].to_numpy() > -th2
    if adx_min is not None:
        sig &= df['adx'].to_numpy() > adx_min
    if atr_ratio_min is not None:
        sig &= df['atr_ratio'].to_numpy() > atr_ratio_min
    if atr_pct_min is not None:
        sig &= df['atr_pct'].to_numpy() > atr_pct_min
    return sig


def run(df, **kw):
    s = build(df, **kw)
    allt = sorted(simulate(df, s, True) + simulate(df, s, False), key=lambda x: x['exit_date'])
    return full_metrics(df, allt)


def row(name, m, base):
    if m is None:
        return f"{name:<30s} {'無交易':>10s}"
    better = (m['calmar_ratio'] > base['calmar_ratio']) and (m['sharpe_ratio'] > base['sharpe_ratio'])
    mark = ' ★' if better else ''
    return (f"{name:<30s} {m['total_pnl']:10.2f} {m['total_trades']:6d} {m['win_rate']:6.2f}% "
            f"{m['profit_factor']:6.2f} {m['max_drawdown']:8.2f} {m['calmar_ratio']:7.2f} {m['sharpe_ratio']:7.2f}{mark}")


if __name__ == '__main__':
    for label, path in DATASETS.items():
        df = prepare(path)
        print("=" * 112)
        print(f"### {label}  ({df['timestamp'].min().date()} ~ {df['timestamp'].max().date()}, {len(df)} 根)")
        print(f"    ADX 分布: 中位數={df['adx'].median():.1f}  <20 佔 {(df['adx']<20).mean()*100:.1f}%  >25 佔 {(df['adx']>25).mean()*100:.1f}%")
        print(f"    ATR擴張比 中位數={df['atr_ratio'].median():.2f} | ATR佔價比 中位數={df['atr_pct'].median()*100:.2f}%")
        print("=" * 112)
        print(f"{'變體':<30s} {'總損益':>10s} {'筆數':>6s} {'勝率':>7s} {'PF':>6s} {'MDD':>8s} {'Calmar':>7s} {'Sharpe':>7s}")
        print("-" * 112)

        base = run(df)
        print(row('baseline (現行)', base, base))
        d2only = run(df, use_d2=True)
        print(row('+曲率 d2 (前次最佳)', d2only, base))
        print('-' * 112)

        for a in [15, 20, 25, 30]:
            print(row(f'+ADX>{a}', run(df, adx_min=a), base))
        for r in [0.9, 1.0, 1.1]:
            print(row(f'+ATR擴張比>{r}', run(df, atr_ratio_min=r), base))
        for p in [0.003, 0.004, 0.005]:
            print(row(f'+ATR佔價比>{p*100:.1f}%', run(df, atr_pct_min=p), base))
        print('-' * 112)

        for a in [15, 20, 25]:
            print(row(f'+曲率+ADX>{a}', run(df, use_d2=True, adx_min=a), base))
        for r in [0.9, 1.0, 1.1]:
            print(row(f'+曲率+ATR擴張比>{r}', run(df, use_d2=True, atr_ratio_min=r), base))
        print()
        print("★ = Calmar 與 Sharpe 同時優於 baseline")
        print()
