import os  # 匯入作業系統模組以讀取檔案
import pandas as pd  # 匯入 pandas 處理表格
import numpy as np  # 匯入 numpy 數值計算
from strategy_arena.base import BaseStrategy  # 匯入策略基類

# 凍結不可動的真實數據源 (TradingView 下載檔)
PATH_4H_4YR = "/Users/evan/Desktop/Github_Projects/Gold_Strategy_Watch/xauusd_4h_4yr.csv"  # 4 年 4H K 線檔
PATH_GOLD_D = "/Users/evan/Desktop/Github_Projects/Gold_Strategy_Watch/xauusd_daily_4yr.csv"  # 黃金日線檔
PATH_DXY_D  = "/Users/evan/Desktop/Github_Projects/Gold_Strategy_Watch/dxy_daily_4yr.csv"  # 美元指數日線檔

def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:  # 計算 14 週期 ATR 函數
    high = df['high']  # 當期最高價
    low = df['low']  # 當期最低價
    close_prev = df['close'].shift(1)  # 前一期收盤價
    tr1 = high - low  # 高低差
    tr2 = (high - close_prev).abs()  # 最高與前收差
    tr3 = (low - close_prev).abs()  # 最低與前收差
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)  # 取最大值 TR
    return tr.rolling(period).mean()  # 14 週期滑動平均

def load_and_prepare_data(csv_4h: str = PATH_4H_4YR, csv_gd: str = PATH_GOLD_D, csv_dxy: str = PATH_DXY_D) -> pd.DataFrame:  # 資料載入與基礎特徵生成
    df_4h = pd.read_csv(csv_4h)  # 讀取 4H 資料
    df_gd = pd.read_csv(csv_gd).rename(columns={'close': 'gc', 'open': 'go', 'high': 'gh', 'low': 'gl'})  # 讀取黃金日線
    df_dxy = pd.read_csv(csv_dxy).rename(columns={'close': 'dc', 'open': 'do', 'high': 'dh', 'low': 'dl'})  # 讀取 DXY 日線

    df_4h['timestamp'] = pd.to_datetime(df_4h['timestamp'])  # 轉為 datetime
    df_gd['timestamp'] = pd.to_datetime(df_gd['timestamp'])  # 轉為 datetime
    df_dxy['timestamp'] = pd.to_datetime(df_dxy['timestamp'])  # 轉為 datetime

    df_daily = pd.merge(df_gd, df_dxy, on='timestamp', how='inner').sort_values('timestamp').reset_index(drop=True)  # 合併日線
    for n in [1, 5, 10]:  # 計算 Alpha 動能
        df_daily[f'alpha_{n}'] = df_daily['gc'].pct_change(n) - df_daily['dc'].pct_change(n)  # 黃金減美元收益

    df_daily['ma20'] = df_daily['gc'].rolling(20).mean()  # 日線 20MA
    df_daily['ma50'] = df_daily['gc'].rolling(50).mean()  # 日線 50MA (Regime)
    df_daily['ma60'] = df_daily['gc'].rolling(60).mean()  # 日線 60MA
    df_daily['date'] = df_daily['timestamp'].dt.date  # 提取日期

    # 嚴格 T-1 偏移以杜絕任何未來數據
    df_daily['daily_close_avail'] = df_daily['gc'].shift(1)  # T-1 日收
    df_daily['daily_ma50_avail'] = df_daily['ma50'].shift(1)  # T-1 50MA
    df_daily['daily_ma20_avail'] = df_daily['ma20'].shift(1)  # T-1 20MA
    df_daily['daily_ma60_avail'] = df_daily['ma60'].shift(1)  # T-1 60MA
    df_daily['daily_alpha1_avail'] = df_daily['alpha_1'].shift(1)  # T-1 Alpha1
    df_daily['daily_alpha5_avail'] = df_daily['alpha_5'].shift(1)  # T-1 Alpha5
    df_daily['daily_alpha10_avail'] = df_daily['alpha_10'].shift(1)  # T-1 Alpha10

    df_4h['date'] = df_4h['timestamp'].dt.date  # 提取 4H 日期
    df = pd.merge(df_4h, df_daily[['date', 'daily_close_avail', 'daily_ma50_avail', 'daily_ma20_avail', 'daily_ma60_avail', 'daily_alpha1_avail', 'daily_alpha5_avail', 'daily_alpha10_avail']], on='date', how='left').ffill()  # 合併

    df['ma30_4h'] = df['close'].rolling(30).mean()  # 4H 30MA
    df['atr14_4h'] = calculate_atr(df, 14)  # 4H 14ATR
    df['dy_raw'] = df['close'].diff()  # 一階差
    df['sig_long_4h'] = (df['close'] > df['ma30_4h']) & (df['dy_raw'] > 0)  # 多頭訊號

    return df.dropna().reset_index(drop=True)  # 回傳乾淨資料集

def backtest_strategy(strategy: BaseStrategy, raw_df: pd.DataFrame) -> dict:  # 執行不可動撮合與績效統計函數
    df = strategy.prepare_indicators(raw_df.copy())  # 讓策略掛鉤自定義指標
    trades = []  # 完結交易紀錄清單

    for is_long_only in [True, False]:  # 獨立執行多頭與空頭子撮合
        pos = []  # 當前持倉部位
        for i in range(len(df) - 1):  # 逐根 K 線撮合
            row = df.iloc[i]  # 當前 K 線資料
            tc, th, tl, tatr = row['close'], row['high'], row['low'], row['atr14_4h']  # 價格與 ATR
            tph = df.loc[i-1, 'high'] if i > 0 else th  # 前一根高
            tpl = df.loc[i-1, 'low'] if i > 0 else tl  # 前一根低

            dy_c = row['daily_close_avail']  # 日線前收
            dy_50 = row['daily_ma50_avail']  # 日線 50MA
            dy_20 = row['daily_ma20_avail']  # 日線 20MA
            dy_60 = row['daily_ma60_avail']  # 日線 60MA
            dy_a1 = row['daily_alpha1_avail']  # Alpha1
            dy_a5 = row['daily_alpha5_avail']  # Alpha5
            dy_a10 = row['daily_alpha10_avail']  # Alpha10

            default_sig = row['sig_long_4h']  # 預設 30MA 訊號
            is_sig = strategy.filter_entry(row, is_long_only, default_sig)  # 呼叫策略進場過濾鉤子
            no = df.loc[i+1, 'open']  # 下期開盤價
            ns = str(df.loc[i+1, 'timestamp'])  # 下期時間戳記

            # 加碼判定條件
            dy_pyr = (dy_a1 > 0 and dy_a5 > 0 and dy_a10 > 0 and dy_20 > dy_60) if is_long_only else (dy_a1 < 0 and dy_a5 < 0 and dy_a10 < 0 and dy_20 < dy_60)

            if is_long_only:  # 多單引擎
                if len(pos) > 0:  # 持有多單
                    m_pos = [p for p in pos if not p['pyr']][0]  # 主多單
                    p_pos = [p for p in pos if p['pyr']]  # 加多單

                    if tc < m_pos['sl'] or not is_sig:  # 觸發平倉
                        for p in pos:  # 結算部位
                            hd = (pd.to_datetime(ns).date() - pd.to_datetime(p['ed']).date()).days  # 跨日持有天數
                            net_pnl = (no - p['ep'] - 0.3 - (hd * 0.75)) * p['u']  # 扣除點差 0.3 與每日 0.75 隔夜費
                            trades.append({'type': 'Long', 'is_pyr': p['pyr'], 'u': p['u'], 'ed': p['ed'], 'xd': ns, 'pnl': round(net_pnl, 2)})  # 記錄
                        pos = []  # 清空
                    else:  # 保留並更新停損
                        if tc > tph:  # 突破前高
                            m_pos['sl'] = strategy.filter_exit(row, m_pos, min(tl, tpl) - 1.0 * tatr)  # 呼叫出場鉤子
                        new_p = [m_pos]  # 新部位清單

                        if len(p_pos) > 0:  # 已有加多單
                            if tc < p_pos[0]['sl']:  # 觸發加多停損
                                hd = (pd.to_datetime(ns).date() - pd.to_datetime(p_pos[0]['ed']).date()).days  # 跨日天數
                                net_pnl = (no - p_pos[0]['ep'] - 0.3 - (hd * 0.75)) * p_pos[0]['u']  # 扣除成本
                                trades.append({'type': 'Long', 'is_pyr': True, 'u': p_pos[0]['u'], 'ed': p_pos[0]['ed'], 'xd': ns, 'pnl': round(net_pnl, 2)})  # 記錄
                            else:  # 保留加多單
                                if tc > tph:  # 突破前高
                                    p_pos[0]['sl'] = strategy.filter_exit(row, p_pos[0], min(tl, tpl) - 1.0 * tatr)  # 呼叫出場鉤子
                                new_p.append(p_pos[0])  # 保留
                        else:  # 檢查是否加多
                            if dy_c > dy_50 and dy_pyr:  # 滿足加多
                                base_u = 2.0 if dy_a10 > 0.03 else 1.0  # 基礎加碼手數
                                final_u = strategy.calculate_pyramid_size(row, is_long_only, base_u)  # 呼叫加碼手數調制鉤子
                                if final_u > 0:  # 若允許加碼
                                    new_p.append({'pyr': True, 'u': final_u, 'ed': ns, 'ep': no, 'sl': min(tl, tpl) - 1.0 * tatr})  # 建立加多
                        pos = new_p  # 更新持倉
                else:  # 空手建立主多
                    if dy_c > dy_50 and is_sig:  # 滿足主多條件
                        pos.append({'pyr': False, 'u': 1.0, 'ed': ns, 'ep': no, 'sl': min(tl, tpl) - 1.0 * tatr})  # 建立主多單

            else:  # 空單引擎
                if len(pos) > 0:  # 持有空單
                    m_pos = [p for p in pos if not p['pyr']][0]  # 主空單
                    p_pos = [p for p in pos if p['pyr']]  # 加空單

                    if tc > m_pos['sl'] or is_sig:  # 觸發平倉
                        for p in pos:  # 結算空單
                            hd = (pd.to_datetime(ns).date() - pd.to_datetime(p['ed']).date()).days  # 跨日天數
                            net_pnl = (p['ep'] - no - 0.3 + (hd * 0.27)) * p['u']  # 扣除點差 0.3 並加上每日 0.27 正利息
                            trades.append({'type': 'Short', 'is_pyr': p['pyr'], 'u': p['u'], 'ed': p['ed'], 'xd': ns, 'pnl': round(net_pnl, 2)})  # 記錄
                        pos = []  # 清空
                    else:  # 保留空單
                        if tc < tpl:  # 跌破前低
                            m_pos['sl'] = strategy.filter_exit(row, m_pos, max(th, tph) + 1.0 * tatr)  # 呼叫出場鉤子
                        new_p = [m_pos]  # 新持倉清單

                        if len(p_pos) > 0:  # 已有加空單
                            if tc > p_pos[0]['sl']:  # 觸發加空停損
                                hd = (pd.to_datetime(ns).date() - pd.to_datetime(p_pos[0]['ed']).date()).days  # 天數
                                net_pnl = (p_pos[0]['ep'] - no - 0.3 + (hd * 0.27)) * p_pos[0]['u']  # 扣除成本加利息
                                trades.append({'type': 'Short', 'is_pyr': True, 'u': p_pos[0]['u'], 'ed': p_pos[0]['ed'], 'xd': ns, 'pnl': round(net_pnl, 2)})  # 記錄
                            else:  # 保留加空
                                if tc < tpl:  # 跌破前低
                                    p_pos[0]['sl'] = strategy.filter_exit(row, p_pos[0], max(th, tph) + 1.0 * tatr)  # 呼叫出場鉤子
                                new_p.append(p_pos[0])  # 保留
                        else:  # 檢查是否加空
                            if dy_c < dy_50 and dy_pyr:  # 滿足加空
                                base_u = 2.0 if dy_a10 < -0.03 else 1.0  # 基礎加空手數
                                final_u = strategy.calculate_pyramid_size(row, is_long_only, base_u)  # 呼叫加碼手數調制鉤子
                                if final_u > 0:  # 若允許加空
                                    new_p.append({'pyr': True, 'u': final_u, 'ed': ns, 'ep': no, 'sl': max(th, tph) + 1.0 * tatr})  # 建立加空
                        pos = new_p  # 更新持倉
                else:  # 空手建立主空單
                    if dy_c < dy_50 and not is_sig:  # 滿足主空條件
                        pos.append({'pyr': False, 'u': 1.0, 'ed': ns, 'ep': no, 'sl': max(th, tph) + 1.0 * tatr})  # 建立主空單

    tdf = pd.DataFrame(trades).sort_values('xd').reset_index(drop=True)  # 排序交易明細
    pnls = tdf['pnl'].values if len(tdf) > 0 else np.array([0.0])  # 提取每筆損益
    eq = np.cumsum(pnls)  # 累積權益
    mdd = float(np.max(np.maximum.accumulate(eq) - eq)) if len(eq) > 0 else 0.0  # 最大回撤
    win_t = tdf[tdf['pnl'] > 0]  # 獲利單
    loss_t = tdf[tdf['pnl'] < 0]  # 虧損單
    wr = len(win_t) / len(tdf) * 100 if len(tdf) > 0 else 0.0  # 勝率
    pf = win_t['pnl'].sum() / abs(loss_t['pnl'].sum()) if len(loss_t) > 0 else 0.0  # 盈虧比
    sharpe = float((pnls.mean() / pnls.std()) * np.sqrt(252)) if pnls.std() > 0 else 0.0  # 夏普比率

    first_d = pd.to_datetime(tdf['ed'].min()) if len(tdf) > 0 else pd.to_datetime('2023-01-01')  # 起始日
    last_d = pd.to_datetime(tdf['xd'].max()) if len(tdf) > 0 else pd.to_datetime('2026-08-01')  # 結束日
    years = max((last_d - first_d).days / 365.25, 0.5)  # 統計年數
    ann_pnl = pnls.sum() / years  # 年化獲利
    calmar = ann_pnl / mdd if mdd > 0 else 0.0  # 卡瑪比率

    return {  # 回傳回測統計結果
        'name': strategy.name, 'desc': strategy.description, 'total_pnl': pnls.sum(),
        'annual_pnl': ann_pnl, 'trades': len(tdf), 'win_rate': wr, 'pf': pf,
        'mdd': mdd, 'sharpe': sharpe, 'calmar': calmar, 'years': years,
        'equity_curve': eq, 'dates': pd.to_datetime(tdf['xd']) if len(tdf) > 0 else []
    }
