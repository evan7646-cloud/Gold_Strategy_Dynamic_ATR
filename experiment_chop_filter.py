"""實驗性腳本：測試「盤整緩衝濾網」對策略績效的影響 (不影響正式回測檔案)。

問題背景：目前已平倉回撤在 2026-07-20 (2.1年版) / 2026-06-29 (4年版) 之後
明顯放大，追查交易明細發現該段期間絕大多數是 Signal Exit (訊號反轉出場)，
代表金價在 4H 30MA 附近反覆打結，多空訊號頻繁翻轉造成連續小額虧損。

測試方法：原本訊號為 close > ma30 (無緩衝)。改為要求收盤價偏離 30MA
至少 buffer_mult * ATR，才視為有效多頭/空頭訊號；價格停留在均線附近的
「死區」內時，既有部位維持不動 (仍受停損保護)，不因訊號模糊而被迫出場，
也不會有新單進場。buffer_mult=0 等同原始行為，作為對照組。
"""

import pandas as pd
import numpy as np
from cost_model import trade_cost_points, DEFAULT_SCENARIO
from daily_align import attach_daily_features
from ea_sizing import quantize_units


def calculate_atr(df, period=14):
    high, low, close_prev = df['high'], df['low'], df['close'].shift(1)
    tr = pd.concat([high - low, (high - close_prev).abs(), (low - close_prev).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def load_dataset():
    gold_d = pd.read_csv('pepperstone_xauusd_daily.csv').rename(columns={'close': 'gold_close', 'open': 'gold_open', 'high': 'gold_high', 'low': 'gold_low'})
    dxy_d = pd.read_csv('pepperstone_usdx_daily.csv').rename(columns={'close': 'dxy_close', 'open': 'dxy_open', 'high': 'dxy_high', 'low': 'dxy_low'})
    gold_4h = pd.read_csv('pepperstone_xauusd_4h_long.csv')

    df_daily = pd.merge(gold_d, dxy_d, on='timestamp', how='left').sort_values('timestamp').reset_index(drop=True)
    df_daily['timestamp'] = pd.to_datetime(df_daily['timestamp'])
    dxy_cols = ['dxy_close', 'dxy_open', 'dxy_high', 'dxy_low']
    df_daily[dxy_cols] = df_daily[dxy_cols].ffill()
    df_daily = df_daily.dropna(subset=['dxy_close']).reset_index(drop=True)

    for n in [1, 5, 10]:
        df_daily[f'gold_ret_{n}'] = df_daily['gold_close'].pct_change(n)
        df_daily[f'dxy_ret_{n}'] = df_daily['dxy_close'].pct_change(n)
        df_daily[f'alpha_{n}'] = df_daily[f'gold_ret_{n}'] - df_daily[f'dxy_ret_{n}']
    df_daily['ma20'] = df_daily['gold_close'].rolling(20).mean()
    df_daily['ma50'] = df_daily['gold_close'].rolling(50).mean()
    df_daily['ma60'] = df_daily['gold_close'].rolling(60).mean()
    df_daily['daily_close_avail'] = df_daily['gold_close']
    df_daily['daily_ma50_avail'] = df_daily['ma50']
    df_daily['daily_ma20_avail'] = df_daily['ma20']
    df_daily['daily_ma60_avail'] = df_daily['ma60']
    df_daily['daily_alpha1_avail'] = df_daily['alpha_1']
    df_daily['daily_alpha5_avail'] = df_daily['alpha_5']
    df_daily['daily_alpha10_avail'] = df_daily['alpha_10']

    gold_4h['timestamp'] = pd.to_datetime(gold_4h['timestamp'])
    gold_4h = gold_4h.sort_values('timestamp').reset_index(drop=True)

    df = attach_daily_features(gold_4h, df_daily, [
        'daily_close_avail', 'daily_ma50_avail', 'daily_ma20_avail', 'daily_ma60_avail',
        'daily_alpha1_avail', 'daily_alpha5_avail', 'daily_alpha10_avail'
    ])
    df['ma30_4h'] = df['close'].rolling(30).mean()
    df['atr14_4h'] = calculate_atr(df, 14)
    df['dy_raw'] = df['close'].diff()
    df = df.dropna().reset_index(drop=True)
    return df


def simulate(df, buffer_mult, is_long_only, baseline_atr=16.0, alpha_floor=1.0, cost_scenario=DEFAULT_SCENARIO):
    """buffer_mult=0 時完全等同原始訊號 (close > ma30 視為多頭，反之視為空頭)。
    buffer_mult>0 時加入死區：|close - ma30| < buffer_mult*ATR 時訊號視為「維持原狀」，
    既有部位不因訊號模糊而出場，也不會新開倉。"""
    n = len(df)
    active_positions = []
    completed_trades = []
    # 逐根計算「離散化」多空狀態：1=多頭有效訊號, -1=空頭有效訊號, 0=死區(維持前一狀態)
    raw_state = np.where(df['close'] > df['ma30_4h'] + buffer_mult * df['atr14_4h'], 1,
                 np.where(df['close'] < df['ma30_4h'] - buffer_mult * df['atr14_4h'], -1, 0))
    state = raw_state.copy()
    for i in range(1, n):
        if state[i] == 0:
            state[i] = state[i - 1]  # 死區內維持前一個有效狀態 (持續碰觸均線帶不會產生新訊號)
    is_long_sig_arr = (state == 1) & (df['dy_raw'].to_numpy() > 0) if buffer_mult == 0 else (state == 1)
    # buffer_mult=0 時完全還原原始邏輯 (含動能 diff>0 條件)；buffer_mult>0 時死區機制已隱含方向持續性，動能條件改由狀態轉換本身把關

    for i in range(n - 1):
        t_close = df.loc[i, 'close']; t_high = df.loc[i, 'high']; t_low = df.loc[i, 'low']; t_atr = df.loc[i, 'atr14_4h']
        t_prev_high = df.loc[i-1, 'high'] if i > 0 else t_high
        t_prev_low = df.loc[i-1, 'low'] if i > 0 else t_low
        dy_close = df.loc[i, 'daily_close_avail']; dy_ma50 = df.loc[i, 'daily_ma50_avail']
        dy_ma20 = df.loc[i, 'daily_ma20_avail']; dy_ma60 = df.loc[i, 'daily_ma60_avail']
        dy_a1 = df.loc[i, 'daily_alpha1_avail']; dy_a5 = df.loc[i, 'daily_alpha5_avail']; dy_a10 = df.loc[i, 'daily_alpha10_avail']
        is_long_sig = bool(is_long_sig_arr[i])
        next_open = df.loc[i+1, 'open']; next_stamp = str(df.loc[i+1, 'timestamp'])
        dy_pyramid_long = (dy_a1 > 0) and (dy_a5 > 0) and (dy_a10 > 0) and (dy_ma20 > dy_ma60)
        dy_pyramid_short = (dy_a1 < 0) and (dy_a5 < 0) and (dy_a10 < 0) and (dy_ma20 < dy_ma60)
        has_pos = len(active_positions) > 0
        new_active = []

        for p in active_positions:
            w_loss = (t_low - p['entry_price']) * p['units'] if is_long_only else (p['entry_price'] - t_high) * p['units']
            p['mae'] = min(p.get('mae', 0.0), w_loss)

        if is_long_only:
            if has_pos:
                main_pos = [p for p in active_positions if not p['is_pyramid']][0]
                pyr_pos = [p for p in active_positions if p['is_pyramid']]
                has_pyr = len(pyr_pos) > 0
                if t_close < main_pos['stop_price'] or not is_long_sig:
                    exit_reason = "Stop Loss Exit" if t_close < main_pos['stop_price'] else "Signal Exit"
                    for p in active_positions:
                        hd = (pd.to_datetime(next_stamp).date() - pd.to_datetime(p['entry_date']).date()).days
                        raw_pnl = next_open - p['entry_price']
                        cost_pts = trade_cost_points(True, hd, exit_reason, t_atr, cost_scenario)
                        net_pnl = (raw_pnl - cost_pts) * p['units']
                        completed_trades.append({'type': 'Long', 'is_pyramid': p['is_pyramid'], 'units': p['units'],
                            'entry_date': p['entry_date'], 'exit_date': next_stamp, 'entry_price': p['entry_price'],
                            'exit_price': next_open, 'pnl_points': round(net_pnl, 2), 'mae_points': round(p.get('mae', 0.0), 2), 'exit_reason': exit_reason})
                    active_positions = []
                else:
                    if t_close > t_prev_high: main_pos['stop_price'] = min(t_low, t_prev_low) - 1.0 * t_atr
                    new_active.append(main_pos)
                    if has_pyr:
                        p_pos = pyr_pos[0]
                        if t_close < p_pos['stop_price']:
                            hd = (pd.to_datetime(next_stamp).date() - pd.to_datetime(p_pos['entry_date']).date()).days
                            raw_pnl = next_open - p_pos['entry_price']
                            cost_pts = trade_cost_points(True, hd, 'Pyramid Stop Loss', t_atr, cost_scenario)
                            net_pnl = (raw_pnl - cost_pts) * p_pos['units']
                            completed_trades.append({'type': 'Long', 'is_pyramid': True, 'units': p_pos['units'],
                                'entry_date': p_pos['entry_date'], 'exit_date': next_stamp, 'entry_price': p_pos['entry_price'],
                                'exit_price': next_open, 'pnl_points': round(net_pnl, 2), 'mae_points': round(p_pos.get('mae', 0.0), 2), 'exit_reason': 'Pyramid Stop Loss'})
                        else:
                            if t_close > t_prev_high: p_pos['stop_price'] = min(t_low, t_prev_low) - 1.0 * t_atr
                            new_active.append(p_pos)
                    else:
                        if dy_close > dy_ma50 and dy_pyramid_long:
                            atr_ratio = baseline_atr / max(t_atr, 4.0) if pd.notna(t_atr) and t_atr > 0 else 1.0
                            base_mult = 2.0 if dy_a10 > 0.03 else 1.0
                            calc_u = min(2.5, max(0.5, base_mult * atr_ratio))
                            if dy_a10 > 0.04 and calc_u < alpha_floor: calc_u = alpha_floor
                            pyr_units = quantize_units(calc_u)
                            new_active.append({'is_pyramid': True, 'units': pyr_units, 'entry_date': next_stamp,
                                'entry_price': next_open, 'stop_price': min(t_low, t_prev_low) - 1.0 * t_atr, 'mae': 0.0})
                    active_positions = new_active
            else:
                if dy_close > dy_ma50 and is_long_sig:
                    active_positions.append({'is_pyramid': False, 'units': 1.0, 'entry_date': next_stamp,
                        'entry_price': next_open, 'stop_price': min(t_low, t_prev_low) - 1.0 * t_atr, 'mae': 0.0})
        else:
            if has_pos:
                main_pos = [p for p in active_positions if not p['is_pyramid']][0]
                pyr_pos = [p for p in active_positions if p['is_pyramid']]
                has_pyr = len(pyr_pos) > 0
                if t_close > main_pos['stop_price'] or is_long_sig:
                    exit_reason = "Stop Loss Exit" if t_close > main_pos['stop_price'] else "Signal Exit"
                    for p in active_positions:
                        hd = (pd.to_datetime(next_stamp).date() - pd.to_datetime(p['entry_date']).date()).days
                        raw_pnl = p['entry_price'] - next_open
                        cost_pts = trade_cost_points(False, hd, exit_reason, t_atr, cost_scenario)
                        net_pnl = (raw_pnl - cost_pts) * p['units']
                        completed_trades.append({'type': 'Short', 'is_pyramid': p['is_pyramid'], 'units': p['units'],
                            'entry_date': p['entry_date'], 'exit_date': next_stamp, 'entry_price': p['entry_price'],
                            'exit_price': next_open, 'pnl_points': round(net_pnl, 2), 'mae_points': round(p.get('mae', 0.0), 2), 'exit_reason': exit_reason})
                    active_positions = []
                else:
                    if t_close < t_prev_low: main_pos['stop_price'] = max(t_high, t_prev_high) + 1.0 * t_atr
                    new_active.append(main_pos)
                    if has_pyr:
                        p_pos = pyr_pos[0]
                        if t_close > p_pos['stop_price']:
                            hd = (pd.to_datetime(next_stamp).date() - pd.to_datetime(p_pos['entry_date']).date()).days
                            raw_pnl = p_pos['entry_price'] - next_open
                            cost_pts = trade_cost_points(False, hd, 'Pyramid Stop Loss', t_atr, cost_scenario)
                            net_pnl = (raw_pnl - cost_pts) * p_pos['units']
                            completed_trades.append({'type': 'Short', 'is_pyramid': True, 'units': p_pos['units'],
                                'entry_date': p_pos['entry_date'], 'exit_date': next_stamp, 'entry_price': p_pos['entry_price'],
                                'exit_price': next_open, 'pnl_points': round(net_pnl, 2), 'mae_points': round(p_pos.get('mae', 0.0), 2), 'exit_reason': 'Pyramid Stop Loss'})
                        else:
                            if t_close < t_prev_low: p_pos['stop_price'] = max(t_high, t_prev_high) + 1.0 * t_atr
                            new_active.append(p_pos)
                    else:
                        if dy_close < dy_ma50 and dy_pyramid_short:
                            atr_ratio = baseline_atr / max(t_atr, 4.0) if pd.notna(t_atr) and t_atr > 0 else 1.0
                            base_mult = 2.0 if dy_a10 < -0.03 else 1.0
                            calc_u = min(2.5, max(0.5, base_mult * atr_ratio))
                            if dy_a10 < -0.04 and calc_u < alpha_floor: calc_u = alpha_floor
                            pyr_units = quantize_units(calc_u)
                            new_active.append({'is_pyramid': True, 'units': pyr_units, 'entry_date': next_stamp,
                                'entry_price': next_open, 'stop_price': max(t_high, t_prev_high) + 1.0 * t_atr, 'mae': 0.0})
                    active_positions = new_active
            else:
                if dy_close < dy_ma50 and not is_long_sig:
                    active_positions.append({'is_pyramid': False, 'units': 1.0, 'entry_date': next_stamp,
                        'entry_price': next_open, 'stop_price': max(t_high, t_prev_high) + 1.0 * t_atr, 'mae': 0.0})
    return completed_trades


def compute_metrics(all_trades):
    if not all_trades:
        return dict(total_trades=0, total_pnl=0.0, win_rate=0.0, profit_factor=0.0, max_drawdown=0.0, calmar=0.0)
    pnl = pd.Series([t['pnl_points'] for t in all_trades])
    cum = pnl.cumsum()
    win = pnl[pnl > 0]; loss = pnl[pnl < 0]
    mdd = float((cum.cummax() - cum).max())
    first_d = pd.to_datetime(all_trades[0]['entry_date']); last_d = pd.to_datetime(all_trades[-1]['exit_date'])
    years = max((last_d - first_d).days / 365.25, 0.5)
    annual_pnl = pnl.sum() / years
    return dict(
        total_trades=len(all_trades),
        total_pnl=round(float(pnl.sum()), 2),
        win_rate=round(len(win) / len(pnl) * 100, 2),
        profit_factor=round(abs(win.sum() / loss.sum()), 2) if len(loss) > 0 else 0.0,
        max_drawdown=round(mdd, 2),
        calmar=round(annual_pnl / mdd, 2) if mdd > 0 else 0.0,
    )


def full_metrics(df, all_trades):
    """完整績效指標，計算方式與 gold_adaptive_strategy.py 一致，
    包含 Sharpe、浮動回撤、單筆最大逆向浮虧 (MAE) 等，供與正式回測直接比較。"""
    if not all_trades:
        return None
    pnl_series = pd.Series([t['pnl_points'] for t in all_trades])
    cum_pnl = pnl_series.cumsum()
    total_pnl = float(pnl_series.sum())
    win_trades = [t for t in all_trades if t['pnl_points'] > 0]
    loss_trades = [t for t in all_trades if t['pnl_points'] < 0]
    win_rate = round(len(win_trades) / len(all_trades) * 100, 2)
    profit_factor = round(abs(sum(t['pnl_points'] for t in win_trades) / sum(t['pnl_points'] for t in loss_trades)), 2) if loss_trades else 0.0

    max_drawdown = round(float((cum_pnl.cummax() - cum_pnl).max()), 2) if len(cum_pnl) > 0 else 0.0
    peak_pnl = float(cum_pnl.max()) if len(cum_pnl) > 0 else 0.0
    current_pnl = float(cum_pnl.iloc[-1]) if len(cum_pnl) > 0 else 0.0
    current_drawdown = round(peak_pnl - current_pnl, 2)
    current_drawdown_pct = round(current_drawdown / peak_pnl * 100, 2) if peak_pnl > 0 else 0.0

    all_maes = [t.get('mae_points', 0.0) for t in all_trades]
    worst_single_mae = round(float(min(all_maes)), 2) if all_maes else 0.0
    pyr_maes = [t.get('mae_points', 0.0) for t in all_trades if t['is_pyramid']]
    worst_pyramid_mae = round(float(min(pyr_maes)), 2) if pyr_maes else 0.0

    first_date = pd.to_datetime(all_trades[0]['entry_date'])
    last_date = pd.to_datetime(all_trades[-1]['exit_date'])
    years = max((last_date - first_date).days / 365.25, 0.5)
    annual_pnl = total_pnl / years
    calmar_ratio = round(annual_pnl / max_drawdown, 2) if max_drawdown > 0 else 0.0
    sharpe_ratio = round(float((pnl_series.mean() / pnl_series.std()) * np.sqrt(252)), 2) if pnl_series.std() > 0 else 0.0

    # 逐根 K 線浮動淨值回撤 (與 gold_adaptive_strategy.py 相同邏輯)
    trade_exit_map = {}
    parsed_trades = []
    for t in all_trades:
        trade_exit_map[t['exit_date']] = trade_exit_map.get(t['exit_date'], 0.0) + t['pnl_points']
        parsed_trades.append({'type': t['type'], 'units': t['units'], 'entry_price': t['entry_price'],
            'entry_dt': pd.Timestamp(t['entry_date']), 'exit_dt': pd.Timestamp(t['exit_date'])})

    df_idx = df[df['timestamp'] >= first_date].reset_index(drop=True)
    bar_equity_curve = []
    bar_floating_pnl_close = []
    cum_tracker = 0.0
    for i in range(len(df_idx) - 1):
        tc = df_idx.loc[i, 'close']
        cur_t = df_idx.loc[i, 'timestamp']
        cur_t_str = str(cur_t)
        if cur_t_str in trade_exit_map:
            cum_tracker += trade_exit_map[cur_t_str]
        fl_close = 0.0
        for t in parsed_trades:
            if t['entry_dt'] <= cur_t < t['exit_dt']:
                fl_close += (tc - t['entry_price']) * t['units'] if t['type'] == 'Long' else (t['entry_price'] - tc) * t['units']
        bar_floating_pnl_close.append(fl_close)
        bar_equity_curve.append(cum_tracker + fl_close)

    eq_arr = np.array(bar_equity_curve)
    floating_drawdown = round(float((np.maximum.accumulate(eq_arr) - eq_arr).max()), 2) if len(eq_arr) > 0 else 0.0
    max_instant_float_loss = round(float(min(bar_floating_pnl_close)), 2) if bar_floating_pnl_close else 0.0

    return dict(
        total_trades=len(all_trades), total_pnl=round(total_pnl, 2), win_rate=win_rate, profit_factor=profit_factor,
        max_drawdown=max_drawdown, current_drawdown=current_drawdown, current_drawdown_pct=current_drawdown_pct,
        floating_drawdown=floating_drawdown, max_instant_float_loss=max_instant_float_loss,
        worst_single_mae=worst_single_mae, worst_pyramid_mae=worst_pyramid_mae,
        calmar_ratio=calmar_ratio, sharpe_ratio=sharpe_ratio, annual_pnl=round(annual_pnl, 2), years=round(years, 2),
    )


def tail_period_metrics(all_trades, since_date):
    tail = [t for t in all_trades if pd.to_datetime(t['exit_date']) >= pd.to_datetime(since_date)]
    if not tail:
        return dict(n=0, pnl=0.0, win=0, loss=0)
    pnl = sum(t['pnl_points'] for t in tail)
    win = sum(1 for t in tail if t['pnl_points'] > 0)
    loss = sum(1 for t in tail if t['pnl_points'] < 0)
    return dict(n=len(tail), pnl=round(pnl, 2), win=win, loss=loss)


def print_full_report(df, buffer_mult, label, cost_scenario=DEFAULT_SCENARIO):
    trades_l = simulate(df, buffer_mult, is_long_only=True, cost_scenario=cost_scenario)
    trades_s = simulate(df, buffer_mult, is_long_only=False, cost_scenario=cost_scenario)
    all_trades = sorted(trades_l + trades_s, key=lambda x: x['exit_date'])
    m = full_metrics(df, all_trades)
    print(f"--- {label} (buffer={buffer_mult}, cost={cost_scenario}) ---")
    print(f"  總交易筆數:           {m['total_trades']}")
    print(f"  總損益:               {m['total_pnl']:+.2f} 點")
    print(f"  年化損益:             {m['annual_pnl']:+.2f} 點/年 (統計 {m['years']} 年)")
    print(f"  勝率:                 {m['win_rate']}%")
    print(f"  盈虧比 (PF):          {m['profit_factor']}")
    print(f"  最大已平倉回撤 (MDD): {m['max_drawdown']:.2f} 點")
    print(f"  目前已平倉回撤:       {m['current_drawdown']:.2f} 點 ({m['current_drawdown_pct']}%)")
    print(f"  浮動淨值最大回撤:     {m['floating_drawdown']:.2f} 點")
    print(f"  單一時間最大浮虧:     {m['max_instant_float_loss']:.2f} 點")
    print(f"  單筆最大逆向浮虧:     {m['worst_single_mae']:.2f} 點")
    print(f"  加碼單最大逆向浮虧:   {m['worst_pyramid_mae']:.2f} 點")
    print(f"  卡瑪比率 (Calmar):    {m['calmar_ratio']}")
    print(f"  夏普比率 (Sharpe):    {m['sharpe_ratio']}")
    print()
    return m


if __name__ == '__main__':
    df = load_dataset()
    df_official = df[df['timestamp'] >= '2024-07-07'].reset_index(drop=True)
    print(f"4年資料: {len(df)} 根 ({df['timestamp'].min()} ~ {df['timestamp'].max()})")
    print(f"官方2.1年資料: {len(df_official)} 根 ({df_official['timestamp'].min()} ~ {df_official['timestamp'].max()})")
    print("=" * 70)

    results = {}
    for dset, dset_label in [(df, '4年全期'), (df_official, '官方2.1年期間')]:
        for buf in [0.0, 0.20]:
            key = f"{dset_label}_buf{buf}"
            results[key] = print_full_report(dset, buf, f"{dset_label} | buffer={'原始(0)' if buf==0 else '候選(0.20)'}")

    print("=" * 70)
    print("📌 成本情境敏感度 (候選 buffer=0.20，4年全期)")
    print("=" * 70)
    for scenario in ['razor_best', 'razor_typical', 'razor_stress']:
        print_full_report(df, 0.20, f"4年全期 | buffer=0.20", cost_scenario=scenario)
