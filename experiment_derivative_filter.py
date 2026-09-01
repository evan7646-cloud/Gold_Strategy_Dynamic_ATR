"""實驗性腳本：以 30MA 的一次/二次微分做趨勢性過濾 (不影響正式回測檔案)。

【動機】
現行訊號僅判斷 close 是否站上 30MA，均線走平的盤整期一樣會反覆觸發多空翻轉。
本實驗改以均線本身的「微分」描述趨勢狀態：

  一次微分 d1 = (ma30[i] - ma30[i-n]) / n / ATR   → 斜率(速度)，衡量趨勢方向與強度
  二次微分 d2 = (d1[i] - d1[i-n]) / n             → 曲率(加速度)，衡量趨勢加速或鈍化

兩者皆以 ATR 正規化，避免金價由 2000 漲到 4400 後門檻失去意義。

【測試的訊號變體】
  baseline : close > ma30 且 close > 前一根 close                 (現行邏輯)
  d1       : 僅看斜率，|d1| 需超過門檻才視為有效趨勢，否則維持前一狀態
  d1_d2    : 斜率方向 + 二次微分需同向 (要求趨勢處於加速或至少未明顯鈍化)
  base_d1  : 現行邏輯之上，額外要求斜率同向且達門檻 (作為純過濾器使用)

所有微分皆只用到第 i 根與更早的資料，於該根收盤時已可得知，無未來函數。
"""

import numpy as np
import pandas as pd

from cost_model import trade_cost_points, DEFAULT_SCENARIO
from daily_align import attach_daily_features
from ea_sizing import quantize_units
from experiment_chop_filter import calculate_atr, full_metrics

DATASETS = {
    '短期(EA同網格)': 'pepperstone_xauusd_4h.csv',
    '長期(原生4H)': 'pepperstone_xauusd_4h_long.csv',
}


def load_dataset(gold_4h_file):
    gold_d = pd.read_csv('pepperstone_xauusd_daily.csv').rename(
        columns={'close': 'gold_close', 'open': 'gold_open', 'high': 'gold_high', 'low': 'gold_low'})
    dxy_d = pd.read_csv('pepperstone_usdx_daily.csv').rename(
        columns={'close': 'dxy_close', 'open': 'dxy_open', 'high': 'dxy_high', 'low': 'dxy_low'})
    gold_4h = pd.read_csv(gold_4h_file)

    df_daily = pd.merge(gold_d, dxy_d, on='timestamp', how='left').sort_values('timestamp').reset_index(drop=True)
    df_daily['timestamp'] = pd.to_datetime(df_daily['timestamp'])
    dxy_cols = ['dxy_close', 'dxy_open', 'dxy_high', 'dxy_low']
    df_daily[dxy_cols] = df_daily[dxy_cols].ffill()
    df_daily = df_daily.dropna(subset=['dxy_close']).reset_index(drop=True)

    for n in [1, 5, 10]:
        df_daily[f'alpha_{n}'] = df_daily['gold_close'].pct_change(n) - df_daily['dxy_close'].pct_change(n)
    for w in [20, 50, 60]:
        df_daily[f'ma{w}'] = df_daily['gold_close'].rolling(w).mean()
    df_daily['daily_close_avail'] = df_daily['gold_close']
    df_daily['daily_ma50_avail'] = df_daily['ma50']
    df_daily['daily_ma20_avail'] = df_daily['ma20']
    df_daily['daily_ma60_avail'] = df_daily['ma60']
    for n in [1, 5, 10]:
        df_daily[f'daily_alpha{n}_avail'] = df_daily[f'alpha_{n}']

    gold_4h['timestamp'] = pd.to_datetime(gold_4h['timestamp'])
    gold_4h = gold_4h.sort_values('timestamp').reset_index(drop=True)

    df = attach_daily_features(gold_4h, df_daily, [
        'daily_close_avail', 'daily_ma50_avail', 'daily_ma20_avail', 'daily_ma60_avail',
        'daily_alpha1_avail', 'daily_alpha5_avail', 'daily_alpha10_avail'])

    df['ma30_4h'] = df['close'].rolling(30).mean()
    df['atr14_4h'] = calculate_atr(df, 14)
    df['dy_raw'] = df['close'].diff()
    return df.dropna().reset_index(drop=True)


def add_derivatives(df, n=3):
    """計算以 ATR 正規化的一次/二次微分。n 為差分跨度 (平滑用，避免逐根雜訊)。"""
    d = df.copy()
    # 一次微分：每根平均斜率，除以 ATR 正規化
    d['d1'] = d['ma30_4h'].diff(n) / n / d['atr14_4h']
    # 二次微分：一次微分的變化率
    d['d2'] = d['d1'].diff(n) / n
    return d


def build_signal(df, variant, th1=0.0, th2=0.0):
    """回傳 is_long_sig 布林陣列。所有變體在『中性區』皆維持前一有效狀態 (hysteresis)。"""
    close = df['close'].to_numpy()
    ma30 = df['ma30_4h'].to_numpy()
    dy = df['dy_raw'].to_numpy()
    d1 = df['d1'].to_numpy()
    d2 = df['d2'].to_numpy()
    n = len(df)

    if variant == 'baseline':
        return (close > ma30) & (dy > 0)

    if variant == 'base_d1':
        # 現行邏輯之上再加斜率過濾：斜率須同向且達門檻，否則不算有效多頭訊號
        return (close > ma30) & (dy > 0) & (d1 > th1)

    # 以下變體採三態 + hysteresis：1=多, -1=空, 0=中性(維持前值)
    if variant == 'd1':
        raw = np.where(d1 > th1, 1, np.where(d1 < -th1, -1, 0))
    elif variant == 'd1_d2':
        # 需斜率達門檻，且二次微分未反向超過 th2 (即趨勢未明顯鈍化)
        raw = np.where((d1 > th1) & (d2 > -th2), 1,
              np.where((d1 < -th1) & (d2 < th2), -1, 0))
    else:
        raise ValueError(variant)

    state = raw.copy()
    for i in range(1, n):
        if state[i] == 0:
            state[i] = state[i - 1]
    return state == 1


def simulate(df, is_long_sig_arr, is_long_only, baseline_atr=16.0, alpha_floor=1.0, cost_scenario=DEFAULT_SCENARIO):
    """與正式回測相同的部位管理引擎，訊號由外部傳入以便比較不同變體。"""
    n = len(df)
    active_positions = []
    completed_trades = []

    for i in range(n - 1):
        t_close = df.loc[i, 'close']; t_high = df.loc[i, 'high']; t_low = df.loc[i, 'low']; t_atr = df.loc[i, 'atr14_4h']
        t_prev_high = df.loc[i-1, 'high'] if i > 0 else t_high
        t_prev_low = df.loc[i-1, 'low'] if i > 0 else t_low
        dy_close = df.loc[i, 'daily_close_avail']; dy_ma50 = df.loc[i, 'daily_ma50_avail']
        dy_ma20 = df.loc[i, 'daily_ma20_avail']; dy_ma60 = df.loc[i, 'daily_ma60_avail']
        dy_a1 = df.loc[i, 'daily_alpha1_avail']; dy_a5 = df.loc[i, 'daily_alpha5_avail']; dy_a10 = df.loc[i, 'daily_alpha10_avail']
        is_long_sig = bool(is_long_sig_arr[i])
        next_open = df.loc[i+1, 'open']; next_stamp = str(df.loc[i+1, 'timestamp'])
        dy_pyr_long = (dy_a1 > 0) and (dy_a5 > 0) and (dy_a10 > 0) and (dy_ma20 > dy_ma60)
        dy_pyr_short = (dy_a1 < 0) and (dy_a5 < 0) and (dy_a10 < 0) and (dy_ma20 < dy_ma60)
        new_active = []

        for p in active_positions:
            w = (t_low - p['entry_price']) * p['units'] if is_long_only else (p['entry_price'] - t_high) * p['units']
            p['mae'] = min(p.get('mae', 0.0), w)

        def close_all(reason, positions):
            for p in positions:
                hd = (pd.to_datetime(next_stamp).date() - pd.to_datetime(p['entry_date']).date()).days
                raw = (next_open - p['entry_price']) if is_long_only else (p['entry_price'] - next_open)
                cost = trade_cost_points(is_long_only, hd, reason, t_atr, cost_scenario)
                completed_trades.append({
                    'type': 'Long' if is_long_only else 'Short', 'is_pyramid': p['is_pyramid'], 'units': p['units'],
                    'entry_date': p['entry_date'], 'exit_date': next_stamp, 'entry_price': p['entry_price'],
                    'exit_price': next_open, 'pnl_points': round((raw - cost) * p['units'], 2),
                    'mae_points': round(p.get('mae', 0.0), 2), 'exit_reason': reason})

        if not active_positions:
            regime_ok = (dy_close > dy_ma50) if is_long_only else (dy_close < dy_ma50)
            sig_ok = is_long_sig if is_long_only else (not is_long_sig)
            if regime_ok and sig_ok:
                stop = (min(t_low, t_prev_low) - t_atr) if is_long_only else (max(t_high, t_prev_high) + t_atr)
                active_positions.append({'is_pyramid': False, 'units': 1.0, 'entry_date': next_stamp,
                                         'entry_price': next_open, 'stop_price': stop, 'mae': 0.0})
            continue

        main_pos = [p for p in active_positions if not p['is_pyramid']][0]
        pyr_pos = [p for p in active_positions if p['is_pyramid']]
        stop_hit = (t_close < main_pos['stop_price']) if is_long_only else (t_close > main_pos['stop_price'])
        sig_lost = (not is_long_sig) if is_long_only else is_long_sig

        if stop_hit or sig_lost:
            close_all("Stop Loss Exit" if stop_hit else "Signal Exit", active_positions)
            active_positions = []
            continue

        broke = (t_close > t_prev_high) if is_long_only else (t_close < t_prev_low)
        new_stop = (min(t_low, t_prev_low) - t_atr) if is_long_only else (max(t_high, t_prev_high) + t_atr)
        if broke:
            main_pos['stop_price'] = new_stop
        new_active.append(main_pos)

        if pyr_pos:
            p = pyr_pos[0]
            p_hit = (t_close < p['stop_price']) if is_long_only else (t_close > p['stop_price'])
            if p_hit:
                close_all('Pyramid Stop Loss', [p])
            else:
                if broke:
                    p['stop_price'] = new_stop
                new_active.append(p)
        else:
            regime_ok = (dy_close > dy_ma50) if is_long_only else (dy_close < dy_ma50)
            pyr_ok = dy_pyr_long if is_long_only else dy_pyr_short
            if regime_ok and pyr_ok:
                ratio = baseline_atr / max(t_atr, 4.0) if pd.notna(t_atr) and t_atr > 0 else 1.0
                strong = (dy_a10 > 0.03) if is_long_only else (dy_a10 < -0.03)
                u = min(2.5, max(0.5, (2.0 if strong else 1.0) * ratio))
                floor_hit = (dy_a10 > 0.04) if is_long_only else (dy_a10 < -0.04)
                if floor_hit and u < alpha_floor:
                    u = alpha_floor
                new_active.append({'is_pyramid': True, 'units': quantize_units(u), 'entry_date': next_stamp,
                                   'entry_price': next_open, 'stop_price': new_stop, 'mae': 0.0})
        active_positions = new_active

    return completed_trades


def run_variant(df, variant, th1=0.0, th2=0.0, cost_scenario=DEFAULT_SCENARIO):
    sig = build_signal(df, variant, th1, th2)
    tl = simulate(df, sig, True, cost_scenario=cost_scenario)
    ts = simulate(df, sig, False, cost_scenario=cost_scenario)
    allt = sorted(tl + ts, key=lambda x: x['exit_date'])
    return full_metrics(df, allt), allt


if __name__ == '__main__':
    for label, path in DATASETS.items():
        df = add_derivatives(load_dataset(path), n=3)
        print("=" * 108)
        print(f"### {label}  ({df['timestamp'].min().date()} ~ {df['timestamp'].max().date()}, {len(df)} 根)")
        print("=" * 108)
        print(f"{'變體':<22s} {'總損益':>10s} {'筆數':>6s} {'勝率':>7s} {'PF':>6s} {'MDD':>8s} {'Calmar':>7s} {'Sharpe':>7s} {'浮動回撤':>9s}")
        print("-" * 108)

        rows = [('baseline (現行)', 'baseline', 0, 0)]
        for t1 in [0.02, 0.05, 0.08, 0.12]:
            rows.append((f'd1 斜率>{t1}', 'd1', t1, 0))
        for t1 in [0.05, 0.08]:
            for t2 in [0.01, 0.03]:
                rows.append((f'd1>{t1}+d2>-{t2}', 'd1_d2', t1, t2))
        for t1 in [0.02, 0.05, 0.08]:
            rows.append((f'現行+斜率>{t1}', 'base_d1', t1, 0))

        for name, variant, t1, t2 in rows:
            m, _ = run_variant(df, variant, t1, t2)
            if m is None:
                print(f"{name:<22s} {'無交易':>10s}")
                continue
            print(f"{name:<22s} {m['total_pnl']:10.2f} {m['total_trades']:6d} {m['win_rate']:6.2f}% "
                  f"{m['profit_factor']:6.2f} {m['max_drawdown']:8.2f} {m['calmar_ratio']:7.2f} "
                  f"{m['sharpe_ratio']:7.2f} {m['floating_drawdown']:9.2f}")
        print()
