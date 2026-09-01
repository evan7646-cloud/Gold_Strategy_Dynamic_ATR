"""日線特徵與 4H K 線的時間對齊模組 (共用於 gold_adaptive_strategy.py 與 run_4yr_backtest.py)。

【為什麼需要這個模組】
原本的作法是「以日曆日期 join + shift(1)」：把 4H K 線的日期標籤 D 對應到日線的 D-1 列。
但本專案資料集的時間標籤為 UTC+8，而 Pepperstone 日線的實際收盤時間是券商伺服器午夜
(GMT+2/+3)，換算後約為 UTC+8 隔日 05:00~06:00 —— 也就是落在「04:00 那根 4H K 線」之內。

因此原作法會產生兩個問題：
  1. 【未來函數】每天第一根 4H K 線 (00:00，收盤於 04:00) 所使用的 D-1 日線，
     其實要再過 1~2 小時才會收盤，回測等於偷看了尚未完結的日線資料。
  2. 【與 EA 不一致】在同一個時間點，MT5 的 iClose(_Symbol, PERIOD_D1, 1) 取得的是
     再前一天的日線 (D-2)，與回測所用的 D-1 差了整整一個交易日。
     此問題影響約 20~25% 的進場訊號。

【本模組的作法】
對每一根 4H K 線，只採用「在該 4H K 線收盤當下已經完結」的最後一根日線，
語意與 MT5 EA 的 iClose(_Symbol, PERIOD_D1, 1) 完全一致，同時消除未來函數。
"""

import pandas as pd

DAILY_CLOSE_HOUR = 6  # 日線實際收盤時點：換算為資料集的 UTC+8 時區後約為隔日 05:00~06:00，取 6 點涵蓋夏令/冬令時差


def attach_daily_features(gold_4h, df_daily, feature_cols, bar_hours=4):
    """把日線特徵以時間對齊方式掛載到 4H K 線上。

    參數：
      gold_4h      : 含 'timestamp' 欄 (4H K 線開盤時間) 的 DataFrame
      df_daily     : 含 'timestamp' 欄 (日線日期) 與各特徵欄的 DataFrame
      feature_cols : 要掛載的日線特徵欄位名稱清單
      bar_hours    : K 線長度 (小時)，用來由開盤時間推算收盤時間

    回傳：
      合併後的 DataFrame，每根 4H K 線只帶有「當下已完結」之最後一根日線的特徵值。
    """
    d = df_daily.copy()  # 複製避免污染原始資料
    d['avail_from'] = pd.to_datetime(d['timestamp']).dt.normalize() + pd.Timedelta(days=1, hours=DAILY_CLOSE_HOUR)  # 該日線實際可用的時點
    d = d.sort_values('avail_from').reset_index(drop=True)  # merge_asof 要求排序

    h = gold_4h.copy()  # 複製 4H 資料
    h['bar_close_time'] = pd.to_datetime(h['timestamp']) + pd.Timedelta(hours=bar_hours)  # 4H K 線的實際收盤時間
    h = h.sort_values('bar_close_time').reset_index(drop=True)  # merge_asof 要求排序

    merged = pd.merge_asof(  # 向後 as-of join：只取收盤時間之前已完結的最後一根日線
        h, d[['avail_from'] + feature_cols],
        left_on='bar_close_time', right_on='avail_from', direction='backward'
    )
    return merged.drop(columns=['avail_from'])  # 移除輔助欄位後回傳
