"""一次性資料重建腳本：所有黃金資料統一改用 PEPPERSTONE:XAUUSD。

背景：舊檔案來源混雜且檔名誤導
  - comex_gc1!_4h.csv    → 實際上已是 Pepperstone XAUUSD (1H 合成 4H)，僅檔名殘留 COMEX 字樣
  - xauusd_4h_4yr.csv    → 經比對「不是」Pepperstone 資料 (2492 根只有 1 根吻合)，來源不明
  - comex_gc1!_daily.csv → 僅 63% 與 Pepperstone 相符，混雜其他來源的歷史資料

本腳本全部重抓並改用明確檔名：
  pepperstone_xauusd_4h.csv       ← 1H 合成之 UTC +0h 網格 4H (與 MT5 EA 的 K 棒切分完全一致)
  pepperstone_xauusd_4h_long.csv  ← TradingView 原生 4H (歷史較長，但為券商時區網格，與 EA 不同)
  pepperstone_xauusd_daily.csv    ← 日線 (完整覆寫，不與舊資料合併)

⚠️ 已知限制：匿名 tvDatafeed 的 1H 歷史只到約 1.7 年，無法合成更長期間的 +0h 網格 4H。
   因此長期壓力測試只能改用原生 4H (資料源同為 PEPPERSTONE:XAUUSD，但 K 棒邊界落在
   券商時區 2/3、6/7、10/11… 而非 EA 所用的 UTC 0/4/8…)。
"""

import datetime
import pandas as pd
from tvDatafeed import TvDatafeed, Interval

FILE_4H_EA_GRID = 'pepperstone_xauusd_4h.csv'
FILE_4H_LONG = 'pepperstone_xauusd_4h_long.csv'
FILE_DAILY = 'pepperstone_xauusd_daily.csv'


def main():
    tv = TvDatafeed()
    tz_correction = datetime.timedelta(hours=8) - datetime.datetime.now().astimezone().utcoffset()

    # --- 1H 合成 UTC +0h 網格 4H (與 EA 的 GetUTC0h4H_BarData 一致) ---
    h1 = tv.get_hist(symbol='XAUUSD', exchange='PEPPERSTONE', interval=Interval.in_1_hour, n_bars=20000)
    h1 = h1.reset_index()
    h1['datetime'] = pd.to_datetime(h1['datetime']) + tz_correction
    syn = (h1.set_index('datetime')
             .resample('4h', origin=pd.Timestamp('2024-01-01 00:00:00'))
             .agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'})
             .dropna().reset_index()
             .rename(columns={'datetime': 'timestamp'}))
    syn['timestamp'] = syn['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
    syn[['timestamp', 'open', 'high', 'low', 'close']].to_csv(FILE_4H_EA_GRID, index=False)
    print(f"✅ {FILE_4H_EA_GRID}: {len(syn)} 根 ({syn['timestamp'].iloc[0]} ~ {syn['timestamp'].iloc[-1]})")

    # --- 原生 4H (歷史較長，供長期壓力測試) ---
    n4 = tv.get_hist(symbol='XAUUSD', exchange='PEPPERSTONE', interval=Interval.in_4_hour, n_bars=20000)
    n4 = n4.reset_index()
    n4['datetime'] = pd.to_datetime(n4['datetime']) + tz_correction
    n4 = n4.rename(columns={'datetime': 'timestamp'})
    n4['timestamp'] = n4['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
    n4[['timestamp', 'open', 'high', 'low', 'close']].to_csv(FILE_4H_LONG, index=False)
    print(f"✅ {FILE_4H_LONG}: {len(n4)} 根 ({n4['timestamp'].iloc[0]} ~ {n4['timestamp'].iloc[-1]})")

    # --- 日線 (完整覆寫，避免混入其他來源的舊資料) ---
    dd = tv.get_hist(symbol='XAUUSD', exchange='PEPPERSTONE', interval=Interval.in_daily, n_bars=5000)
    dd = dd.reset_index()
    dd['datetime'] = pd.to_datetime(dd['datetime']) + tz_correction
    dd = dd.rename(columns={'datetime': 'timestamp'})
    dd['timestamp'] = dd['timestamp'].dt.strftime('%Y-%m-%d')
    dd = dd[['timestamp', 'open', 'high', 'low', 'close']].drop_duplicates(subset=['timestamp'], keep='last')
    dd.to_csv(FILE_DAILY, index=False)
    print(f"✅ {FILE_DAILY}: {len(dd)} 根 ({dd['timestamp'].iloc[0]} ~ {dd['timestamp'].iloc[-1]})")


if __name__ == '__main__':
    main()
