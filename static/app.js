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
    const fetchControllers = new Map();

    const isAbortError = error => error && error.name === "AbortError";

    const jFetch = (url, opts = {}) => {
      const requestKey = opts.key || url;
      const previous = fetchControllers.get(requestKey);
      if (previous) {
        previous.abort();
      }

      const controller = new AbortController();
      fetchControllers.set(requestKey, controller);

      const fetchOptions = { ...opts, signal: controller.signal };
      delete fetchOptions.key;
      if (!fetchOptions.cache) {
        fetchOptions.cache = "no-store";
      }

      return fetch(url, fetchOptions)
        .then(async response => {
          if (!response.ok) {
            const text = await response.text();
            throw new Error(`Fetch failed (${response.status}): ${text}`);
          }
          return response.json();
        })
        .finally(() => {
          if (fetchControllers.get(requestKey) === controller) {
            fetchControllers.delete(requestKey);
          }
        });
    };
  
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
    const statusMeta = $("status-meta");
    const SETTINGS_KEY = "timetable-app-settings-v1";

    function readSettings() {
      try {
        return JSON.parse(localStorage.getItem(SETTINGS_KEY) || "{}");
      } catch (_error) {
        return {};
      }
    }

    function writeSettings(nextSettings) {
      try {
        localStorage.setItem(SETTINGS_KEY, JSON.stringify(nextSettings));
      } catch (_error) {
        // localStorage が使えない環境では何もしない
      }
    }

    function collectSettings() {
      const routeSettings = routesInit
        ? { visible: showRoutes.slice(), counts: { ...countMap } }
        : (storedSettings?.routes || { visible: [], counts: {} });

      return {
        ui: {
          zoom: zoomSl?.value || "100",
          font: fontSl?.value || "100",
          resize: !!resizeChk?.checked,
          display: {
            status: !!toggles.status?.checked,
            weather: !!toggles.weather?.checked,
            news: !!toggles.news?.checked,
            schedule: !!toggles.schedule?.checked,
          },
          maxStatusLines: maxStatusLinesInput?.value || "2",
          colors: {
            statusBg: pickers.statusBg?.value || "#ffffff",
            statusText: pickers.statusText?.value || "#000000",
            weatherBg: pickers.weatherBg?.value || "#ffffff",
            weatherText: pickers.weatherText?.value || "#000000",
            newsBg: pickers.newsBg?.value || "#ffffff",
            newsText: pickers.newsText?.value || "#000000",
            schedBg: pickers.schedBg?.value || "#ffffff",
            schedText: pickers.schedText?.value || "#000000",
            fontFam: pickers.fontFam?.value || "Arial, sans-serif",
          },
        },
        routes: routeSettings,
      };
    }

    function saveSettings() {
      writeSettings(collectSettings());
    }

    const storedSettings = readSettings();
  
    /* ─────────── グローバル状態 ─────────── */
    const timers = new Set();          // すべての setInterval ID
    let statusAll = [];                // 運行情報の全件
    let statusArr = [];                // 現在表示中のページ
    let statusPageIdx = 0;             // 現在ページ
    let statusPageSize = 2;            // 1ページの表示件数
    let statusTotalPages = 0;          // 総ページ数
    let statusUpdatedAt = null;        // 最終更新時刻
    let statusSource = null;           // 取得元
    let lastStatusFetchAt = 0;         // サーバ再取得時刻
    let statusHasLoaded = false;       // 初回取得済み?
    let weatherHasLoaded = false;      // 天気取得済み?
    let newsHasLoaded = false;         // ニュース取得済み?
    let scheduleHasLoaded = false;     // 発車案内取得済み?
    let newsArr   = [], newsIdx   = -1;// ニュース
    let scheduleJson = {};            // /api/schedule 結果
    let routesInit   = false;         // routeBox 生成済み?
    let showRoutes   = [];            // 表示路線
    let countMap     = {};            // { 路線 : 表示本数 }
    let isModalOpen  = false;
    let isPageVisible = !document.hidden;
  
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

    function applyScaleSettings() {
      document.documentElement.style.setProperty("--ui-scale", String((parseInt(zoomSl.value, 10) || 100) / 100));
      document.documentElement.style.setProperty("--text-scale", String((parseInt(fontSl.value, 10) || 100) / 100));
      zoomVal.textContent = `${zoomSl.value}%`;
      fontVal.textContent = `${fontSl.value}%`;
    }

    function applyStoredSettings() {
      const ui = storedSettings?.ui || {};
      const colors = ui.colors || {};
      const display = ui.display || {};

      if (zoomSl && ui.zoom) zoomSl.value = ui.zoom;
      if (fontSl && ui.font) fontSl.value = ui.font;
      if (resizeChk && typeof ui.resize === "boolean") resizeChk.checked = ui.resize;
      if (toggles.status && typeof display.status === "boolean") toggles.status.checked = display.status;
      if (toggles.weather && typeof display.weather === "boolean") toggles.weather.checked = display.weather;
      if (toggles.news && typeof display.news === "boolean") toggles.news.checked = display.news;
      if (toggles.schedule && typeof display.schedule === "boolean") toggles.schedule.checked = display.schedule;
      if (maxStatusLinesInput && ui.maxStatusLines) maxStatusLinesInput.value = ui.maxStatusLines;
      if (pickers.statusBg && colors.statusBg) pickers.statusBg.value = colors.statusBg;
      if (pickers.statusText && colors.statusText) pickers.statusText.value = colors.statusText;
      if (pickers.weatherBg && colors.weatherBg) pickers.weatherBg.value = colors.weatherBg;
      if (pickers.weatherText && colors.weatherText) pickers.weatherText.value = colors.weatherText;
      if (pickers.newsBg && colors.newsBg) pickers.newsBg.value = colors.newsBg;
      if (pickers.newsText && colors.newsText) pickers.newsText.value = colors.newsText;
      if (pickers.schedBg && colors.schedBg) pickers.schedBg.value = colors.schedBg;
      if (pickers.schedText && colors.schedText) pickers.schedText.value = colors.schedText;
      if (pickers.fontFam && colors.fontFam) pickers.fontFam.value = colors.fontFam;
    }

    function renderState(container, title, message, detail = "", tone = "loading") {
      if (!container) return;
      container.innerHTML = "";
      const box = document.createElement("div");
      box.className = `data-state ${tone}`;

      const heading = document.createElement("strong");
      heading.textContent = title;
      box.appendChild(heading);

      const body = document.createElement("div");
      body.textContent = message;
      box.appendChild(body);

      if (detail) {
        const small = document.createElement("small");
        small.textContent = detail;
        box.appendChild(small);
      }

      container.appendChild(box);
    }

    function renderStatusState(title, message, detail = "", tone = "loading") {
      const ul = $("status-list");
      if (!ul) return;
      ul.innerHTML = "";

      const li = document.createElement("li");
      li.className = `status-state ${tone}`;

      const heading = document.createElement("strong");
      heading.textContent = title;
      li.appendChild(heading);

      const body = document.createElement("span");
      body.textContent = message;
      li.appendChild(body);

      if (detail) {
        const small = document.createElement("small");
        small.textContent = detail;
        li.appendChild(small);
      }

      ul.appendChild(li);
    }
  
    /* ============================ 運行情報 ============================ */
    // 表示を更新するメイン関数
    function drawStatus() {
      const ul = $("status-list");
      if (!ul) return;
      ul.innerHTML = "";
  
      if (!statusArr || statusArr.length === 0) {
        renderStatusState("運行情報はありません", "最新情報を取得できませんでした", "しばらくしてから再試行してください", "empty");
        return;
      }
  
      statusArr.forEach(it => {
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

    function setStatusMeta(data) {
      if (!statusMeta) return;

      const updatedAt = data?.updated_at ? new Date(data.updated_at) : null;
      const updatedLabel = updatedAt && !Number.isNaN(updatedAt.getTime())
        ? `更新 ${updatedAt.toLocaleString("ja-JP", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })}`
        : "更新時刻不明";
      const sourceLabel = data?.source === "live" ? "ライブ取得" : data?.source === "cache" ? "Rustキャッシュ" : data?.source === "unavailable" ? "取得待ち" : "DBキャッシュ";

      statusMeta.textContent = `${updatedLabel} / ${sourceLabel}`;
    }

    function normalizeStatusItems(items) {
      return (items || []).map(item => {
        if (item.logo && typeof item.logo === 'string' && !item.logo.startsWith('http')) {
          item.logo = `/static/img/${item.logo}`;
        }
        return item;
      });
    }

    function renderStatusPage() {
      statusPageSize = parseInt(maxStatusLinesInput?.value || statusPageSize || 2, 10) || 2;
      statusTotalPages = statusAll.length ? Math.max(1, Math.ceil(statusAll.length / statusPageSize)) : 0;
      if (statusTotalPages && statusPageIdx >= statusTotalPages) {
        statusPageIdx = 0;
      }

      const start = statusPageIdx * statusPageSize;
      statusArr = statusAll.slice(start, start + statusPageSize);
      drawStatus();
    }

    // 4秒ごとにローカルページを切り替える関数
    function cycleStatusPageLocal() {
      if (!statusAll.length) {
        return;
      }

      if (statusTotalPages > 1) {
        statusPageIdx = (statusPageIdx + 1) % statusTotalPages;
      } else {
        statusPageIdx = 0;
      }

      renderStatusPage();
    }

    // サーバーから最新の運行情報を読み込む関数
    const loadStatus = ({ force = false } = {}) => {
      const now = Date.now();
      statusPageSize = parseInt(maxStatusLinesInput?.value || statusPageSize || 2, 10) || 2;

      if (!force && statusAll.length && now - lastStatusFetchAt < 60000) {
        renderStatusPage();
        setStatusMeta({ updated_at: statusUpdatedAt, source: statusSource });
        return Promise.resolve(statusAll);
      }

      if (!statusAll.length && !statusHasLoaded) {
        renderStatusState("運行情報を取得中", "初回読み込み中です", "しばらくお待ちください", "loading");
      }

      return jFetch(`/api/status?all=1`, { key: "status" })
        .then(data => {
          if (!data || !Array.isArray(data.status)) {
            console.error("運行情報データが不正です:", data);
            statusAll = [];
            statusArr = [];
            setStatusMeta({ source: "unavailable" });
            drawStatus();
            return null;
          }

          statusAll = normalizeStatusItems(data.status);
          statusUpdatedAt = data.updated_at || null;
          statusSource = data.source || null;
          lastStatusFetchAt = now;
          statusHasLoaded = true;
          statusPageIdx = 0;
          renderStatusPage();
          setStatusMeta(data);
          return data;
        })
        .catch(err => {
          if (isAbortError(err)) {
            return null;
          }
          console.error("運行情報の取得に失敗:", err);
          if (!statusAll.length) {
            renderStatusState("運行情報を取得できませんでした", "30秒後に再試行します", "前回データがないため表示できません", "error");
            setStatusMeta({ source: "unavailable" });
          }
          return null;
        });
    };
  
    /* ============================ 天気 ============================ */
    function drawWeather(d){
        const cont = $("weather-info"); cont.innerHTML = "";
        const forecasts = Array.isArray(d?.forecasts) ? d.forecasts : [];
        if (!forecasts.length) {
          renderState(cont, "天気情報", "一時的に取得できませんでした", "前回データがないため表示できません", "error");
          return;
        }
        weatherHasLoaded = true;
        forecasts.slice(0,3).forEach(f=>{
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
    const loadWeather = () => jFetch("/api/weather", { key: "weather" })
      .then(drawWeather).catch(err => {
        if (!isAbortError(err)) {
          console.error("天気情報の取得に失敗:", err);
          if (!weatherHasLoaded) {
            renderState($("weather-info"), "天気情報を取得できませんでした", "30秒後に再試行します", "前回データがないため表示できません", "error");
          }
        }
      });
    };
  
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
      if (!newsHasLoaded) {
        const headline = $("news-headline");
        if (headline) {
          headline.textContent = "ニュースを取得中...";
          headline.style.opacity = "1";
        }
      }

      return jFetch("/api/news", { key: "news" }).then(d=>{
        newsArr = d.news||[];
        newsHasLoaded = true;
        if(newsIdx<0&&newsArr.length){
          newsIdx=0; $("news-headline").textContent=newsArr[0];
        } else if (!newsArr.length) {
          $("news-headline").textContent = "現在お知らせはありません";
        }
      }).catch(err => {
        if (!isAbortError(err)) {
          console.error("ニュースの取得に失敗:", err);
          if (!newsHasLoaded) {
            const headline = $("news-headline");
            if (headline) {
              headline.textContent = "ニュースを取得できませんでした";
              headline.style.opacity = "1";
            }
          }
        }
      });
    }
  
    /* ============================ 発車案内 ============================ */
    function buildRouteSelectors(){
      routeBox.innerHTML="";
      showRoutes=[]; countMap={};
      const savedRoutes = storedSettings?.routes || {};
      const savedVisible = Array.isArray(savedRoutes.visible) ? savedRoutes.visible : null;
      const savedCounts = savedRoutes.counts || {};
      (scheduleJson.routes||[]).forEach(r=>{
        const label=r.label; countMap[label]=2;
        const line=document.createElement("div"); line.style.marginBottom="4px";
  
        const cb=document.createElement("input");
        cb.type="checkbox"; cb.checked=savedVisible ? savedVisible.includes(label) : true; cb.value=label;
        if (cb.checked) {
          showRoutes.push(label);
        }
        cb.addEventListener("change",()=>{
          showRoutes=Array.from(routeBox.querySelectorAll("input[type=checkbox]:checked"))
                          .map(x=>x.value);
          saveSettings();
          renderSchedule(scheduleJson);
        });
  
        const num=document.createElement("input");
        num.type="number"; num.min=1; num.max=10; num.value=2;
        num.value = savedCounts[label] ?? 2;
        countMap[label] = parseInt(num.value, 10) || 2;
        num.style.width="50px"; num.style.marginLeft="6px";
        num.addEventListener("input",()=>{
          const v=parseInt(num.value,10);
          countMap[label]=(isNaN(v)||v<1)?1:v;
          saveSettings();
          renderSchedule(scheduleJson);
        });
  
        line.appendChild(cb);
        line.appendChild(document.createTextNode(" "+label));
        line.appendChild(num);
        routeBox.appendChild(line);
      });
      routesInit=true;
      saveSettings();
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
        const structuredPairs=(route.structured_schedules && typeof route.structured_schedules==="object" && !Array.isArray(route.structured_schedules) && Object.keys(route.structured_schedules).length)
          ? Object.entries(route.structured_schedules)
          : null;
        const legacyPairs=(typeof route.schedules==="object"&&!Array.isArray(route.schedules))
          ? Object.entries(route.schedules)
          : [["",route.schedules]];
        const pairs = structuredPairs || legacyPairs;

        const prefixMap={日本語:["先発","次発","次々発"]};
        pairs.forEach(([dirName,list])=>{
          const dir=document.createElement("div"); dir.className="direction";
          if(dirName) dir.innerHTML=`<div class="direction-title">${dirName}</div>`;
          const body=document.createElement("div"); body.className="schedule-list";
  
          if (structuredPairs) {
            list.slice(0,limit).forEach((item,i)=>{
              const row=document.createElement("div");
              row.className="schedule-row";

              const main=document.createElement("div");
              main.className="schedule-main";

              const rank=document.createElement("span");
              rank.className="schedule-rank";
              rank.textContent=item.rank||prefixMap.日本語[i]||"";

              const time=document.createElement("span");
              time.className="schedule-time";
              time.textContent=item.time||"";

              const dest=document.createElement("span");
              dest.className="schedule-destination";
              const typePrefix=item.type ? `【${item.type}】` : "";
              const destText=item.destination ? `${item.destination}行` : "";
              dest.textContent=[typePrefix, destText].filter(Boolean).join(" ");

              const minutes=document.createElement("span");
              minutes.className="schedule-minutes";
              minutes.textContent=typeof item.minutes === "number" ? `あと${item.minutes}分` : "";

              main.appendChild(rank);
              main.appendChild(time);
              if (dest.textContent) main.appendChild(dest);
              if (minutes.textContent) main.appendChild(minutes);

              const advice=document.createElement("div");
              advice.className="schedule-advice";
              advice.textContent=item.advice_label||"";

              row.appendChild(main);
              if (advice.textContent) row.appendChild(advice);
              body.appendChild(row);
            });
          } else {
            list.slice(0,limit).forEach((ln,i)=>{
              const idx=ln.indexOf(":"); const pre=ln.slice(0,idx);
              const rest=ln.slice(idx+1).trim();
              const p=document.createElement("p");
              p.textContent=`${prefixMap.日本語[i]||pre}:${rest}`;
              if(i===0) p.classList.add("first-dep");
              if(i===1) p.classList.add("second-dep");
              body.appendChild(p);
            });
          }
          dir.appendChild(body); wrap.appendChild(dir);
        });
  
        card.appendChild(wrap); cont.appendChild(card);
      });
    }
  
    function loadSchedule(){
      if (!scheduleHasLoaded) {
        renderState(panels.schedule, "発車案内", "取得中...", "しばらくお待ちください", "loading");
      }

      return jFetch("/api/schedule", { key: "schedule" })
        .then(js => {
          scheduleJson = js;
          scheduleHasLoaded = true;
          renderSchedule(js);
        })
        .catch(err => {
          if (!isAbortError(err)) {
            console.error('Fetch failed:', err);
            if (!scheduleHasLoaded) {
              renderState(panels.schedule, "発車案内を取得できませんでした", "30秒後に再試行します", "前回データがないため表示できません", "error");
            }
          }
        });
    }
  
    /* ============================ UI バインド ============================ */
    zoomSl.addEventListener("input", applyScaleSettings);
    zoomSl.addEventListener("input", saveSettings);
    fontSl.addEventListener("input", applyScaleSettings);
    fontSl.addEventListener("input", saveSettings);
    resizeChk.addEventListener("change",()=>{
      document.querySelectorAll(".panel").forEach(el=>{
        el.classList.toggle("resizable-on", resizeChk.checked);
        el.classList.toggle("resizable-off",!resizeChk.checked);
      });
      saveSettings();
    });
  
    function updateVisibility(){
      for(const k in toggles){
        panels[k].style.display = toggles[k].checked ? "" : "none";
      }
    }
    Object.values(toggles).forEach(el=>el.addEventListener("change",()=>{updateVisibility(); saveSettings();}));
  
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
      el.addEventListener(el.tagName==="SELECT"?"change":"input",()=>{applyColors(); saveSettings();});
    });
  
    function startVisibleTimers() {
      addTimer(setInterval(updateClock, 1000));
      addTimer(setInterval(cycleStatusPageLocal, 4000));
      addTimer(setInterval(loadWeather, 600000));
      addTimer(setInterval(loadSchedule, 30000));
      addTimer(setInterval(loadNews, 30000));
      addTimer(setInterval(newsCycle, 4000));
    }

    function startHiddenTimers() {
      addTimer(setInterval(cycleStatusPageLocal, 4000));
      addTimer(setInterval(newsCycle, 4000));
    }

    function applyTimerState() {
      clearAllTimers();
      if (isModalOpen) {
        return;
      }

      if (isPageVisible) {
        startVisibleTimers();
      } else {
        startHiddenTimers();
      }
    }

    btnSet  .addEventListener("click",()=>{isModalOpen = true; modal.classList.add("active"); applyTimerState();});
    btnClose.addEventListener("click",()=>{isModalOpen = false; modal.classList.remove("active"); applyTimerState(); if (isPageVisible) { loadStatus({ force: true }); loadWeather(); loadSchedule(); loadNews(); } });

    if (maxStatusLinesInput) {
      maxStatusLinesInput.addEventListener("change",()=>{
        statusPageIdx = 0;
        saveSettings();
        if (statusAll.length) {
          renderStatusPage();
        } else {
          loadStatus({ force: true });
        }
      });
    }

    document.addEventListener("visibilitychange",()=>{
      isPageVisible = !document.hidden;
      if (isModalOpen) {
        return;
      }
      applyTimerState();
      if (isPageVisible) {
        loadStatus({ force: true });
        loadWeather();
        loadSchedule();
        loadNews();
      }
    });
  
    /* ============================ タイマー管理 ============================ */
    function addTimer(id){timers.add(id);}
    function clearAllTimers(){timers.forEach(clearInterval); timers.clear();}
  
    /* ============================ 初期化 ============================ */
    applyStoredSettings();
    applyScaleSettings();
    updateVisibility();
    applyColors();
    resizeChk.dispatchEvent(new Event("change"));
    updateClock();   loadStatus({ force: true }); loadWeather(); loadSchedule(); loadNews();
    applyTimerState();
  });
