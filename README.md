# ⚡ Gold_Strategy_Dynamic_ATR: 黃金 4H 30MA 波動度自適應調倉系統 (51Bitquant Dynamic ATR + FTMO)

> 專為黃金 (XAUUSD) 打造的高夏普、高卡瑪比率量化交易系統。結合 **4H 30MA 趨勢突破**、**DXY 跨市場 Alpha 動能過濾**、**51Bitquant 波動度自適應手數調制** 與 **FTMO 企業級風控保護機制**。

---

## 🌟 策略核心優勢與防禦亮點

1. **⚡ 51Bitquant 波動度自適應調倉 (Dynamic ATR Sizing)**：
   - 解決傳統金字塔加碼在劇烈波動時停損過大、浮虧惡化的致命痛點。
   - 依據當前 4H 14ATR 與基準 ATR (預設 16.0 點) 之比值動態調節加碼手數 ($0.50\times \sim 2.50\times$)。
   - **低波動大趨勢放大手數賺足波段，高波動震盪縮小手數主動防禦**。
2. **🛡️ 浮動虧損大幅驟降 (Floating Risk Safeguard)**：
   - **單點最大未平倉浮虧 (Close)**：由 `-392.10 點` 暴降至 **`-151.77 點`（-61.3%）**！
   - **極端影線最大未平倉浮虧 (Worst)**：由 `-485.82 點` 暴降至 **`-222.54 點`（-54.2%）**！
   - **逐根浮動淨值最大回撤 (Floating MDD)**：由 `837.81 點` 降低至 **`581.79 點`（-30.6%）**！
   - **加碼單最差逆向浮虧 (Pyramid MAE)**：由 `-382.92 點` 鎖死在 **`-95.73 點`（-75.0%）**！
3. **📊 實盤回測指標表現**：
   - **卡瑪比率 (Calmar Ratio)**：高達 **7.44**（頂級基金抗回撤水準）
   - **夏普比率 (Sharpe Ratio)**：穩定維持在 **2.57**
   - **盈虧比 (Profit Factor)**：**1.82** (勝率 40.5%)
   - **最大已平倉回撤 (MDD)**：**321.62 點**（相較於原始版的 475.89 點，**回撤降低 32.4%**）
4. **🛡️ 嚴格實盤交易成本扣除 (100% 貼合實盤環境)**：
   - 每筆交易扣除 **0.3 點點差**。
   - 多單每日扣除 **0.75 點隔夜利息**，空單每日增加 **0.27 點正隔夜利息**。

---

## 📂 專案檔案架構

```text
Gold_Strategy_Dynamic_ATR/
├── STRATEGY_LOGIC.md                                # 📖 策略完整邏輯規格與數學公式詳細說明
├── BACKTEST_REPORT.md                               # 📊 回測與浮動虧損防禦成效詳報 (2.1Y 實盤 & 4Y 壓力測試)
├── Gold_4H_30MA_51Bitquant_Adaptive_Offset+0h_FTMO.mq5 # 🤖 MT5 實盤 EA (含圖表即時 HUD、51Bitquant 調制與 FTMO 風控)
├── gold_adaptive_strategy.py                        # 🐍 Python 核心回測與 MAE/浮動淨值計算引擎
├── run_4yr_backtest.py                              # 🧪 4 年 (5,585 根 K 線) 全歷史基準壓力測試腳本
├── strategy_results.json                            # 📊 供前端網頁載入之最新回測與即時數據
├── all_trades_detail_adaptive.csv                   # 📋 546 筆已平倉交易明細 (含每筆調制手數、MAE 與淨損益)
├── all_trades_4yr_adaptive.csv                      # 📋 4 年 1,108 筆壓力測試完整明細
├── backtest_equity_curve_adaptive.png               # 📈 2.1 年權益曲線與水下回撤圖 (高清導出圖)
├── backtest_equity_curve_4yr_adaptive.png           # 📈 4 年權益曲線與水下回撤圖
├── index.html                                       # 🌐 現代高階暗黑玻璃擬態儀表板 (支援 2.1Y / 4Y 切換與交易聚焦)
├── styles.css                                       # 🎨 完整玻璃擬態 CSS 樣式庫 (全繁體中文註釋)
├── app.js                                           # ⚡ 前端 Plotly.js 互動渲染與圖表跳轉邏輯
├── .github/workflows/update_data.yml                # ⏰ GitHub Actions 平日每 4H 自動更新排程
└── requirements.txt                                 # 📦 Python 依賴清單
```

---

## 🚀 快速上手指南

### 1. 執行本地回測與資料更新
```bash
python3 gold_adaptive_strategy.py  # 執行 2.1 年實盤回測與資料導出
python3 run_4yr_backtest.py        # 執行 4 年 (5,585 根 K 線) 深度全量回測
```

### 2. 開啟互動式網頁儀表板
```bash
python3 -m http.server 8080        # 啟動本地 Web 伺服器
# 開啟瀏覽器訪問: http://localhost:8080/
```

### 3. 部署至 MetaTrader 5 (MT5)
1. 將 [`Gold_4H_30MA_51Bitquant_Adaptive_Offset+0h_FTMO.mq5`](file:///Users/evan/Desktop/Github_Projects/Gold_Strategy_Dynamic_ATR/Gold_4H_30MA_51Bitquant_Adaptive_Offset+0h_FTMO.mq5) 複製至 MT5 `MQL5/Experts/` 資料夾。
2. 在 MT5 MetaEditor 中按 `F7` 編譯。
3. 拖曳至 `XAUUSD` 的 `H1` (自動 resample) 或 `H4` 圖表上，圖表左上角將即時顯示 HUD 儀表板監控波動度調制與 FTMO 今日浮動損益！
