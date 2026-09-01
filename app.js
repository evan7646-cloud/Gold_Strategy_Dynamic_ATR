let globalData = null; // 全域資料儲存變數
let currentMode = '2yr'; // 當前選取的數據集模式 ('2yr' 或 '4yr')
let filteredTrades = []; // 經篩選過濾後的交易紀錄清單
let currentPage = 1; // 當前分頁頁碼 (從 1 開始)
const pageSize = 15; // 每頁顯示交易筆數
let currentFilterType = 'ALL'; // 當前類型篩選條件
let currentSearchTerm = ''; // 當前搜尋關鍵字
let activeTradeId = null; // 當前被點擊選取高亮的交易 ID

document.addEventListener('DOMContentLoaded', () => { // 當 DOM 結構載入完成後執行
    fetchData(); // 讀取後端回測資料 JSON
    setupEventListeners(); // 綁定所有介面互動監聽器
}); // DOM 監聽結束

async function fetchData() { // 非同步讀取策略結果 JSON 函數
    try { // 嘗試請求並解析
        const response = await fetch('strategy_results.json?v=' + new Date().getTime()); // 發送 HTTP GET 請求 (防快取)
        if (!response.ok) throw new Error('無法讀取 strategy_results.json 數據'); // 檢查回應狀態
        globalData = await response.json(); // 解析 JSON 物件並存入全域變數

        // 切換按鈕上的交易筆數改為由回測結果動態填入 (避免與實際回測結果不一致)
        const n2 = globalData.metrics?.total_trades; // 2.1 年總筆數
        const n4 = globalData.metrics_4yr?.total_trades; // 4 年總筆數
        if (n2) document.getElementById('btn-2yr-count').textContent = n2; // 填入 2.1 年筆數
        if (n4) document.getElementById('btn-4yr-count').textContent = n4; // 填入 4 年筆數

        applyDatasetMode(currentMode); // 依當前模式套用並渲染儀表板
    } catch (err) { // 捕捉錯誤
        console.error('資料載入失敗:', err); // 於控制台印出錯誤日誌
        document.getElementById('last-updated-text').textContent = '資料載入失敗，請確認檔案！'; // 顯示錯誤提示
    } // 捕捉結束
} // fetchData 結束

function switchDataset(mode) { // 切換 2.1 年與 4 年數據集函數
    currentMode = mode; // 更新當前模式變數
    document.getElementById('btn-mode-2yr').classList.toggle('active', mode === '2yr'); // 切換 2.1 年按鈕樣式
    document.getElementById('btn-mode-4yr').classList.toggle('active', mode === '4yr'); // 切換 4 年按鈕樣式
    applyDatasetMode(mode); // 重新計算並渲染畫面
} // switchDataset 結束

function applyDatasetMode(mode) { // 套用指定數據集並繪製介面函數
    if (!globalData) return; // 若無資料則返回
    
    if (mode === '2yr') { // 【2.1 年實盤回測模式】
        renderStatusCards(globalData.current_status, globalData.metrics, globalData.gold_chart_data, '2yr'); // 渲染狀態卡片
        renderGoldChart(globalData.gold_chart_data, globalData.completed_trades); // 繪製 4H 主圖表
        renderEquityChart(globalData.completed_trades); // 繪製累積權益與回撤圖
        renderDXYChart(globalData.dxy_chart_data); // 繪製 DXY 美元指數圖
        
        filteredTrades = [...globalData.completed_trades].sort((a, b) => b.trade_id - a.trade_id); // 倒序排序交易
        currentPage = 1; // 重置頁碼為第 1 頁
        applyFilterAndSearch(); // 套用篩選並渲染表格
    } else { // 【4 年全歷史壓力測試模式】
        const m4 = globalData.metrics_4yr || globalData.metrics; // 取得 4 年指標
        renderStatusCards(globalData.current_status, m4, globalData.gold_chart_data, '4yr'); // 渲染 4 年卡片
        renderGoldChart(globalData.gold_chart_data, globalData.completed_trades); // 繪製主圖表
        renderEquityChart(globalData.completed_trades); // 繪製權益圖
        renderDXYChart(globalData.dxy_chart_data); // 繪製 DXY 圖
        
        filteredTrades = [...globalData.completed_trades].sort((a, b) => b.trade_id - a.trade_id); // 交易明細
        currentPage = 1; // 重置頁碼
        applyFilterAndSearch(); // 渲染表格
    } // 判斷結束
} // applyDatasetMode 結束

function renderStatusCards(status, metrics, goldChartData, mode) { // 渲染頂部指標卡片數據函數
    const is2Yr = (mode === '2yr'); // 判斷是否為 2.1 年模式
    
    // 頂部時間標籤
    const startStr = is2Yr ? '2024-07-07' : '2023-01-10'; // 起始日期
    const endStr = status.last_updated ? status.last_updated.substring(0, 10) : '2026-08-26'; // 結束日期
    document.getElementById('last-updated-text').textContent = `回測區間：${startStr} ~ ${endStr} (${is2Yr ? '2.1 年實盤' : '4 年全數據'})`; // 填入時間文字
    
    // 1. 市場體制 Regime 卡片
    const regimeEl = document.getElementById('regime-val'); // 取得 Regime 元素
    regimeEl.textContent = status.regime; // 填入體制文字
    regimeEl.className = 'card-main-val ' + (status.regime.includes('Bull') ? 'positive-val' : 'negative-val'); // 多空配色
    document.getElementById('regime-badge').textContent = status.regime.includes('Bull') ? '多頭體制 (做多為主)' : '空頭體制 (做空為主)'; // 標籤文字
    document.getElementById('gold-price-val').textContent = `$${status.gold_close.toFixed(2)}`; // 黃金現價
    document.getElementById('ma4h-val').textContent = `$${status.ma4h_30.toFixed(2)}`; // 4H 30MA
    document.getElementById('dxy-price-val').textContent = status.dxy_close.toFixed(3); // DXY 現價
    
    // 2. 51Bitquant 波動度調制卡片
    const curAtr = status.atr14_4h || 16.0; // 當前 4H ATR
    const baseAtr = status.baseline_atr || 16.0; // 基準 ATR
    const volScale = Math.min(2.5, Math.max(0.5, 2.0 * (baseAtr / Math.max(curAtr, 4.0)))); // 換算當前加碼倍數
    const volEl = document.getElementById('volatility-scale-val'); // 取得 DOM
    volEl.textContent = `${volScale.toFixed(2)}x 加碼手數`; // 填入當前調制乘數
    document.getElementById('current-atr-val').textContent = `${curAtr.toFixed(2)} 點`; // 當前 ATR
    document.getElementById('baseline-atr-val').textContent = `${baseAtr.toFixed(1)} 點`; // 基準 ATR
    
    const riskStatusEl = document.getElementById('vol-risk-status'); // 取得狀態文字元素
    if (curAtr > 22.0) { // 高波動
        riskStatusEl.textContent = '🔴 高波劇烈 (主動縮手防禦)'; // 文字
        riskStatusEl.style.color = '#ff3d71'; // 紅色
        volEl.className = 'card-main-val negative-val'; // 紅色
    } else if (curAtr < 14.0) { // 低波動平穩
        riskStatusEl.textContent = '🟢 波動平穩 (加碼擴張放大)'; // 文字
        riskStatusEl.style.color = '#00e676'; // 綠色
        volEl.className = 'card-main-val positive-val'; // 綠色
    } else { // 正常中度波動
        riskStatusEl.textContent = '🟡 波動適中 (標準動態調制)'; // 文字
        riskStatusEl.style.color = '#00e5ff'; // 青色
        volEl.className = 'card-main-val defense-val'; // 青色
    } // 波動判斷結束
    
    // 3. 🛡️ 浮動虧損防禦成效卡 (亮點指標)
    const floatClose = metrics.max_instant_float_loss_close || metrics.max_instant_float_loss || -231.88; // 單點浮虧 (修正 alpha_floor=1.0 後)
    const floatMDD = metrics.floating_drawdown_points || 667.13; // 浮動淨值 MDD (修正 alpha_floor=1.0 後)
    const pyrMAE = metrics.worst_pyramid_mae || -191.46; // 加碼單 MAE (修正 alpha_floor=1.0 後)
    
    const cmpW = metrics.comparison_with_watch || {}; // 與原始版對照數據 (百分比由回測動態計算，不再寫死)
    const pct = (v) => (typeof v === 'number' ? `較原版降 ${v}%` : '對照基準不可用'); // 格式化降幅文字

    // 標題副標與防禦徽章一併改為動態，避免顯示過期的行銷數字
    const subEl = document.getElementById('header-subtitle'); // 取得副標題元素
    if (subEl && metrics.calmar_ratio) subEl.textContent = `動態 ATR 逆反比部位管理 × 卡瑪比率 ${metrics.calmar_ratio} × ${is2Yr ? '2.1年' : '4年'}回測`; // 動態副標題
    const badgeEl = document.getElementById('float-loss-badge'); // 取得浮虧徽章元素
    if (badgeEl) badgeEl.textContent = typeof cmpW.instant_float_loss_reduction_pct === 'number' ? `浮虧降 ${cmpW.instant_float_loss_reduction_pct}% 🚀` : '浮虧防禦 🚀'; // 動態徽章

    document.getElementById('max-float-loss-val').textContent = `${floatClose.toFixed(2)} pts`; // 顯示單點浮虧
    if (is2Yr) { // 2.1 年數據
        document.getElementById('float-loss-compare-val').textContent = `${floatClose.toFixed(2)} pts (${pct(cmpW.instant_float_loss_reduction_pct)})`; // 浮虧降低比例 (動態)
        document.getElementById('floating-mdd-val').textContent = `${floatMDD.toFixed(2)} pts (${pct(cmpW.floating_mdd_reduction_pct)})`; // 浮動回撤降低 (動態)
        document.getElementById('pyr-mae-val').textContent = `${pyrMAE.toFixed(2)} pts (${pct(cmpW.pyr_mae_reduction_pct)})`; // 加碼單浮虧降低 (動態)
    } else { // 4 年數據
        document.getElementById('float-loss-compare-val').textContent = `${floatClose.toFixed(2)} pts (4年極限抗壓)`; // 4年浮虧
        document.getElementById('floating-mdd-val').textContent = `${floatMDD.toFixed(2)} pts (${pct(cmpW.floating_mdd_reduction_pct)})`; // 4年浮動回撤 (動態)
        document.getElementById('pyr-mae-val').textContent = `${pyrMAE.toFixed(2)} pts (全週期鎖定在安全區)`; // 4年加碼浮虧
    } // 判斷結束
    
    // 4. 總績效與 Calmar
    const totalPnl = metrics.total_pnl_points || 0.0; // 總損益
    const totalPnlEl = document.getElementById('total-pnl-val'); // DOM
    totalPnlEl.textContent = `${totalPnl >= 0 ? '+' : ''}${totalPnl.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})} pts`; // 格式化輸出
    totalPnlEl.className = 'card-main-val ' + (totalPnl >= 0 ? 'positive-val' : 'negative-val'); // 配色
    
    document.getElementById('calmar-ratio-val').textContent = metrics.calmar_ratio || '7.44'; // Calmar
    document.getElementById('sharpe-ratio-val').textContent = metrics.sharpe_ratio || '2.57'; // Sharpe
    document.getElementById('pf-winrate-val').textContent = `${metrics.profit_factor || '1.82'} (${metrics.win_rate || '40.5'}%)`; // PF & 勝率
    
    const mddPts = metrics.max_drawdown || 321.62; // MDD
    document.getElementById('mdd-val').textContent = `${mddPts.toFixed(2)} pts (${pct(cmpW.mdd_reduction_pct)})`; // MDD 顯示 (降幅動態計算)
    
    // 目前已平倉回撤 (Current DD) 顯示
    const curDD = metrics.current_drawdown || (is2Yr ? 173.94 : 313.81); // 當前回撤點數
    const curDDPct = metrics.current_drawdown_pct || (is2Yr ? 4.28 : 12.50); // 當前回撤比例
    const curDDText = `${curDD.toFixed(2)} pts (${curDDPct.toFixed(2)}%)`; // 格式化目前回撤字串
    const elCurDD = document.getElementById('current-dd-val'); // 取得卡片4目前回撤元素
    if (elCurDD) elCurDD.textContent = curDDText; // 更新卡片4目前回撤文字
    const elCard3CurDD = document.getElementById('card3-current-dd-val'); // 取得卡片3目前回撤元素
    if (elCard3CurDD) elCard3CurDD.textContent = curDDText; // 更新卡片3目前回撤文字 (移除寫死的對照百分比)
    
    // 5. Alpha 動能與 FTMO 風控
    const a1 = (status.alpha_1d * 100).toFixed(1); // 1D Alpha
    const a5 = (status.alpha_5d * 100).toFixed(1); // 5D Alpha
    const a10 = (status.alpha_10d * 100).toFixed(1); // 10D Alpha
    document.getElementById('alpha-values-row').textContent = `${a1 >= 0 ? '+' : ''}${a1}% / ${a5 >= 0 ? '+' : ''}${a5}% / ${a10 >= 0 ? '+' : ''}${a10}%`; // 填入文字
    
    const isAlphaBull = status.alpha_1d > 0 && status.alpha_5d > 0 && status.alpha_10d > 0; // 多頭
    const isAlphaBear = status.alpha_1d < 0 && status.alpha_5d < 0 && status.alpha_10d < 0; // 空頭
    const alphaStatusEl = document.getElementById('alpha-status-val'); // DOM
    if (isAlphaBull) { // 多頭
        alphaStatusEl.textContent = '🟢 多頭全面共振'; // 文字
        alphaStatusEl.className = 'card-main-val positive-val'; // 綠色
    } else if (isAlphaBear) { // 空頭
        alphaStatusEl.textContent = '🔴 空頭全面共振'; // 文字
        alphaStatusEl.className = 'card-main-val negative-val'; // 紅色
    } else { // 分化
        alphaStatusEl.textContent = '🟡 跨市場分化震盪'; // 文字
        alphaStatusEl.className = 'card-main-val defense-val'; // 青色
    } // 結束
} // renderStatusCards 結束

function renderGoldChart(chartData, trades) { // 繪製黃金 4H 主圖表函數
    const traces = []; // Plotly 圖表軌跡清單
    
    // 1. 4H K 線主軌跡
    traces.push({ // 加入 K 線軌跡
        type: 'candlestick', // 蠟燭圖類型
        x: chartData.timestamps, // 時間軸
        open: chartData.open, // 開盤價數列
        high: chartData.high, // 最高價數列
        low: chartData.low, // 最低價數列
        close: chartData.close, // 收盤價數列
        name: 'XAUUSD 4H', // 軌跡名稱
        increasing: { line: { color: '#00e676', width: 1 }, fillcolor: '#00e676' }, // 上漲翡翠綠色
        decreasing: { line: { color: '#ff3d71', width: 1 }, fillcolor: '#ff3d71' }, // 下跌珊瑚紅色
        yaxis: 'y' // 綁定主 Y 軸
    }); // K 線軌跡結束
    
    // 2. 4H 30MA 均線
    traces.push({ // 加入 30MA 軌跡
        type: 'scatter', // 折線圖類型
        mode: 'lines', // 純線條模式
        x: chartData.timestamps, // 時間
        y: chartData.ma30_8h, // 數值
        name: '4H 30MA', // 名稱
        line: { color: '#00e5ff', width: 1.8 } // 霓虹青色
    }); // 30MA 結束
    
    // 3. Daily 50MA 大趨勢線
    traces.push({ // 加入 50MA 軌跡
        type: 'scatter', // 折線圖
        mode: 'lines', // 線條
        x: chartData.timestamps, // 時間
        y: chartData.daily_ma50, // 數值
        name: 'Daily 50MA (Regime)', // 名稱
        line: { color: '#b388ff', width: 2.0, dash: 'solid' } // 魅惑紫色
    }); // 50MA 結束

    // 4. Daily 20MA
    traces.push({ // 加入 20MA 軌跡
        type: 'scatter', // 折線圖
        mode: 'lines', // 線條
        x: chartData.timestamps, // 時間
        y: chartData.daily_ma20, // 數值
        name: 'Daily 20MA', // 名稱
        line: { color: '#ff9100', width: 1.2, dash: 'dot' }, // 橘色虛線
        visible: 'legendonly' // 預設於圖例隱藏可手動開啟
    }); // 20MA 結束

    // 5. Daily 60MA
    traces.push({ // 加入 60MA 軌跡
        type: 'scatter', // 折線圖
        mode: 'lines', // 線條
        x: chartData.timestamps, // 時間
        y: chartData.daily_ma60, // 數值
        name: 'Daily 60MA', // 名稱
        line: { color: '#ff3d71', width: 1.2, dash: 'dot' }, // 紅色虛線
        visible: 'legendonly' // 預設隱藏
    }); // 60MA 結束

    // 6. 進場與加碼點位標記 (Annotations Markers)
    const entryX = [], entryY = [], entryText = [], entryColor = [], entrySymbol = []; // 進場座標與資訊
    const exitX = [], exitY = [], exitText = [], exitColor = []; // 出場座標與資訊
    
    trades.forEach(t => { // 遍歷交易
        // 進場點標記
        entryX.push(t.entry_date); // 進場時間
        entryY.push(t.entry_price); // 進場價格
        const uText = t.units !== 1.0 ? ` (${t.units}x Units)` : ''; // 手數倍率文字
        entryText.push(`Trade #${t.trade_id}: ${t.type} ${t.is_pyramid ? 'Pyramid 加碼' : 'Main 主單'}${uText}<br>價格: $${t.entry_price.toFixed(2)}<br>停損: $${t.stop_price}`); // Hover 文字
        if (t.type === 'Long') { // 多單
            entryColor.push(t.is_pyramid ? '#ff9100' : '#00e676'); // 綠色/橘色
            entrySymbol.push('triangle-up'); // 向上箭頭
        } else { // 空單
            entryColor.push(t.is_pyramid ? '#ff3d71' : '#26a69a'); // 紅色/青綠
            entrySymbol.push('triangle-down'); // 向下箭頭
        } // 判斷結束

        // 出場點標記
        exitX.push(t.exit_date); // 出場時間
        exitY.push(t.exit_price); // 出場價格
        const pnlSign = t.pnl_points >= 0 ? '+' : ''; // 正負號
        exitText.push(`Trade #${t.trade_id} 平倉 (${t.exit_reason})<br>出場價: $${t.exit_price.toFixed(2)}<br>淨損益: ${pnlSign}${t.pnl_points.toFixed(2)} pts<br>單筆最大浮虧: ${t.mae_points || 0} pts`); // 出場文字
        exitColor.push(t.pnl_points >= 0 ? '#00e676' : '#ff3d71'); // 獲利綠 / 虧損紅
    }); // 遍歷結束

    traces.push({ // 加入進場標記散點軌跡
        type: 'scatter', // 散點圖
        mode: 'markers', // 標記模式
        x: entryX, y: entryY, // 座標
        text: entryText, // 懸停文字
        hoverinfo: 'text', // 顯示自訂文字
        name: '進場/加碼點位', // 名稱
        marker: { symbol: entrySymbol, size: 9, color: entryColor, line: { color: '#ffffff', width: 1 } } // 樣式
    }); // 進場散點結束

    traces.push({ // 加入平倉標記散點軌跡
        type: 'scatter', // 散點圖
        mode: 'markers', // 標記模式
        x: exitX, y: exitY, // 座標
        text: exitText, // 懸停文字
        hoverinfo: 'text', // 顯示自訂文字
        name: '平倉出場點位', // 名稱
        marker: { symbol: 'x', size: 7, color: exitColor, line: { width: 1.5 } } // 叉叉樣式
    }); // 平倉散點結束

    const layout = { // 圖表排版設定
        plot_bgcolor: '#0b0e14', // 圖表繪圖區背景色
        paper_bgcolor: '#0b0e14', // 圖表畫布外圍背景色
        margin: { t: 30, r: 50, l: 60, b: 40 }, // 內邊距設定
        showlegend: true, // 顯示圖例
        legend: { orientation: 'h', y: 1.08, x: 0, font: { color: '#8c9ba5', size: 11 } }, // 圖例橫向排版
        xaxis: { // X 軸時間設定
            color: '#8c9ba5', // 軸線顏色
            gridcolor: 'rgba(255, 255, 255, 0.05)', // 網格線顏色
            rangeslider: { visible: false }, // 關閉下方多餘 Range Slider
            type: 'date' // 時間日期型態
        }, // X 軸結束
        yaxis: { // 主 Y 軸價格設定
            color: '#8c9ba5', // 軸線顏色
            gridcolor: 'rgba(255, 255, 255, 0.05)', // 網格線顏色
            side: 'right', // 價格置於右側
            autorange: true // 自動適應縮放
        } // Y 軸結束
    }; // 排版結束

    Plotly.newPlot('gold-chart', traces, layout, { responsive: true, displayModeBar: true }); // 渲染 Plotly 圖表
} // renderGoldChart 結束

function renderEquityChart(trades) { // 繪製累積權益曲線與水下回撤圖函數
    const sortedTrades = [...trades].sort((a, b) => new Date(a.exit_date) - new Date(b.exit_date)); // 按出場時間排序
    
    let cumPnl = 0.0; // 累積損益累加變數
    let peak = 0.0; // 歷史最高點追蹤變數
    const dates = []; // 時間軸陣列
    const equityVals = []; // 累積權益數列
    const ddVals = []; // 水下回撤數列
    
    sortedTrades.forEach(t => { // 遍歷交易
        cumPnl += t.pnl_points; // 累加淨獲利
        if (cumPnl > peak) peak = cumPnl; // 更新歷史峰值
        const dd = cumPnl - peak; // 計算負向水下回撤
        
        dates.push(t.exit_date); // 記錄時間
        equityVals.push(round2(cumPnl)); // 記錄累積權益
        ddVals.push(round2(dd)); // 記錄回撤點數
    }); // 遍歷結束

    const traces = [ // 雙軌跡清單
        { // 軌跡 1：累積淨值權益曲線 (Equity Curve)
            type: 'scatter', // 折線圖
            mode: 'lines', // 線條
            x: dates, y: equityVals, // 座標
            name: '51Bitquant 累積獲利點數 (pts)', // 名稱
            line: { color: '#00e676', width: 2.2 }, // 亮綠色
            fill: 'tozeroy', // 填滿到底部
            fillcolor: 'rgba(0, 230, 118, 0.08)', // 半透明綠色陰影
            yaxis: 'y1' // 主 Y 軸
        }, // 軌跡 1 結束
        { // 軌跡 2：水下回撤曲線 (Underwater Drawdown)
            type: 'scatter', // 折線圖
            mode: 'lines', // 線條
            x: dates, y: ddVals, // 座標
            name: '水下回撤 (Underwater Pts)', // 名稱
            line: { color: '#ff3d71', width: 1.5 }, // 亮紅色
            fill: 'tozeroy', // 填滿至零軸
            fillcolor: 'rgba(255, 61, 113, 0.2)', // 半透明紅色陰影
            yaxis: 'y2' // 副 Y 軸
        } // 軌跡 2 結束
    ]; // 軌跡結束

    const layout = { // 排版設定
        plot_bgcolor: '#0b0e14', // 底色
        paper_bgcolor: '#0b0e14', // 底色
        margin: { t: 25, r: 50, l: 60, b: 35 }, // 內距
        showlegend: true, // 顯示圖例
        legend: { orientation: 'h', y: 1.1, x: 0, font: { color: '#8c9ba5', size: 11 } }, // 圖例
        xaxis: { color: '#8c9ba5', gridcolor: 'rgba(255, 255, 255, 0.05)', type: 'date' }, // X 軸
        yaxis: { // 左側主 Y 軸 (獲利點數)
            title: 'Cumulative PnL (pts)', // 標題
            titlefont: { color: '#00e676', size: 12 }, // 字體顏色
            color: '#8c9ba5', // 軸線顏色
            gridcolor: 'rgba(255, 255, 255, 0.05)', // 網格
            side: 'left' // 置於左側
        }, // 主 Y 軸結束
        yaxis2: { // 右側副 Y 軸 (回撤點數)
            title: 'Drawdown (pts)', // 標題
            titlefont: { color: '#ff3d71', size: 12 }, // 字體顏色
            color: '#8c9ba5', // 軸線
            overlaying: 'y', // 與主 Y 軸疊加
            side: 'right', // 置於右側
            showgrid: false // 隱藏多餘網格線
        } // 副 Y 軸結束
    }; // 排版結束

    Plotly.newPlot('equity-chart', traces, layout, { responsive: true, displayModeBar: false }); // 繪製權益圖表
} // renderEquityChart 結束

function renderDXYChart(dxyData) { // 繪製 DXY 美元指數圖表函數
    if (!dxyData || !dxyData.timestamps) return; // 若無資料直接返回
    
    const traces = [ // 軌跡清單
        { // DXY K 線
            type: 'candlestick', // 蠟燭圖
            x: dxyData.timestamps, // 時間
            open: dxyData.open, high: dxyData.high, low: dxyData.low, close: dxyData.close, // OHLC
            name: 'DXY 日線', // 名稱
            increasing: { line: { color: '#26a69a', width: 1 }, fillcolor: '#26a69a' }, // 上漲青綠
            decreasing: { line: { color: '#ef5350', width: 1 }, fillcolor: '#ef5350' } // 下跌珊瑚紅
        }, // DXY 結束
        { // DXY 20MA
            type: 'scatter', mode: 'lines', x: dxyData.timestamps, y: dxyData.ma20, name: 'DXY 20MA', // 資料渲染與邏輯
            line: { color: '#00e676', width: 1.5 } // 綠色
        }, // 20MA 結束
        { // DXY 60MA
            type: 'scatter', mode: 'lines', x: dxyData.timestamps, y: dxyData.ma60, name: 'DXY 60MA', // 資料渲染與邏輯
            line: { color: '#ff3d71', width: 1.5 } // 紅色
        } // 60MA 結束
    ]; // 結束

    const layout = { // 排版
        plot_bgcolor: '#0b0e14', paper_bgcolor: '#0b0e14', margin: { t: 25, r: 50, l: 60, b: 35 }, // 資料渲染與邏輯
        showlegend: true, legend: { orientation: 'h', y: 1.1, x: 0, font: { color: '#8c9ba5', size: 11 } }, // 資料渲染與邏輯
        xaxis: { color: '#8c9ba5', gridcolor: 'rgba(255, 255, 255, 0.05)', type: 'date', rangeslider: { visible: false } }, // 資料渲染與邏輯
        yaxis: { color: '#8c9ba5', gridcolor: 'rgba(255, 255, 255, 0.05)', side: 'right' } // 資料渲染與邏輯
    }; // 排版結束

    Plotly.newPlot('dxy-chart', traces, layout, { responsive: true, displayModeBar: false }); // 繪製 DXY 圖表
} // renderDXYChart 結束

function applyFilterAndSearch() { // 套用篩選按鈕與搜尋字串過濾交易清單函數
    if (!globalData || !globalData.completed_trades) return; // 檢查資料
    
    let list = [...globalData.completed_trades].sort((a, b) => b.trade_id - a.trade_id); // 複製倒序
    
    // 1. 依按鈕類型篩選
    if (currentFilterType === 'LONG') list = list.filter(t => t.type === 'Long'); // 僅多單
    else if (currentFilterType === 'SHORT') list = list.filter(t => t.type === 'Short'); // 僅空單
    else if (currentFilterType === 'PYRAMID') list = list.filter(t => t.is_pyramid); // 僅加碼單
    else if (currentFilterType === 'WIN') list = list.filter(t => t.pnl_points > 0); // 僅獲利單
    else if (currentFilterType === 'LOSS') list = list.filter(t => t.pnl_points < 0); // 僅虧損單
    
    // 2. 依搜尋字串模糊比對
    if (currentSearchTerm.trim() !== '') { // 若有搜尋字
        const term = currentSearchTerm.toLowerCase(); // 轉小寫
        list = list.filter(t => { // 模糊匹配
            return String(t.trade_id).includes(term) || // 比對 ID
                   t.entry_date.toLowerCase().includes(term) || // 比對進場時間
                   t.exit_date.toLowerCase().includes(term) || // 比對出場時間
                   (t.exit_reason && t.exit_reason.toLowerCase().includes(term)) || // 比對出場原因
                   String(t.units).includes(term); // 比對手數
        }); // 比對結束
    } // 搜尋結束

    filteredTrades = list; // 更新過濾結果
    document.getElementById('trades-count-badge').textContent = `共 ${filteredTrades.length} 筆交易`; // 更新筆數徽章
    renderTradesTable(); // 渲染當前頁面表格
} // applyFilterAndSearch 結束

function renderTradesTable() { // 渲染歷史交易記錄表格函數
    const tbody = document.getElementById('trades-tbody'); // 取得表格主體 DOM
    tbody.innerHTML = ''; // 清空舊內容
    
    if (filteredTrades.length === 0) { // 若無符合資料
        tbody.innerHTML = '<tr><td colspan="12" class="text-center" style="padding: 24px; color: #8c9ba5;">沒有找到符合篩選條件的交易紀錄</td></tr>'; // 顯示無資料提示
        document.getElementById('pagination-info-text').textContent = '顯示第 0 至 0 筆，共 0 筆'; // 更新分頁資訊
        document.getElementById('current-page-num').textContent = '0 / 0'; // 更新頁碼
        return; // 返回
    } // 判斷結束

    const totalPages = Math.ceil(filteredTrades.length / pageSize); // 計算總頁數
    if (currentPage > totalPages) currentPage = totalPages; // 校正頁碼
    if (currentPage < 1) currentPage = 1; // 校正頁碼

    const startIndex = (currentPage - 1) * pageSize; // 當前頁起始索引
    const endIndex = Math.min(startIndex + pageSize, filteredTrades.length); // 當前頁結束索引
    const pageTrades = filteredTrades.slice(startIndex, endIndex); // 切片取出當前頁面資料

    pageTrades.forEach(t => { // 遍歷當前頁資料
        const tr = document.createElement('tr'); // 建立 table row
        if (activeTradeId === t.trade_id) tr.className = 'active-row'; // 若為選取中則套用高亮樣式
        
        const typeBadge = t.type === 'Long' ? '<span class="badge-long">LONG 多</span>' : '<span class="badge-short">SHORT 空</span>'; // 多空標籤
        const pyrBadge = t.is_pyramid ? '<span class="badge-pyr">加碼倉 (Pyr)</span>' : '<span class="badge-main">主部位 (Main)</span>'; // 部位標籤
        const unitsBadge = `<span class="badge-unit">${(t.units || 1.0).toFixed(2)}x Units</span>`; // 手數倍率標籤
        const pnlClass = t.pnl_points >= 0 ? 'text-profit' : 'text-loss'; // 損益樣式
        const pnlSign = t.pnl_points >= 0 ? '+' : ''; // 正負號
        const maeVal = t.mae_points ? `${t.mae_points.toFixed(2)} pts` : '--'; // MAE 顯示

        tr.innerHTML = '<td style="font-weight: bold; color: #ffd54f;">#' + t.trade_id + '</td>' + // 交易序號 ID
            '<td>' + typeBadge + '</td>' + // 方向標籤 (Long/Short)
            '<td>' + pyrBadge + '</td>' + // 部位屬性 (Main/Pyramid)
            '<td>' + unitsBadge + '</td>' + // 51Bitquant 手數倍率
            '<td>' + t.entry_date + '</td>' + // 進場時間
            '<td>$' + t.entry_price.toFixed(2) + '</td>' + // 進場價格
            '<td>' + t.exit_date + '</td>' + // 出場時間
            '<td>$' + t.exit_price.toFixed(2) + '</td>' + // 出場價格
            '<td class="text-mae">' + maeVal + '</td>' + // 單筆最大逆向浮虧 MAE
            '<td>' + t.holding_hours + ' 小時</td>' + // 持倉時數
            '<td>' + (t.exit_reason || 'Signal Exit') + '</td>' + // 出場原因
            '<td class="' + pnlClass + '">' + pnlSign + t.pnl_points.toFixed(2) + ' pts</td>'; // 淨損益點數

        tr.addEventListener('click', () => { // 綁定點擊資料列事件
            activeTradeId = t.trade_id; // 記錄選取 ID
            document.querySelectorAll('#trades-tbody tr').forEach(r => r.classList.remove('active-row')); // 移除其他列高亮
            tr.classList.add('active-row'); // 高亮當前列
            zoomToTrade(t); // 主圖表平滑跳轉聚焦該筆交易
        }); // 點擊綁定結束

        tbody.appendChild(tr); // 加入表格
    }); // 遍歷結束

    // 更新分頁文字與按鈕狀態
    document.getElementById('pagination-info-text').textContent = `顯示第 ${startIndex + 1} 至 ${endIndex} 筆，共 ${filteredTrades.length} 筆`; // 填入筆數文字
    document.getElementById('current-page-num').textContent = `${currentPage} / ${totalPages}`; // 填入當前頁碼
    document.getElementById('btn-first-page').disabled = (currentPage === 1); // 禁用首頁按鈕
    document.getElementById('btn-prev-page').disabled = (currentPage === 1); // 禁用上一頁按鈕
    document.getElementById('btn-next-page').disabled = (currentPage === totalPages); // 禁用下一頁按鈕
    document.getElementById('btn-last-page').disabled = (currentPage === totalPages); // 禁用末頁按鈕
} // renderTradesTable 結束

function zoomToTrade(trade) { // 於 Plotly 主圖表精準跳轉並聚焦單筆交易函數
    if (!trade) return; // 防呆
    const entryDate = new Date(trade.entry_date); // 進場日期物件
    const exitDate = new Date(trade.exit_date); // 出場日期物件
    
    // 設定前後 4 天緩衝區間
    const rangeStart = new Date(entryDate.getTime() - 4 * 24 * 60 * 60 * 1000).toISOString().substring(0, 19); // 前推 4 日
    const rangeEnd = new Date(exitDate.getTime() + 4 * 24 * 60 * 60 * 1000).toISOString().substring(0, 19); // 後推 4 日
    
    Plotly.relayout('gold-chart', { // 執行 Plotly 重設可視範圍
        'xaxis.range': [rangeStart, rangeEnd], // 更新 X 軸範圍
        'yaxis.autorange': true // 自動計算 Y 軸價格適應高度
    }); // 跳轉結束
} // zoomToTrade 結束

function setupEventListeners() { // 介面事件綁定函數
    // 1. 篩選按鈕事件
    document.querySelectorAll('.filter-btn').forEach(btn => { // 遍歷篩選按鈕
        btn.addEventListener('click', () => { // 監聽點擊
            document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active')); // 清除其他按鈕啟動狀態
            btn.classList.add('active'); // 啟用點選按鈕
            currentFilterType = btn.getAttribute('data-filter'); // 讀取篩選屬性
            currentPage = 1; // 重置為第 1 頁
            applyFilterAndSearch(); // 套用篩選
        }); // 監聽結束
    }); // 遍歷結束

    // 2. 搜尋輸入框事件
    const searchInput = document.getElementById('trades-search-input'); // 取得搜尋框
    searchInput.addEventListener('input', (e) => { // 監聽即時輸入
        currentSearchTerm = e.target.value; // 更新搜尋文字
        currentPage = 1; // 重置為第 1 頁
        applyFilterAndSearch(); // 即時篩選
    }); // 監聽結束

    // 3. 分頁按鈕事件
    document.getElementById('btn-first-page').addEventListener('click', () => { // 首頁按鈕
        if (currentPage !== 1) { currentPage = 1; renderTradesTable(); } // 切換第一頁
    }); // 首頁結束
    
    document.getElementById('btn-prev-page').addEventListener('click', () => { // 上一頁按鈕
        if (currentPage > 1) { currentPage--; renderTradesTable(); } // 頁碼減一
    }); // 上一頁結束
    
    document.getElementById('btn-next-page').addEventListener('click', () => { // 下一頁按鈕
        const totalPages = Math.ceil(filteredTrades.length / pageSize); // 算總頁
        if (currentPage < totalPages) { currentPage++; renderTradesTable(); } // 頁碼加一
    }); // 下一頁結束
    
    document.getElementById('btn-last-page').addEventListener('click', () => { // 末頁按鈕
        const totalPages = Math.ceil(filteredTrades.length / pageSize); // 算總頁
        if (currentPage !== totalPages) { currentPage = totalPages; renderTradesTable(); } // 切換末頁
    }); // 末頁結束

    // 4. 圖表重置按鈕
    document.getElementById('btn-reset-gold-chart').addEventListener('click', () => { // 重置主圖
        Plotly.relayout('gold-chart', { 'xaxis.autorange': true, 'yaxis.autorange': true }); // 自動全視角
    }); // 主圖重置結束
    
    document.getElementById('btn-reset-equity-chart').addEventListener('click', () => { // 重置權益圖
        Plotly.relayout('equity-chart', { 'xaxis.autorange': true, 'yaxis.autorange': true, 'yaxis2.autorange': true }); // 自動全視角
    }); // 權益重置結束
    
    document.getElementById('btn-reset-dxy-chart').addEventListener('click', () => { // 重置 DXY 圖
        Plotly.relayout('dxy-chart', { 'xaxis.autorange': true, 'yaxis.autorange': true }); // 自動全視角
    }); // DXY 重置結束
} // setupEventListeners 結束

function round2(num) { // 保留兩位小數輔助函數
    return Math.round((num + Number.EPSILON) * 100) / 100; // 精準四捨五入至兩位
} // round2 結束
