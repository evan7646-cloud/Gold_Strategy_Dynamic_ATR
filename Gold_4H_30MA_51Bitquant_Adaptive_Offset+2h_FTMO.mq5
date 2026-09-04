//+------------------------------------------------------------------+ // 頭部註釋
//|              Gold_4H_30MA_51Bitquant_Adaptive_Offset+2h_FTMO.mq5 | // 檔名與模組註釋
//|                黃金 4H 30MA 51Bitquant 波動度自適應調倉 FTMO 版 EA (+2h Offset 錯開版) | // 版權與模組說明
//|                       Copyright 2026, Gold Strategy Watch        | // 版權聲明註釋
//+------------------------------------------------------------------+ // 分隔線註釋
#property copyright "Copyright 2026, Gold Strategy Watch" // 程式版權資訊
#property link      "https://github.com/evan7646/Gold_Strategy_Watch" // 專案連結
#property version   "1.00" // 程式版本號
#property strict    // 嚴格模式編譯

#include <Trade\Trade.mqh> // 引用 MT5 官方交易庫

//--- 策略參數設定 (與最終版 Gold_4H_30MA_add2.0>3%_Strategy_Offset+0h.mq5 100% 同步)
input ulong    InpMagicMain              = 44440011;         // 主部位 Magic Number (與 +0h 版錯開，兩實例部位互不干擾)
input ulong    InpMagicPyramid           = 44440012;         // 加碼部位 Magic Number (與 +0h 版錯開)
input double   InpLotSize                = 0.10;             // 初始交易手數 (Standard Lots)
input bool     InpEnablePyramid          = true;             // 是否啟用加碼機制 (True/False)
input double   InpPyramidBoostMultiplier = 2.0;              // Alpha 強烈時加碼手數基準倍率 (預設 2.0 倍)
input double   InpAlphaBoostThresh       = 0.03;             // Alpha10 觸發加碼門檻 (預設 3.0% = 0.03)
input double   InpBaselineATR            = 16.0;             // 51Bitquant 基準 ATR 點數 (波動度基準 16.0 點)
input double   InpMaxPyrMult             = 2.5;              // 51Bitquant 自適應加碼倍率上限 (預設 2.5x)
input double   InpMinPyrMult             = 0.5;              // 51Bitquant 自適應加碼倍率下限 (預設 0.5x)
input double   InpAlphaTrendFloor        = 1.0;              // 超強單邊趨勢加碼手數保底倍率 (預設 1.0x)
input string   InpDXYSymbol              = "USDX";           // 美元指數圖表代號 (同步最終版預設 USDX)

//--- 趨勢曲率過濾參數 (30MA 二次微分)
input bool     InpEnableCurvature        = true;             // 是否啟用趨勢曲率過濾 (二次微分)
input double   InpCurvatureThreshold     = 0.010;            // 曲率門檻：d2 <= -此值 視為動能急速衰竭，不進多單
input int      InpCurvatureSpan          = 3;                // 微分跨度 (4H K棒數，實測 n=3 最佳)

//--- 4H K 棒時間網格偏移 (可跑多個實例錯開觀察時點，避免 4 小時內錯過大行情)
input int      InpBarOffsetHours         = 2;                // 4H 網格偏移小時 (本版預設 2 = 02/06/10/14/18/22 UTC)

//--- 指標週期參數宣告 (修復未定義編譯錯誤)
input int      InpMA4H_Period            = 30;               // 4H 均線 (SMA) 週期 (預設 30MA)
input int      InpATR4H_Period           = 14;               // 4H ATR 週期 (預設 14ATR)
input int      InpMA50_Period            = 50;               // 日線 50MA 週期 (大趨勢過濾)
input int      InpMA20_Period            = 20;               // 日線 20MA 週期 (加倉過濾)
input int      InpMA60_Period            = 60;               // 日線 60MA 週期 (加倉過濾)

//--- FTMO 帳戶類型 (依官方 trading objectives 之風控門檻)
//    1-Step : 每日最大虧損 3%  / 總最大虧損 10%
//    2-Step : 每日最大虧損 5%  / 總最大虧損 10%
//    選定類型後 EA 會自動套用「略低於官方上限」的熔斷門檻並預留緩衝，
//    避免在不同帳戶間切換時忘記調整參數而導致考核失敗。
enum ENUM_FTMO_ACCOUNT_TYPE
{
   FTMO_2STEP = 0,  // 2-Step 考核 (每日 5% / 總 10%) -> 套用 4.5% / 9.0%
   FTMO_1STEP = 1,  // 1-Step 考核 (每日 3% / 總 10%) -> 套用 2.5% / 9.0%
   FTMO_MANUAL = 2  // 手動指定 (使用下方 InpMaxDailyLossPct / InpMaxTotalLossPct)
};

//--- FTMO 風控專屬參數
input double   InpInitialBalance         = 100000.0;         // FTMO 帳戶初始資金 (0.0 表示不開啟總虧損熔斷)
input ENUM_FTMO_ACCOUNT_TYPE InpFTMOAccountType = FTMO_2STEP; // FTMO 帳戶類型 (自動套用對應風控門檻，避免手動設錯)
input double   InpMaxDailyLossPct        = 4.5;              // 每日最大虧損熔斷 (%) ※ 僅在帳戶類型選「手動」時生效
input double   InpMaxTotalLossPct        = 9.0;              // 帳戶總最大虧損熔斷 (%) ※ 僅在帳戶類型選「手動」時生效
input bool     InpCloseAllAccountPos     = false;            // ⚠️ 雙實例運行時務必設為 false，否則本實例熔斷會連帶平掉 +0h 版的部位
input bool     InpEnableAlerts           = true;             // 是否開啟 FTMO 風控與交易通知

//--- 全域變數宣告
CTrade   g_trade;                 // 交易執行物件
double   g_MainStopPrice    = 0.0; // 主部位移動停損價
double   g_PyramidStopPrice = 0.0; // 加碼部位移動停損價
datetime g_LastBar4H        = 0;   // 上次執行的 4H K 線時間
datetime g_LastBarDaily     = 0;   // 上次執行的 Daily K 線時間
bool     g_DailyReady       = false; // 日線過濾器是否就緒

//--- FTMO 風控全域變數
double   g_MaxDailyLossPct  = 4.5;   // 實際生效之每日虧損熔斷門檻 (依帳戶類型於 OnInit 決定)
double   g_MaxTotalLossPct  = 9.0;   // 實際生效之總虧損熔斷門檻 (依帳戶類型於 OnInit 決定)
double   g_SOD_Baseline     = 0.0;   // 今日 Start of Day 權益基準點
datetime g_LastServerDate   = 0;     // 當前伺服器日期
bool     g_DailyHalted      = false; // 今日是否觸發熔斷停止交易

//--- 日線與趨勢狀態變數
bool     g_RegimeBull       = false; // 大趨勢是否為多頭 (Close > 50SMA)
bool     g_PyramidLongOK    = false; // 日線是否允許加多
bool     g_PyramidShortOK   = false; // 日線是否允許加空

double   g_LastATR4H        = 0.0;   // 最近一次 4H 交易邏輯所用之 ATR (供 HUD 顯示，確保與下單邏輯同源)
double   g_LastCurvature    = 0.0;   // 最近一次計算之 30MA 二次微分 (曲率)，供 HUD 顯示

//--- 指標句柄全域變數
int      g_hMA50D           = INVALID_HANDLE; // 日線 50SMA 句柄
int      g_hMA20D           = INVALID_HANDLE; // 日線 20SMA 句柄
int      g_hMA60D           = INVALID_HANDLE; // 日線 60SMA 句柄
int      g_hMA4H            = INVALID_HANDLE; // 4H 30MA 句柄
int      g_hATR4H           = INVALID_HANDLE; // 4H 14ATR 句柄

//--- 全域變數持久化 Key
string   g_gvKeyMainStop;      // 主部位停損 Key
string   g_gvKeyPyramidStop;   // 加倉部位停損 Key
string   g_gvKeyLastBar4H;     // 4H 時間 Key
string   g_gvKeySODBaseline;   // SOD 基準價 Key
string   g_gvKeyLastServerDate;// 伺服器日期 Key
string   g_gvKeyDailyHalted;   // 今日熔斷 Key

//+------------------------------------------------------------------+
//| 取得合規成交模式 (GetValidFillingMode)                            |
//+------------------------------------------------------------------+
ENUM_ORDER_TYPE_FILLING GetValidFillingMode() // 取得下單填單模式
{ // 函數開頭
   uint filling = (uint)SymbolInfoInteger(_Symbol, SYMBOL_FILLING_MODE); // 讀取商品填單屬性
   if((filling & SYMBOL_FILLING_IOC) != 0) return ORDER_FILLING_IOC;    // 優先使用 IOC
   if((filling & SYMBOL_FILLING_FOK) != 0) return ORDER_FILLING_FOK;    // 次選 FOK
   return ORDER_FILLING_RETURN;                                         // 預設使用 RETURN
} // 函數結束

//+------------------------------------------------------------------+
//| 規範手數至平台限制 (NormalizeLot) (同步最終版精準算式)              |
//+------------------------------------------------------------------+
double NormalizeLot(double lot) // 手數標準化
{ // 函數開頭
   double step   = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP); // 讀取手數步長
   double minLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);  // 讀取最小手數
   double maxLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);  // 讀取最大手數
   if(step <= 0) step = 0.01; // 防空值保護
   double normalized = MathFloor(lot / step + 0.000001) * step; // 向下微調對齊
   if(normalized < minLot) normalized = minLot; // 不得低於最小手數
   if(normalized > maxLot) normalized = maxLot; // 不得高於最大手數
   return NormalizeDouble(normalized, 2); // 規範小數位數 (同步最終版)
} // 函數結束

//+------------------------------------------------------------------+
//| 保存 FTMO 風控狀態 (SaveFTMOState)                                 |
//+------------------------------------------------------------------+
void SaveFTMOState() // 保存 FTMO 狀態
{ // 函數開頭
   GlobalVariableSet(g_gvKeySODBaseline, g_SOD_Baseline); // 寫入 SOD 基準價
   GlobalVariableSet(g_gvKeyLastServerDate, (double)g_LastServerDate); // 寫入伺服器日期
   GlobalVariableSet(g_gvKeyDailyHalted, g_DailyHalted ? 1.0 : 0.0); // 寫入今日熔斷狀態
} // 函數結束

//+------------------------------------------------------------------+
//| 載入 FTMO 風控狀態 (LoadFTMOState)                                 |
//+------------------------------------------------------------------+
void LoadFTMOState() // 載入 FTMO 狀態
{ // 函數開頭
   if(GlobalVariableCheck(g_gvKeySODBaseline)) g_SOD_Baseline = GlobalVariableGet(g_gvKeySODBaseline); // 載入 SOD 基準價
   if(GlobalVariableCheck(g_gvKeyLastServerDate)) g_LastServerDate = (datetime)GlobalVariableGet(g_gvKeyLastServerDate); // 載入日期
   if(GlobalVariableCheck(g_gvKeyDailyHalted)) g_DailyHalted = (GlobalVariableGet(g_gvKeyDailyHalted) > 0.5); // 載入熔斷狀態
} // 函數結束

//+------------------------------------------------------------------+
//| 寫入持久化狀態 (SavePersistentState)                             |
//+------------------------------------------------------------------+
void SavePersistentState() // 保存 EA 持久化狀態
{ // 函數開頭
   GlobalVariableSet(g_gvKeyMainStop, g_MainStopPrice); // 保存主部位停損價
   GlobalVariableSet(g_gvKeyPyramidStop, g_PyramidStopPrice); // 保存加倉停損價
   GlobalVariableSet(g_gvKeyLastBar4H, (double)g_LastBar4H); // 保存上次 4H 時間
   SaveFTMOState(); // 順便保存 FTMO 風控狀態
} // 函數結束

//+------------------------------------------------------------------+
//| 讀取持久化狀態 (LoadPersistentState)                             |
//+------------------------------------------------------------------+
void LoadPersistentState() // 讀取 EA 持久化狀態
{ // 函數開頭
   if(GlobalVariableCheck(g_gvKeyMainStop)) g_MainStopPrice = GlobalVariableGet(g_gvKeyMainStop); // 讀取主部位停損價
   if(GlobalVariableCheck(g_gvKeyPyramidStop)) g_PyramidStopPrice = GlobalVariableGet(g_gvKeyPyramidStop); // 讀取加倉停損價
   if(GlobalVariableCheck(g_gvKeyLastBar4H)) g_LastBar4H = (datetime)GlobalVariableGet(g_gvKeyLastBar4H); // 讀取上次 4H 時間
   LoadFTMOState(); // 讀取 FTMO 風控狀態
   PrintFormat("💾 [狀態載入] 主停損=%.2f | 加倉停損=%.2f | 上次4H時間=%s", g_MainStopPrice, g_PyramidStopPrice, TimeToString(g_LastBar4H)); // 印出日誌 (同步最終版)
} // 函數結束

//+------------------------------------------------------------------+
//| 取得有效的 DXY 美元指數商品名稱 (同步最終版多重搜尋)                |
//+------------------------------------------------------------------+
string GetValidDXYSymbol() // 自動搜尋經紀商相符 DXY 代號
{ // 條件/區塊開頭
   if(SymbolSelect(InpDXYSymbol, true)) return InpDXYSymbol; // 指定商品存在則使用
   string candidates[] = {"DXY.cash", "DXY", "USDX", "USDOLLAR", "DXY_U6", "USDINDEX", "DXY.ecn", "DXY!", "USDX.cash"}; // 備選清單 (加入 FTMO 之 DXY.cash)
   for(int i = 0; i < ArraySize(candidates); i++) // 遍歷備選清單
   { // 條件/區塊開頭
      if(SymbolSelect(candidates[i], true)) return candidates[i]; // 找到可用即回傳
   } // 條件/區塊結束
   return InpDXYSymbol; // 找不到則回傳預設值
} // 條件/區塊結束

//+------------------------------------------------------------------+
//| 統計當前商品與本 EA MagicNumber 之持倉 (CountPositionsByEA)        |
//+------------------------------------------------------------------+
int CountPositionsByEA(ulong &mainTicket, ulong &pyrTicket) // 統計持倉票號
{ // 函數開頭
   mainTicket = 0; // 重置主部位票號
   pyrTicket  = 0; // 重置加倉部位票號
   int count = 0;  // 統計總個數

   for(int i = PositionsTotal() - 1; i >= 0; i--) // 遍歷當前所有持倉
   { // 迴圈開頭
      ulong ticket = PositionGetTicket(i); // 取得持倉票號
      if(ticket <= 0) continue; // 若票號無效跳過 (同步最終版)
      if(PositionGetString(POSITION_SYMBOL) == _Symbol) // 檢查是否為當前商品
      { // 條件開頭
         ulong magic = PositionGetInteger(POSITION_MAGIC); // 讀取 Magic Number
         if(magic == InpMagicMain) // 若為主部位
         { // 條件開頭
            mainTicket = ticket; // 保存主部位票號
            count++; // 計數加一
         } // 條件結束
         else if(magic == InpMagicPyramid) // 若為加倉部位
         { // 條件開頭
            pyrTicket = ticket; // 保存加倉部位票號
            count++; // 計數加一
         } // 條件結束
      } // 條件結束
   } // 迴圈結束
   return count; // 回傳持倉數量
} // 函數結束

//+------------------------------------------------------------------+
//| 平倉指定 Magic Number 之所有部位 (ClosePositionsByMagic)          |
//+------------------------------------------------------------------+
bool ClosePositionsByMagic(ulong magic) // 平倉指定 Magic 部位
{ // 函數開頭
   bool allClosed = true; // 平倉結果標誌
   g_trade.SetExpertMagicNumber(magic); // 切換 CTrade Magic Number (同步最終版)
   for(int i = PositionsTotal() - 1; i >= 0; i--) // 遍歷所有持倉
   { // 迴圈開頭
      ulong ticket = PositionGetTicket(i); // 取得持倉票號
      if(ticket <= 0) continue; // 無效票號跳過
      if(PositionGetString(POSITION_SYMBOL) == _Symbol && PositionGetInteger(POSITION_MAGIC) == magic) // 符合條件
      { // 條件開頭
         if(!g_trade.PositionClose(ticket)) // 執行平倉
         { // 條件開頭
            PrintFormat("❌ 平倉失敗 [Ticket=%d, Magic=%d]: %s", ticket, magic, g_trade.ResultComment()); // 印出日誌
            allClosed = false; // 標記失敗
         } // 條件結束
      } // 條件結束
   } // 迴圈結束
   return allClosed; // 回傳平倉結果
} // 函數結束

//+------------------------------------------------------------------+
//| 平倉帳戶內「所有」頭寸 (包含手動與其他 EA) (CloseAllAccountPositions) |
//+------------------------------------------------------------------+
void CloseAllAccountPositions() // 平倉帳戶全數頭寸
{ // 函數開頭
   for(int retry = 0; retry < 3; retry++) // 最多重試 3 次
   { // 迴圈開頭
      int posCount = PositionsTotal(); // 當前頭寸數
      if(posCount == 0) break; // 若已清空則退出

      for(int i = posCount - 1; i >= 0; i--) // 遍歷清空
      { // 迴圈開頭
         ulong ticket = PositionGetTicket(i); // 取得頭寸票號
         if(ticket > 0) // 票號有效
         { // 條件開頭
            g_trade.PositionClose(ticket); // 執行市價平倉
         } // 條件結束
      } // 迴圈結束
      Sleep(200); // 暫停 200ms 等待成交
   } // 迴圈結束
} // 函數結束

//+------------------------------------------------------------------+
//| 取得指定年月的最後一個週日 (LastSundayOfMonth)                      |
//| 供計算歐洲夏令時間 (CE(S)T) 的切換日使用                            |
//+------------------------------------------------------------------+
datetime LastSundayOfMonth(int year, int month) // 回傳該月最後一個週日之零點
{ // 函數開頭
   int dim[12] = {31,28,31,30,31,30,31,31,30,31,30,31}; // 各月天數
   int lastDay = dim[month - 1]; // 該月最後一天
   if(month == 2 && ((year % 4 == 0 && year % 100 != 0) || year % 400 == 0)) lastDay = 29; // 閏年二月修正
   MqlDateTime d; // 時間結構
   d.year = year; d.mon = month; d.day = lastDay; d.hour = 0; d.min = 0; d.sec = 0; // 設為該月最後一天零點
   datetime t = StructToTime(d); // 轉為時間戳
   MqlDateTime chk; TimeToStruct(t, chk); // 解析以取得星期
   return t - (datetime)(chk.day_of_week * 86400); // day_of_week 0=週日，往回推至最近的週日
} // 函數結束

//+------------------------------------------------------------------+
//| 判斷指定 UTC 時點歐洲是否為夏令時間 (IsEuropeSummerTime)            |
//| 歐盟規則：三月最後週日 01:00 UTC 起，至十月最後週日 01:00 UTC 止    |
//+------------------------------------------------------------------+
bool IsEuropeSummerTime(datetime utcTime) // 判斷是否 CEST (UTC+2)
{ // 函數開頭
   MqlDateTime d; TimeToStruct(utcTime, d); // 解析年份
   datetime dstStart = LastSundayOfMonth(d.year, 3) + 3600;  // 夏令起始：三月最後週日 01:00 UTC
   datetime dstEnd   = LastSundayOfMonth(d.year, 10) + 3600; // 夏令結束：十月最後週日 01:00 UTC
   return (utcTime >= dstStart && utcTime < dstEnd); // 落在區間內即為夏令
} // 函數結束

//+------------------------------------------------------------------+
//| 取得目前所屬「FTMO 交易日」識別碼 (GetFTMODayId)                    |
//| ⚠️ FTMO 官方明訂每日虧損限額於 00:00 CE(S)T 重新計算，              |
//|    而非 MT5 券商伺服器時間的午夜。以本券商 GMT+3 為例，             |
//|    伺服器午夜比 FTMO 實際結算時點早 1~2 小時，若沿用伺服器時間，     |
//|    EA 會在 FTMO 仍計入前一日的時段就提前重置額度，導致風控失準。      |
//+------------------------------------------------------------------+
datetime GetFTMODayId() // 回傳 CE(S)T 當日零點，作為交易日唯一識別
{ // 函數開頭
   datetime utcNow = TimeGMT(); // 取得標準 UTC 時間
   int cetOffset = IsEuropeSummerTime(utcNow) ? 2 * 3600 : 1 * 3600; // CEST=UTC+2, CET=UTC+1
   datetime cetNow = utcNow + (datetime)cetOffset; // 換算為 CE(S)T 當地時間
   MqlDateTime d; TimeToStruct(cetNow, d); // 解析
   d.hour = 0; d.min = 0; d.sec = 0; // 歸零時分秒
   return StructToTime(d); // 回傳 CE(S)T 當日零點
} // 函數結束

//+------------------------------------------------------------------+
//| FTMO 每日風控檢查與 SOD 基準重置 (CheckAndResetDailySOD)          |
//+------------------------------------------------------------------+
void CheckAndResetDailySOD() // FTMO 每日風控邏輯
{ // 函數開頭
   // ⚠️ 以 00:00 CE(S)T 為交易日分界 (FTMO 官方計算方式)，非 MT5 伺服器午夜
   datetime ftmoDayId = GetFTMODayId(); // 取得目前所屬之 FTMO 交易日

   if(ftmoDayId != g_LastServerDate || g_SOD_Baseline == 0.0) // 若進入新的 FTMO 交易日或尚未初始化
   { // 條件開頭
      double curBalance = AccountInfoDouble(ACCOUNT_BALANCE); // 當前餘額
      double curEquity  = AccountInfoDouble(ACCOUNT_EQUITY);  // 當前權益 (僅供日誌參考)
      // FTMO 明訂以「00:00 CE(S)T 當下的帳戶餘額」為每日虧損基準，
      // 原本取 MathMax(餘額, 淨值) 會在有浮盈時墊高基準、使熔斷線過鬆，故改為僅取餘額
      g_SOD_Baseline   = curBalance;                         // 以帳戶餘額為今日 SOD 基準 (對齊 FTMO 算法)
      g_LastServerDate = ftmoDayId;                          // 更新交易日識別
      g_DailyHalted    = false;                              // 重置今日熔斷狀態
      SaveFTMOState();                                       // 保存狀態
      PrintFormat("☀️ [FTMO 每日風控重置] 已進入新的 FTMO 交易日 (00:00 CE(S)T)！SOD Baseline = %.2f (Balance=%.2f, Equity=%.2f)", g_SOD_Baseline, curBalance, curEquity); // 印出日誌
      if(InpEnableAlerts) Alert("☀️ FTMO 每日風控重置！今日 SOD 基準價為 ", DoubleToString(g_SOD_Baseline, 2)); // 發送通知
   } // 條件結束

   if(g_DailyHalted) // 若今日已經觸發過熔斷
   { // 條件開頭
      if(PositionsTotal() > 0 && InpCloseAllAccountPos) CloseAllAccountPositions(); // 再次確保強制清空
      return; // 直接返回跳過後續交易
   } // 條件結束

   double curEquity = AccountInfoDouble(ACCOUNT_EQUITY); // 取當前即時權益
   if(g_SOD_Baseline > 0.0) // 確保基準點有效
   { // 條件開頭
      double dailyHardFloor = g_SOD_Baseline * (1.0 - g_MaxDailyLossPct / 100.0); // 計算當日死線金額
      if(curEquity <= dailyHardFloor) // 若即時權益跌破當日死線
      { // 條件開頭
         double actualLossPct = ((g_SOD_Baseline - curEquity) / g_SOD_Baseline) * 100.0; // 計算實際虧損比例
         g_DailyHalted = true; // 標記今日觸發熔斷
         SaveFTMOState(); // 保存狀態
         PrintFormat("🚨🚨🚨 [FTMO 緊急風控熔斷] 即時權益 %.2f 跌破當日死線 %.2f！當日虧損 %.2f%% >= 門檻 %.2f%% (SOD Baseline: %.2f)", curEquity, dailyHardFloor, actualLossPct, g_MaxDailyLossPct, g_SOD_Baseline); // 印出日誌
         if(InpEnableAlerts) Alert("🚨 [FTMO 風控觸發] 當前權益跌破當日死線 ", DoubleToString(dailyHardFloor, 2), "！緊急全數平倉並停止今日交易！"); // 發送警報
         if(InpCloseAllAccountPos) CloseAllAccountPositions(); // 清空帳戶所有頭寸
         else { ClosePositionsByMagic(InpMagicMain); ClosePositionsByMagic(InpMagicPyramid); } // 僅清空本 EA 部位
         g_MainStopPrice = 0.0; // 清空主停損價
         g_PyramidStopPrice = 0.0; // 清空加倉停損價
         SavePersistentState(); // 儲存狀態
         return; // 結束
      } // 條件結束
   } // 條件結束

   if(InpInitialBalance > 0.0) // 確保初始資金參數有效
   { // 條件開頭
      double totalHardFloor = InpInitialBalance * (1.0 - g_MaxTotalLossPct / 100.0); // 計算帳戶總死線
      if(curEquity <= totalHardFloor) // 觸及總最大虧損線
      { // 條件開頭
         g_DailyHalted = true; // 標記熔斷
         SaveFTMOState(); // 保存狀態
         PrintFormat("🚨🚨🚨 [FTMO 總虧損熔斷] 即時權益 %.2f 跌破帳戶總死線 %.2f！(初始資金: %.2f)", curEquity, totalHardFloor, InpInitialBalance); // 印出日誌
         if(InpEnableAlerts) Alert("🚨 [FTMO 總風控觸發] 當前權益跌破總死線 ", DoubleToString(totalHardFloor, 2), "！緊急平倉並終止所有交易！"); // 發送通知
         if(InpCloseAllAccountPos) CloseAllAccountPositions(); // 清空全部位
         else { ClosePositionsByMagic(InpMagicMain); ClosePositionsByMagic(InpMagicPyramid); } // 僅清空本 EA 部位
         g_MainStopPrice = 0.0; // 清空停損
         g_PyramidStopPrice = 0.0; // 清空停損
         SavePersistentState(); // 儲存狀態
         return; // 結束
      } // 條件結束
   } // 條件結束
} // 函數結束

//+------------------------------------------------------------------+
//| 於已合成之 4H 陣列上計算指定索引處的 SMA (BarsSMA)                  |
//+------------------------------------------------------------------+
double BarsSMA(const double &arr[], int endIdx, int period) // 陣列版 SMA
{ // 函數開頭
   if(endIdx - period + 1 < 0) return 0.0; // 資料不足回傳 0
   double s = 0.0; // 累加值
   for(int k = endIdx - period + 1; k <= endIdx; k++) s += arr[k]; // 累加區間收盤價
   return s / period; // 回傳平均
} // 函數結束

//+------------------------------------------------------------------+
//| 於已合成之 4H 陣列上計算指定索引處的算術平均 ATR (BarsATR)           |
//+------------------------------------------------------------------+
double BarsATR(const double &hArr[], const double &lArr[], const double &cArr[], int endIdx, int period) // 陣列版 ATR
{ // 函數開頭
   if(endIdx - period < 0) return 0.0; // 需有前一根收盤價，資料不足回傳 0
   double s = 0.0; // TR 累加值
   for(int k = endIdx - period + 1; k <= endIdx; k++) // 累加 period 根 TR
   { // 迴圈開頭
      double tr = MathMax(hArr[k] - lArr[k], MathMax(MathAbs(hArr[k] - cArr[k-1]), MathAbs(lArr[k] - cArr[k-1]))); // 真實波幅
      s += tr; // 累加
   } // 迴圈結束
   return s / period; // 回傳算術平均 ATR
} // 函數結束

//+------------------------------------------------------------------+
//| 計算 30MA 二次微分 (曲率) CalcCurvature                            |
//| d1 = (ma[i] - ma[i-n]) / n / ATR[i]   一次微分，以 ATR 正規化       |
//| d2 = (d1[i] - d1[i-n]) / n            二次微分 (加速度)            |
//| d2 明顯為負代表上升動能急速衰竭，趨勢可能翻轉，此時不進多單。        |
//+------------------------------------------------------------------+
double CalcCurvature(double maNow, double maPrev, double maPrev2, double atrNow, double atrPrev, int span) // 計算曲率
{ // 函數開頭
   if(atrNow <= 0.0 || atrPrev <= 0.0 || span <= 0) return 0.0; // 防除零，回傳 0 表示不過濾
   double d1Now  = (maNow  - maPrev)  / span / atrNow;  // 當期一次微分
   double d1Prev = (maPrev - maPrev2) / span / atrPrev; // 前期一次微分
   return (d1Now - d1Prev) / span; // 回傳二次微分
} // 函數結束

//+------------------------------------------------------------------+
//| 計算 H4 簡單平均 ATR (CalcSimpleATR_H4)                            |
//| ⚠️ MT5 內建 iATR 採用 Wilder 平滑 (RMA)，與 Python 回測所用的       |
//|    「14 根 TR 算術平均」不同，會導致停損價與回測產生系統性偏差。     |
//|    故此處自行計算算術平均 ATR，確保 EA 與網頁回測邏輯完全一致。      |
//+------------------------------------------------------------------+
double CalcSimpleATR_H4(int shift, int period) // 計算 H4 算術平均 ATR
{ // 函數開頭
   double sumTR = 0.0; // TR 累加值
   for(int k = 0; k < period; k++) // 累加 period 根 TR
   { // 迴圈開頭
      int i = shift + k; // 當前 K 線索引
      double h  = iHigh(_Symbol, PERIOD_H4, i);      // 當根最高價
      double l  = iLow(_Symbol, PERIOD_H4, i);       // 當根最低價
      double cp = iClose(_Symbol, PERIOD_H4, i + 1); // 前一根收盤價
      if(h == 0 || l == 0 || cp == 0) return 0.0; // 資料未就緒則回傳 0
      double tr = MathMax(h - l, MathMax(MathAbs(h - cp), MathAbs(l - cp))); // 計算真實波幅 TR
      sumTR += tr; // 累加
   } // 迴圈結束
   return sumTR / period; // 回傳算術平均 ATR
} // 函數結束

//+------------------------------------------------------------------+
//| 計算 Alpha 因子 (CalculateAlpha) (同步最終版精準減號算式)            |
//+------------------------------------------------------------------+
bool CalculateAlpha(double &alpha1, double &alpha5, double &alpha10) // 計算日線 Alpha
{ // 函數開頭
   string dxySym = GetValidDXYSymbol(); // 取得有效的 DXY 商品代號 (同步最終版)

   double goldCloses[12]; // 宣告黃金收盤價陣列
   double dxyCloses[12];  // 宣告 DXY 收盤價陣列
   for(int i = 0; i < 12; i++) // 迴圈讀取 12 根日線收盤價
   { // 迴圈開頭
      goldCloses[i] = iClose(_Symbol, PERIOD_D1, i + 1); // 從 bar[1] 開始讀取黃金
      if(goldCloses[i] == 0) return false; // 若未準備好則回傳失敗

      // ⚠️ DXY 必須依「日期」對齊，不可沿用相同的 K 棒索引：
      //    XAUUSD 與 USDX 每週的 D1 根數可能不同 (例如黃金有週日 K 棒而 USDX 沒有)，
      //    若直接用 i+1 取 DXY，兩者會比較到不同日期，且誤差隨回看天數累積放大
      //    (Alpha10 可能錯開 2 天以上)。此處以黃金 K 棒時間反查對應之 DXY K 棒。
      datetime goldBarTime = iTime(_Symbol, PERIOD_D1, i + 1); // 取得該根黃金日線的時間
      if(goldBarTime == 0) return false; // 時間未就緒則回傳失敗
      int dxyShift = iBarShift(dxySym, PERIOD_D1, goldBarTime, false); // 反查同日期(或之前最近一根)的 DXY 索引
      if(dxyShift < 0) return false; // 查無對應 K 棒則回傳失敗
      dxyCloses[i] = iClose(dxySym, PERIOD_D1, dxyShift); // 讀取日期對齊後的 DXY 收盤價
      if(dxyCloses[i] == 0) return false; // 若未準備好則回傳失敗
   } // 迴圈結束

   double g_ret1  = (goldCloses[0] - goldCloses[1])  / goldCloses[1];  // 黃金 1 日報酬
   double g_ret5  = (goldCloses[0] - goldCloses[5])  / goldCloses[5];  // 黃金 5 日報酬
   double g_ret10 = (goldCloses[0] - goldCloses[10]) / goldCloses[10]; // 黃金 10 日報酬

   double d_ret1  = (dxyCloses[0] - dxyCloses[1])  / dxyCloses[1];  // 美元 1 日報酬
   double d_ret5  = (dxyCloses[0] - dxyCloses[5])  / dxyCloses[5];  // 美元 5 日報酬
   double d_ret10 = (dxyCloses[0] - dxyCloses[10]) / dxyCloses[10]; // 美元 10 日報酬

   alpha1  = g_ret1  - d_ret1;  // Alpha1 因子 (修正：精準對齊最終版減號 g_ret - d_ret)
   alpha5  = g_ret5  - d_ret5;  // Alpha5 因子 (修正：精準對齊最終版減號 g_ret - d_ret)
   alpha10 = g_ret10 - d_ret10; // Alpha10 因子 (修正：精準對齊最終版減號 g_ret - d_ret)
   return true; // 計算成功
} // 函數結束

//+------------------------------------------------------------------+
//| 更新日線過濾器與 Alpha 加倉許可 (UpdateDailyFilters) (同步最終版) |
//+------------------------------------------------------------------+
void UpdateDailyFilters() // 更新日線趨勢與加倉權限
{ // 函數開頭
   double ma50Array[1], ma20Array[1], ma60Array[1], dailyCloseArray[1]; // 宣告暫存陣列 (同步最終版)
   if(CopyBuffer(g_hMA50D, 0, 1, 1, ma50Array) <= 0) return; // 讀取日線 50SMA
   if(CopyBuffer(g_hMA20D, 0, 1, 1, ma20Array) <= 0) return; // 讀取日線 20SMA
   if(CopyBuffer(g_hMA60D, 0, 1, 1, ma60Array) <= 0) return; // 讀取日線 60SMA

   dailyCloseArray[0] = iClose(_Symbol, PERIOD_D1, 1); // 讀取日線前一根收盤價
   if(dailyCloseArray[0] == 0) return; // 防零值

   double alpha1 = 0, alpha5 = 0, alpha10 = 0; // 宣告 Alpha 變數
   bool alphaOK = CalculateAlpha(alpha1, alpha5, alpha10); // 計算 Alpha (同步最終版)

   g_RegimeBull = (dailyCloseArray[0] > ma50Array[0]); // 牛市條件: 收盤價 > 日線 50MA

   if(alphaOK) // 若 Alpha 計算成功
   { // 條件開頭
      g_PyramidLongOK  = (alpha1 > 0) && (alpha5 > 0) && (alpha10 > 0) && (ma20Array[0] > ma60Array[0]); // 加多條件
      g_PyramidShortOK = (alpha1 < 0) && (alpha5 < 0) && (alpha10 < 0) && (ma20Array[0] < ma60Array[0]); // 加空條件
   } // 條件結束
   else // 若 Alpha 數據不可用 -> 一律禁止加碼 (保守)
   { // 條件開頭
      // ⚠️ 原本在此回退為「純 MA 過濾」(ma20 > ma60)，但該條件比回測寬鬆許多，
      //    會在缺少跨市場 Alpha 驗證的情況下放行加碼，與網頁回測邏輯不一致。
      //    改為直接禁止加碼：寧可少賺，不可在資料缺失時放大部位。
      g_PyramidLongOK  = false; // 禁止加多
      g_PyramidShortOK = false; // 禁止加空
      PrintFormat("⚠️ [Alpha 資料不可用] 已暫停加碼機制 (DXY=%s)，主部位邏輯不受影響", GetValidDXYSymbol()); // 印出警示日誌
   } // 條件結束

   g_DailyReady = true; // 標記日線過濾器就緒
} // 函數結束

//+------------------------------------------------------------------+
//| 由 1H 數據合成指定偏移之 4H K 線 (GetOffset4H_BarData)              |
//| ⚠️ 舊版以「陣列連續 4 個索引 = 一根 4H」分組，遇到每日休市或週末缺口   |
//|    會把不同時段拼接成同一根 K 棒。實測最近 200 根中有 13% 跨距異常     |
//|    (20 根跨 4 小時、6 根跨 52 小時，將週五與週一併為一根)，導致       |
//|    30MA / ATR 與訊號和 Python 回測分歧 (16% 收盤價不同，最大差 19 點)。|
//|    本版改為「依實際 UTC 時間」歸戶，並自動跳過無資料的空窗口。         |
//+------------------------------------------------------------------+
bool GetOffset4H_BarData(int nBars, int offsetHours, double &outOpen[], double &outHigh[], double &outLow[], double &outClose[]) // 依時間合成 4H K線
{ // 函數開頭
   ArrayResize(outOpen, nBars);  // 調整 Open 陣列
   ArrayResize(outHigh, nBars);  // 調整 High 陣列
   ArrayResize(outLow, nBars);   // 調整 Low 陣列
   ArrayResize(outClose, nBars); // 調整 Close 陣列

   MqlRates rates1H[]; // 1H 數據陣列 (動態)
   ArraySetAsSeries(rates1H, false); // 設為由舊到新排列
   int need = nBars * 4 + 300; // 預留休市與週末缺口所需的額外根數
   if(need > 3000) need = 3000; // 上限保護
   int copied = CopyRates(_Symbol, PERIOD_H1, 0, need, rates1H); // 讀取 1H 數據
   if(copied < nBars * 4 + 20) return false; // 數據不足跳過

   int gmtOffset = (int)(TimeCurrent() - TimeGMT()); // 券商伺服器對 GMT 的動態偏移
   long win = 4 * 3600;                    // 一根 4H 的秒數
   long off = (long)offsetHours * 3600;    // 網格偏移秒數

   long lastUtc = (long)(rates1H[copied - 2].time - gmtOffset); // 最後一根「已完結」1H 的 UTC 時間
   long winEnd = ((lastUtc + 3600 - off) / win) * win + off;    // 最新已完結 4H 窗口的結束時間

   int filled = 0; // 已填入根數
   for(int w = 0; w < nBars * 8 && filled < nBars; w++) // 由新到舊逐一窗口掃描 (上限避免無限迴圈)
   { // 迴圈開頭
      long ws = winEnd - (long)(w + 1) * win; // 該窗口起始時間
      long we = winEnd - (long)w * win;       // 該窗口結束時間
      bool has = false; // 該窗口是否有資料
      double o = 0, hi = 0, lo = 0, c = 0; // 該窗口 OHLC

      for(int i = copied - 2; i >= 0; i--) // 由新到舊掃描 1H 資料
      { // 迴圈開頭
         long t = (long)(rates1H[i].time - gmtOffset); // 該根 1H 的 UTC 時間
         if(t >= we) continue;  // 尚未進入本窗口 (較新)，略過
         if(t < ws) break;      // 已早於本窗口，結束掃描
         if(!has) { c = rates1H[i].close; hi = rates1H[i].high; lo = rates1H[i].low; has = true; } // 首見者為該窗口最後一根 -> 收盤價
         else { if(rates1H[i].high > hi) hi = rates1H[i].high; if(rates1H[i].low < lo) lo = rates1H[i].low; } // 更新極值
         o = rates1H[i].open; // 迴圈由新到舊，最後寫入者即為該窗口最早一根 -> 開盤價
      } // 迴圈結束

      if(has) // 該窗口有資料才寫入 (空窗口如週末自動跳過)
      { // 條件開頭
         int idx = nBars - 1 - filled; // 由陣列尾端往前填 (索引越大越新)
         outOpen[idx] = o; outHigh[idx] = hi; outLow[idx] = lo; outClose[idx] = c; // 寫入 OHLC
         filled++; // 計數
      } // 條件結束
   } // 迴圈結束

   return (filled == nBars); // 需完整填滿才視為成功
} // 函數結束

//+------------------------------------------------------------------+
//| 重構移動停損價 (ReconstructStopPrices) (同步最終版)               |
//+------------------------------------------------------------------+
void ReconstructStopPrices() // 重構移動停損價
{ // 函數開頭
   ulong mainTicket = 0, pyrTicket = 0; // 持倉票號
   int totalEAPos = CountPositionsByEA(mainTicket, pyrTicket); // 統計持倉
   if(totalEAPos == 0) return; // 無持倉無需重構

   Print("🔄 [狀態重構] 正在為當前持倉重構歷史軌跡停損價..."); // 印出日誌

   datetime entryTime = 0; // 進場時間
   ENUM_POSITION_TYPE posType = POSITION_TYPE_BUY; // 方向
   if(mainTicket > 0 && PositionSelectByTicket(mainTicket)) // 主部位
   { // 條件開頭
      entryTime = (datetime)PositionGetInteger(POSITION_TIME); // 時間
      posType   = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE); // 方向
   } // 條件結束
   else if(pyrTicket > 0 && PositionSelectByTicket(pyrTicket)) // 加倉部位
   { // 條件開頭
      entryTime = (datetime)PositionGetInteger(POSITION_TIME); // 時間
      posType   = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE); // 方向
   } // 條件結束

   double stopPrice = 0.0; // 停損價變數

   if(_Period == PERIOD_H1) // 掛載在 H1 圖表上時，完全使用合成之 +0h 4H 數據重構停損 (同步最終版)
   { // 條件開頭
      double oBars[100], hBars[100], lBars[100], cBars[100]; // 宣告 100 根 4H 陣列
      if(GetOffset4H_BarData(100, InpBarOffsetHours, oBars, hBars, lBars, cBars)) // 精準合成 +0h 4H K 線
      { // 條件開頭
         for(int i = 2; i < 100; i++) // 正向重放歷史 4H 軌跡
         { // 迴圈開頭
            double h = hBars[i]; // 當前 High
            double l = lBars[i]; // 當前 Low
            double h_prev = hBars[i-1]; // 前 High
            double l_prev = lBars[i-1]; // 前 Low

            double atr = 0.0; // 該時點之 14ATR (算術平均，對齊回測；原本誤用單根 TR 導致停損價偏差)
            if(i >= InpATR4H_Period) // 需有足夠歷史根數才能計算
            { // 條件開頭
               double sumTR = 0.0; // TR 累加值
               for(int m = i - InpATR4H_Period + 1; m <= i; m++) // 累加 14 根 TR
               { // 迴圈開頭
                  double trm = MathMax(hBars[m] - lBars[m], MathMax(MathAbs(hBars[m] - cBars[m-1]), MathAbs(lBars[m] - cBars[m-1]))); // 該根 TR
                  sumTR += trm; // 累加
               } // 迴圈結束
               atr = sumTR / InpATR4H_Period; // 算術平均 ATR
            } // 條件結束
            else continue; // 資料不足則跳過該根

            if(posType == POSITION_TYPE_BUY) // 多頭軌跡
            { // 條件開頭
               double initStop = MathMin(l, l_prev) - 1.0 * atr; // 計算初始停損
               if(stopPrice == 0.0 || initStop > stopPrice) stopPrice = initStop; // 首根賦值
               else if(cBars[i] > h_prev) // 突破前高
               { // 條件開頭
                  double newStop = MathMin(l, l_prev) - 1.0 * atr; // 計算新停損
                  if(newStop > stopPrice) stopPrice = newStop; // 向上移動停損
               } // 條件結束
            } // 條件結束
            else // 空頭軌跡
            { // 條件開頭
               double initStop = MathMax(h, h_prev) + 1.0 * atr; // 計算初始停損
               if(stopPrice == 0.0 || initStop < stopPrice) stopPrice = initStop; // 首根賦值
               else if(cBars[i] < l_prev) // 跌破前低
               { // 條件開頭
                  double newStop = MathMax(h, h_prev) + 1.0 * atr; // 計算新停損
                  if(newStop < stopPrice) stopPrice = newStop; // 向下移動停損
               } // 條件結束
            } // 條件結束
         } // 迴圈結束
      } // 條件結束
   } // 條件結束
   else // 原 H4 圖表相容模式
   { // 條件開頭
      int startBarIndex = iBarShift(_Symbol, PERIOD_H4, entryTime, false); // 計算進場對應之 4H K 線索引
      if(startBarIndex < 0) startBarIndex = 100; // 防錯保護

      for(int i = startBarIndex; i >= 1; i--) // 從進場 K 線正向重放至上一根完結 K 線
      { // 迴圈開頭
         double h = iHigh(_Symbol, PERIOD_H4, i); // 取當時 High
         double l = iLow(_Symbol, PERIOD_H4, i); // 取當時 Low
         double h_prev = iHigh(_Symbol, PERIOD_H4, i + 1); // 取前 High
         double l_prev = iLow(_Symbol, PERIOD_H4, i + 1); // 取前 Low

         double atr = CalcSimpleATR_H4(i, InpATR4H_Period); // 讀取當時 14ATR (算術平均，對齊回測而非 Wilder 平滑的 iATR)
         if(atr <= 0.0) continue; // ATR 未就緒則跳過

         if(posType == POSITION_TYPE_BUY) // 多頭軌跡
         { // 條件開頭
            double initStop = MathMin(l, l_prev) - 1.0 * atr; // 計算初始停損
            if(stopPrice == 0.0 || initStop > stopPrice) stopPrice = initStop; // 首根賦值
            else if(iClose(_Symbol, PERIOD_H4, i) > h_prev) // 若突破前高
            { // 條件開頭
               double newStop = MathMin(l, l_prev) - 1.0 * atr; // 計算新停損
               if(newStop > stopPrice) stopPrice = newStop; // 上移停損
            } // 條件結束
         } // 條件結束
         else // 空頭軌跡
         { // 條件開頭
            double initStop = MathMax(h, h_prev) + 1.0 * atr; // 計算初始停損
            if(stopPrice == 0.0 || initStop < stopPrice) stopPrice = initStop; // 首根賦值
            else if(iClose(_Symbol, PERIOD_H4, i) < l_prev) // 若跌破前低
            { // 條件開頭
               double newStop = MathMax(h, h_prev) + 1.0 * atr; // 計算新停損
               if(newStop < stopPrice) stopPrice = newStop; // 下移停損
            } // 條件結束
         } // 條件結束
      } // 迴圈結束
   } // 條件結束

   if(mainTicket > 0) g_MainStopPrice = stopPrice; // 寫入主停損
   if(pyrTicket > 0)  g_PyramidStopPrice = stopPrice; // 寫入加倉停損
   SavePersistentState(); // 保存狀態
   PrintFormat("✅ [狀態重構完成] 計算出之移動停損價: %.2f", stopPrice); // 日誌
} // 函數結束

//+------------------------------------------------------------------+
//| 處理新完結之 4H K 線交易邏輯 (ProcessNew4HBar) (同步最終版)        |
//+------------------------------------------------------------------+
void ProcessNew4HBar() // 新 4H K 線完結邏輯
{ // 函數開頭
   double c1, c2, h1, l1, h2, l2, ma4h, atr4h; // 宣告核心 OHLC 與指標變數
   double curvature = 0.0; // 30MA 二次微分 (曲率)，預設 0 表示不觸發過濾

   if(_Period == PERIOD_H1) // 圖表為 1H 時採用 UTC +0h 合成數據
   { // 條件開頭
      // 需額外 2*Span 根歷史才能算出二次微分，故合成 41 根 (最新完結者為索引 40)
      double oBars[41], hBars[41], lBars[41], cBars[41]; // 宣告暫存陣列
      if(!GetOffset4H_BarData(41, InpBarOffsetHours, oBars, hBars, lBars, cBars)) // 合成 41 根 +0h 4H K線
      { // 條件開頭
         Print("⚠️ [+0h 數據合成中] 等待 1H 數據加載..."); // 印出提示
         return; // 數據未就緒跳過
      } // 條件結束

      int last = 40; // 最新完結之 4H K 線索引
      c1 = cBars[last];     // bar[1] 完結 4H 收盤價
      c2 = cBars[last - 1]; // bar[2] 完結 4H 收盤價
      h1 = hBars[last];     // bar[1] 完結 4H 最高價
      l1 = lBars[last];     // bar[1] 完結 4H 最低價
      h2 = hBars[last - 1]; // bar[2] 完結 4H 最高價
      l2 = lBars[last - 1]; // bar[2] 完結 4H 最低價

      ma4h  = BarsSMA(cBars, last, InpMA4H_Period);                        // 4H 30MA
      atr4h = BarsATR(hBars, lBars, cBars, last, InpATR4H_Period);         // 4H 14ATR (算術平均)

      int sp = InpCurvatureSpan; // 微分跨度
      double maPrev  = BarsSMA(cBars, last - sp, InpMA4H_Period);          // sp 根前的 30MA
      double maPrev2 = BarsSMA(cBars, last - 2 * sp, InpMA4H_Period);      // 2*sp 根前的 30MA
      double atrPrev = BarsATR(hBars, lBars, cBars, last - sp, InpATR4H_Period); // sp 根前的 ATR
      curvature = CalcCurvature(ma4h, maPrev, maPrev2, atr4h, atrPrev, sp); // 計算二次微分
   } // 條件結束
   else // 原 H4 圖表相容模式
   { // 條件開頭
      double ma4hArray[1]; // 宣告快取陣列
      if(CopyBuffer(g_hMA4H, 0, 1, 1, ma4hArray) <= 0) return; // 讀取 4H MA
      double simpleATR = CalcSimpleATR_H4(1, InpATR4H_Period); // 改用算術平均 ATR (對齊回測，不用 Wilder 平滑的 iATR)
      if(simpleATR <= 0.0) return; // ATR 未就緒則跳過

      c1 = iClose(_Symbol, PERIOD_H4, 1); // bar[1] 收盤價
      c2 = iClose(_Symbol, PERIOD_H4, 2); // bar[2] 收盤價
      h1 = iHigh(_Symbol, PERIOD_H4, 1);  // bar[1] 最高價
      l1 = iLow(_Symbol, PERIOD_H4, 1);   // bar[1] 最低價
      h2 = iHigh(_Symbol, PERIOD_H4, 2);  // bar[2] 最高價
      l2 = iLow(_Symbol, PERIOD_H4, 2);   // bar[2] 最低價
      ma4h = ma4hArray[0]; // 4H MA 值
      atr4h = simpleATR; // 4H ATR 值 (算術平均，對齊回測)

      int sp4 = InpCurvatureSpan; // 微分跨度
      double maPrevArr[1], maPrev2Arr[1]; // 前期 MA 快取
      if(CopyBuffer(g_hMA4H, 0, 1 + sp4, 1, maPrevArr) > 0 && CopyBuffer(g_hMA4H, 0, 1 + 2 * sp4, 1, maPrev2Arr) > 0) // 讀取前期 30MA
      { // 條件開頭
         double atrPrev4 = CalcSimpleATR_H4(1 + sp4, InpATR4H_Period); // sp 根前的 ATR
         curvature = CalcCurvature(ma4h, maPrevArr[0], maPrev2Arr[0], atr4h, atrPrev4, sp4); // 計算二次微分
      } // 條件結束
   } // 條件結束

   g_LastATR4H = atr4h; // 快取本次交易邏輯所用之 ATR (供 HUD 顯示同源數值)

   g_LastCurvature = curvature; // 快取供 HUD 顯示

   // 4H 多頭訊號：Close > 30MA 且動能 > 0，並加入曲率過濾
   // 曲率 <= -門檻代表上升動能急速衰竭，此時不進多單 (空單條件為多頭訊號之反面，故同時放行做空)
   bool curvatureOK = (!InpEnableCurvature) || (curvature > -InpCurvatureThreshold); // 曲率過濾判定
   bool sig_long_4h = (c1 > ma4h) && (c1 > c2) && curvatureOK; // 4H 多頭訊號

   double longStopInit  = MathMin(l1, l2) - 1.0 * atr4h; // 初始多單停損價
   double shortStopInit = MathMax(h1, h2) + 1.0 * atr4h; // 初始空單停損價

   ulong mainTicket = 0, pyrTicket = 0; // 持倉票號
   int totalEAPos = CountPositionsByEA(mainTicket, pyrTicket); // 統計持倉

   if(totalEAPos > 0 && g_MainStopPrice == 0.0) // 若有持倉但停損為零 (防失億)
   { // 條件開頭
      ReconstructStopPrices(); // 重構停損價
   } // 條件結束

   //--- 孤兒加碼單安全防護：若主部位已被手動平倉或止損，但加碼單仍孤立存在
   if(mainTicket == 0 && pyrTicket > 0) // 檢測是否出現孤兒加碼單
   { // 條件開頭
      PrintFormat("⚠️ [孤兒加碼單防護] 主部位已平倉但加碼單 [Ticket=%d] 仍存在，緊急平倉孤兒加碼單！", pyrTicket); // 印出安全日誌
      ClosePositionsByMagic(InpMagicPyramid); // 清空孤兒加碼部位
      g_PyramidStopPrice = 0.0; // 清空加倉停損價
      SavePersistentState(); // 保存狀態
   } // 條件結束

   //--- CASE A: 當前持有【主多單】
   if(mainTicket > 0 && PositionSelectByTicket(mainTicket) && PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) // 判斷是否持有主多單
   { // 條件開頭
      if(c1 < g_MainStopPrice || !sig_long_4h) // 觸發停損或多頭訊號消失
      { // 條件開頭
         string reason = (c1 < g_MainStopPrice) ? "跌破移動停損" : "4H多頭訊號消失"; // 出場原因
         PrintFormat("🔴 [主多單平倉] 收盤=%.2f | 停損=%.2f | 原因=%s", c1, g_MainStopPrice, reason); // 印出日誌
         ClosePositionsByMagic(InpMagicMain); // 平倉主多單
         ClosePositionsByMagic(InpMagicPyramid); // 一併平倉加多單
         g_MainStopPrice = 0.0; // 清空主停損價
         g_PyramidStopPrice = 0.0; // 清空加倉停損價
         SavePersistentState(); // 儲存狀態
         return; // 結束執行
      } // 條件結束
      else // 未平倉，進行移動停損與加多檢查
      { // 條件開頭
         if(c1 > h2) // 突破前高
         { // 條件開頭
            g_MainStopPrice = longStopInit; // 向上移動主多停損
            SavePersistentState(); // 儲存狀態
         } // 條件結束

         if(InpEnablePyramid && pyrTicket > 0 && PositionSelectByTicket(pyrTicket)) // 若持有加多單
         { // 條件開頭
            if(c1 < g_PyramidStopPrice) // 觸發加多單停損
            { // 條件開頭
               PrintFormat("🟠 [加多單平倉] 收盤=%.2f | 停損=%.2f", c1, g_PyramidStopPrice); // 印出日誌
               ClosePositionsByMagic(InpMagicPyramid); // 單獨平倉加多單
               g_PyramidStopPrice = 0.0; // 清空加多停損價
               SavePersistentState(); // 儲存狀態
            } // 條件結束
            else if(c1 > h2) // 突破前高
            { // 條件開頭
               g_PyramidStopPrice = longStopInit; // 向上移動加多單停損
               SavePersistentState(); // 儲存狀態
            } // 條件結束
         } // 條件結束
         else if(InpEnablePyramid && pyrTicket == 0 && g_RegimeBull && g_PyramidLongOK && !g_DailyHalted) // 滿足加多條件
         { // 條件開頭
            double a1 = 0, a5 = 0, a10 = 0; // Alpha 變數
            if(!CalculateAlpha(a1, a5, a10)) // Alpha 取不到則放棄本次加碼 (與 UpdateDailyFilters 的保守策略一致)
            { // 條件開頭
               Print("⚠️ [加多略過] Alpha 資料暫不可用，本次不執行加碼"); // 印出略過日誌
               return; // 結束本次 4H 邏輯，不以殘缺數據放大部位
            } // 條件結束
            g_trade.SetExpertMagicNumber(InpMagicPyramid); // 切換 Magic Number
            double atr_safe = MathMax(atr4h, 4.0); // 確保 ATR 大於等於 4.0 點防止極端除零或過度放大
            double atr_ratio = InpBaselineATR / atr_safe; // 51Bitquant 核心：計算波動度倒數權重
            double base_mult = (a10 > InpAlphaBoostThresh) ? InpPyramidBoostMultiplier : 1.0; // 基礎乘數 (Alpha10 > 3% 為 2.0x，否則 1.0x)
            double dynamic_mult = MathMin(InpMaxPyrMult, MathMax(InpMinPyrMult, base_mult * atr_ratio)); // 限制在 [Min, Max] 範圍
            if(a10 > 0.04 && dynamic_mult < InpAlphaTrendFloor) dynamic_mult = InpAlphaTrendFloor; // 超強單邊動能保底保護 (防止高 ATR 誤殺順勢利潤)
            double pyrLot = NormalizeLot(InpLotSize * dynamic_mult); // 規範最終加多手數

            if(g_trade.Buy(pyrLot, _Symbol, 0, 0, 0, "Pyramid_Long")) // 買入加多
            { // 條件開頭
               g_PyramidStopPrice = longStopInit; // 設定加多停損
               PrintFormat("🟢 [51Bitquant加多進場] 手數=%.2f (%.2fx ATR調制, ATR=%.2f) | 停損=%.2f", pyrLot, dynamic_mult, atr4h, g_PyramidStopPrice); // 印出日誌
               SavePersistentState(); // 儲存狀態
            } // 條件結束
         } // 條件結束
      } // 條件結束
   } // 條件結束

   //--- CASE B: 當前持有【主空單】
   else if(mainTicket > 0 && PositionSelectByTicket(mainTicket) && PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_SELL) // 判斷是否持有主空單
   { // 條件開頭
      if(c1 > g_MainStopPrice || sig_long_4h) // 觸發停損或轉多頭訊號
      { // 條件開頭
         string reason = (c1 > g_MainStopPrice) ? "突破移動停損" : "4H訊號轉多"; // 出場原因
         PrintFormat("🔴 [主空單平倉] 收盤=%.2f | 停損=%.2f | 原因=%s", c1, g_MainStopPrice, reason); // 印出日誌
         ClosePositionsByMagic(InpMagicMain); // 平倉主空單
         ClosePositionsByMagic(InpMagicPyramid); // 一併平倉加空單
         g_MainStopPrice = 0.0; // 清空主停損價
         g_PyramidStopPrice = 0.0; // 清空加倉停損價
         SavePersistentState(); // 儲存狀態
         return; // 結束執行
      } // 條件結束
      else // 未平倉，進行移動停損與加空檢查
      { // 條件開頭
         if(c1 < l2) // 跌破前低
         { // 條件開頭
            g_MainStopPrice = shortStopInit; // 向下移動主空停損
            SavePersistentState(); // 儲存狀態
         } // 條件結束

         if(InpEnablePyramid && pyrTicket > 0 && PositionSelectByTicket(pyrTicket)) // 若持有加空單
         { // 條件開頭
            if(c1 > g_PyramidStopPrice) // 觸發加空單停損
            { // 條件開頭
               PrintFormat("🟠 [加空單平倉] 收盤=%.2f | 停損=%.2f", c1, g_PyramidStopPrice); // 印出日誌
               ClosePositionsByMagic(InpMagicPyramid); // 單獨平倉加空單
               g_PyramidStopPrice = 0.0; // 清空加空停損價
               SavePersistentState(); // 儲存狀態
            } // 條件結束
            else if(c1 < l2) // 跌破前低
            { // 條件開頭
               g_PyramidStopPrice = shortStopInit; // 向下移動加空單停損
               SavePersistentState(); // 儲存狀態
            } // 條件結束
         } // 條件結束
         else if(InpEnablePyramid && pyrTicket == 0 && !g_RegimeBull && g_PyramidShortOK && !g_DailyHalted) // 滿足加空條件
         { // 條件開頭
            double a1 = 0, a5 = 0, a10 = 0; // Alpha 變數
            if(!CalculateAlpha(a1, a5, a10)) // Alpha 取不到則放棄本次加碼 (與 UpdateDailyFilters 的保守策略一致)
            { // 條件開頭
               Print("⚠️ [加空略過] Alpha 資料暫不可用，本次不執行加碼"); // 印出略過日誌
               return; // 結束本次 4H 邏輯，不以殘缺數據放大部位
            } // 條件結束
            g_trade.SetExpertMagicNumber(InpMagicPyramid); // 切換 Magic Number
            double atr_safe = MathMax(atr4h, 4.0); // 確保 ATR 大於等於 4.0 點防止極端除零或過度放大
            double atr_ratio = InpBaselineATR / atr_safe; // 51Bitquant 核心：計算波動度倒數權重
            double base_mult = (a10 < -InpAlphaBoostThresh) ? InpPyramidBoostMultiplier : 1.0; // 基礎乘數 (Alpha10 < -3% 為 2.0x，否則 1.0x)
            double dynamic_mult = MathMin(InpMaxPyrMult, MathMax(InpMinPyrMult, base_mult * atr_ratio)); // 限制在 [Min, Max] 範圍
            if(a10 < -0.04 && dynamic_mult < InpAlphaTrendFloor) dynamic_mult = InpAlphaTrendFloor; // 超強單邊動能保底保護 (防止高 ATR 誤殺順勢利潤)
            double pyrLot = NormalizeLot(InpLotSize * dynamic_mult); // 規範最終加空手數

            if(g_trade.Sell(pyrLot, _Symbol, 0, 0, 0, "Pyramid_Short")) // 賣出加空
            { // 條件開頭
               g_PyramidStopPrice = shortStopInit; // 設定加空停損
               PrintFormat("🔻 [51Bitquant加空進場] 手數=%.2f (%.2fx ATR調制, ATR=%.2f) | 停損=%.2f", pyrLot, dynamic_mult, atr4h, g_PyramidStopPrice); // 印出日誌
               SavePersistentState(); // 儲存狀態
            } // 條件結束
         } // 條件結束
      } // 條件結束
   } // 條件結束

   //--- CASE C: 當前無持倉，檢查建倉 (同步最終版：重新統計持倉數量)
   totalEAPos = CountPositionsByEA(mainTicket, pyrTicket); // 重新統計持倉 (同步最終版)
   if(totalEAPos == 0 && !g_DailyHalted) // 無持倉且當日未熔斷
   { // 條件開頭
      double mainLot = NormalizeLot(InpLotSize); // 規範主部位手數 (同步最終版)
      if(g_RegimeBull && sig_long_4h) // 牛市且 4H 轉多頭
      { // 條件開頭
         g_trade.SetExpertMagicNumber(InpMagicMain); // 切換 Magic Number
         if(g_trade.Buy(mainLot, _Symbol, 0, 0, 0, "Main_Long")) // 買入主多單
         { // 條件開頭
            g_MainStopPrice = longStopInit; // 設定主多停損
            PrintFormat("🟢 [主多單進場] 手數=%.2f | 停損=%.2f | MA4H=%.2f", mainLot, g_MainStopPrice, ma4h); // 印出日誌
            if(InpEnableAlerts) Alert("🟢 Gold 4H: 主多單進場 @ ", DoubleToString(SymbolInfoDouble(_Symbol, SYMBOL_ASK), 2)); // 發送警報
            SavePersistentState(); // 儲存狀態
         } // 條件結束
      } // 條件結束
      else if(!g_RegimeBull && !sig_long_4h) // 熊市且 4H 轉空頭
      { // 條件開頭
         g_trade.SetExpertMagicNumber(InpMagicMain); // 切換 Magic Number
         if(g_trade.Sell(mainLot, _Symbol, 0, 0, 0, "Main_Short")) // 賣出主空單
         { // 條件開頭
            g_MainStopPrice = shortStopInit; // 設定主空停損
            PrintFormat("🔻 [主空單進場] 手數=%.2f | 停損=%.2f | MA4H=%.2f", mainLot, g_MainStopPrice, ma4h); // 印出日誌
            SavePersistentState(); // 儲存狀態
            if(InpEnableAlerts) Alert("🔻 Gold 4H: 主空單進場 @ ", DoubleToString(SymbolInfoDouble(_Symbol, SYMBOL_BID), 2)); // 發送警報
         } // 條件結束
      } // 條件結束
   } // 條件結束
} // 函數結束

//+------------------------------------------------------------------+
//| 判斷當前 1H K 線是否為台北時間 +0h (00, 04, 08, 12, 16, 20) 新 4H 開盤 |
//+------------------------------------------------------------------+
bool IsNewUTC4HBar(datetime current1HTime) // 判斷是否為指定偏移之 4H 新 K 線
{ // 函數開頭
   int gmtOffset = (int)(TimeCurrent() - TimeGMT()); // 券商伺服器對 GMT 的動態偏移秒數
   datetime utcTime = current1HTime - gmtOffset; // 動態轉為標準 UTC 時間
   MqlDateTime dt; // 時間結構體
   TimeToStruct(utcTime, dt); // 解析 UTC 時間
   return ((((dt.hour - InpBarOffsetHours) % 4) + 4) % 4 == 0); // 偏移 0 -> 00/04/08/12/16/20；偏移 2 -> 02/06/10/14/18/22
} // 函數結束

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit() // EA 初始化函數
{ // 函數開頭
   string prefix = "G4H_" + IntegerToString(InpMagicMain) + "_"; // 建立前綴字串 (同步最終版)
   g_gvKeyMainStop       = prefix + "MainStop";      // 建立主停損 Key (同步最終版)
   g_gvKeyPyramidStop    = prefix + "PyramidStop";   // 建立加倉停損 Key (同步最終版)
   g_gvKeyLastBar4H      = prefix + "LastBar4H";     // 建立時間 Key (同步最終版)
   g_gvKeySODBaseline    = prefix + "SODBaseline";   // 建立 SOD 基準價 Key
   g_gvKeyLastServerDate = prefix + "LastServerDate";// 建立日期 Key
   g_gvKeyDailyHalted    = prefix + "DailyHalted";   // 建立熔斷狀態 Key

   // 依 FTMO 帳戶類型自動套用風控門檻 (略低於官方上限以預留緩衝)
   switch(InpFTMOAccountType)
   { // switch 開頭
      case FTMO_1STEP:  g_MaxDailyLossPct = 2.5; g_MaxTotalLossPct = 9.0; break; // 官方 3%/10%
      case FTMO_2STEP:  g_MaxDailyLossPct = 4.5; g_MaxTotalLossPct = 9.0; break; // 官方 5%/10%
      default:          g_MaxDailyLossPct = InpMaxDailyLossPct; g_MaxTotalLossPct = InpMaxTotalLossPct; break; // 手動模式
   } // switch 結束
   PrintFormat("🛡️ [FTMO 風控設定] 帳戶類型=%s | 每日熔斷=%.2f%% | 總熔斷=%.2f%%",
               (InpFTMOAccountType==FTMO_1STEP ? "1-Step (官方上限 3%)" :
                InpFTMOAccountType==FTMO_2STEP ? "2-Step (官方上限 5%)" : "手動指定"),
               g_MaxDailyLossPct, g_MaxTotalLossPct); // 印出實際生效之風控門檻

   g_trade.SetExpertMagicNumber(InpMagicMain); // 設定預設 Magic Number
   g_trade.SetTypeFilling(GetValidFillingMode());  // 設定成交填單模式 (同步最終版 GetValidFillingMode)

   g_hMA4H  = iMA(_Symbol, PERIOD_H4, InpMA4H_Period, 0, MODE_SMA, PRICE_CLOSE); // 建立 4H SMA 指標 (同步最終版參數)
   g_hATR4H = iATR(_Symbol, PERIOD_H4, InpATR4H_Period);                         // 建立 4H ATR 指標 (同步最終版參數)
   g_hMA50D = iMA(_Symbol, PERIOD_D1, InpMA50_Period, 0, MODE_SMA, PRICE_CLOSE); // 建立日線 50SMA 指標
   g_hMA20D = iMA(_Symbol, PERIOD_D1, InpMA20_Period, 0, MODE_SMA, PRICE_CLOSE); // 建立日線 20SMA 指標
   g_hMA60D = iMA(_Symbol, PERIOD_D1, InpMA60_Period, 0, MODE_SMA, PRICE_CLOSE); // 建立日線 60SMA 指標

   string dxySym = GetValidDXYSymbol(); // 取得有效 DXY 代號 (同步最終版)
   if(!SymbolSelect(dxySym, true)) // 若無法加入
   { // 條件開頭
      PrintFormat("⚠️ 警告：無法將 %s 加入 Market Watch", dxySym); // 印出警告
   } // 條件結束

   LoadPersistentState(); // 載入 EA 歷史狀態
   UpdateDailyFilters();  // 更新日線過濾器
   CheckAndResetDailySOD(); // 初始化 FTMO 每日風控基準
   ProcessNew4HBar(); // 開機自動補單與極速訊號判定 (同步最終版 L147)

   PrintFormat("🚀 Gold 4H 30MA FTMO 版 EA 初始化成功！[MaxDailyLoss=%.1f%%, SOD_Baseline=%.2f]", g_MaxDailyLossPct, g_SOD_Baseline); // 印出日誌
   return(INIT_SUCCEEDED); // 回傳初始化成功
} // 函數結束

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason) // EA 解除初始化函數
{ // 函數開頭
   SavePersistentState(); // 保存當前狀態
   if(g_hMA50D != INVALID_HANDLE) IndicatorRelease(g_hMA50D); // 釋放 50SMA 句柄
   if(g_hMA20D != INVALID_HANDLE) IndicatorRelease(g_hMA20D); // 釋放 20SMA 句柄
   if(g_hMA60D != INVALID_HANDLE) IndicatorRelease(g_hMA60D); // 釋放 60SMA 句柄
   if(g_hMA4H  != INVALID_HANDLE) IndicatorRelease(g_hMA4H);  // 釋放 4H MA 句柄
   if(g_hATR4H != INVALID_HANDLE) IndicatorRelease(g_hATR4H); // 釋放 4H ATR 句柄
   Comment(""); // 清空圖表 HUD 儀表板
   PrintFormat("👋 EA 已終止執行 (原因碼=%d)，狀態已自動保存。", reason); // 印出日誌 (同步最終版)
} // 函數結束

//+------------------------------------------------------------------+
//| Expert tick function                                             |
//+------------------------------------------------------------------+
//+------------------------------------------------------------------+
//| 更新圖表即時 HUD 儀表板 (UpdateChartDashboard)                     |
//+------------------------------------------------------------------+
void UpdateChartDashboard() // 更新圖表 HUD 儀表板
{ // 函數開頭
   double a1 = 0, a5 = 0, a10 = 0; // Alpha 變數
   bool hudAlphaOK = CalculateAlpha(a1, a5, a10); // 計算最新 Alpha 動能 (並保留成功與否供顯示)
   
   double curATR = 16.0; // 預設安全 ATR 值
   if(g_LastATR4H > 0.0) curATR = g_LastATR4H; // 顯示交易邏輯實際採用之 ATR (與回測同為算術平均，避免 HUD 與下單依據不一致)
   else { double atrArr[1]; if(g_hATR4H != INVALID_HANDLE && CopyBuffer(g_hATR4H, 0, 1, 1, atrArr) > 0) curATR = atrArr[0]; } // 尚未跑過 4H 邏輯時的暫時備援值
   
   double atr_safe = MathMax(curATR, 4.0); // 安全 ATR 防除零
   double volScale = InpBaselineATR / atr_safe; // 波動度調制係數
   string volRisk = "🟢 波動平穩 (加碼擴張)"; // 波動狀態評語
   if(curATR > 22.0) volRisk = "🔴 高波劇烈 (主動縮手防禦)"; // 高波警示
   else if(curATR > 16.0) volRisk = "🟡 波動中等 (標準動態調制)"; // 中波提示
   
   double currentEquity = AccountInfoDouble(ACCOUNT_EQUITY); // 當前帳戶淨值
   double floatingLoss = currentEquity - g_SOD_Baseline; // 今日浮動損益金額
   double dailyLossLimit = g_SOD_Baseline * (g_MaxDailyLossPct / 100.0); // 日內熔斷金額死線 (依帳戶類型)
   double buffer = dailyLossLimit + floatingLoss; // 離熔斷剩餘安全緩衝額度
   
   ulong mainTicket = 0, pyrTicket = 0; // 持倉票號變數
   CountPositionsByEA(mainTicket, pyrTicket); // 統計持倉部位
   
   string mainInfo = "無持倉 (Flat)"; // 主單狀態文字
   if(mainTicket > 0 && PositionSelectByTicket(mainTicket)) // 若主部位存在
   { // 條件開頭
      string pType = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? "BUY 多單" : "SELL 空單"; // 多空判定
      mainInfo = StringFormat("[%s] 手數: %.2f | 進場: %.2f | 停損: %.2f", pType, PositionGetDouble(POSITION_VOLUME), PositionGetDouble(POSITION_PRICE_OPEN), g_MainStopPrice); // 格式化文字
   } // 條件結束
   
   string pyrInfo = "無加碼 (None)"; // 加碼單狀態文字
   if(pyrTicket > 0 && PositionSelectByTicket(pyrTicket)) // 若加碼單存在
   { // 條件開頭
      string pType = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? "BUY 加多" : "SELL 加空"; // 多空判定
      pyrInfo = StringFormat("[%s] 手數: %.2f (%.2fx) | 進場: %.2f | 停損: %.2f", pType, PositionGetDouble(POSITION_VOLUME), PositionGetDouble(POSITION_VOLUME)/InpLotSize, PositionGetDouble(POSITION_PRICE_OPEN), g_PyramidStopPrice); // 格式化文字
   } // 條件結束

   string hud = ""; // 初始化儀表板字串
   hud += "══════════════════════════════════════════════════════════════════\n"; // 拼接儀表板頂部分隔線
   hud += " ⚡ XAUUSD 4H 30MA 51Bitquant 調倉 EA (FTMO 版) [+2h 錯開網格]\n"; // 系統標題文字
   hud += "══════════════════════════════════════════════════════════════════\n"; // 拼接標題分隔線
   hud += StringFormat(" 📈 大趨勢體制 (Regime 50SMA): %s\n", g_RegimeBull ? "🟢 牛市多頭 (Long Only)" : "🔴 熊市空頭 (Short Only)"); // 體制狀態資訊
   hud += StringFormat(" ⚡ 4H 14ATR 波動度: %.2f 點 (基準: %.1f 點) | %s\n", curATR, InpBaselineATR, volRisk); // 波動度即時狀態
   hud += StringFormat(" 🎯 51Bitquant 當前加碼乘數: %.2fx (範圍: %.1fx ~ %.1fx)\n", MathMin(InpMaxPyrMult, MathMax(InpMinPyrMult, InpPyramidBoostMultiplier * volScale)), InpMinPyrMult, InpMaxPyrMult); // 加碼乘數資訊
   if(hudAlphaOK) // Alpha 可用時顯示實際數值
      hud += StringFormat(" 🌐 Alpha 跨市場動能: 1D: %+.2f%% | 5D: %+.2f%% | 10D: %+.2f%%\n", a1 * 100.0, a5 * 100.0, a10 * 100.0); // 跨市場 Alpha 動能資訊
   else // Alpha 不可用時明確標示，避免誤讀為 0.00%
      hud += " 🌐 Alpha 跨市場動能: ⚠️ 資料不可用 (加碼機制已暫停)\n"; // Alpha 缺失警示
   if(InpEnableCurvature) // 顯示曲率過濾狀態
   { // 條件開頭
      bool cvOK = (g_LastCurvature > -InpCurvatureThreshold); // 是否通過曲率過濾
      hud += StringFormat(" 📐 30MA 曲率(二次微分): %+.4f (門檻 -%.3f) | %s\n", g_LastCurvature, InpCurvatureThreshold,
                          cvOK ? "🟢 動能正常，多單訊號可成立" : "🔴 動能衰竭中，暫停多單"); // 曲率狀態
   } // 條件結束
   hud += "──────────────────────────────────────────────────────────────────\n"; // 拼接資訊中隔線
   hud += StringFormat(" 🛡️ FTMO 每日風控 (%.1f%%): SOD基準=$%.2f | 當日浮動=%+$.2f\n", g_MaxDailyLossPct, g_SOD_Baseline, floatingLoss); // FTMO 當日風控基準
   hud += StringFormat(" 🚨 離 %.1f%% 熔斷死線剩餘緩衝: $%.2f (%s)\n", g_MaxDailyLossPct, buffer, g_DailyHalted ? "🔴 今日已熔斷停止交易" : "🟢 運行安全正常"); // 熔斷緩衝額度
   hud += "──────────────────────────────────────────────────────────────────\n"; // 拼接部位中隔線
   hud += StringFormat(" 💼 主持倉部位: %s\n", mainInfo); // 主持倉狀態資訊
   hud += StringFormat(" ➕ 加碼持倉: %s\n", pyrInfo); // 加碼部位狀態資訊
   hud += "══════════════════════════════════════════════════════════════════\n"; // 拼接儀表板底部分隔線
   Comment(hud); // 輸出至圖表左上角
} // 函數結束

void OnTick() // 每次 Tick 觸發函數
{ // 函數開頭
   UpdateChartDashboard(); // 即時更新圖表 HUD 儀表板
   CheckAndResetDailySOD(); // 檢查 FTMO 每日風控熔斷死線
   if(g_DailyHalted) return; // 若已熔斷則不執行交易 logic

   datetime currentDailyTime = iTime(_Symbol, PERIOD_D1, 0); // 取得當前日線時間 (與最終版同步)
   if(currentDailyTime != g_LastBarDaily || !g_DailyReady) // 若跳新日線或過濾器未就緒
   { // 條件開頭
      g_LastBarDaily = currentDailyTime; // 更新日線時間紀錄
      UpdateDailyFilters(); // 即時更新日線過濾狀態
   } // 條件結束

   datetime triggerTime = (_Period == PERIOD_H1) ? iTime(_Symbol, PERIOD_H1, 0) : iTime(_Symbol, PERIOD_H4, 0); // 取得當前開盤時間 (與最終版同步)
   if(triggerTime != g_LastBar4H) // 若跳新 K 線
   { // 條件開頭
      bool isTrigger = (_Period == PERIOD_H1) ? IsNewUTC4HBar(triggerTime) : true; // 依 UTC +0h 動態夏令時間點位觸發
      if(isTrigger) // 滿足觸發條件
      { // 條件開頭
         g_LastBar4H = triggerTime; // 更新 4H 時間紀錄
         ProcessNew4HBar();            // 執行 4H 交易邏輯
         SavePersistentState();        // 保存狀態
      } // 條件結束
   } // 條件結束
} // 函數結束
