import os  # 匯入作業系統模組以處理路徑
import json  # 匯入 JSON 模組解析資料
import pandas as pd  # 匯入 pandas 處理表格
import numpy as np  # 匯入 numpy 數值運算
import matplotlib.pyplot as plt  # 匯入 matplotlib 繪製 4 年權益圖
from cost_model import trade_cost_points, COST_SCENARIOS, DEFAULT_SCENARIO  # 匯入 Pepperstone Razor 成本模型
from daily_align import attach_daily_features  # 匯入日線時間對齊模組 (消除未來函數並對齊 EA 的 iClose(PERIOD_D1,1) 語意)
from ea_sizing import quantize_units  # 匯入 EA 手數量化模組 (對齊 EA NormalizeLot 的無條件捨去規則)

def calculate_atr(df, period=14):  # 計算真實波幅均值 ATR 函數
    high = df['high']  # 最高價
    low = df['low']  # 最低價
    close_prev = df['close'].shift(1)  # 前收盤價
    tr1 = high - low  # 高低差
    tr2 = (high - close_prev).abs()  # 最高與前收差
    tr3 = (low - close_prev).abs()  # 最低與前收差
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)  # 取最大值
    return tr.rolling(period).mean()  # 回傳滑動均值

def compute_cost_sensitivity(trade_records):  # 成本情境敏感度分析：交易本身(進出場/方向/持倉天數/出場ATR)不變，只替換成本假設
    result = {}  # 各情境結果
    for scenario_name in COST_SCENARIOS:  # 遍歷 best/typical/stress
        pnl_list = []  # 逐筆淨損益
        for t in trade_records:  # 遍歷交易
            is_long = t['type'] == 'Long'  # 判斷方向
            raw_pnl_unit = (t['exit_price'] - t['entry_price']) if is_long else (t['entry_price'] - t['exit_price'])  # 還原原始價差
            holding_days = t['holding_hours'] / 24.0  # 還原持倉天數
            cost_pts = trade_cost_points(is_long, holding_days, t['exit_reason'], t.get('atr_at_exit'), scenario_name)  # 依情境重算成本
            pnl_list.append(round((raw_pnl_unit - cost_pts) * t['units'], 2))  # 記錄
        pnl_series = pd.Series(pnl_list)  # 轉序列
        cum = pnl_series.cumsum()  # 累積損益
        win = pnl_series[pnl_series > 0]  # 獲利筆
        loss = pnl_series[pnl_series < 0]  # 虧損筆
        result[scenario_name] = {  # 記錄指標
            'total_pnl_points': round(float(pnl_series.sum()), 2),  # 總損益
            'max_drawdown': round(float((cum.cummax() - cum).max()), 2) if len(cum) > 0 else 0.0,  # 最大回撤
            'win_rate': round(len(win) / len(pnl_series) * 100, 2) if len(pnl_series) > 0 else 0.0,  # 勝率
            'profit_factor': round(abs(win.sum() / loss.sum()), 2) if len(loss) > 0 and loss.sum() != 0 else 0.0,  # 盈虧比
        }  # 情境結束
    return result  # 回傳三情境對照

def run_4yr_adaptive_backtest():  # 執行 4 年全數據回測
    gold_d_file = 'comex_gc1!_daily.csv'  # 黃金日線檔案
    dxy_d_file = 'iceus_dxy_daily.csv'  # DXY 日線檔案
    gold_4h_file = 'xauusd_4h_4yr.csv'  # 4 年 XAUUSD 4H K線檔案 (5,585 根)

    gold_d = pd.read_csv(gold_d_file).rename(columns={'close': 'gc', 'open': 'go', 'high': 'gh', 'low': 'gl'})  # 讀取黃金日線
    dxy_d = pd.read_csv(dxy_d_file).rename(columns={'close': 'dc', 'open': 'do', 'high': 'dh', 'low': 'dl'})  # 讀取 DXY 日線
    gold_4h = pd.read_csv(gold_4h_file)  # 讀取 4 年 4H K線

    df_daily = pd.merge(gold_d, dxy_d, on='timestamp', how='inner')  # 合併日線
    df_daily['timestamp'] = pd.to_datetime(df_daily['timestamp'])  # 轉為 datetime
    df_daily = df_daily.sort_values('timestamp').reset_index(drop=True)  # 排序

    for n in [1, 5, 10]:  # 計算 Alpha 動能
        df_daily[f'alpha_{n}'] = df_daily['gc'].pct_change(n) - df_daily['dc'].pct_change(n)  # 相對動能

    df_daily['ma20'] = df_daily['gc'].rolling(20).mean()  # 20MA
    df_daily['ma50'] = df_daily['gc'].rolling(50).mean()  # 50MA
    df_daily['ma60'] = df_daily['gc'].rolling(60).mean()  # 60MA
    df_daily['date'] = df_daily['timestamp'].dt.date  # 提取日期

    # 日線特徵改用「時間對齊」掛載 (取代原本的日曆日期 join + shift(1))，消除未來函數並對齊 EA 語意
    df_daily['daily_close_avail'] = df_daily['gc']  # 日收 (由 as-of join 保證已完結)
    df_daily['daily_ma50_avail'] = df_daily['ma50']  # 50MA
    df_daily['daily_ma20_avail'] = df_daily['ma20']  # 20MA
    df_daily['daily_ma60_avail'] = df_daily['ma60']  # 60MA
    df_daily['daily_alpha1_avail'] = df_daily['alpha_1']  # Alpha1
    df_daily['daily_alpha5_avail'] = df_daily['alpha_5']  # Alpha5
    df_daily['daily_alpha10_avail'] = df_daily['alpha_10']  # Alpha10

    gold_4h['timestamp'] = pd.to_datetime(gold_4h['timestamp'])  # 轉 datetime
    gold_4h = gold_4h.sort_values('timestamp').reset_index(drop=True)  # 排序
    gold_4h['date'] = gold_4h['timestamp'].dt.date  # 提取日期

    df = attach_daily_features(gold_4h, df_daily, ['daily_close_avail', 'daily_ma50_avail', 'daily_ma20_avail', 'daily_ma60_avail', 'daily_alpha1_avail', 'daily_alpha5_avail', 'daily_alpha10_avail'])  # 以 4H 收盤時間 as-of 對齊已完結之日線

    df['ma30_4h'] = df['close'].rolling(30).mean()  # 4H 30MA
    df['atr14_4h'] = calculate_atr(df, 14)  # 4H 14ATR
    df['dy_raw'] = df['close'].diff()  # 一階差
    df['sig_long_4h'] = (df['close'] > df['ma30_4h']) & (df['dy_raw'] > 0)  # 多頭訊號
    df = df.dropna().reset_index(drop=True)  # 去除空值

    baseline_atr = 16.0  # 基準 ATR 設定 (16.0 點)
    trades = []  # 交易記錄清單

    for is_long_only in [True, False]:  # 分別模擬多頭與空頭
        pos = []  # 當前持倉
        for i in range(len(df) - 1):  # 遍歷資料
            tc = df.loc[i, 'close']  # 收盤
            th = df.loc[i, 'high']  # 最高
            tl = df.loc[i, 'low']  # 最低
            tatr = df.loc[i, 'atr14_4h']  # 當期 ATR
            tph = df.loc[i-1, 'high'] if i > 0 else th  # 前高
            tpl = df.loc[i-1, 'low'] if i > 0 else tl  # 前低
            dy_c = df.loc[i, 'daily_close_avail']  # 日收
            dy_50 = df.loc[i, 'daily_ma50_avail']  # 50MA
            dy_20 = df.loc[i, 'daily_ma20_avail']  # 20MA
            dy_60 = df.loc[i, 'daily_ma60_avail']  # 60MA
            dy_a1 = df.loc[i, 'daily_alpha1_avail']  # Alpha1
            dy_a5 = df.loc[i, 'daily_alpha5_avail']  # Alpha5
            dy_a10 = df.loc[i, 'daily_alpha10_avail']  # Alpha10
            is_sig = df.loc[i, 'sig_long_4h']  # 訊號
            no = df.loc[i+1, 'open']  # 下期開盤
            ns = str(df.loc[i+1, 'timestamp'])  # 下期時間
            dy_pyr = (dy_a1 > 0 and dy_a5 > 0 and dy_a10 > 0 and dy_20 > dy_60) if is_long_only else (dy_a1 < 0 and dy_a5 < 0 and dy_a10 < 0 and dy_20 < dy_60)  # 加碼條件

            for p in pos:  # 更新 MAE
                w_loss = (tl - p['ep']) * p['u'] if is_long_only else (p['ep'] - th) * p['u']  # 計算逆向浮虧
                p['mae'] = min(p.get('mae', 0.0), w_loss)  # 記錄最差浮虧

            if is_long_only:  # 多單
                if len(pos) > 0:  # 有部位
                    m_pos = [p for p in pos if not p['pyr']][0]  # 主多單
                    p_pos = [p for p in pos if p['pyr']]  # 加多單
                    if tc < m_pos['sl'] or not is_sig:  # 平倉全數部位
                        exit_reason = 'Stop Loss Exit' if tc < m_pos['sl'] else 'Signal Exit'  # 平倉原因
                        for p in pos:  # 結算
                            hd = (pd.to_datetime(ns).date() - pd.to_datetime(p['ed']).date()).days  # 跨日天數
                            cost_pts = trade_cost_points(True, hd, exit_reason, tatr, DEFAULT_SCENARIO)  # Pepperstone Razor 成本模型
                            net_pnl = (no - p['ep'] - cost_pts) * p['u']  # 扣除點差+佣金+隔夜利息+滑價
                            trades.append({'type': 'Long', 'is_pyramid': p['pyr'], 'units': p['u'], 'entry_date': p['ed'], 'exit_date': ns, 'entry_price': p['ep'], 'exit_price': no, 'pnl_points': round(net_pnl, 2), 'mae_points': round(p.get('mae', 0.0), 2), 'atr_at_exit': round(float(tatr), 2) if pd.notna(tatr) else None, 'holding_hours': hd * 24, 'exit_reason': exit_reason})  # 記錄
                        pos = []  # 清空
                    else:  # 保留並更新停損
                        if tc > tph:  # 突破前高
                            m_pos['sl'] = min(tl, tpl) - 1.0 * tatr  # 移動停損
                        new_p = [m_pos]  # 新持倉
                        if len(p_pos) > 0:  # 已有加多
                            if tc < p_pos[0]['sl']:  # 觸發加多停損
                                hd = (pd.to_datetime(ns).date() - pd.to_datetime(p_pos[0]['ed']).date()).days  # 跨日天數
                                cost_pts = trade_cost_points(True, hd, 'Pyramid Stop Loss', tatr, DEFAULT_SCENARIO)  # 成本模型
                                net_pnl = (no - p_pos[0]['ep'] - cost_pts) * p_pos[0]['u']  # 扣成本
                                trades.append({'type': 'Long', 'is_pyramid': True, 'units': p_pos[0]['u'], 'entry_date': p_pos[0]['ed'], 'exit_date': ns, 'entry_price': p_pos[0]['ep'], 'exit_price': no, 'pnl_points': round(net_pnl, 2), 'mae_points': round(p_pos[0].get('mae', 0.0), 2), 'atr_at_exit': round(float(tatr), 2) if pd.notna(tatr) else None, 'holding_hours': hd * 24, 'exit_reason': 'Pyramid Stop Loss'})  # 記錄
                            else:  # 保留加多
                                if tc > tph:  # 突破前高
                                    p_pos[0]['sl'] = min(tl, tpl) - 1.0 * tatr  # 移動停損
                                new_p.append(p_pos[0])  # 保留
                        else:  # 51Bitquant 波動度自適應加碼
                            if dy_c > dy_50 and dy_pyr:  # 滿足加多條件
                                atr_ratio = baseline_atr / max(tatr, 4.0)  # 計算波動度倒數係數
                                base_mult = 2.0 if dy_a10 > 0.03 else 1.0  # 基礎乘數
                                u = min(2.5, max(0.5, base_mult * atr_ratio))  # 調制手數
                                if dy_a10 > 0.04 and u < 1.0:  # 超強單邊動能保底保護 (對齊 EA InpAlphaTrendFloor=1.0)
                                    u = 1.0  # 強制保底至 1.0x
                                u = quantize_units(u)  # 依 EA NormalizeLot 規則量化為實際可下單倍率
                                new_p.append({'pyr': True, 'u': u, 'ed': ns, 'ep': no, 'sl': min(tl, tpl) - 1.0 * tatr, 'mae': 0.0})  # 加多
                        pos = new_p  # 更新部位
                else:  # 空手主多
                    if dy_c > dy_50 and is_sig:  # 滿足主多
                        pos.append({'pyr': False, 'u': 1.0, 'ed': ns, 'ep': no, 'sl': min(tl, tpl) - 1.0 * tatr, 'mae': 0.0})  # 建立主多
            else:  # 空單
                if len(pos) > 0:  # 有空單部位
                    m_pos = [p for p in pos if not p['pyr']][0]  # 主空單
                    p_pos = [p for p in pos if p['pyr']]  # 加空單
                    if tc > m_pos['sl'] or is_sig:  # 出場全數空單
                        exit_reason = 'Stop Loss Exit' if tc > m_pos['sl'] else 'Signal Exit'  # 平倉原因
                        for p in pos:  # 結算
                            hd = (pd.to_datetime(ns).date() - pd.to_datetime(p['ed']).date()).days  # 跨日天數
                            cost_pts = trade_cost_points(False, hd, exit_reason, tatr, DEFAULT_SCENARIO)  # Pepperstone Razor 成本模型
                            net_pnl = (p['ep'] - no - cost_pts) * p['u']  # 扣除點差+佣金+隔夜利息+滑價
                            trades.append({'type': 'Short', 'is_pyramid': p['pyr'], 'units': p['u'], 'entry_date': p['ed'], 'exit_date': ns, 'entry_price': p['ep'], 'exit_price': no, 'pnl_points': round(net_pnl, 2), 'mae_points': round(p.get('mae', 0.0), 2), 'atr_at_exit': round(float(tatr), 2) if pd.notna(tatr) else None, 'holding_hours': hd * 24, 'exit_reason': exit_reason})  # 記錄
                        pos = []  # 清空
                    else:  # 保留並更新
                        if tc < tpl:  # 跌破前低
                            m_pos['sl'] = max(th, tph) + 1.0 * tatr  # 向下移動停損
                        new_p = [m_pos]  # 新持倉
                        if len(p_pos) > 0:  # 已加空
                            if tc > p_pos[0]['sl']:  # 觸發加空停損
                                hd = (pd.to_datetime(ns).date() - pd.to_datetime(p_pos[0]['ed']).date()).days  # 天數
                                cost_pts = trade_cost_points(False, hd, 'Pyramid Stop Loss', tatr, DEFAULT_SCENARIO)  # 成本模型
                                net_pnl = (p_pos[0]['ep'] - no - cost_pts) * p_pos[0]['u']  # 扣成本
                                trades.append({'type': 'Short', 'is_pyramid': True, 'units': p_pos[0]['u'], 'entry_date': p_pos[0]['ed'], 'exit_date': ns, 'entry_price': p_pos[0]['ep'], 'exit_price': no, 'pnl_points': round(net_pnl, 2), 'mae_points': round(p_pos[0].get('mae', 0.0), 2), 'atr_at_exit': round(float(tatr), 2) if pd.notna(tatr) else None, 'holding_hours': hd * 24, 'exit_reason': 'Pyramid Stop Loss'})  # 記錄
                            else:  # 保留加空
                                if tc < tpl:  # 跌破前低
                                    p_pos[0]['sl'] = max(th, tph) + 1.0 * tatr  # 移動停損
                                new_p.append(p_pos[0])  # 保留
                        else:  # 51Bitquant 波動度自適應加空
                            if dy_c < dy_50 and dy_pyr:  # 滿足加空條件
                                atr_ratio = baseline_atr / max(tatr, 4.0)  # 計算波動度係數
                                base_mult = 2.0 if dy_a10 < -0.03 else 1.0  # 基礎乘數
                                u = min(2.5, max(0.5, base_mult * atr_ratio))  # 調制手數
                                if dy_a10 < -0.04 and u < 1.0:  # 超強單邊空頭動能保底保護 (對齊 EA InpAlphaTrendFloor=1.0)
                                    u = 1.0  # 強制保底至 1.0x
                                u = quantize_units(u)  # 依 EA NormalizeLot 規則量化為實際可下單倍率
                                new_p.append({'pyr': True, 'u': u, 'ed': ns, 'ep': no, 'sl': max(th, tph) + 1.0 * tatr, 'mae': 0.0})  # 加空
                        pos = new_p  # 更新持倉
                else:  # 空手主空
                    if dy_c < dy_50 and not is_sig:  # 滿足主空
                        pos.append({'pyr': False, 'u': 1.0, 'ed': ns, 'ep': no, 'sl': max(th, tph) + 1.0 * tatr, 'mae': 0.0})  # 建立主空

    df_trades_4yr = pd.DataFrame(trades).sort_values('exit_date').reset_index(drop=True)  # 排序交易記錄
    for idx, t in enumerate(df_trades_4yr.to_dict('records')):  # 重設流水號
        df_trades_4yr.loc[idx, 'trade_id'] = idx + 1  # 賦予 ID
    df_trades_4yr['trade_id'] = df_trades_4yr['trade_id'].astype(int)  # 轉為整數
    
    # 績效統計
    pnl_series = df_trades_4yr['pnl_points']  # 損益數列
    total_pnl = round(pnl_series.sum(), 2)  # 總獲利
    cum_pnl = pnl_series.cumsum()  # 累積權益
    mdd = round(float((cum_pnl.cummax() - cum_pnl).max()), 2)  # 最大已平倉回撤
    win_trades = df_trades_4yr[df_trades_4yr['pnl_points'] > 0]  # 獲利筆數
    loss_trades = df_trades_4yr[df_trades_4yr['pnl_points'] < 0]  # 虧損筆數
    win_rate = round(len(win_trades) / len(df_trades_4yr) * 100, 2)  # 勝率
    pf = round(abs(win_trades['pnl_points'].sum() / loss_trades['pnl_points'].sum()), 2)  # 盈虧比
    
    first_d = pd.to_datetime(df_trades_4yr['entry_date'].min())  # 起始日期
    last_d = pd.to_datetime(df_trades_4yr['exit_date'].max())  # 結束日期
    years = (last_d - first_d).days / 365.25  # 統計年數 (約 3.63 年)
    annual_pnl = round(total_pnl / years, 2)  # 年化獲利
    calmar = round(annual_pnl / mdd, 2) if mdd > 0 else 0.0  # 卡瑪比率
    sharpe = round(float((pnl_series.mean() / pnl_series.std()) * np.sqrt(252)), 2) if pnl_series.std() > 0 else 0.0  # 夏普比率

    # 計算 4 年逐根浮動淨值回撤
    trade_exit_map_4yr = {}  # 4 年出場映射
    parsed_trades_4yr = []  # 預解析
    for _, t in df_trades_4yr.iterrows():  # 遍歷
        trade_exit_map_4yr[t['exit_date']] = trade_exit_map_4yr.get(t['exit_date'], 0.0) + t['pnl_points']  # 累積
        parsed_trades_4yr.append({  # 構造
            'type': t['type'], 'units': t['units'], 'entry_price': t['entry_price'],  # 執行策略運算
            'entry_dt': pd.Timestamp(t['entry_date']), 'exit_dt': pd.Timestamp(t['exit_date'])  # 執行策略運算
        })  # 結束

    bar_eq_4yr = []  # 4 年淨值
    bar_fl_close_4yr = []  # 4 年收盤浮虧
    bar_fl_worst_4yr = []  # 4 年極端浮虧
    cum_tracker = 0.0  # 追蹤

    for i in range(len(df) - 1):  # 遍歷 K 線
        tc = df.loc[i, 'close']  # 收盤
        th = df.loc[i, 'high']  # 最高
        tl = df.loc[i, 'low']  # 最低
        cur_t = df.loc[i, 'timestamp']  # 時間
        cur_t_str = str(cur_t)  # 字串
        if cur_t_str in trade_exit_map_4yr:  # 平倉
            cum_tracker += trade_exit_map_4yr[cur_t_str]  # 累加
        fl_c = 0.0  # 收盤浮虧
        fl_w = 0.0  # 極端浮虧
        for t in parsed_trades_4yr:  # 遍歷
            if t['entry_dt'] <= cur_t < t['exit_dt']:  # 持倉中
                if t['type'] == 'Long':  # 多
                    fl_c += (tc - t['entry_price']) * t['units']  # 收盤
                    fl_w += (tl - t['entry_price']) * t['units']  # 最低
                else:  # 空
                    fl_c += (t['entry_price'] - tc) * t['units']  # 收盤
                    fl_w += (t['entry_price'] - th) * t['units']  # 最高
        bar_fl_close_4yr.append(round(fl_c, 2))  # 記錄
        bar_fl_worst_4yr.append(round(fl_w, 2))  # 記錄
        bar_eq_4yr.append(round(cum_tracker + fl_c, 2))  # 記錄

    eq_arr_4yr = np.array(bar_eq_4yr)  # 轉陣列
    floating_mdd_4yr = round(float((np.maximum.accumulate(eq_arr_4yr) - eq_arr_4yr).max()), 2) if len(eq_arr_4yr) > 0 else 0.0  # 4年浮動回撤
    max_instant_float_loss_4yr = round(float(min(bar_fl_close_4yr)), 2) if bar_fl_close_4yr else 0.0  # 4年最大浮虧

    # 匯出 4 年回測 CSV
    df_trades_4yr.to_csv('all_trades_4yr_adaptive.csv', index=False, encoding='utf-8-sig')  # 儲存明細

    # 繪製 4 年權益曲線圖
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True, gridspec_kw={'height_ratios': [3, 1]})  # 建立雙子圖
    dates = pd.to_datetime(df_trades_4yr['exit_date'])  # 時間軸
    ax1.plot(dates, cum_pnl, label='4-Year 51Bitquant Dynamic ATR Equity Curve', color='#00e676', linewidth=2.0)  # 權益線
    ax1.set_title(f'XAUUSD 4H 30MA 4-Year Backtest (5,585 Bars) - Total PnL: +{total_pnl:.2f} pts | Calmar: {calmar} | MDD: {mdd:.1f} pts | Floating MDD: {floating_mdd_4yr:.1f} pts', fontsize=13, fontweight='bold')  # 標題
    ax1.set_ylabel('Cumulative PnL (Points)', fontsize=12)  # Y 軸標籤
    ax1.grid(True, linestyle='--', alpha=0.5)  # 網格線
    ax1.legend(loc='upper left', fontsize=11)  # 圖例

    dd_series = (cum_pnl.cummax() - cum_pnl) * -1.0  # 負回撤數列
    ax2.fill_between(dates, dd_series, 0, color='#ef5350', alpha=0.4, label='Underwater Drawdown (Points)')  # 填色
    ax2.plot(dates, dd_series, color='#ef5350', linewidth=1.2)  # 回撤線
    ax2.set_ylabel('Drawdown (Pts)', fontsize=12)  # Y 軸標籤
    ax2.set_xlabel('Date', fontsize=12)  # X 軸標籤
    ax2.grid(True, linestyle='--', alpha=0.5)  # 網格線
    ax2.legend(loc='lower left', fontsize=11)  # 圖例

    plt.tight_layout()  # 自動排版
    plt.savefig('backtest_equity_curve_4yr_adaptive.png', dpi=300)  # 儲存圖檔
    plt.close()  # 關閉釋放

    # 4年當前回撤計算
    peak_4yr = float(cum_pnl.max()) if len(cum_pnl) > 0 else 0.0  # 4年歷史權益峰值
    cur_pnl_4yr = float(cum_pnl.iloc[-1]) if len(cum_pnl) > 0 else 0.0  # 4年當前累積損益
    cur_dd_4yr = round(peak_4yr - cur_pnl_4yr, 2)  # 4年當前回撤點數
    cur_dd_pct_4yr = round(cur_dd_4yr / peak_4yr * 100, 2) if peak_4yr > 0 else 0.0  # 4年當前回撤比例

    cost_sensitivity_4yr = compute_cost_sensitivity(df_trades_4yr.to_dict('records'))  # Pepperstone 成本情境敏感度 (best/typical/stress)

    # 單筆 MAE 統計 (補齊網頁 4 年模式所需欄位，避免前端退回顯示過期的預設值)
    pyr_maes_4yr = df_trades_4yr[df_trades_4yr['is_pyramid']]['mae_points']  # 加碼單 MAE 序列
    worst_pyr_mae_4yr = round(float(pyr_maes_4yr.min()), 2) if len(pyr_maes_4yr) > 0 else 0.0  # 加碼單最大逆向浮虧
    worst_single_mae_4yr = round(float(df_trades_4yr['mae_points'].min()), 2) if len(df_trades_4yr) > 0 else 0.0  # 單筆最大逆向浮虧

    # 與原始固定倉位版對照 (基準值產生於舊成本模型與舊日線對齊，非同基準比較，百分比改為動態計算)
    MDD_WATCH_4YR = 907.0  # 原始版 4 年最大已平倉回撤
    FLOAT_MDD_WATCH_4YR = 824.0  # 原始版 4 年浮動淨值最大回撤
    mdd_red_4yr = round((MDD_WATCH_4YR - mdd) / MDD_WATCH_4YR * 100, 1)  # 回撤降低比例
    float_mdd_red_4yr = round((FLOAT_MDD_WATCH_4YR - floating_mdd_4yr) / FLOAT_MDD_WATCH_4YR * 100, 1)  # 浮動回撤降低比例

    # 更新 strategy_results.json 加入 4 年全歷史指標
    if os.path.exists('strategy_results.json'):  # 檢查 JSON
        with open('strategy_results.json', 'r', encoding='utf-8') as f:  # 讀取
            res_json = json.load(f)  # 解析
        res_json['metrics_4yr'] = {  # 寫入 4 年指標
            'total_trades': len(df_trades_4yr),  # 筆數
            'total_pnl_points': total_pnl,  # 總獲利
            'annual_pnl_points': annual_pnl,  # 年化
            'win_rate': win_rate,  # 勝率
            'profit_factor': pf,  # 盈虧比
            'max_drawdown': mdd,  # 最大回撤
            'current_drawdown': cur_dd_4yr,  # 當前回撤點數
            'current_drawdown_pct': cur_dd_pct_4yr,  # 當前回撤比例
            'floating_drawdown_points': floating_mdd_4yr,  # 浮動回撤
            'max_instant_float_loss': max_instant_float_loss_4yr,  # 最大浮虧
            'max_instant_float_loss_close': max_instant_float_loss_4yr,  # 最大浮虧 (與 2.1 年欄位命名一致，供前端讀取)
            'worst_pyramid_mae': worst_pyr_mae_4yr,  # 加碼單最大逆向浮虧
            'worst_single_mae': worst_single_mae_4yr,  # 單筆最大逆向浮虧
            'calmar_ratio': calmar,  # 卡瑪比率
            'sharpe_ratio': sharpe,  # 夏普比率
            'years': round(years, 2),  # 統計年數
            'cost_scenario_used': DEFAULT_SCENARIO,  # 主指標所用成本情境
            'cost_sensitivity': cost_sensitivity_4yr,  # best/typical/stress 三情境對照 (swap/滑價為非官方保守估計)
            'comparison_with_watch': {  # 與原始固定倉位版對照 (百分比動態計算)
                'baseline_is_comparable': False,  # 基準來自舊成本模型與舊對齊，不可直接比較
                'mdd_watch': MDD_WATCH_4YR,  # 原始版回撤
                'mdd_reduction_pct': mdd_red_4yr,  # 回撤降低比例
                'floating_mdd_watch': FLOAT_MDD_WATCH_4YR,  # 原始版浮動回撤
                'floating_mdd_reduction_pct': float_mdd_red_4yr  # 浮動回撤降低比例
            }  # 對照結束
        }  # 結束
        with open('strategy_results.json', 'w', encoding='utf-8') as f:  # 寫回
            json.dump(res_json, f, ensure_ascii=False, indent=2)  # 格式化寫入

    print("==========================================================================")  # 分隔線
    print("🏆 【4 年黃金 4H (5,585 根 K 線) 51Bitquant 自適應回測結果】")  # 標題
    print("==========================================================================")  # 分隔線
    print(f" • 數據期間:           {first_d.strftime('%Y-%m-%d')} 至 {last_d.strftime('%Y-%m-%d')} ({years:.2f} 年)")  # 時間
    print(f" • 總累積獲利:         +{total_pnl:.2f} 點 (年化獲利: {annual_pnl:.1f} 點/年)")  # 獲利
    print(f" • 總成交筆數:         {len(df_trades_4yr)} 筆 (勝率: {win_rate}%)")  # 筆數與勝率
    print(f" • 盈虧比 (PF):        {pf}")  # 盈虧比
    print(f" • 最大已平倉回撤:     {mdd:.2f} 點 (相較原始版 {MDD_WATCH_4YR:.0f} 點降 {mdd_red_4yr}%)")  # 回撤 (百分比動態計算)
    print(f" • 浮動淨值最大回撤:   {floating_mdd_4yr:.2f} 點 (相較原始版 {FLOAT_MDD_WATCH_4YR:.0f} 點降 {float_mdd_red_4yr}%)")  # 浮動回撤 (百分比動態計算)
    print("   ⚠️ 上述對照基準來自舊成本模型與舊日線對齊，非同基準比較，僅供粗略參考")  # 標註基準限制
    print(f" • 卡瑪比率 (Calmar):   {calmar}")  # 卡瑪
    print(f" • 夏普比率 (Sharpe):   {sharpe}")  # 夏普
    print(" • 已輸出檔案: all_trades_4yr_adaptive.csv, backtest_equity_curve_4yr_adaptive.png")  # 檔案
    print("--------------------------------------------------------------------------")  # 分隔線
    print(f" 💰 成本情境敏感度分析 (Pepperstone Razor 帳戶, 主指標採用: {DEFAULT_SCENARIO})")  # 標題
    print("    ⚠️ 點差/佣金為官網公告數值；swap 與停損滑價為非官方保守估計，僅供參考")  # 警語
    for sc_name, sc_val in cost_sensitivity_4yr.items():  # 遍歷三種情境
        print(f"    - {sc_name:15s}: 總損益 {sc_val['total_pnl_points']:>9.2f} 點 | MDD {sc_val['max_drawdown']:>8.2f} 點 | 勝率 {sc_val['win_rate']:>6.2f}% | PF {sc_val['profit_factor']:>5.2f}")  # 輸出各情境
    print("==========================================================================\n")  # 結束線

if __name__ == '__main__':  # 主執行入口
    run_4yr_adaptive_backtest()  # 啟動 4 年回測
