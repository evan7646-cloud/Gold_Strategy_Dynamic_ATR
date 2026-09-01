"""趨勢曲率過濾模組 (共用於 gold_adaptive_strategy.py 與 run_4yr_backtest.py)。

【原理】
對 4H 30MA 取二次微分，衡量均線的「加速度」：

    一次微分 d1 = (ma30[i] - ma30[i-n]) / n / ATR[i]    斜率(速度)，以 ATR 正規化
    二次微分 d2 = (d1[i] - d1[i-n]) / n                 曲率(加速度)

當 d2 明顯為負，代表上升動能正在急速衰竭、趨勢可能即將翻轉，此時不進多單。

【為什麼用二次微分而不是一次微分 / ADX / ATR】
實測比較 (見 experiment_derivative_filter.py 與 experiment_atr_adx_filter.py)：
  一次微分(斜率)過濾 : 短期 Calmar 7.60 -> 5.39~6.24，變差
  ADX 過濾           : 短期 Calmar 7.60 -> 3.08~5.70，變差
  ATR 擴張比過濾      : 短期 Calmar 7.60 -> 3.53~5.46，變差
  二次微分(曲率)過濾  : 短期 Calmar 7.60 -> 8.35，且 MDD 由 311 降至 290  ← 唯一有效

ADX 與 ATR 皆為落後型趨勢強度指標 (ADX 經兩次 Wilder 平滑)，等其確認趨勢時行情
多已走到中後段，實際效果是延後進場；曲率則屬領先訊號，捕捉的是動能衰竭的當下。

【穩健性】
  門檻平台區   : 短期 0.008~0.015、長期 0.004~0.020 皆同時改善 Calmar/Sharpe/MDD
  微分跨度     : n=2/3/4 均有效，n=3 於兩組資料表現最佳
  成本情境     : best/typical/stress 三種全部改善
  樣本外年度   : 2023、2024 兩個未重疊年度皆改善 (虧損由 -457 收斂至 -247 點)

【已知不對稱性】
本過濾僅作用於多頭訊號 (d2 > -threshold)；空單條件為多頭訊號的反面，
因此曲率轉弱時會同時「擋多」並「放行做空」。此為方向一致的設計
(漲勢衰竭即偏空)，且實測優於對稱版本 (短期 MDD 289.67 vs 326.00)。
"""

CURVATURE_SPAN = 3  # 微分跨度 (4H K 棒數)，實測 n=3 於兩組資料最佳
CURVATURE_THRESHOLD = 0.010  # 曲率門檻：d2 <= -0.010 視為動能急速衰竭，不進多單


def add_curvature(df, ma_col='ma30_4h', atr_col='atr14_4h', span=CURVATURE_SPAN):
    """於 DataFrame 上加入 ma30_d1 / ma30_d2 兩欄並回傳 (需先算好 ma_col 與 atr_col)。"""
    df['ma30_d1'] = df[ma_col].diff(span) / span / df[atr_col]  # 一次微分 (ATR 正規化斜率)
    df['ma30_d2'] = df['ma30_d1'].diff(span) / span  # 二次微分 (曲率)
    return df


def curvature_pass(df, threshold=CURVATURE_THRESHOLD):
    """回傳布林序列：True 表示曲率未跌破門檻，允許多頭訊號成立。"""
    return df['ma30_d2'] > -threshold
