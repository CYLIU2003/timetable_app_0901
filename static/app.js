// app.js – 2025-05-08 FULL (運行情報・天気・ニュース・発車案内・設定 UI すべて含む)
document.addEventListener("DOMContentLoaded", () => {

    /* ─────────── DOM ヘルパ ─────────── */
    const $  = id  => document.getElementById(id);
    const $$ = sel => document.querySelector(sel);

    function adjustStatusListHeight() {
      const statusWrapper = document.querySelector('.box-item.status'); // 運行情報全体を囲む要素のクラス名
      const statusList = document.getElementById('status-list');

      if (statusWrapper && statusList) {
        const wrapperHeight = statusWrapper.offsetHeight;
        statusList.style.maxHeight = `${wrapperHeight - 40}px`; // 40px は上下のパディングや他の要素のスペースを考慮した調整値
        statusList.style.overflowY = 'auto';
      }
    }
  
    /* ─────────── 共通 fetch (JSON) ─────────── */
    const jFetch = (url, opts) => fetch(url, opts).then(r => r.json());
  
    /* ─────────── 設定 UI 要素 ─────────── */
    const zoomSl    = $("zoom-slider");
    const fontSl    = $("font-slider");
    const resizeChk = $("resize-toggle");
    const zoomVal   = $("zoom-value");
    const fontVal   = $("font-value");
  
    const btnSet   = $("settings-button");
    const modal    = $("settings-modal");
    const btnClose = $("close-settings");
  
    const toggles = {
      status   : $("toggle-status"),
      weather  : $("toggle-weather"),
      news     : $("toggle-news"),
      schedule : $("toggle-schedule")
    };
  
    const panels = {
      status   : $("status-card"),
      weather  : $("weather-card"),
      news     : $("news-ticker"),
      schedule : $("routes-container")
    };
  
    const pickers = {
      statusBg : $("color-status-bg"),   statusText : $("color-status-text"),
      weatherBg: $("color-weather-bg"),  weatherText: $("color-weather-text"),
      newsBg   : $("color-news-bg"),     newsText   : $("color-news-text"),
      schedBg  : $("color-schedule-bg"), schedText  : $("color-schedule-text"),
      fontFam  : $("font-family-select")
    };
  
    const routeBox = $("route-selector-container");
    const maxStatusLinesInput = document.getElementById('max-status-lines-input');
  
    /* ─────────── グローバル状態 ─────────── */
    const timers = new Set();          // すべての setInterval ID
    let statusArr = [], statusIdx = 0; // 運行情報
    let newsArr   = [], newsIdx   = -1;// ニュース
    let scheduleJson = {};            // /api/schedule 結果
    let routesInit   = false;         // routeBox 生成済み?
    let showRoutes   = [];            // 表示路線
    let countMap     = {};            // { 路線 : 表示本数 }
  
    /* ─────────── ローカル画像マッピング ─────────── */
    const ICON_MAP = {
      /* 東急電鉄 */
      "大井町線"       : ["OM.png", "OM_1.png"],
      "田園都市線"     : ["tokyurailway/icon_DT.png"],
      "東横線"         : ["tokyurailway/icon_TY.png"],
      "目黒線"         : ["tokyurailway/icon_MG.png"],
      "池上線"         : ["tokyurailway/icon_IK.png"],
      "多摩川線"       : ["tokyurailway/icon_TM.png"],
      "こどもの国線"   : ["tokyurailway/icon_KD.png"],
      "東急新横浜線"   : ["tokyurailway/icon_SH.png"],

      /* ★★★ 東武鉄道 路線アイコン追加 ★★★ */
      "東上線":             ["tobu/icon_tojo.png"],
      "伊勢崎線":           ["tobu/icon_isesaki.png"],
      "スカイツリーライン": ["tobu/icon_skytree.png"],
      "日光線":             ["tobu/icon_nikko.png"],
      "アーバンパークライン": ["tobu/icon_urbanpark.png"],

      /* バス */
      "玉11"           : ["tokyu_bus.png"],
      "園02"           : ["tokyu_bus.png"],
      "等01"           : ["tokyu_bus.png"],

      /* === 東京メトロ === */
      "丸の内線"               : ["tokyometro/icon_marunouchi.png"],
      "丸の内線方南町支線"     : ["tokyometro/icon_marunouchi.png"],
      "南北線"                 : ["tokyometro/icon_namboku.png"],
      "東西線"                 : ["tokyometro/icon_tozai.png"],
      "有楽町線"               : ["tokyometro/icon_yurakucho.png"],
      "千代田線"               : ["tokyometro/icon_chiyoda.png"],
      "副都心線"               : ["tokyometro/icon_fukutoshin.png"],
      "銀座線"                 : ["tokyometro/icon_ginza.png"],
      "半蔵門線"               : ["tokyometro/icon_hanzomon.png"],
      "日比谷線"               : ["tokyometro/icon_hibiya.png"],

      /* === 都営地下鉄 === */
      "浅草線"                 : ["toei/icon_asakusa.png"],
      "三田線"                 : ["toei/icon_mita.png"],
      "新宿線"                 : ["toei/icon_shinjuku.png"],
      "大江戸線"               : ["toei/icon_oedo.png"],

      /* 都電 */
      "都電荒川線（東京さくらトラム）": ["toei/icon_arakawa.png"],

      /* 横浜市営地下鉄 */
      "グリーンライン": ["yokohama/icon_green.png"],
      "ブルーライン":   ["yokohama/icon_blue.png"],

      /* その他 */
      // "りんかい線"             : ["icon_rinkai.png"],
      // "つくばエクスプレス線"   : ["icon_tx.png"],
      "多摩モノレール"         : ["icon_tamamonorail.png"]
    };
    /* ← 保険：混在文字列があっても強制配列化 */
    for(const k in ICON_MAP){
      if(!Array.isArray(ICON_MAP[k])) ICON_MAP[k] = [ICON_MAP[k]];
    }
  
    /* ─────────── 汎用 ─────────── */
    const imgTag = fn => `<img class="logo" src="/static/img/${fn}" alt="">`;
    const getIcons = label => {
      for(const key in ICON_MAP){
        if(label.includes(key)) return ICON_MAP[key];
      }
      return [];
    };
  
    /* ─────────── 時計 ─────────── */
    function updateClock(){
      const n = new Date();
      $("current-time").textContent = n.toLocaleTimeString("ja-JP",{hour12:false});
      $("current-date").textContent = n.toLocaleDateString("ja-JP",
        {year:"numeric",month:"2-digit",day:"2-digit",weekday:"short"});
    }
  
    /* ============================ 運行情報 ============================ */
    // グローバル状態変数 statusArr はそのまま、statusIdx はページインデックスとして再利用
    let statusPageIdx = 0; 
  
    // 表示を更新するメイン関数
    function drawStatus() {
      const ul = $("status-list");
      if (!ul) return;
      ul.innerHTML = "";
  
      if (!statusArr || statusArr.length === 0) {
        // 表示する情報がない場合
        const li = document.createElement("li");
        li.className = "status-item";
        li.textContent = "運行情報はありません";
        ul.appendChild(li);
        return;
      }
  
      // 設定から表示する行数を取得
      const linesPerPage = parseInt($("max-status-lines-input")?.value || 2, 10);
      
      // 表示するべきページの開始位置を計算
      const start = statusPageIdx * linesPerPage;
      
      // 配列から現在のページに表示する要素を切り出す
      const itemsToShow = statusArr.slice(start, start + linesPerPage);
  
      // 切り出した要素をリストに描画
      itemsToShow.forEach(it => {
        const li = document.createElement("li");
        li.className = "status-item";
        if (it.logo) {
          li.insertAdjacentHTML("beforeend", `<img class="status-logo" src="${it.logo}">`);
        } else {
          getIcons(it.text).forEach(fn => {
            li.insertAdjacentHTML("beforeend", `<img class="status-logo" src="/static/img/${fn}">`);
          });
        }
        li.appendChild(document.createTextNode(it.text));
        ul.appendChild(li);
      });
    }
  
    // 4秒ごとにページを切り替える関数
    function cycleStatusPage() {
      if (!statusArr || statusArr.length === 0) return;
      
      const linesPerPage = parseInt($("max-status-lines-input")?.value || 2, 10);
      const totalPages = Math.ceil(statusArr.length / linesPerPage);
  
      if (totalPages > 1) {
        statusPageIdx = (statusPageIdx + 1) % totalPages;
      } else {
        statusPageIdx = 0;
      }
      
      drawStatus();
    }
  
    // サーバーから最新の運行情報を読み込む関数
    const loadStatus = () => {
      const maxLines = maxStatusLinesInput.value || 2;
      jFetch(`/api/status?max_lines=${maxLines}`, { cache: 'no-store' })
        .then(data => {
          if (!data || !data.status) {
            console.error("運行情報データが不正です:", data);
            return;
          }
          statusArr = data.status.map(item => {
            // logoがパス文字列の場合、完全なURLを生成する
            if (item.logo && typeof item.logo === 'string' && !item.logo.startsWith('http')) {
              item.logo = `/static/img/${item.logo}`;
            }
            return item;
          });
          statusIdx = 0;
          if (timers.size === 0) { // 初回またはリセット後
            drawStatus();
            timers.add(setInterval(cycleStatusPage, 4000));  // 4秒ごとにページ切替
          }
        })
        .catch(err => console.error("運行情報の取得に失敗:", err));
    };
  
    /* ============================ 天気 ============================ */
    function drawWeather(d){
      const cont = $("weather-info"); cont.innerHTML = "";
      d.forecasts.slice(0,3).forEach(f=>{
        const div = document.createElement("div"); div.className="forecast-day";
        div.innerHTML = `
          <div class="forecast-date">${f.dateLabel}</div>
          <div class="forecast-main">
            <img src="${f.image.url}" class="forecast-icon">
            <span>${f.telop}</span>
          </div>
          <div class="forecast-rain">降水確率：${f.chanceOfRain.T12_18||"--%"}</div>
          <div class="forecast-wind">風：${f.detail.wind||""}</div>`;
        cont.appendChild(div);
      });
    }
    const loadWeather = () => jFetch("/api/weather").then(drawWeather);
  
    /* ============================ ニュース ============================ */
    function newsCycle(){
      if(!newsArr.length) return;
      newsIdx = (newsIdx+1)%newsArr.length;
      const el = $("news-headline");
      el.style.opacity="0";
      setTimeout(()=>{
        el.textContent = newsArr[newsIdx];
        el.style.opacity="1";
      },200);
    }
    function loadNews(){
      jFetch("/api/news").then(d=>{
        newsArr = d.news||[];
        if(newsIdx<0&&newsArr.length){
          newsIdx=0; $("news-headline").textContent=newsArr[0];
        }
      });
    }
  
    /* ============================ 発車案内 ============================ */
    function buildRouteSelectors(){
      routeBox.innerHTML="";
      showRoutes=[]; countMap={};
      (scheduleJson.routes||[]).forEach(r=>{
        const label=r.label; showRoutes.push(label); countMap[label]=2;
        const line=document.createElement("div"); line.style.marginBottom="4px";
  
        const cb=document.createElement("input");
        cb.type="checkbox"; cb.checked=true; cb.value=label;
        cb.addEventListener("change",()=>{
          showRoutes=Array.from(routeBox.querySelectorAll("input[type=checkbox]:checked"))
                          .map(x=>x.value);
          renderSchedule(scheduleJson);
        });
  
        const num=document.createElement("input");
        num.type="number"; num.min=1; num.max=10; num.value=2;
        num.style.width="50px"; num.style.marginLeft="6px";
        num.addEventListener("input",()=>{
          const v=parseInt(num.value,10);
          countMap[label]=(isNaN(v)||v<1)?1:v; renderSchedule(scheduleJson);
        });
  
        line.appendChild(cb);
        line.appendChild(document.createTextNode(" "+label));
        line.appendChild(num);
        routeBox.appendChild(line);
      });
      routesInit=true;
    }
  
    function renderSchedule(js){
      if(!js.routes) return;
      if(!routesInit) buildRouteSelectors();
  
      const cont=panels.schedule; cont.innerHTML="";
      js.routes.filter(r=>showRoutes.includes(r.label)).forEach(route=>{
        /* ===== カード一枚 ===== */
        const card=document.createElement("section"); card.className="route";
        const wrap=document.createElement("div");   wrap.className="route-wrap";
  
        /* タイトル (ロゴ+路線名) */
        const logoHTML=getIcons(route.label).map(imgTag).join("");
        wrap.innerHTML=`<h2 class="route-title">${logoHTML}${route.label}</h2>`;
  
        /* 時刻リスト */
        const limit=countMap[route.label]||2;
        const pairs=(typeof route.schedules==="object"&&!Array.isArray(route.schedules))
          ? Object.entries(route.schedules)
          : [["",route.schedules]];
  
        const prefixMap={日本語:["先発","次発","次々発"]};
        pairs.forEach(([dirName,list])=>{
          const dir=document.createElement("div"); dir.className="direction";
          if(dirName) dir.innerHTML=`<div class="direction-title">${dirName}</div>`;
          const body=document.createElement("div"); body.className="schedule-list";
  
          list.slice(0,limit).forEach((ln,i)=>{
            const idx=ln.indexOf(":"); const pre=ln.slice(0,idx);
            const rest=ln.slice(idx+1).trim();
            const p=document.createElement("p");
            p.textContent=`${prefixMap.日本語[i]||pre}:${rest}`;
            if(i===0) p.classList.add("first-dep");
            if(i===1) p.classList.add("second-dep");
            body.appendChild(p);
          });
          dir.appendChild(body); wrap.appendChild(dir);
        });
  
        card.appendChild(wrap); cont.appendChild(card);
      });
    }
  
    function loadSchedule(){
      fetch("/api/schedule")
        .then(async res => {
          if (!res.ok) {
            const text = await res.text();
            console.error('Schedule API Error:', res.status, text);
            throw new Error(`Schedule API returned ${res.status}`);
          }
          return res.json();
        })
        .then(js => {
          scheduleJson = js;
          renderSchedule(js);
        })
        .catch(err => {
          console.error('Fetch failed:', err);
        });
    }
  
    /* ============================ UI バインド ============================ */
    zoomSl.addEventListener("input",()=>{
      document.body.style.zoom=zoomSl.value+"%";
      zoomVal.textContent=zoomSl.value+"%";
    });
    fontSl.addEventListener("input",()=>{
      document.body.style.fontSize=fontSl.value+"%";
      fontVal.textContent=fontSl.value+"%";
    });
    resizeChk.addEventListener("change",()=>{
      document.querySelectorAll(".panel").forEach(el=>{
        el.classList.toggle("resizable-on", resizeChk.checked);
        el.classList.toggle("resizable-off",!resizeChk.checked);
      });
    });
  
    function updateVisibility(){
      for(const k in toggles){
        panels[k].style.display = toggles[k].checked ? "" : "none";
      }
    }
    Object.values(toggles).forEach(el=>el.addEventListener("change",updateVisibility));
  
    function applyColors(){
      panels.status .style.background=pickers.statusBg.value;
      panels.status .style.color      =pickers.statusText.value;
      panels.weather.style.background=pickers.weatherBg.value;
      panels.weather.style.color      =pickers.weatherText.value;
      panels.news   .style.background=pickers.newsBg.value;
      panels.news   .style.color      =pickers.newsText.value;
      panels.schedule.style.background=pickers.schedBg.value;
      panels.schedule.style.color     =pickers.schedText.value;
      document.body.style.fontFamily  =pickers.fontFam.value;
    }
    Object.values(pickers).forEach(el=>{
      el.addEventListener(el.tagName==="SELECT"?"change":"input",applyColors);
    });
  
    btnSet  .addEventListener("click",()=>{modal.classList.add("active"); clearAllTimers();});
    btnClose.addEventListener("click",()=>{modal.classList.remove("active"); startTimers();});
  
    /* ============================ タイマー管理 ============================ */
    function addTimer(id){timers.add(id);}
    function clearAllTimers(){timers.forEach(clearInterval); timers.clear();}
    function startTimers() {
      addTimer(setInterval(updateClock, 1000));
      addTimer(setInterval(cycleStatusPage, 4000)); // ★★★ 4秒ごとにページ切替
      addTimer(setInterval(loadStatus, 60000));
      addTimer(setInterval(loadWeather, 600000));
      addTimer(setInterval(loadSchedule, 30000));
      addTimer(setInterval(loadNews, 30000));
      addTimer(setInterval(newsCycle, 4000));
    }
  
    /* ============================ 初期化 ============================ */
    document.body.style.zoom=zoomSl.value+"%";
    document.body.style.fontSize=fontSl.value+"%";
    resizeChk.dispatchEvent(new Event("change"));
    updateClock();   loadStatus(); loadWeather(); loadSchedule(); loadNews();
    startTimers();
  });
