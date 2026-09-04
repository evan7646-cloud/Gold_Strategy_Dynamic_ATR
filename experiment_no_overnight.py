"""實驗性腳本：測試「不留倉過夜」的可行做法 (不影響正式回測檔案)。

【背景】
現行策略中位數持倉時間很短，但仍有 39.9% 的交易跨過午夜、7.7% 可能跨週末
(週末缺口平均 13.7 點、最大 101.4 點)。使用者想測試若不留倉過夜可以怎麼做：

  方法一：每天 MT5 券商時間 0:00 前一小時強制平倉，隔天開盤後重新進場
  方法二：其他讓策略變成日內交易的做法 (本實驗另測「僅週末平倉」與「持倉時數上限」)

【關於「MT5 的 0:00」】
資料的 4H K 棒切分為 UTC 00/04/08/12/16/20 (與 EA 的 +0h 網格一致)。
不同券商的伺服器時區不同 (常見 GMT+2 或 GMT+3)，故「券商午夜」實際落在
UTC 21:00 或 22:00 附近，落在「20:00 那根 4H K 棒」的區間內。
本實驗假設持倉不可跨過 20:00 UTC 那根 K 棒，於該根之前強制平倉、
於次日 00:00 UTC 那根重新依正常訊號進場 —— 這是對「券商午夜前一小時平倉」
的近似，實際確切時點需視券商真實 GMT 偏移微調。

【測試的變體】
  baseline      : 現行邏輯，不設任何平倉限制
  daily_flat    : 每天 20:00 UTC 那根 K 棒前強制平倉，00:00 UTC 恢復正常進場邏輯
  weekend_flat  : 僅在週末缺口前強制平倉 (只避開最大的跳空風險，平日照常持倉過夜)
  max_hold_Nh   : 持倉超過 N 小時即強制平倉 (不分日夜，另一種限制曝險時間的做法)
"""

import numpy as np
import pandas as pd

from cost_model import trade_cost_points, DEFAULT_SCENARIO
from daily_align import attach_daily_features
from ea_sizing import quantize_units
from experiment_chop_filter import calculate_atr, full_metrics
from trend_filter import add_curvature, curvature_pass, CURVATURE_THRESHOLD, CURVATURE_SPAN

GOLD_4H_FILE = 'pepperstone_xauusd_4h.csv'


def load_dataset():
    gold_d = pd.read_csv('pepperstone_xauusd_daily.csv').rename(
        columns={'close': 'gold_close', 'open': 'gold_open', 'high': 'gold_high', 'low': 'gold_low'})
    dxy_d = pd.read_csv('pepperstone_usdx_daily.csv').rename(
        columns={'close': 'dxy_close', 'open': 'dxy_open', 'high': 'dxy_high', 'low': 'dxy_low'})
    gold_4h = pd.read_csv(GOLD_4H_FILE)

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
    df = add_curvature(df, span=CURVATURE_SPAN)
    df['sig_long_4h'] = (df['close'] > df['ma30_4h']) & (df['dy_raw'] > 0) & curvature_pass(df)
    return df.dropna().reset_index(drop=True)


def is_weekend_gap_bar(ts_series, i):
    """判斷第 i+1 根是否為週末缺口後的第一根 (即 bar[i] 到 bar[i+1] 跨越週末)。"""
    if i + 1 >= len(ts_series):
        return False
    return (ts_series.iloc[i + 1] - ts_series.iloc[i]).total_seconds() > 20 * 3600  # 超過 20 小時視為跨週末


def simulate(df, is_long_only, mode='baseline', max_hold_hours=None, cost_scenario=DEFAULT_SCENARIO,
             baseline_atr=16.0, alpha_floor=1.0):
    """mode: 'baseline' | 'daily_flat' | 'weekend_flat'
    max_hold_hours: 設定則另外套用「持倉超過此時數強制平倉」規則 (可與 mode 疊加測試，但本次分開測試)"""
    n = len(df)
    active_positions = []
    completed_trades = []
    ts = df['timestamp']

    for i in range(n - 1):
        t_close = df.loc[i, 'close']; t_high = df.loc[i, 'high']; t_low = df.loc[i, 'low']; t_atr = df.loc[i, 'atr14_4h']
        t_prev_high = df.loc[i-1, 'high'] if i > 0 else t_high
        t_prev_low = df.loc[i-1, 'low'] if i > 0 else t_low
        dy_close = df.loc[i, 'daily_close_avail']; dy_ma50 = df.loc[i, 'daily_ma50_avail']
        dy_ma20 = df.loc[i, 'daily_ma20_avail']; dy_ma60 = df.loc[i, 'daily_ma60_avail']
        dy_a1 = df.loc[i, 'daily_alpha1_avail']; dy_a5 = df.loc[i, 'daily_alpha5_avail']; dy_a10 = df.loc[i, 'daily_alpha10_avail']
        is_long_sig = bool(df.loc[i, 'sig_long_4h'])
        next_open = df.loc[i+1, 'open']; next_stamp = df.loc[i+1, 'timestamp']; next_stamp_str = str(next_stamp)
        dy_pyr_long = (dy_a1 > 0) and (dy_a5 > 0) and (dy_a10 > 0) and (dy_ma20 > dy_ma60)
        dy_pyr_short = (dy_a1 < 0) and (dy_a5 < 0) and (dy_a10 < 0) and (dy_ma20 < dy_ma60)

        # --- 判斷本次是否進入「禁止持倉/進場」的黑窗期 ---
        force_flat = False       # 是否強制平倉現有部位
        block_entry = False      # 是否禁止本次新增/延續部位
        if mode == 'daily_flat':
            if next_stamp.hour == 20:  # 次一根即將進入 20:00 UTC (跨越券商午夜的那根)，強制平倉並禁止進場
                force_flat = True; block_entry = True
        elif mode == 'weekend_flat':
            if is_weekend_gap_bar(ts, i):  # 次一根跨越週末缺口，強制平倉並禁止進場
                force_flat = True; block_entry = True

        new_active = []
        for p in active_positions:
            w = (t_low - p['entry_price']) * p['units'] if is_long_only else (p['entry_price'] - t_high) * p['units']
            p['mae'] = min(p.get('mae', 0.0), w)

        def close_all(reason, positions):
            for p in positions:
                hd = (next_stamp.date() - pd.to_datetime(p['entry_date']).date()).days
                raw = (next_open - p['entry_price']) if is_long_only else (p['entry_price'] - next_open)
                cost = trade_cost_points(is_long_only, hd, reason, t_atr, cost_scenario)
                completed_trades.append({
                    'type': 'Long' if is_long_only else 'Short', 'is_pyramid': p['is_pyramid'], 'units': p['units'],
                    'entry_date': p['entry_date'], 'exit_date': next_stamp_str, 'entry_price': p['entry_price'],
                    'exit_price': next_open, 'pnl_points': round((raw - cost) * p['units'], 2),
                    'mae_points': round(p.get('mae', 0.0), 2), 'exit_reason': reason})

        # 檢查現有部位是否因持倉時數上限被強制平倉 (與 mode 獨立疊加)
        if max_hold_hours is not None and active_positions:
            oldest_hours = (next_stamp - pd.to_datetime(active_positions[0]['entry_date'])).total_seconds() / 3600
            if oldest_hours >= max_hold_hours:
                force_flat = True

        if force_flat and active_positions:
            close_all('Daily Flatten' if mode == 'daily_flat' else ('Weekend Flatten' if mode == 'weekend_flat' else 'Max Hold Exit'), active_positions)
            active_positions = []
            continue  # 平倉後本根不再處理進出場，下一根重新評估

        if not active_positions:
            if block_entry:
                continue  # 黑窗期禁止新倉
            regime_ok = (dy_close > dy_ma50) if is_long_only else (dy_close < dy_ma50)
            sig_ok = is_long_sig if is_long_only else (not is_long_sig)
            if regime_ok and sig_ok:
                stop = (min(t_low, t_prev_low) - t_atr) if is_long_only else (max(t_high, t_prev_high) + t_atr)
                active_positions.append({'is_pyramid': False, 'units': 1.0, 'entry_date': next_stamp_str,
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
        elif not block_entry:
            regime_ok = (dy_close > dy_ma50) if is_long_only else (dy_close < dy_ma50)
            pyr_ok = dy_pyr_long if is_long_only else dy_pyr_short
            if regime_ok and pyr_ok:
                ratio = baseline_atr / max(t_atr, 4.0) if pd.notna(t_atr) and t_atr > 0 else 1.0
                strong = (dy_a10 > 0.03) if is_long_only else (dy_a10 < -0.03)
                u = min(2.5, max(0.5, (2.0 if strong else 1.0) * ratio))
                floor_hit = (dy_a10 > 0.04) if is_long_only else (dy_a10 < -0.04)
                if floor_hit and u < alpha_floor:
                    u = alpha_floor
                new_active.append({'is_pyramid': True, 'units': quantize_units(u), 'entry_date': next_stamp_str,
                                   'entry_price': next_open, 'stop_price': new_stop, 'mae': 0.0})
        active_positions = new_active

    return completed_trades


def run(df, mode='baseline', max_hold_hours=None, cost_scenario=DEFAULT_SCENARIO):
    tl = simulate(df, True, mode, max_hold_hours, cost_scenario)
    ts = simulate(df, False, mode, max_hold_hours, cost_scenario)
    allt = sorted(tl + ts, key=lambda x: x['exit_date'])
    return full_metrics(df, allt), allt


def swap_cost_paid(all_trades, cost_scenario=DEFAULT_SCENARIO):
    """估算該組交易總共支付了多少隔夜利息成本 (從 trade_cost_points 拆解出的 swap 部分)。"""
    from cost_model import COST_SCENARIOS
    c = COST_SCENARIOS[cost_scenario]
    total = 0.0
    for t in all_trades:
        hd = t['holding_hours'] / 24.0 if 'holding_hours' in t else \
             max((pd.to_datetime(t['exit_date']) - pd.to_datetime(t['entry_date'])).days, 0)
        is_long = t['type'] == 'Long'
        swap_rate = c['swap_long'] if is_long else c['swap_short']
        total += (-swap_rate) * hd * t['units']
    return round(total, 2)


if __name__ == '__main__':
    df = load_dataset()
    print(f"資料: {df['timestamp'].min()} ~ {df['timestamp'].max()}  共 {len(df)} 根")
    print(f"曲率過濾: 已啟用 (現行正式邏輯)")
    print("=" * 118)
    print(f"{'變體':<20s} {'總損益':>10s} {'筆數':>6s} {'勝率':>7s} {'PF':>6s} {'MDD':>8s} {'Calmar':>7s} {'Sharpe':>7s} {'浮動回撤':>9s} {'估算swap':>9s}")
    print("-" * 118)

    variants = [
        ('baseline (現行)', 'baseline', None),
        ('daily_flat (方法一)', 'daily_flat', None),
        ('weekend_flat (僅避週末)', 'weekend_flat', None),
        ('max_hold_24h', 'baseline', 24),
        ('max_hold_48h', 'baseline', 48),
    ]
    results = {}
    for name, mode, mh in variants:
        m, allt = run(df, mode, mh)
        results[name] = (m, allt)
        for t in allt:
            t.setdefault('holding_hours', (pd.to_datetime(t['exit_date']) - pd.to_datetime(t['entry_date'])).total_seconds()/3600)
        swap = swap_cost_paid(allt)
        print(f"{name:<20s} {m['total_pnl']:10.2f} {m['total_trades']:6d} {m['win_rate']:6.2f}% "
              f"{m['profit_factor']:6.2f} {m['max_drawdown']:8.2f} {m['calmar_ratio']:7.2f} "
              f"{m['sharpe_ratio']:7.2f} {m['floating_drawdown']:9.2f} {swap:9.2f}")

    print()
    print("=== exit_reason 分布 (daily_flat 變體) ===")
    _, allt_df = results['daily_flat (方法一)']
    reasons = pd.Series([t['exit_reason'] for t in allt_df]).value_counts()
    print(reasons.to_string())

    print()
    print("=== 成本情境敏感度 (daily_flat vs baseline) ===")
    for cs in ['razor_best', 'razor_typical', 'razor_stress']:
        mb, _ = run(df, 'baseline', None, cs)
        md, _ = run(df, 'daily_flat', None, cs)
        print(f"  {cs:14s}: baseline PF={mb['profit_factor']:.2f} Calmar={mb['calmar_ratio']:5.2f}  |  "
              f"daily_flat PF={md['profit_factor']:.2f} Calmar={md['calmar_ratio']:5.2f}")


def simulate_daily_flat_v2(df, is_long_only, blackout_hour=20, soft_reentry=True, cost_scenario=DEFAULT_SCENARIO,
                           baseline_atr=16.0, alpha_floor=1.0):
    """daily_flat 的改良版：
    - blackout_hour 可調整 (逼近真實券商/FTMO 的伺服器午夜前一小時)
    - soft_reentry=True 時，剛被強制平倉的部位在黑窗期結束後的第一根立即恢復
      (只需日線體制符合方向，不需重新確認 4H 動能/曲率)，避免因被迫平倉而錯過
      原本已經成立的趨勢。"""
    n = len(df); active = []; trades = []
    ts = df['timestamp']
    was_flattened_dir = None
    for i in range(n - 1):
        t_close=df.loc[i,'close']; t_high=df.loc[i,'high']; t_low=df.loc[i,'low']; t_atr=df.loc[i,'atr14_4h']
        t_prev_high=df.loc[i-1,'high'] if i>0 else t_high; t_prev_low=df.loc[i-1,'low'] if i>0 else t_low
        dy_close=df.loc[i,'daily_close_avail']; dy_ma50=df.loc[i,'daily_ma50_avail']
        dy_ma20=df.loc[i,'daily_ma20_avail']; dy_ma60=df.loc[i,'daily_ma60_avail']
        dy_a1=df.loc[i,'daily_alpha1_avail']; dy_a5=df.loc[i,'daily_alpha5_avail']; dy_a10=df.loc[i,'daily_alpha10_avail']
        is_long_sig=bool(df.loc[i,'sig_long_4h'])
        next_open=df.loc[i+1,'open']; next_stamp=df.loc[i+1,'timestamp']; next_stamp_str=str(next_stamp)
        dy_pyr_long=(dy_a1>0)and(dy_a5>0)and(dy_a10>0)and(dy_ma20>dy_ma60)
        dy_pyr_short=(dy_a1<0)and(dy_a5<0)and(dy_a10<0)and(dy_ma20<dy_ma60)
        block_entry = next_stamp.hour == blackout_hour
        force_flat = block_entry

        for p in active:
            w=(t_low-p['entry_price'])*p['units'] if is_long_only else (p['entry_price']-t_high)*p['units']
            p['mae']=min(p.get('mae',0.0),w)

        def close_all(reason, positions):
            for p in positions:
                hd=(next_stamp.date()-pd.to_datetime(p['entry_date']).date()).days
                raw=(next_open-p['entry_price']) if is_long_only else (p['entry_price']-next_open)
                cost=trade_cost_points(is_long_only,hd,reason,t_atr,cost_scenario)
                trades.append({'type':'Long' if is_long_only else 'Short','is_pyramid':p['is_pyramid'],'units':p['units'],
                    'entry_date':p['entry_date'],'exit_date':next_stamp_str,'entry_price':p['entry_price'],
                    'exit_price':next_open,'pnl_points':round((raw-cost)*p['units'],2),
                    'mae_points':round(p.get('mae',0.0),2),'exit_reason':reason})

        if force_flat and active:
            close_all('Daily Flatten', active)
            was_flattened_dir = is_long_only
            active=[]
            continue

        if not active:
            if block_entry:
                continue
            regime_ok=(dy_close>dy_ma50) if is_long_only else (dy_close<dy_ma50)
            just_reopened = soft_reentry and was_flattened_dir==is_long_only and i>0 and df.loc[i-1,'timestamp'].hour==blackout_hour
            sig_ok = True if just_reopened else (is_long_sig if is_long_only else (not is_long_sig))
            if regime_ok and sig_ok:
                stop=(min(t_low,t_prev_low)-t_atr) if is_long_only else (max(t_high,t_prev_high)+t_atr)
                active.append({'is_pyramid':False,'units':1.0,'entry_date':next_stamp_str,
                               'entry_price':next_open,'stop_price':stop,'mae':0.0})
                was_flattened_dir=None
            continue

        main_pos=[p for p in active if not p['is_pyramid']][0]
        pyr_pos=[p for p in active if p['is_pyramid']]
        stop_hit=(t_close<main_pos['stop_price']) if is_long_only else (t_close>main_pos['stop_price'])
        sig_lost=(not is_long_sig) if is_long_only else is_long_sig
        if stop_hit or sig_lost:
            close_all("Stop Loss Exit" if stop_hit else "Signal Exit", active); active=[]; continue
        broke=(t_close>t_prev_high) if is_long_only else (t_close<t_prev_low)
        new_stop=(min(t_low,t_prev_low)-t_atr) if is_long_only else (max(t_high,t_prev_high)+t_atr)
        if broke: main_pos['stop_price']=new_stop
        new_active=[main_pos]
        if pyr_pos:
            p=pyr_pos[0]
            p_hit=(t_close<p['stop_price']) if is_long_only else (t_close>p['stop_price'])
            if p_hit: close_all('Pyramid Stop Loss',[p])
            else:
                if broke: p['stop_price']=new_stop
                new_active.append(p)
        elif not block_entry:
            regime_ok=(dy_close>dy_ma50) if is_long_only else (dy_close<dy_ma50)
            pyr_ok=dy_pyr_long if is_long_only else dy_pyr_short
            if regime_ok and pyr_ok:
                ratio=baseline_atr/max(t_atr,4.0) if pd.notna(t_atr) and t_atr>0 else 1.0
                strong=(dy_a10>0.03) if is_long_only else (dy_a10<-0.03)
                u=min(2.5,max(0.5,(2.0 if strong else 1.0)*ratio))
                floor_hit=(dy_a10>0.04) if is_long_only else (dy_a10<-0.04)
                if floor_hit and u<alpha_floor: u=alpha_floor
                new_active.append({'is_pyramid':True,'units':quantize_units(u),'entry_date':next_stamp_str,
                                   'entry_price':next_open,'stop_price':new_stop,'mae':0.0})
        active=new_active
    return trades


def run_v2(df, blackout_hour=20, soft_reentry=True, cost_scenario=DEFAULT_SCENARIO):
    tl = simulate_daily_flat_v2(df, True, blackout_hour, soft_reentry, cost_scenario)
    ts = simulate_daily_flat_v2(df, False, blackout_hour, soft_reentry, cost_scenario)
    allt = sorted(tl + ts, key=lambda x: x['exit_date'])
    return full_metrics(df, allt), allt


def simulate_ftmo_compliant(df, is_long_only, soft_reentry=True, cost_scenario=DEFAULT_SCENARIO,
                            baseline_atr=16.0, alpha_floor=1.0, gap_threshold_h=4.0):
    """FTMO 正式帳戶合規版：僅在「市場休市超過 2 小時」前強制平倉。

    依 FTMO 官方 FAQ，正式帳戶需於週末休市前、或 rollover(市場中斷)超過 2 小時前平倉；
    每日例行休市為 1 小時 (未超過門檻)，故『不需』每天平倉。
    以 4H 資料判定：相鄰 K 棒間隔 > 4 小時即代表跨越了需平倉的休市。

    soft_reentry：休市結束後第一根立即恢復原方向部位 (僅需日線體制符合)，
    避免因被迫平倉而錯過原本已成立的趨勢。
    """
    n = len(df); active = []; trades = []
    ts = df['timestamp']
    was_flattened_dir = None
    for i in range(n - 1):
        t_close=df.loc[i,'close']; t_high=df.loc[i,'high']; t_low=df.loc[i,'low']; t_atr=df.loc[i,'atr14_4h']
        t_prev_high=df.loc[i-1,'high'] if i>0 else t_high; t_prev_low=df.loc[i-1,'low'] if i>0 else t_low
        dy_close=df.loc[i,'daily_close_avail']; dy_ma50=df.loc[i,'daily_ma50_avail']
        dy_ma20=df.loc[i,'daily_ma20_avail']; dy_ma60=df.loc[i,'daily_ma60_avail']
        dy_a1=df.loc[i,'daily_alpha1_avail']; dy_a5=df.loc[i,'daily_alpha5_avail']; dy_a10=df.loc[i,'daily_alpha10_avail']
        is_long_sig=bool(df.loc[i,'sig_long_4h'])
        next_open=df.loc[i+1,'open']; next_stamp=df.loc[i+1,'timestamp']; next_stamp_str=str(next_stamp)
        dy_pyr_long=(dy_a1>0)and(dy_a5>0)and(dy_a10>0)and(dy_ma20>dy_ma60)
        dy_pyr_short=(dy_a1<0)and(dy_a5<0)and(dy_a10<0)and(dy_ma20<dy_ma60)

        # 次一根與本根間隔超過門檻 -> 中間有需平倉的休市
        gap_h = (next_stamp - ts.iloc[i]).total_seconds()/3600
        crossing_break = gap_h > gap_threshold_h
        prev_gap_h = (ts.iloc[i] - ts.iloc[i-1]).total_seconds()/3600 if i > 0 else 0.0
        just_after_break = prev_gap_h > gap_threshold_h

        for p in active:
            w=(t_low-p['entry_price'])*p['units'] if is_long_only else (p['entry_price']-t_high)*p['units']
            p['mae']=min(p.get('mae',0.0),w)

        def close_all(reason, positions):
            for p in positions:
                hd=(next_stamp.date()-pd.to_datetime(p['entry_date']).date()).days
                raw=(next_open-p['entry_price']) if is_long_only else (p['entry_price']-next_open)
                cost=trade_cost_points(is_long_only,hd,reason,t_atr,cost_scenario)
                trades.append({'type':'Long' if is_long_only else 'Short','is_pyramid':p['is_pyramid'],'units':p['units'],
                    'entry_date':p['entry_date'],'exit_date':next_stamp_str,'entry_price':p['entry_price'],
                    'exit_price':next_open,'pnl_points':round((raw-cost)*p['units'],2),
                    'mae_points':round(p.get('mae',0.0),2),'exit_reason':reason})

        if crossing_break and active:
            close_all('Market Break Flatten', active)
            was_flattened_dir = is_long_only
            active=[]
            continue

        if not active:
            if crossing_break:
                continue  # 不在休市前開新倉
            regime_ok=(dy_close>dy_ma50) if is_long_only else (dy_close<dy_ma50)
            just_reopened = soft_reentry and was_flattened_dir==is_long_only and just_after_break
            sig_ok = True if just_reopened else (is_long_sig if is_long_only else (not is_long_sig))
            if regime_ok and sig_ok:
                stop=(min(t_low,t_prev_low)-t_atr) if is_long_only else (max(t_high,t_prev_high)+t_atr)
                active.append({'is_pyramid':False,'units':1.0,'entry_date':next_stamp_str,
                               'entry_price':next_open,'stop_price':stop,'mae':0.0})
                was_flattened_dir=None
            continue

        main_pos=[p for p in active if not p['is_pyramid']][0]
        pyr_pos=[p for p in active if p['is_pyramid']]
        stop_hit=(t_close<main_pos['stop_price']) if is_long_only else (t_close>main_pos['stop_price'])
        sig_lost=(not is_long_sig) if is_long_only else is_long_sig
        if stop_hit or sig_lost:
            close_all("Stop Loss Exit" if stop_hit else "Signal Exit", active); active=[]; continue
        broke=(t_close>t_prev_high) if is_long_only else (t_close<t_prev_low)
        new_stop=(min(t_low,t_prev_low)-t_atr) if is_long_only else (max(t_high,t_prev_high)+t_atr)
        if broke: main_pos['stop_price']=new_stop
        new_active=[main_pos]
        if pyr_pos:
            p=pyr_pos[0]
            p_hit=(t_close<p['stop_price']) if is_long_only else (t_close>p['stop_price'])
            if p_hit: close_all('Pyramid Stop Loss',[p])
            else:
                if broke: p['stop_price']=new_stop
                new_active.append(p)
        elif not crossing_break:
            regime_ok=(dy_close>dy_ma50) if is_long_only else (dy_close<dy_ma50)
            pyr_ok=dy_pyr_long if is_long_only else dy_pyr_short
            if regime_ok and pyr_ok:
                ratio=baseline_atr/max(t_atr,4.0) if pd.notna(t_atr) and t_atr>0 else 1.0
                strong=(dy_a10>0.03) if is_long_only else (dy_a10<-0.03)
                u=min(2.5,max(0.5,(2.0 if strong else 1.0)*ratio))
                floor_hit=(dy_a10>0.04) if is_long_only else (dy_a10<-0.04)
                if floor_hit and u<alpha_floor: u=alpha_floor
                new_active.append({'is_pyramid':True,'units':quantize_units(u),'entry_date':next_stamp_str,
                                   'entry_price':next_open,'stop_price':new_stop,'mae':0.0})
        active=new_active
    return trades


def run_ftmo(df, soft_reentry=True, cost_scenario=DEFAULT_SCENARIO):
    tl = simulate_ftmo_compliant(df, True, soft_reentry, cost_scenario)
    ts = simulate_ftmo_compliant(df, False, soft_reentry, cost_scenario)
    allt = sorted(tl + ts, key=lambda x: x['exit_date'])
    return full_metrics(df, allt), allt
