import os  # 匯入作業系統模組以處理檔案路徑
import json  # 匯入 JSON 模組以導出網頁資料
import datetime  # 匯入 datetime 模組進行時區轉換
import pandas as pd  # 匯入 pandas 模組進行資料分析與表格處理
import numpy as np  # 匯入 numpy 模組進行數值計算
import matplotlib.pyplot as plt  # 匯入 matplotlib 繪製回測權益曲線圖
from tvDatafeed import TvDatafeed, Interval  # 匯入 tvDatafeed 以抓取 TradingView 資料
from cost_model import trade_cost_points, COST_SCENARIOS, DEFAULT_SCENARIO  # 匯入 Pepperstone Razor 成本模型 (點差/佣金/隔夜利息估計/停損滑價)
from daily_align import attach_daily_features  # 匯入日線時間對齊模組 (消除未來函數並對齊 EA 的 iClose(PERIOD_D1,1) 語意)
from ea_sizing import quantize_units  # 匯入 EA 手數量化模組 (對齊 EA NormalizeLot 的無條件捨去規則)
from trend_filter import add_curvature, curvature_pass, CURVATURE_THRESHOLD  # 匯入趨勢曲率過濾 (30MA 二次微分)

# 美元指數資料源：改用券商自身的 PEPPERSTONE:USDX，對齊 EA 參數 InpDXYSymbol="USDX"
# (原本使用外部的 ICEUS:DXY 指數，與 EA 實際讀取的商品不同，且日線邊界與 XAUUSD 不一致)
DXY_DAILY_FILE = 'pepperstone_usdx_daily.csv'  # 美元指數日線檔案路徑
# 黃金資料一律使用 PEPPERSTONE:XAUUSD；4H 由 1H 合成 UTC +0h 網格，與 EA 的 K 棒切分完全一致
GOLD_4H_FILE = 'pepperstone_xauusd_4h.csv'  # 黃金 4H (1H 合成，EA 同網格)
GOLD_DAILY_FILE = 'pepperstone_xauusd_daily.csv'  # 黃金日線

def download_data(force=False):  # 定義下載數據的函數
    if not force and os.path.exists(GOLD_4H_FILE) and os.path.exists(GOLD_DAILY_FILE) and os.path.exists(DXY_DAILY_FILE):  # 若本地數據檔案皆已存在
        print("⚡ 本地數據已就緒，直接使用本地高精準數據庫進行回測...")  # 印出本地就緒提示
        return  # 直接返回
    print("正在檢查並下載最新 K 線數據...")  # 印出下載提示訊息
    try:  # 嘗試初始化與下載
        tv = TvDatafeed()  # 初始化 TradingView 匿名客戶端實例
        local_utc_offset = datetime.datetime.now().astimezone().utcoffset()  # 取得本機 UTC 偏移量
        utc8_offset = datetime.timedelta(hours=8)  # 定義台北時間 (UTC+8) 的固定偏移量
        tz_correction = utc8_offset - local_utc_offset  # 計算時區修正量
        try:  # 嘗試下載 Pepperstone USDX 美元指數日線
            # 使用券商自身的 USDX CFD (對齊 EA 參數 InpDXYSymbol="USDX")；
            # 同時因與 XAUUSD 同屬 Pepperstone，日線邊界一致，優於外部的 ICEUS:DXY 指數。
            df_dxy = tv.get_hist(symbol='USDX', exchange='PEPPERSTONE', interval=Interval.in_daily, n_bars=5000)  # 下載美元指數日線資料
            if df_dxy is not None and not df_dxy.empty:  # 檢查美元指數資料是否成功取得
                df_dxy = df_dxy.reset_index()  # 重設索引
                df_dxy['datetime'] = pd.to_datetime(df_dxy['datetime']) + tz_correction  # 修正為 UTC+8
                df_dxy = df_dxy.rename(columns={'datetime': 'timestamp'})  # 重新命名欄位
                df_dxy['timestamp'] = df_dxy['timestamp'].dt.strftime('%Y-%m-%d')  # 格式化日期
                df_new_dxy = df_dxy[['timestamp', 'open', 'high', 'low', 'close']]  # 取標準五欄位
                if os.path.exists(DXY_DAILY_FILE):  # 檢查舊檔
                    df_old_dxy = pd.read_csv(DXY_DAILY_FILE)  # 讀取舊 CSV
                    df_new_dxy = pd.concat([df_old_dxy, df_new_dxy]).drop_duplicates(subset=['timestamp'], keep='last').sort_values('timestamp').reset_index(drop=True)  # 合併去重
                df_new_dxy.to_csv(DXY_DAILY_FILE, index=False)  # 儲存 CSV
                print("✅ Pepperstone USDX 美元指數日線下載與合併成功")  # 印出成功提示
        except Exception as e_dxy:  # 捕捉 DXY 異常
            print(f"⚠️ Pepperstone USDX 下載警告: {e_dxy}")  # 印出警告

        try:  # 嘗試下載 Pepperstone XAUUSD 黃金日線
            df_gold_d = tv.get_hist(symbol='XAUUSD', exchange='PEPPERSTONE', interval=Interval.in_daily, n_bars=5000)  # 下載黃金日線
            if df_gold_d is not None and not df_gold_d.empty:  # 檢查資料
                df_gold_d = df_gold_d.reset_index()  # 重設索引
                df_gold_d['datetime'] = pd.to_datetime(df_gold_d['datetime']) + tz_correction  # 修正為 UTC+8
                df_gold_d = df_gold_d.rename(columns={'datetime': 'timestamp'})  # 重新命名欄位
                df_gold_d['timestamp'] = df_gold_d['timestamp'].dt.strftime('%Y-%m-%d')  # 格式化日期
                df_new_gd = df_gold_d[['timestamp', 'open', 'high', 'low', 'close']]  # 取標準五欄位
                if os.path.exists(GOLD_DAILY_FILE):  # 檢查舊檔
                    df_old_gd = pd.read_csv(GOLD_DAILY_FILE)  # 讀取舊檔
                    df_new_gd = pd.concat([df_old_gd, df_new_gd]).drop_duplicates(subset=['timestamp'], keep='last').sort_values('timestamp').reset_index(drop=True)  # 合併去重
                df_new_gd.to_csv(GOLD_DAILY_FILE, index=False)  # 儲存 CSV
                print("✅ Pepperstone XAUUSD 日線下載與合併成功")  # 印出成功提示
        except Exception as e_gd:  # 捕捉日線異常
            print(f"⚠️ Pepperstone XAUUSD 日線下載警告: {e_gd}")  # 印出警告

        try:  # 嘗試下載 Pepperstone XAUUSD 1H K線並合成 +0h 4H K線
            df_gold_raw = tv.get_hist(symbol='XAUUSD', exchange='PEPPERSTONE', interval=Interval.in_1_hour, n_bars=10000)  # 讀取 1H K線
            if df_gold_raw is not None and not df_gold_raw.empty:  # 檢查 1H 資料
                df_gold_raw = df_gold_raw.reset_index()  # 重設索引
                df_gold_raw['datetime'] = pd.to_datetime(df_gold_raw['datetime']) + tz_correction  # 修正為 UTC+8
                df_gold_raw = df_gold_raw.rename(columns={'datetime': 'timestamp'})  # 重新命名為 timestamp
                df_gold_raw.set_index('timestamp', inplace=True)  # 設為索引
                origin_tz = pd.Timestamp('2024-01-01 00:00:00')  # UTC+8 錨點
                df_gold_4h = df_gold_raw.resample('4h', origin=origin_tz).agg({  # 重取樣合成 4H K線
                    'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'  # 執行策略運算
                }).dropna().reset_index()  # 去除空值
                df_save = df_gold_4h[['timestamp', 'open', 'high', 'low', 'close']].copy()  # 取標準欄位
                df_save['timestamp'] = df_save['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')  # 格式化時間
                df_save.to_csv(GOLD_4H_FILE, index=False)  # 儲存 4H CSV
                print("✅ Pepperstone XAUUSD 4H K線精準合成與儲存成功")  # 印出成功提示
        except Exception as e_g4h:  # 捕捉 4H 異常
            print(f"⚠️ Pepperstone XAUUSD 4H K線下載警告: {e_g4h}")  # 印出警告
    except Exception as e_main:  # 捕捉連線異常
        print(f"⚠️ 下載數據發生連線異常: {e_main}，將使用本地數據進行回測")  # 印出警告

def calculate_atr(df, period=14):  # 計算真實波幅均值 ATR 函數
    high = df['high']  # 取得最高價
    low = df['low']  # 取得最低價
    close_prev = df['close'].shift(1)  # 取得前一期收盤價
    tr1 = high - low  # 計算高低差
    tr2 = (high - close_prev).abs()  # 計算當期最高與前收差
    tr3 = (low - close_prev).abs()  # 計算當期最低與前收差
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)  # 取最大值作為 TR
    return tr.rolling(period).mean()  # 回傳 14 週期滑動平均 ATR

def sanitize_list(lst):  # 替換 NaN 為 None (JSON null) 函數
    return [None if (v is None or pd.isna(v) or np.isnan(v)) else float(v) for v in lst]  # 遍歷替換

def compute_rolling_performance(all_trades, windows_months=(3, 6, 12)):  # 近期滾動績效：分段揭露最近 N 個月表現
    """以最後一筆出場時間為基準往回推 N 個月，計算各區間績效。
    市場 regime 變化快，長期累積數字會掩蓋近期是否開始失效，故獨立揭露。"""
    if not all_trades:  # 無交易則回傳空結果
        return {}  # 空字典
    last_dt = pd.to_datetime(max(t['exit_date'] for t in all_trades))  # 資料最後時點
    result = {}  # 各窗口結果
    for months in windows_months:  # 遍歷每個回看窗口
        cutoff = last_dt - pd.DateOffset(months=months)  # 起算時點
        seg = [t for t in all_trades if pd.to_datetime(t['exit_date']) >= cutoff]  # 篩出窗口內交易
        if not seg:  # 該窗口無交易
            result[f'last_{months}m'] = {'total_trades': 0, 'total_pnl_points': 0.0, 'win_rate': 0.0,
                                         'profit_factor': 0.0, 'max_drawdown': 0.0,
                                         'period_start': str(cutoff.date()), 'period_end': str(last_dt.date())}  # 空值
            continue  # 下一個窗口
        pnl = pd.Series([t['pnl_points'] for t in seg])  # 該窗口損益序列
        cum = pnl.cumsum()  # 累積損益
        win = pnl[pnl > 0]  # 獲利筆
        loss = pnl[pnl < 0]  # 虧損筆
        result[f'last_{months}m'] = {  # 記錄該窗口指標
            'total_trades': len(seg),  # 筆數
            'total_pnl_points': round(float(pnl.sum()), 2),  # 總損益
            'win_rate': round(len(win) / len(pnl) * 100, 2),  # 勝率
            'profit_factor': round(abs(win.sum() / loss.sum()), 2) if len(loss) > 0 and loss.sum() != 0 else 0.0,  # 盈虧比
            'max_drawdown': round(float((cum.cummax() - cum).max()), 2),  # 該區間最大回撤
            'period_start': str(cutoff.date()),  # 區間起
            'period_end': str(last_dt.date()),  # 區間迄
        }  # 記錄結束
    return result  # 回傳滾動績效

def compute_cost_sensitivity(all_trades):  # 成本情境敏感度分析：同一組交易 (進出場時間/方向/持倉天數/出場ATR皆不變)，
    result = {}  # 只替換 Pepperstone 成本假設，揭露績效數字對成本假設的敏感程度
    for scenario_name in COST_SCENARIOS:  # 遍歷 best/typical/stress 三種情境
        pnl_list = []  # 該情境下的逐筆淨損益
        for t in all_trades:  # 遍歷所有已完成交易
            is_long = t['type'] == 'Long'  # 判斷方向
            raw_pnl_unit = (t['exit_price'] - t['entry_price']) if is_long else (t['entry_price'] - t['exit_price'])  # 還原原始價差
            holding_days = t['holding_hours'] / 24.0  # 還原持倉天數
            cost_pts = trade_cost_points(is_long, holding_days, t['exit_reason'], t.get('atr_at_exit'), scenario_name)  # 依情境重算成本
            pnl_list.append(round((raw_pnl_unit - cost_pts) * t['units'], 2))  # 記錄該情境淨損益
        pnl_series = pd.Series(pnl_list)  # 轉為序列
        cum = pnl_series.cumsum()  # 累積損益
        win = pnl_series[pnl_series > 0]  # 獲利筆
        loss = pnl_series[pnl_series < 0]  # 虧損筆
        result[scenario_name] = {  # 記錄該情境指標
            'total_pnl_points': round(float(pnl_series.sum()), 2),  # 總損益
            'max_drawdown': round(float((cum.cummax() - cum).max()), 2) if len(cum) > 0 else 0.0,  # 最大回撤
            'win_rate': round(len(win) / len(pnl_series) * 100, 2) if len(pnl_series) > 0 else 0.0,  # 勝率
            'profit_factor': round(abs(win.sum() / loss.sum()), 2) if len(loss) > 0 and loss.sum() != 0 else 0.0,  # 盈虧比
        }  # 情境結束
    return result  # 回傳三情境對照結果

def simulate_adaptive_direction(df, is_long_only=True, baseline_atr=16.0, alpha_floor=1.0, cost_scenario=DEFAULT_SCENARIO):  # 51Bitquant 波動度自適應單向策略模擬子引擎 (alpha_floor 對齊 EA InpAlphaTrendFloor=1.0)
    n = len(df)  # 資料總筆數
    active_positions = []  # 當前持倉部位清單
    completed_trades = []  # 已完結交易記錄清單
    annotations = []  # 圖表買賣標記清單

    for i in range(n - 1):  # 遍歷 K 線序列
        t_close = df.loc[i, 'close']  # 當期收盤價
        t_high = df.loc[i, 'high']  # 當期最高價
        t_low = df.loc[i, 'low']  # 當期最低價
        t_atr = df.loc[i, 'atr14_4h']  # 4H 14ATR 波動度數值

        t_prev_high = df.loc[i-1, 'high'] if i > 0 else t_high  # 前一根 K 線最高價
        t_prev_low = df.loc[i-1, 'low'] if i > 0 else t_low  # 前一根 K 線最低價

        dy_close = df.loc[i, 'daily_close_avail']  # T-1 日線收盤價
        dy_ma50 = df.loc[i, 'daily_ma50_avail']  # T-1 日線 50MA
        dy_ma20 = df.loc[i, 'daily_ma20_avail']  # T-1 日線 20MA
        dy_ma60 = df.loc[i, 'daily_ma60_avail']  # T-1 日線 60MA
        dy_a1 = df.loc[i, 'daily_alpha1_avail']  # T-1 日 Alpha1
        dy_a5 = df.loc[i, 'daily_alpha5_avail']  # T-1 日 Alpha5
        dy_a10 = df.loc[i, 'daily_alpha10_avail']  # T-1 日 Alpha10

        is_long_sig = df.loc[i, 'sig_long_4h']  # 4H 多頭突破訊號
        next_open = df.loc[i+1, 'open']  # 下期開盤價 (實際成交價)
        next_stamp = str(df.loc[i+1, 'timestamp'])  # 下期時間戳記

        dy_pyramid_long = (dy_a1 > 0) and (dy_a5 > 0) and (dy_a10 > 0) and (dy_ma20 > dy_ma60)  # 加多條件
        dy_pyramid_short = (dy_a1 < 0) and (dy_a5 < 0) and (dy_a10 < 0) and (dy_ma20 < dy_ma60)  # 加空條件

        has_pos = len(active_positions) > 0  # 是否持有部位
        new_active = []  # 新持倉清單

        # 更新當前持倉的單筆最大逆向浮虧 (MAE)
        for p in active_positions:  # 遍歷部位
            if is_long_only:  # 多頭部位
                w_loss = (t_low - p['entry_price']) * p.get('units', 1.0)  # 當根最低點逆向浮虧
                p['mae'] = min(p.get('mae', 0.0), w_loss)  # 記錄最差浮動虧損
            else:  # 空頭部位
                w_loss = (p['entry_price'] - t_high) * p.get('units', 1.0)  # 當根最高點逆向浮虧
                p['mae'] = min(p.get('mae', 0.0), w_loss)  # 記錄最差浮動虧損

        if is_long_only:  # 【多單處理引擎】
            if has_pos:  # 持有多單
                main_pos = [p for p in active_positions if not p['is_pyramid']][0]  # 主多單
                pyr_pos = [p for p in active_positions if p['is_pyramid']]  # 加多單
                has_pyr = len(pyr_pos) > 0  # 是否已加碼

                if t_close < main_pos['stop_price'] or not is_long_sig:  # 觸發主停損或訊號結束 -> 全數平倉
                    exit_reason = "Stop Loss Exit" if t_close < main_pos['stop_price'] else "Signal Exit"  # 平倉原因
                    for p in active_positions:  # 結算所有部位
                        holding_days = (pd.to_datetime(next_stamp).date() - pd.to_datetime(p['entry_date']).date()).days  # 持倉跨日天數
                        raw_pnl = next_open - p['entry_price']  # 原始價格差
                        cost_pts = trade_cost_points(True, holding_days, exit_reason, t_atr, cost_scenario)  # Pepperstone Razor 點差+佣金+隔夜利息+滑價
                        net_pnl_unit = raw_pnl - cost_pts  # 扣除交易成本
                        net_pnl = net_pnl_unit * p.get('units', 1.0)  # 加權淨損益
                        completed_trades.append({  # 記錄平倉明細
                            'type': 'Long', 'is_pyramid': p['is_pyramid'], 'units': p.get('units', 1.0),  # 執行策略運算
                            'entry_date': p['entry_date'], 'entry_price': p['entry_price'],  # 執行策略運算
                            'exit_date': next_stamp, 'exit_price': next_open,  # 執行策略運算
                            'stop_price': round(p['stop_price'], 2), 'pnl_points': round(net_pnl, 2),  # 執行策略運算
                            'mae_points': round(p.get('mae', 0.0), 2),  # 記錄單筆最大浮虧
                            'atr_at_exit': round(float(t_atr), 2) if pd.notna(t_atr) else None,  # 記錄出場當下ATR (供成本情境敏感度分析用)
                            'holding_hours': holding_days * 24, 'exit_reason': exit_reason  # 執行策略運算
                        })  # 記錄結束
                        annotations.append({  # 圖表標記
                            'time': next_stamp, 'price': next_open, 'title': f"Exit Long ({exit_reason})",  # 執行策略運算
                            'text': f"PnL: {net_pnl:.2f}", 'shape': 'arrowDown', 'color': '#ef5350'
                        })  # 標記結束
                    active_positions = []  # 清空持倉
                else:  # 保留多頭部位並動態更新停損
                    if t_close > t_prev_high:  # 價格突破前高
                        main_pos['stop_price'] = min(t_low, t_prev_low) - 1.0 * t_atr  # 向上移動主多停損價
                    new_active.append(main_pos)  # 保留主多單

                    if has_pyr:  # 檢查已存在之加碼多單
                        p_pos = pyr_pos[0]  # 取得加多單
                        if t_close < p_pos['stop_price']:  # 觸發加多單獨立停損
                            holding_days = (pd.to_datetime(next_stamp).date() - pd.to_datetime(p_pos['entry_date']).date()).days  # 跨日天數
                            raw_pnl = next_open - p_pos['entry_price']  # 價差
                            cost_pts = trade_cost_points(True, holding_days, 'Pyramid Stop Loss', t_atr, cost_scenario)  # 成本模型
                            net_pnl_unit = raw_pnl - cost_pts  # 扣成本
                            net_pnl = net_pnl_unit * p_pos.get('units', 1.0)  # 加權淨損益
                            completed_trades.append({  # 記錄平倉加多單
                                'type': 'Long', 'is_pyramid': True, 'units': p_pos.get('units', 1.0),  # 執行策略運算
                                'entry_date': p_pos['entry_date'], 'entry_price': p_pos['entry_price'],  # 執行策略運算
                                'exit_date': next_stamp, 'exit_price': next_open,  # 執行策略運算
                                'stop_price': round(p_pos['stop_price'], 2), 'pnl_points': round(net_pnl, 2),  # 執行策略運算
                                'mae_points': round(p_pos.get('mae', 0.0), 2),  # 記錄加多單最大浮虧
                                'atr_at_exit': round(float(t_atr), 2) if pd.notna(t_atr) else None,  # 記錄出場當下ATR
                                'holding_hours': holding_days * 24, 'exit_reason': 'Pyramid Stop Loss'  # 執行策略運算
                            })  # 記錄結束
                            annotations.append({  # 圖表標記
                                'time': next_stamp, 'price': next_open, 'title': 'Exit Pyramid Long',  # 執行策略運算
                                'text': f"PnL: {net_pnl:.2f}", 'shape': 'arrowDown', 'color': '#ff9800'
                            })  # 標記結束
                        else:  # 保留加多單
                            if t_close > t_prev_high:  # 突破前高
                                p_pos['stop_price'] = min(t_low, t_prev_low) - 1.0 * t_atr  # 向上移動加多停損
                            new_active.append(p_pos)  # 保留加多單
                    else:  # 尚未加多，檢查「51Bitquant 波動度自適應加多」
                        if dy_close > dy_ma50 and dy_pyramid_long:  # 滿足加多條件
                            # ⚡ 51Bitquant 核心公式：加碼手數與波動度 (ATR) 成反比動態調制
                            atr_ratio = baseline_atr / max(t_atr, 4.0) if pd.notna(t_atr) and t_atr > 0 else 1.0  # 波動度倒數權重
                            base_mult = 2.0 if dy_a10 > 0.03 else 1.0  # Alpha10 > 3% 基準乘數
                            calc_u = min(2.5, max(0.5, base_mult * atr_ratio))  # 動態調制手數 (0.5x~2.5x)
                            if dy_a10 > 0.04 and calc_u < alpha_floor:  # 超強單邊動能保底保護
                                calc_u = alpha_floor  # 保底手數
                            pyr_units = quantize_units(calc_u)  # 依 EA NormalizeLot 規則量化為實際可下單倍率
                            new_active.append({  # 建立加多單
                                'type': 'Long', 'is_pyramid': True, 'units': pyr_units, 'entry_date': next_stamp,  # 執行策略運算
                                'entry_price': next_open, 'stop_price': min(t_low, t_prev_low) - 1.0 * t_atr, 'mae': 0.0  # 執行策略運算
                            })  # 建立結束
                            annotations.append({  # 圖表標記
                                'time': next_stamp, 'price': next_open, 'title': f"+Pyramid Long ({pyr_units}x ATR-Adaptive)",  # 執行策略運算
                                'text': f"Price: {next_open:.2f} | ATR: {t_atr:.1f}", 'shape': 'arrowUp', 'color': '#26a69a'
                            })  # 標記結束
                    active_positions = new_active  # 更新持倉
            else:  # 空手建立主多單
                if dy_close > dy_ma50 and is_long_sig:  # 滿足主多條件
                    active_positions.append({  # 建立主多
                        'type': 'Long', 'is_pyramid': False, 'units': 1.0, 'entry_date': next_stamp,  # 執行策略運算
                        'entry_price': next_open, 'stop_price': min(t_low, t_prev_low) - 1.0 * t_atr, 'mae': 0.0  # 執行策略運算
                    })  # 建立結束
                    annotations.append({  # 圖表標記
                        'time': next_stamp, 'price': next_open, 'title': 'Buy Main Long',  # 執行策略運算
                        'text': f"Price: {next_open:.2f}", 'shape': 'arrowUp', 'color': '#00e676'
                    })  # 標記結束

        else:  # 【空單處理引擎】
            if has_pos:  # 持有空單
                main_pos = [p for p in active_positions if not p['is_pyramid']][0]  # 主空單
                pyr_pos = [p for p in active_positions if p['is_pyramid']]  # 加空單
                has_pyr = len(pyr_pos) > 0  # 是否已加空

                if t_close > main_pos['stop_price'] or is_long_sig:  # 觸發主停損或出現反向多頭訊號 -> 全數平倉
                    exit_reason = "Stop Loss Exit" if t_close > main_pos['stop_price'] else "Signal Exit"  # 平倉原因
                    for p in active_positions:  # 結算空單
                        holding_days = (pd.to_datetime(next_stamp).date() - pd.to_datetime(p['entry_date']).date()).days  # 持倉天數
                        raw_pnl = p['entry_price'] - next_open  # 空單價格差
                        cost_pts = trade_cost_points(False, holding_days, exit_reason, t_atr, cost_scenario)  # Pepperstone Razor 點差+佣金+隔夜利息+滑價
                        net_pnl_unit = raw_pnl - cost_pts  # 扣除交易成本
                        net_pnl = net_pnl_unit * p.get('units', 1.0)  # 加權淨損益
                        completed_trades.append({  # 記錄平倉明細
                            'type': 'Short', 'is_pyramid': p['is_pyramid'], 'units': p.get('units', 1.0),  # 執行策略運算
                            'entry_date': p['entry_date'], 'entry_price': p['entry_price'],  # 執行策略運算
                            'exit_date': next_stamp, 'exit_price': next_open,  # 執行策略運算
                            'stop_price': round(p['stop_price'], 2), 'pnl_points': round(net_pnl, 2),  # 執行策略運算
                            'mae_points': round(p.get('mae', 0.0), 2),  # 記錄單筆最大浮虧
                            'atr_at_exit': round(float(t_atr), 2) if pd.notna(t_atr) else None,  # 記錄出場當下ATR (供成本情境敏感度分析用)
                            'holding_hours': holding_days * 24, 'exit_reason': exit_reason  # 執行策略運算
                        })  # 記錄結束
                        annotations.append({  # 圖表標記
                            'time': next_stamp, 'price': next_open, 'title': f"Exit Short ({exit_reason})",  # 執行策略運算
                            'text': f"PnL: {net_pnl:.2f}", 'shape': 'arrowUp', 'color': '#26a69a'
                        })  # 標記結束
                    active_positions = []  # 清空持倉
                else:  # 保留空頭部位
                    if t_close < t_prev_low:  # 價格跌破前低
                        main_pos['stop_price'] = max(t_high, t_prev_high) + 1.0 * t_atr  # 向下移動主空停損
                    new_active.append(main_pos)  # 保留主空單

                    if has_pyr:  # 檢查已加空單
                        p_pos = pyr_pos[0]  # 取得加空單
                        if t_close > p_pos['stop_price']:  # 觸發加空停損
                            holding_days = (pd.to_datetime(next_stamp).date() - pd.to_datetime(p_pos['entry_date']).date()).days  # 天數
                            raw_pnl = p_pos['entry_price'] - next_open  # 價差
                            cost_pts = trade_cost_points(False, holding_days, 'Pyramid Stop Loss', t_atr, cost_scenario)  # 成本模型
                            net_pnl_unit = raw_pnl - cost_pts  # 扣成本
                            net_pnl = net_pnl_unit * p_pos.get('units', 1.0)  # 加權淨損益
                            completed_trades.append({  # 記錄加空平倉
                                'type': 'Short', 'is_pyramid': True, 'units': p_pos.get('units', 1.0),  # 執行策略運算
                                'entry_date': p_pos['entry_date'], 'entry_price': p_pos['entry_price'],  # 執行策略運算
                                'exit_date': next_stamp, 'exit_price': next_open,  # 執行策略運算
                                'stop_price': round(p_pos['stop_price'], 2), 'pnl_points': round(net_pnl, 2),  # 執行策略運算
                                'mae_points': round(p_pos.get('mae', 0.0), 2),  # 記錄加空單最大浮虧
                                'atr_at_exit': round(float(t_atr), 2) if pd.notna(t_atr) else None,  # 記錄出場當下ATR
                                'holding_hours': holding_days * 24, 'exit_reason': 'Pyramid Stop Loss'  # 執行策略運算
                            })  # 記錄結束
                            annotations.append({  # 圖表標記
                                'time': next_stamp, 'price': next_open, 'title': 'Exit Pyramid Short',  # 執行策略運算
                                'text': f"PnL: {net_pnl:.2f}", 'shape': 'arrowUp', 'color': '#ff9800'
                            })  # 標記結束
                        else:  # 保留加空
                            if t_close < t_prev_low:  # 跌破前低
                                p_pos['stop_price'] = max(t_high, t_prev_high) + 1.0 * t_atr  # 向下移動加空停損
                            new_active.append(p_pos)  # 保留
                    else:  # 尚未加空，檢查「51Bitquant 波動度自適應加空」
                        if dy_close < dy_ma50 and dy_pyramid_short:  # 滿足加空條件
                            atr_ratio = baseline_atr / max(t_atr, 4.0) if pd.notna(t_atr) and t_atr > 0 else 1.0  # 波動度倒數權重
                            base_mult = 2.0 if dy_a10 < -0.03 else 1.0  # Alpha10 < -3% 基準乘數
                            calc_u = min(2.5, max(0.5, base_mult * atr_ratio))  # 動態調制手數 (0.5x~2.5x)
                            if dy_a10 < -0.04 and calc_u < alpha_floor:  # 超強單邊空頭動能保底保護
                                calc_u = alpha_floor  # 保底手數
                            pyr_units = quantize_units(calc_u)  # 依 EA NormalizeLot 規則量化為實際可下單倍率
                            new_active.append({  # 建立加空單
                                'type': 'Short', 'is_pyramid': True, 'units': pyr_units, 'entry_date': next_stamp,  # 執行策略運算
                                'entry_price': next_open, 'stop_price': max(t_high, t_prev_high) + 1.0 * t_atr, 'mae': 0.0  # 執行策略運算
                            })  # 建立結束
                            annotations.append({  # 圖表標記
                                'time': next_stamp, 'price': next_open, 'title': f"+Pyramid Short ({pyr_units}x ATR-Adaptive)",  # 執行策略運算
                                'text': f"Price: {next_open:.2f} | ATR: {t_atr:.1f}", 'shape': 'arrowDown', 'color': '#ef5350'
                            })  # 標記結束
                    active_positions = new_active  # 更新持倉
            else:  # 空手建立主空單
                if dy_close < dy_ma50 and not is_long_sig:  # 滿足主空條件
                    active_positions.append({  # 建立主空
                        'type': 'Short', 'is_pyramid': False, 'units': 1.0, 'entry_date': next_stamp,  # 執行策略運算
                        'entry_price': next_open, 'stop_price': max(t_high, t_prev_high) + 1.0 * t_atr, 'mae': 0.0  # 執行策略運算
                    })  # 建立結束
                    annotations.append({  # 圖表標記
                        'time': next_stamp, 'price': next_open, 'title': 'Sell Main Short',  # 執行策略運算
                        'text': f"Price: {next_open:.2f}", 'shape': 'arrowUp', 'color': '#00e676'
                    })  # 標記結束

    return active_positions, completed_trades, annotations  # 回傳回測產出

def run_backtest():  # 執行自適應策略回測主程式
    download_data()  # 嘗試下載最新數據或使用本機快取

    gold_daily_file = GOLD_DAILY_FILE  # 黃金日線路徑 (PEPPERSTONE:XAUUSD)
    dxy_daily_file = DXY_DAILY_FILE  # DXY 日線路徑 (Pepperstone USDX，對齊 EA)
    gold_4h_file = GOLD_4H_FILE  # 黃金 4H 路徑 (PEPPERSTONE:XAUUSD, 1H 合成 UTC+0h 網格)

    gold_d = pd.read_csv(gold_daily_file)  # 讀取黃金日線
    dxy_d = pd.read_csv(dxy_daily_file)  # 讀取 DXY 日線
    gold_4h = pd.read_csv(gold_4h_file)  # 讀取 4H K線

    gold_d = gold_d.rename(columns={'close': 'gold_close', 'open': 'gold_open', 'high': 'gold_high', 'low': 'gold_low'})  # 重新命名欄位
    dxy_d = dxy_d.rename(columns={'close': 'dxy_close', 'open': 'dxy_open', 'high': 'dxy_high', 'low': 'dxy_low'})  # 重新命名欄位

    # 以黃金日線為基準做左連結並前向填補 DXY：
    # XAUUSD 有週日 K 棒而 Pepperstone USDX 沒有，若用 inner join 會丟棄約 17% 的黃金交易日，
    # 破壞 MA 與 N 日報酬的計算。左連結 + ffill 等同 EA 內 iBarShift(..., exact=false) 的語意。
    df_daily = pd.merge(gold_d, dxy_d, on='timestamp', how='left')  # 保留全部黃金交易日
    _dxy_cols = [c for c in df_daily.columns if c.startswith('dxy_')]  # 取出 DXY 相關欄位
    df_daily = df_daily.sort_values('timestamp')  # 先依時間排序才能正確前向填補
    df_daily[_dxy_cols] = df_daily[_dxy_cols].ffill()  # 前向填補 DXY (週日沿用前一交易日收盤)
    df_daily = df_daily.dropna(subset=_dxy_cols).reset_index(drop=True)  # 去除開頭尚無 DXY 可填補的列
    df_daily['timestamp'] = pd.to_datetime(df_daily['timestamp'])  # 轉為 datetime
    df_daily = df_daily.sort_values('timestamp').reset_index(drop=True)  # 排序

    for n in [1, 5, 10]:  # 計算 Alpha 動能
        df_daily[f'gold_ret_{n}'] = df_daily['gold_close'].pct_change(n)  # 黃金報酬
        df_daily[f'dxy_ret_{n}'] = df_daily['dxy_close'].pct_change(n)  # DXY 報酬
        df_daily[f'alpha_{n}'] = df_daily[f'gold_ret_{n}'] - df_daily[f'dxy_ret_{n}']  # 相對 Alpha

    df_daily['ma20'] = df_daily['gold_close'].rolling(20).mean()  # 20MA
    df_daily['ma50'] = df_daily['gold_close'].rolling(50).mean()  # 50MA
    df_daily['ma60'] = df_daily['gold_close'].rolling(60).mean()  # 60MA

    df_daily['dxy_ma20'] = df_daily['dxy_close'].rolling(20).mean()  # DXY 20MA
    df_daily['dxy_ma60'] = df_daily['dxy_close'].rolling(60).mean()  # DXY 60MA

    df_daily['date'] = df_daily['timestamp'].dt.date  # 提取日期

    # 日線特徵改用「時間對齊」掛載 (取代原本的日曆日期 join + shift(1))
    # 原作法會讓每天第一根 4H K 線偷看到尚未收盤的日線，且與 EA 的 iClose(PERIOD_D1,1) 差一個交易日
    df_daily['daily_close_avail'] = df_daily['gold_close']  # 日收 (由 as-of join 保證已完結)
    df_daily['daily_ma50_avail'] = df_daily['ma50']  # 50MA
    df_daily['daily_ma20_avail'] = df_daily['ma20']  # 20MA
    df_daily['daily_ma60_avail'] = df_daily['ma60']  # 60MA
    df_daily['daily_alpha1_avail'] = df_daily['alpha_1']  # Alpha1
    df_daily['daily_alpha5_avail'] = df_daily['alpha_5']  # Alpha5
    df_daily['daily_alpha10_avail'] = df_daily['alpha_10']  # Alpha10

    gold_4h['timestamp'] = pd.to_datetime(gold_4h['timestamp'])  # 轉 datetime
    gold_4h = gold_4h.sort_values('timestamp').reset_index(drop=True)  # 排序
    gold_4h['date'] = gold_4h['timestamp'].dt.date  # 提取日期

    df = attach_daily_features(gold_4h, df_daily, [  # 以 4H 收盤時間 as-of 對齊已完結之日線
        'daily_close_avail', 'daily_ma50_avail', 'daily_ma20_avail', 'daily_ma60_avail',  # 日線價格與均線特徵
        'daily_alpha1_avail', 'daily_alpha5_avail', 'daily_alpha10_avail'  # 跨市場 Alpha 特徵
    ])  # 對齊完成

    df['ma30_4h'] = df['close'].rolling(30).mean()  # 4H 30MA
    df['atr14_4h'] = calculate_atr(df, 14)  # 4H 14ATR
    df['dy_raw'] = df['close'].diff()  # 動能一階差
    df = add_curvature(df)  # 計算 30MA 一次/二次微分 (以 ATR 正規化)
    # 曲率過濾：d2 <= -門檻代表上升動能急速衰竭，不進多單 (實測為唯一有效的趨勢性過濾)
    df['sig_long_4h'] = (df['close'] > df['ma30_4h']) & (df['dy_raw'] > 0) & curvature_pass(df)  # 4H 多頭訊號 (含曲率過濾)

    df = df.dropna().reset_index(drop=True)  # 去除 NaN
    df = df[df['timestamp'] >= '2024-07-07'].reset_index(drop=True)  # 對齊正式回測起始期

    # 執行 51Bitquant 波動度自適應回測 (基準 ATR = 16.0 點)
    baseline_atr_setting = 16.0  # 設定黃金 4H 基準 ATR
    pos_l, trades_l, ann_l = simulate_adaptive_direction(df, is_long_only=True, baseline_atr=baseline_atr_setting, alpha_floor=1.0)  # 模擬自適應多頭 (alpha_floor=1.0 對齊 EA)
    pos_s, trades_s, ann_s = simulate_adaptive_direction(df, is_long_only=False, baseline_atr=baseline_atr_setting, alpha_floor=1.0)  # 模擬自適應空頭 (alpha_floor=1.0 對齊 EA)

    all_active = pos_l + pos_s  # 聯集持倉
    all_trades = trades_l + trades_s  # 聯集交易
    all_trades = sorted(all_trades, key=lambda x: str(x['exit_date']))  # 按出場時間排序
    for idx, t in enumerate(all_trades):  # 重設流水號
        t['trade_id'] = idx + 1  # 賦予 ID

    all_ann = ann_l + ann_s  # 聯集標記

    latest_row = df.iloc[-1]  # 取得最新行
    dxy_df_final = df_daily[df_daily['timestamp'] >= df['timestamp'].min()].dropna(subset=['dxy_close']).reset_index(drop=True)  # 對齊 DXY

    # 計算全週期逐根 K 線即時浮動盈虧與動態淨值
    trade_exit_map = {}  # 出場時間損益映射表
    parsed_trades = []  # 預先解析時間戳的交易清單
    for t in all_trades:  # 遍歷交易
        e_time = t['exit_date']  # 出場時間字串
        trade_exit_map[e_time] = trade_exit_map.get(e_time, 0.0) + t['pnl_points']  # 累積已平倉損益
        parsed_trades.append({  # 構造預解析物件
            'type': t['type'], 'units': t['units'], 'entry_price': t['entry_price'],  # 執行策略運算
            'entry_dt': pd.Timestamp(t['entry_date']), 'exit_dt': pd.Timestamp(t['exit_date'])  # 執行策略運算
        })  # 構造結束

    bar_floating_pnl_close = []  # 收盤價即時浮虧清單
    bar_floating_pnl_worst = []  # 極端價即時浮虧清單
    bar_equity_curve = []  # 逐根動態淨值清單
    cum_pnl_tracker = 0.0  # 追蹤累計損益

    for i in range(len(df) - 1):  # 遍歷 K 線
        tc = df.loc[i, 'close']  # 當前收盤
        th = df.loc[i, 'high']  # 當前最高
        tl = df.loc[i, 'low']  # 當前最低
        cur_t = df.loc[i, 'timestamp']  # 當前 Timestamp
        cur_t_str = str(cur_t)  # 時間字串
        
        if cur_t_str in trade_exit_map:  # 檢查當期平倉
            cum_pnl_tracker += trade_exit_map[cur_t_str]  # 累加已平倉損益

        fl_close = 0.0  # 收盤浮虧
        fl_worst = 0.0  # 極端浮虧
        for t in parsed_trades:  # 遍歷預解析交易
            if t['entry_dt'] <= cur_t < t['exit_dt']:  # 處於持倉中
                if t['type'] == 'Long':  # 多單
                    fl_close += (tc - t['entry_price']) * t['units']  # 收盤浮虧
                    fl_worst += (tl - t['entry_price']) * t['units']  # 最低價浮虧
                else:  # 空單
                    fl_close += (t['entry_price'] - tc) * t['units']  # 收盤浮虧
                    fl_worst += (t['entry_price'] - th) * t['units']  # 最高價浮虧

        bar_floating_pnl_close.append(round(fl_close, 2))  # 記錄收盤浮虧
        bar_floating_pnl_worst.append(round(fl_worst, 2))  # 記錄極端浮虧
        bar_equity_curve.append(round(cum_pnl_tracker + fl_close, 2))  # 記錄動態淨值

    eq_arr = np.array(bar_equity_curve)  # 轉為 numpy 陣列
    floating_drawdown_pts = round(float((np.maximum.accumulate(eq_arr) - eq_arr).max()), 2) if len(eq_arr) > 0 else 0.0  # 浮動淨值最大回撤
    max_instant_float_loss_close = round(float(min(bar_floating_pnl_close)), 2) if bar_floating_pnl_close else 0.0  # 收盤價最大未平倉浮虧
    max_instant_float_loss_worst = round(float(min(bar_floating_pnl_worst)), 2) if bar_floating_pnl_worst else 0.0  # 極端價最大未平倉浮虧

    current_status = {  # 即時狀態字典
        'last_updated': str(latest_row['timestamp']),  # 最新時間
        'gold_close': float(latest_row['close']),  # 黃金現價
        'dxy_close': float(dxy_df_final.iloc[-1]['dxy_close']),  # DXY 現價
        'regime': 'Bull (牛市多頭)' if (latest_row['daily_close_avail'] > latest_row['daily_ma50_avail']) else 'Bear (熊市空頭)',  # 最新體制
        'ma4h_30': float(latest_row['ma30_4h']),  # 4H 30MA
        'atr14_4h': float(latest_row['atr14_4h']),  # 當前 ATR
        'baseline_atr': baseline_atr_setting,  # 基準 ATR
        'volatility_scale': round(baseline_atr_setting / max(float(latest_row['atr14_4h']), 4.0), 2),  # 當前波動度手數乘數
        # 訊號診斷：揭露目前各項條件的成立與否，便於與 MT5 上的 EA 逐項對照
        'signal_diagnostics': {
            'is_bull_regime': bool(latest_row['daily_close_avail'] > latest_row['daily_ma50_avail']),  # 日線 50MA 體制
            'close_above_ma30': bool(latest_row['close'] > latest_row['ma30_4h']),  # 收盤是否站上 4H 30MA
            'momentum_positive': bool(latest_row['dy_raw'] > 0),  # 動能 (較前一根收高)
            'curvature': round(float(latest_row['ma30_d2']), 5),  # 30MA 二次微分 (曲率)
            'curvature_threshold': -CURVATURE_THRESHOLD,  # 曲率門檻
            'curvature_pass': bool(latest_row['ma30_d2'] > -CURVATURE_THRESHOLD),  # 曲率是否通過
            'sig_long_4h': bool(latest_row['sig_long_4h']),  # 綜合後的 4H 多頭訊號
            'pyramid_long_ok': bool((latest_row['daily_alpha1_avail'] > 0) and (latest_row['daily_alpha5_avail'] > 0)
                                    and (latest_row['daily_alpha10_avail'] > 0)
                                    and (latest_row['daily_ma20_avail'] > latest_row['daily_ma60_avail'])),  # 加多條件
            'pyramid_short_ok': bool((latest_row['daily_alpha1_avail'] < 0) and (latest_row['daily_alpha5_avail'] < 0)
                                     and (latest_row['daily_alpha10_avail'] < 0)
                                     and (latest_row['daily_ma20_avail'] < latest_row['daily_ma60_avail'])),  # 加空條件
        },
        'daily_ma50': float(latest_row['daily_ma50_avail']),  # 50MA
        'daily_ma20': float(latest_row['daily_ma20_avail']),  # 20MA
        'daily_ma60': float(latest_row['daily_ma60_avail']),  # 60MA
        'alpha_1d': float(latest_row['daily_alpha1_avail']),  # Alpha 1D
        'alpha_5d': float(latest_row['daily_alpha5_avail']),  # Alpha 5D
        'alpha_10d': float(latest_row['daily_alpha10_avail']),  # Alpha 10D
        'active_positions': [  # 活躍部位清單
            {  # 執行策略運算
                'type': p['type'], 'is_pyramid': p['is_pyramid'], 'units': p.get('units', 1.0), 'entry_date': p['entry_date'],  # 執行策略運算
                'entry_price': float(p['entry_price']), 'stop_price': round(float(p['stop_price']), 2),  # 執行策略運算
                'unrealized_pnl': round((latest_row['close'] - p['entry_price']) * p.get('units', 1.0) if p['type'] == 'Long' else (p['entry_price'] - latest_row['close']) * p.get('units', 1.0), 2)  # 執行策略運算
            } for p in all_active  # 執行策略運算
        ]  # 部位結束
    }  # 狀態結束

    total_pnl = sum([t['pnl_points'] for t in all_trades])  # 總損益點數
    win_trades = [t for t in all_trades if t['pnl_points'] > 0]  # 獲利單
    loss_trades = [t for t in all_trades if t['pnl_points'] < 0]  # 虧損單
    win_rate = round(len(win_trades) / len(all_trades) * 100, 2) if len(all_trades) > 0 else 0  # 勝率
    profit_factor = round(abs(sum([t['pnl_points'] for t in win_trades]) / sum([t['pnl_points'] for t in loss_trades])), 2) if loss_trades else 0.0  # 盈虧比

    pnl_series = pd.Series([t['pnl_points'] for t in all_trades])  # 損益序列
    cum_pnl = pnl_series.cumsum()  # 累積損益
    max_drawdown = round((cum_pnl.cummax() - cum_pnl).max(), 2) if len(cum_pnl) > 0 else 0  # 最大回撤點數
    peak_pnl = float(cum_pnl.max()) if len(cum_pnl) > 0 else 0.0  # 歷史峰值
    current_pnl = float(cum_pnl.iloc[-1]) if len(cum_pnl) > 0 else 0.0  # 當前損益
    current_drawdown = round(peak_pnl - current_pnl, 2)  # 當前回撤點
    current_drawdown_pct = round(current_drawdown / peak_pnl * 100, 2) if peak_pnl > 0 else 0.0  # 當前回撤比例

    # 單筆交易 MAE 統計
    all_maes = [t.get('mae_points', 0.0) for t in all_trades]  # 提取 MAE
    worst_single_mae = round(float(min(all_maes)), 2) if all_maes else 0.0  # 單筆最慘逆向浮虧
    pyr_maes = [t.get('mae_points', 0.0) for t in all_trades if t['is_pyramid']]  # 加碼單 MAE
    worst_pyramid_mae = round(float(min(pyr_maes)), 2) if pyr_maes else 0.0  # 加碼單最慘逆向浮虧

    # 計算統計年數與風險指標
    first_date = pd.to_datetime(all_trades[0]['entry_date']) if all_trades else pd.to_datetime('2025-01-01')  # 起始日期
    last_date = pd.to_datetime(all_trades[-1]['exit_date']) if all_trades else pd.to_datetime('2026-08-26')  # 結束日期
    years = max((last_date - first_date).days / 365.25, 0.5)  # 統計年數 (約 1.63 年)
    annual_pnl = total_pnl / years  # 年化獲利點數
    calmar_ratio = round(annual_pnl / max_drawdown, 2) if max_drawdown > 0 else 0.0  # 卡瑪比率
    sharpe_ratio = round(float((pnl_series.mean() / pnl_series.std()) * np.sqrt(252)), 2) if pnl_series.std() > 0 else 0.0  # 夏普比率

    unrealized_pnl_sum = sum([p['unrealized_pnl'] for p in current_status['active_positions']]) if current_status.get('active_positions') else 0.0  # 未平倉損益
    realtime_total_pnl = round(total_pnl + unrealized_pnl_sum, 2)  # 即時總點數
    cost_sensitivity = compute_cost_sensitivity(all_trades)  # Pepperstone 成本情境敏感度 (best/typical/stress)
    rolling_perf = compute_rolling_performance(all_trades)  # 近期滾動績效 (近 3/6/12 個月)

    metrics = {  # 指標字典
        'total_trades': len(all_trades),  # 總筆數
        'total_pnl_points': round(total_pnl, 2),  # 總點數
        'unrealized_pnl_points': round(unrealized_pnl_sum, 2),  # 未實現點數
        'realtime_total_pnl_points': realtime_total_pnl,  # 即時總點數
        'win_rate': win_rate,  # 勝率
        'profit_factor': profit_factor,  # 盈虧比
        'max_drawdown': max_drawdown,  # 最大已平倉回撤 (MDD)
        'current_drawdown': current_drawdown,  # 當前回撤
        'current_drawdown_pct': current_drawdown_pct,  # 當前回撤百分比
        'floating_drawdown_points': floating_drawdown_pts,  # 浮動淨值最大回撤 (Floating MDD)
        'max_instant_float_loss_close': max_instant_float_loss_close,  # 單一時間最大未平倉浮虧 (收盤)
        'max_instant_float_loss_worst': max_instant_float_loss_worst,  # 單一時間極端最大未平倉浮虧 (影線)
        'worst_single_mae': worst_single_mae,  # 單筆交易最大持倉浮虧
        'worst_pyramid_mae': worst_pyramid_mae,  # 加碼單最大持倉浮虧
        'calmar_ratio': calmar_ratio,  # 卡瑪比率
        'sharpe_ratio': sharpe_ratio,  # 夏普比率
        'annual_pnl_points': round(annual_pnl, 2),  # 年化獲利點數
        'years': round(years, 2),  # 實際涵蓋年數 (由首筆進場至末筆出場計算)
        'data_start': str(first_date.date()),  # 實際回測起始日
        'data_end': str(last_date.date()),  # 實際回測結束日
        'data_source': 'PEPPERSTONE:XAUUSD (1H 合成 UTC+0h 網格 4H，與 EA 同切分)',  # 資料源標註
        'comparison_with_watch': {  # 與原始固定倉位版 (Watch) 對照
            # ⚠️ 下列 *_watch 基準值產生於「舊成本模型 + 舊日線對齊」，與本次結果並非同基準，
            #    僅供粗略參考；如需嚴謹對照，須以相同成本模型與對齊方式重跑原始版策略。
            'baseline_is_comparable': False,  # 明確標記基準不可直接比較
            'pnl_watch': 5090.59,  # 原始獲利
            'mdd_watch': 475.89,  # 原始回撤
            'mdd_reduction_pct': round((475.89 - max_drawdown) / 475.89 * 100, 1),  # 回撤降低比例 (動態計算)
            'floating_mdd_watch': 837.81,  # 原始浮動回撤
            'floating_mdd_reduction_pct': round((837.81 - floating_drawdown_pts) / 837.81 * 100, 1),  # 浮動回撤降低比例 (動態計算)
            'instant_float_loss_watch': -392.10,  # 原始單點浮虧
            'instant_float_loss_reduction_pct': round((392.10 - abs(max_instant_float_loss_close)) / 392.10 * 100, 1),  # 浮虧降低比例 (動態計算)
            'pyr_mae_watch': -382.92,  # 原始加碼最大浮虧
            'pyr_mae_reduction_pct': round((382.92 - abs(worst_pyramid_mae)) / 382.92 * 100, 1),  # 加碼浮虧降低比例 (動態計算)
            'calmar_watch': 6.58,  # 原始卡瑪
            'calmar_improvement_pct': round((calmar_ratio - 6.58) / 6.58 * 100, 1)  # 卡瑪提升比例 (動態計算)
        },  # 對照結束
        'cost_scenario_used': DEFAULT_SCENARIO,  # 本次主要指標所用的成本情境
        'cost_sensitivity': cost_sensitivity,  # Pepperstone Razor 帳戶 best/typical/stress 三情境敏感度對照 (swap/滑價為非官方保守估計，僅供參考)
        'rolling_performance': rolling_perf,  # 近 3/6/12 個月滾動績效 (揭露策略是否開始失效)
        'curvature_filter': {'enabled': True, 'threshold': CURVATURE_THRESHOLD, 'span': 3}  # 趨勢曲率過濾設定
    }  # 指標結束

    gold_chart_data = {  # 圖表數據
        'timestamps': df['timestamp'].astype(str).tolist(),  # 時間
        'open': df['open'].tolist(), 'high': df['high'].tolist(), 'low': df['low'].tolist(), 'close': df['close'].tolist(),  # 價格
        'ma30_8h': sanitize_list(df['ma30_4h'].tolist()),  # 30MA
        'daily_ma50': sanitize_list(df['daily_ma50_avail'].tolist()),  # 50MA
        'daily_ma20': sanitize_list(df['daily_ma20_avail'].tolist()),  # 20MA
        'daily_ma60': sanitize_list(df['daily_ma60_avail'].tolist()),  # 60MA
        'atr14': sanitize_list(df['atr14_4h'].tolist())  # ATR 數列
    }  # 圖表結束

    dxy_chart_data = {  # DXY 圖表
        'timestamps': dxy_df_final['timestamp'].dt.strftime('%Y-%m-%d').tolist(),  # 時間
        'open': dxy_df_final['dxy_open'].tolist(), 'high': dxy_df_final['dxy_high'].tolist(), 'low': dxy_df_final['dxy_low'].tolist(), 'close': dxy_df_final['dxy_close'].tolist(),  # 價格
        'ma20': sanitize_list(dxy_df_final['dxy_ma20'].tolist()),  # 20MA
        'ma60': sanitize_list(dxy_df_final['dxy_ma60'].tolist()),  # 60MA
    }  # DXY 結束

    output_data = {  # 輸出 JSON 字典
        'current_status': current_status, 'metrics': metrics,  # 執行策略運算
        'gold_chart_data': gold_chart_data, 'dxy_chart_data': dxy_chart_data,  # 執行策略運算
        'completed_trades': all_trades, 'chart_annotations': all_ann  # 執行策略運算
    }  # 輸出結束

    # 1. 寫入 JSON 結果檔
    with open('strategy_results.json', 'w', encoding='utf-8') as f:  # 開啟 JSON 檔案
        json.dump(output_data, f, ensure_ascii=False, indent=2)  # 寫入格式化 JSON

    # 2. 匯出詳細交易 CSV 檔
    df_trades = pd.DataFrame(all_trades)  # 轉為 DataFrame
    df_trades.to_csv('all_trades_detail_adaptive.csv', index=False, encoding='utf-8-sig')  # 匯出 CSV 檔

    # 3. 繪製並儲存權益曲線圖 (Equity Curve & Underwater Drawdown)
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True, gridspec_kw={'height_ratios': [3, 1]})  # 建立雙子圖視窗
    
    dates = pd.to_datetime([t['exit_date'] for t in all_trades])  # 取得出場時間軸
    ax1.plot(dates, cum_pnl, label='51Bitquant Dynamic ATR Equity Curve', color='#00e676', linewidth=2.0)  # 繪製累積權益線
    ax1.set_title(f'XAUUSD 4H 30MA 51Bitquant Dynamic ATR Strategy - Total PnL: +{total_pnl:.2f} pts (Calmar: {calmar_ratio}, MDD: {max_drawdown:.1f} pts, Floating MDD: {floating_drawdown_pts:.1f} pts)', fontsize=13, fontweight='bold')  # 設定大標題
    ax1.set_ylabel('Cumulative PnL (Points)', fontsize=12)  # Y 軸標籤
    ax1.grid(True, linestyle='--', alpha=0.5)  # 網格線
    ax1.legend(loc='upper left', fontsize=11)  # 圖例

    dd_series = (cum_pnl.cummax() - cum_pnl) * -1.0  # 計算負向回撤序列
    ax2.fill_between(dates, dd_series, 0, color='#ef5350', alpha=0.4, label='Underwater Drawdown (Points)')  # 填色水下回撤
    ax2.plot(dates, dd_series, color='#ef5350', linewidth=1.2)  # 繪製回撤邊緣線
    ax2.set_ylabel('Drawdown (Pts)', fontsize=12)  # Y 軸標籤
    ax2.set_xlabel('Date', fontsize=12)  # X 軸標籤
    ax2.grid(True, linestyle='--', alpha=0.5)  # 網格線
    ax2.legend(loc='lower left', fontsize=11)  # 圖例

    plt.tight_layout()  # 自動調整間距
    plt.savefig('backtest_equity_curve_adaptive.png', dpi=300)  # 儲存高解析度圖檔
    plt.close()  # 關閉圖表釋放記憶體

    print("==========================================================================")  # 分隔線
    print("🎉 【51Bitquant 波動度自適應調倉策略回測完成】")  # 完成標題
    print("==========================================================================")  # 分隔線
    print(f" • 總累積淨損益:       +{total_pnl:.2f} 點")  # 輸出獲利
    print(f" • 總成交筆數:         {len(all_trades)} 筆 (勝率: {win_rate}%)")  # 輸出筆數與勝率
    print(f" • 盈虧比 (PF):        {profit_factor}")  # 輸出盈虧比
    cmp_w = metrics['comparison_with_watch']  # 取出與原始版對照數據 (百分比皆為動態計算)
    print(f" • 已平倉最大回撤:     {max_drawdown:.2f} 點 (較原始版降 {cmp_w['mdd_reduction_pct']}%；當前回撤: {current_drawdown_pct}%)")  # 輸出回撤
    print(f" • 浮動淨值最大回撤:   {floating_drawdown_pts:.2f} 點 (較原始版降 {cmp_w['floating_mdd_reduction_pct']}%)")  # 輸出浮動回撤
    print(f" • 單點最大浮動虧損:   {max_instant_float_loss_close:.2f} 點 (收盤) / {max_instant_float_loss_worst:.2f} 點 (影線) (較原始版降 {cmp_w['instant_float_loss_reduction_pct']}%)")  # 輸出單點浮虧
    print(f" • 加碼單最大逆向浮虧: {worst_pyramid_mae:.2f} 點 (較原始版降 {cmp_w['pyr_mae_reduction_pct']}%)")  # 輸出加碼浮虧
    print("   ⚠️ 上述對照基準來自舊成本模型與舊日線對齊，非同基準比較，僅供粗略參考")  # 明確標註基準不可直接比較
    print(f" • 卡瑪比率 (Calmar):   {calmar_ratio} (年化獲利: {annual_pnl:.1f} 點/年)")  # 輸出卡瑪比率
    print(f" • 夏普比率 (Sharpe):   {sharpe_ratio}")  # 輸出夏普值
    print(" • 已輸出檔案: strategy_results.json, all_trades_detail_adaptive.csv, backtest_equity_curve_adaptive.png")  # 輸出檔案清單
    print("--------------------------------------------------------------------------")  # 分隔線
    print(f" 💰 成本情境敏感度分析 (Pepperstone Razor 帳戶, 主指標採用: {DEFAULT_SCENARIO})")  # 標題
    print("    ⚠️ 點差/佣金為官網公告數值；swap 與停損滑價為非官方保守估計，僅供參考")  # 警語
    for sc_name, sc_val in cost_sensitivity.items():  # 遍歷三種情境
        print(f"    - {sc_name:15s}: 總損益 {sc_val['total_pnl_points']:>9.2f} 點 | MDD {sc_val['max_drawdown']:>8.2f} 點 | 勝率 {sc_val['win_rate']:>6.2f}% | PF {sc_val['profit_factor']:>5.2f}")  # 輸出各情境
    print("==========================================================================\n")  # 結束分隔線

if __name__ == '__main__':  # 程式主入口
    run_backtest()  # 啟動回測
