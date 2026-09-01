"""EA 手數量化模組 (共用於 gold_adaptive_strategy.py 與 run_4yr_backtest.py)。

【為什麼需要這個模組】
MT5 EA 內的 NormalizeLot() 會把手數無條件捨去到券商的最小跳動量 (SYMBOL_VOLUME_STEP)：

    normalized = MathFloor(lot / step + 0.000001) * step

因此當基礎手數 InpLotSize = 0.10、step = 0.01 時，加碼倍率的實際解析度只有 0.1x：
例如回測算出 1.33x，EA 實際會下 0.13 手，等於 1.3x。

原本 Python 回測使用的是精確倍率 (1.33x)，與 EA 實際成交手數不一致。
本模組複製 EA 的量化規則，讓回測的加碼倍率與 EA 實際下單完全一致。
"""

import math

EA_LOT_SIZE = 0.10  # 對齊 EA 參數 InpLotSize (基礎交易手數)
EA_VOLUME_STEP = 0.01  # 券商最小手數跳動量 (XAUUSD 常見值)
EA_VOLUME_MIN = 0.01  # 券商最小手數


def quantize_units(mult, lot_size=EA_LOT_SIZE, step=EA_VOLUME_STEP, min_lot=EA_VOLUME_MIN):
    """把倍率換算成 EA 實際會下的手數後，再換算回等效倍率。

    完全複製 EA NormalizeLot() 的無條件捨去規則，確保回測倉位與實盤一致。
    """
    lot = lot_size * mult  # 換算為實際手數
    normalized = math.floor(lot / step + 0.000001) * step  # 無條件捨去至最小跳動量 (同 EA)
    if normalized < min_lot:  # 不得低於券商最小手數
        normalized = min_lot  # 提升至最小手數
    normalized = round(normalized, 2)  # 規範小數位數 (同 EA NormalizeDouble(...,2))
    return normalized / lot_size  # 換算回等效倍率
