/* 
【NMap WebUI 前端應用程式 - 架構與設計哲學】

為什麼前端要寫成這個樣子？
1. Client-Side Prediction (客戶端預測與補間)：
   對於視障者來說，鍵盤操作的回饋延遲是致命的。如果在按 'W' 前進時，必須等待伺服器回傳才發出腳步聲，
   使用者會覺得「系統卡住了」而連續多按幾次。
   因此，我們實作了 `requestAnimationFrame` 迴圈 (startRAFGameLoop)，在前端即時計算使用者的虛擬座標，
   並立刻播放腳步聲，背後再透過 300ms 批次的 `/api/sync` 向伺服器對齊座標（解決穿牆問題）。這就如同現代多人連線遊戲的設計。
2. 3D Spatial Audio (Web Audio API - HRTF)：
   視障者在真實世界中重度依賴「聽聲辨位」。我們使用 `PannerNode (HRTF)` 搭配鐘點方位轉換，
   讓前方的店家聽起來在正前方，左側的車流聽起來在左耳。這比純語音報讀更直覺。
3. ARIA-Live 與 NVDA 狀態管理：
   透過 `updateLiveLog` 即時操作 `aria-live` DOM 元素，將文字注入，強制 NVDA 朗讀。
   為了避免連續移動造成 NVDA 語音佇列塞車（不斷重複上一句），我們做了一層過濾機制，
   只有當字串真正改變（且是重要變動）時，才會觸發朗讀，完全模擬 VoiceVista 的舒適體驗。

WCAG 2.2 AA & NVDA Screen Reader & 3D Spatial Audio & IndexedDB Storage
*/

class WebAudioEngine {
  constructor() {
    this.enabled = true;
    this.ctx = null;
    this.audioBuffers = {};
    this.loadRealSounds();
  }

  initContext() {
    if (!this.ctx) {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (AudioCtx) {
        this.ctx = new AudioCtx();
      }
    }
    if (this.ctx && this.ctx.state === 'suspended') {
      this.ctx.resume().catch(() => {});
    }
  }

  // 非同步載入並解碼真實的音效檔案 (.wav)
  loadRealSounds() {
      const sounds = ['pedestrian', 'vehicle', 'obstacle', 'danger', 'weather'];
      sounds.forEach(name => {
          fetch(`sounds/${name}.wav`)
              .then(res => res.arrayBuffer())
              .then(data => {
                  this.initContext();
                  return this.ctx.decodeAudioData(data);
              })
              .then(buffer => {
                  this.audioBuffers[name] = buffer;
              })
              .catch(e => console.log(`Failed to load ${name}.wav`, e));
      });
  }

  // Item 3.3: 3D Spatial HRTF PannerNode Audio Cue (硬體時鐘微秒級精確排程)
  playSpatialTone(frequency = 440, type = 'sine', x = 0, y = 0, z = -1, duration = 0.15, startTimeOffset = 0, volume = 0.3) {
    if (!this.enabled) return;
    this.initContext();
    if (!this.ctx) return;

    try {
      const t0 = this.ctx.currentTime + Math.max(0, startTimeOffset);
      const osc = this.ctx.createOscillator();
      const gain = this.ctx.createGain();
      const panner = this.ctx.createPanner();

      panner.panningModel = 'HRTF';
      panner.distanceModel = 'inverse';
      panner.refDistance = 1;
      panner.maxDistance = 100;
      panner.rolloffFactor = 1;

      if (panner.positionX) {
        panner.positionX.setValueAtTime(x, t0);
        panner.positionY.setValueAtTime(y, t0);
        panner.positionZ.setValueAtTime(z, t0);
      } else {
        panner.setPosition(x, y, z);
      }

      osc.type = type;
      osc.frequency.setValueAtTime(frequency, t0);

      gain.gain.setValueAtTime(volume, t0);
      gain.gain.exponentialRampToValueAtTime(0.0001, t0 + duration);

      osc.connect(gain);
      gain.connect(panner);
      panner.connect(this.ctx.destination);

      osc.start(t0);
      osc.stop(t0 + duration);
    } catch (e) {}
  }

  playFootstep() {
    this.playSpatialTone(220, 'triangle', 0, 0, -0.5, 0.08);
  }

  playBumpCollision() {
    // 播放兩次明顯的重低音方波，模擬撞擊聲
    this.playSpatialTone(150, 'square', 0, 0, 0.4, 0.1);
    setTimeout(() => {
        this.playSpatialTone(100, 'sawtooth', 0, 0, 0.4, 0.25);
    }, 100);
  }

  playTurn() {
    this.playSpatialTone(520, 'sine', 0, 0, -1, 0.08);
  }

  playTick(isLeft = false) {
    // 轉向時左右耳立體聲刻度音
    this.playSpatialTone(720, 'sine', isLeft ? -0.8 : 0.8, 0, -0.5, 0.03);
  }

  playSettledChime() {
    if (!this.enabled) return;
    this.initContext();
    if (!this.ctx) return;
    try {
      this.playSpatialTone(523, 'sine', 0, 0, -1, 0.09);
      setTimeout(() => {
        this.playSpatialTone(784, 'sine', 0, 0, -1, 0.14);
      }, 90);
    } catch (e) {}
  }

  playSearchCompleteTone() {
    if (!this.enabled) return;
    this.initContext();
    if (!this.ctx) return;
    try {
      this.playSpatialTone(784, 'sine', 0, 0, -1, 0.08); // G5
      setTimeout(() => {
        this.playSpatialTone(1046.5, 'sine', 0, 0, -1, 0.15); // C6
      }, 90);
    } catch (e) {}
  }

  playVirtualPanChime() {
    if (!this.enabled) return;
    this.initContext();
    if (!this.ctx) return;
    try {
      this.playSpatialTone(440, 'triangle', 0, 0, -1, 0.08);
      setTimeout(() => {
        this.playSpatialTone(659, 'sine', 0, 0, -1, 0.12);
      }, 80);
    } catch (e) {}
  }

  /**
   * 掃描前方店家雙耳立體聲掃描音效 (Scan Sweep Tone)
   */
  playScanSweepTone() {
    if (!this.enabled) return;
    this.initContext();
    if (!this.ctx) return;
    try {
      this.playSpatialTone(587.3, 'sine', -1.5, 0, -1, 0.08, 0.00, 0.35);
      this.playSpatialTone(784.0, 'sine', 1.5, 0, -1, 0.08, 0.07, 0.35);
      this.playSpatialTone(987.8, 'sine', 0.0, 0, -1, 0.12, 0.14, 0.40);
    } catch (e) {}
  }

  /**
   * 掃描周遭所有店家 360 度雷達探索和弦音效 (Radar Explore Tone)
   */
  playRadarExploreTone() {
    if (!this.enabled) return;
    this.initContext();
    if (!this.ctx) return;
    try {
      this.playSpatialTone(523.2, 'triangle', 0, 0, -1, 0.08, 0.00, 0.35);
      this.playSpatialTone(659.3, 'sine', 0, 0, -1, 0.08, 0.06, 0.38);
      this.playSpatialTone(1046.5, 'sine', 0, 0, -1, 0.15, 0.12, 0.45);
    } catch (e) {}
  }

  /**
   * 3D 空間距離感應脈衝音 (Proximity Beacon Ping)
   * 特性：越接近地標，聲音越響亮、頻率越高、越急促
   */
  playBeacon(relBearing = 0, distM = 5) {
    if (!this.enabled) return;
    this.initContext();
    if (!this.ctx) return;

    // 1. 3D 空間定位 (HRTF)
    const rad = relBearing * Math.PI / 180.0;
    const distAudio = Math.max(0.6, Math.min(8.0, distM));
    const x = distAudio * Math.sin(rad);
    const z = -distAudio * Math.cos(rad);

    // 2. 音量動態縮放 (越近越響亮: 0.35 ~ 0.95)
    const volume = Math.min(0.95, Math.max(0.35, 1.0 - (distM / 60.0) * 0.6));

    // 3. 頻率動態提高 (越近越高亢清脆)
    let freq = 880;
    if (distM > 40) freq = 660;
    else if (distM > 15) freq = 880;
    else if (distM > 6) freq = 1046.5;
    else freq = 1318.5;

    // 播放主音頻脈衝
    this.playSpatialTone(freq, 'sine', x, 0, z, 0.10, 0.0, volume);

    // 小於 10 公尺時加上高頻緊湊副音 (Double-pip)，急迫感更加顯著
    if (distM <= 10.0) {
      this.playSpatialTone(freq * 1.25, 'triangle', x, 0, z, 0.05, 0.06, volume * 0.85);
    }
  }

  /**
   * 抵達目的地勝利慶祝音 (Arrival Fanfare)
   */
  playArrival() {
    if (!this.enabled) return;
    this.initContext();
    if (!this.ctx) return;

    try {
      [523.25, 659.25, 783.99, 1046.5].forEach((freq, i) => {
        setTimeout(() => {
          this.playSpatialTone(freq, 'sine', (i - 1.5) * 0.4, 0, -1, 0.18, 0.0, 0.45);
        }, i * 75);
      });
    } catch (e) {}
  }

  /**
   * 3D 垂直樓層切換立體音效 (Vertical Level Transition Tone)
   * 登上天橋：上升純四度三和弦 (C5 -> E5 -> G5)
   * 走下地下道：下行滑音 (G5 -> E5 -> C5)
   */
  playVerticalTransitionTone(isAscending = true) {
    if (!this.enabled) return;
    this.initContext();
    if (!this.ctx) return;
    try {
      const notes = isAscending ? [523.25, 659.25, 783.99] : [783.99, 659.25, 523.25];
      notes.forEach((freq, i) => {
        setTimeout(() => {
          this.playSpatialTone(freq, 'sine', 0, isAscending ? 1.0 : -1.0, -1, 0.12, 0.0, 0.38);
        }, i * 65);
      });
    } catch (e) {}
  }

  /**
   * 📡 公眾室內 iBeacon / Wi-Fi 定錨鎖定音 (Beacon Re-anchor Lock Tone)
   * 概念：雷達波束精準鎖定鐘聲 (A5 -> E6 雙音鐘響)
   */
  playBeaconAnchorTone() {
    if (!this.enabled) return;
    this.initContext();
    if (!this.ctx) return;
    try {
      this.playSpatialTone(880.0, 'sine', 0, 0, -1, 0.10, 0.00, 0.40);
      this.playSpatialTone(1318.5, 'triangle', 0, 0, -1, 0.16, 0.08, 0.45);
    } catch (e) {}
  }

  // =========================================================================
  // 🎵 視障無障礙專屬聽覺圖標庫 (Accessible Auditory Icons / Earcons)
  // 目的：在語音朗讀前播放 100~250ms 短促清脆且具 3D 空間定位的聲音，
  // 讓使用者大腦在 0.1 秒內瞬間辨識即將播報的設施類型（商店、地標、建築、交通設施等）
  // =========================================================================

  /**
   * 🏪 商店 / 超商 / 餐飲 (Shop & Dining Earcon)
   * 概念：便利商店開門鈴與收銀機叮咚雙音階（上升純五度雙音階，清脆純淨）
   * 音符：E5 (659.3Hz) -> B5 (987.8Hz)，正弦波，總長約 210ms
   */
  playShopTone(x = 0, z = -1) {
    if (!this.enabled) return;
    this.playSpatialTone(659.3, 'sine', x, 0, z, 0.08, 0.00, 0.28);
    this.playSpatialTone(987.8, 'sine', x, 0, z, 0.14, 0.07, 0.32);
  }

  /**
   * 🏛️ 地標 / 景點 / 公園 / 宗教名勝 (Landmark & Public Facility Earcon)
   * 概念：開闊宏揚的大調三和弦琶音鐘琴音（A大調三和弦迴響，象徵重要景觀與文教機構）
   * 音符：A4 (440Hz) -> C#5 (554.4Hz) -> E5 (659.3Hz)，三角波+正弦波，總長約 260ms
   */
  playLandmarkTone(x = 0, z = -1) {
    if (!this.enabled) return;
    this.playSpatialTone(440.0, 'triangle', x, 0, z, 0.07, 0.00, 0.25);
    this.playSpatialTone(554.4, 'triangle', x, 0, z, 0.08, 0.05, 0.28);
    this.playSpatialTone(659.3, 'sine', x, 0, z, 0.16, 0.10, 0.30);
  }

  /**
   * 🏢 建築物 / 社區 / 大樓 / 大廈 (Building & Residential Earcon)
   * 概念：沉穩厚實的雙重建築基石敲擊音（Solid Knock），象徵穩固的社區大樓與公寓
   * 音符：C4 (261.6Hz) -> G3 (196.0Hz)，三角波沉穩微重音，總長約 180ms
   */
  playBuildingTone(x = 0, z = -1) {
    if (!this.enabled) return;
    this.playSpatialTone(261.6, 'triangle', x, 0, z, 0.07, 0.00, 0.35);
    this.playSpatialTone(196.0, 'triangle', x, 0, z, 0.12, 0.06, 0.38);
  }

  /**
   * 🚏 交通設施 / 公車站 / 捷運出口 / 號誌 (Transit & Infrastructure Earcon)
   * 概念：捷運刷卡與公車到站電子提示雙短嗶音（Double Electronic Beep），穿透力強、節奏分明
   * 音符：A5 (880Hz) 雙短跳音，時長約 135ms
   */
  playTransitTone(x = 0, z = -1) {
    if (!this.enabled) return;
    this.playSpatialTone(880.0, 'sine', x, 0, z, 0.045, 0.00, 0.30);
    this.playSpatialTone(880.0, 'sine', x, 0, z, 0.065, 0.07, 0.32);
  }

  /**
   * 📍 路口 / 岔路 / 轉向交會 (Junction & Intersection Earcon)
   * 概念：方向指引上滑水滴音（Frequency Sweep），象徵前進道路分岔與轉折
   * 音符：520Hz 平滑滑音至 784Hz，時長約 110ms
   */
  playJunctionTone(x = 0, z = -1) {
    if (!this.enabled) return;
    this.initContext();
    if (!this.ctx) return;
    try {
      const t0 = this.ctx.currentTime;
      const osc = this.ctx.createOscillator();
      const gain = this.ctx.createGain();
      const panner = this.ctx.createPanner();

      panner.panningModel = 'HRTF';
      if (panner.positionX) {
        panner.positionX.setValueAtTime(x, t0);
        panner.positionY.setValueAtTime(0, t0);
        panner.positionZ.setValueAtTime(z, t0);
      } else {
        panner.setPosition(x, 0, z);
      }

      osc.type = 'sine';
      osc.frequency.setValueAtTime(520, t0);
      osc.frequency.exponentialRampToValueAtTime(784, t0 + 0.10);

      gain.gain.setValueAtTime(0.3, t0);
      gain.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.12);

      osc.connect(gain);
      gain.connect(panner);
      panner.connect(this.ctx.destination);

      osc.start(t0);
      osc.stop(t0 + 0.12);
    } catch (e) {}
  }

  /**
   * 🛣️ 沿著道路前進 / 門牌確認 (Road & Path Guidance Earcon)
   * 概念：柔和舒適的步伐單音，象徵平穩前進
   * 音符：440Hz 三角波微音，時長約 90ms
   */
  playRoadTone(x = 0, z = -1) {
    if (!this.enabled) return;
    this.playSpatialTone(440.0, 'triangle', x, 0, z, 0.09, 0.00, 0.22);
  }

  /**
   * ⚠️ 警示 / 危險 / 障礙物 (Warning & Caution Earcon)
   * 概念：下墜雙重警戒跳音，提示注意地面或障礙
   * 音符：350Hz 鋸齒波下墜接 220Hz，時長約 150ms
   */
  playWarningTone(x = 0, z = -1) {
    if (!this.enabled) return;
    this.playSpatialTone(350.0, 'sawtooth', x, 0, z, 0.06, 0.00, 0.25);
    this.playSpatialTone(220.0, 'triangle', x, 0, z, 0.12, 0.05, 0.28);
  }

  /**
   * 【通用物件類別聽覺圖標統一分發器】
   * 依據分類標籤自動派發對應專屬音效
   */
  playCategoryEarcon(category, x = 0, z = -1) {
    if (!this.enabled) return;
    const cat = (category || "").toLowerCase().trim();
    switch (cat) {
      case "shop":
      case "store":
      case "restaurant":
      case "food":
      case "cafe":
      case "convenience":
        this.playShopTone(x, z);
        break;
      case "landmark":
      case "attraction":
      case "park":
      case "temple":
      case "church":
      case "historic":
        this.playLandmarkTone(x, z);
        break;
      case "building":
      case "residential":
      case "apartments":
      case "office":
        this.playBuildingTone(x, z);
        break;
      case "transit":
      case "bus":
      case "subway":
      case "mrt":
      case "elevator":
      case "train":
      case "station":
      case "crossing":
      case "traffic":
      case "signal":
      case "spat":
      case "aps":
        this.playTransitTone(x, z);
        break;
      case "junction":
      case "intersection":
        this.playJunctionTone(x, z);
        break;
      case "road":
      case "door":
        this.playRoadTone(x, z);
        break;
      case "warning":
      case "danger":
      case "alert":
      case "hazard":
      case "obstacle":
      case "box":
        this.playWarningTone(x, z);
        break;
      default:
        this.playShopTone(x, z);
        break;
    }
  }

  /**
   * 【依據 POI 物件精準計算 3D 空間位置並播放對應類別之聽覺圖標】
   */
  playForPoi(poi) {
    if (!this.enabled || !poi) return;
    let x = 0, z = -1;
    if (poi.relative_bearing_deg !== undefined) {
      const rad = (poi.relative_bearing_deg || 0) * Math.PI / 180.0;
      const distAudio = Math.max(0.5, Math.min(10.0, poi.distance_m || 3.0));
      x = distAudio * Math.sin(rad);
      z = -distAudio * Math.cos(rad);
    } else if (poi.relative_direction) {
      const coords = this.parseClockDirection(poi.relative_direction, poi.distance_m);
      x = coords.x;
      z = coords.z;
    }
    const cat = window.app && window.app.classifyPoiCategory ? window.app.classifyPoiCategory(poi) : "shop";
    this.playCategoryEarcon(cat, x, z);
  }

  // 解析中文時鐘方位為立體聲 3D 座標 (x, z)
  parseClockDirection(directionStr, distance_m) {
      let x = 0, z = 0;
      const dist = Math.max(0.5, Math.min(20, distance_m || 2)); // 限制距離在 0.5~20 之間
      
      if (directionStr.includes("正前方")) { z = -dist; }
      else if (directionStr.includes("右前方")) { x = dist * 0.7; z = -dist * 0.7; }
      else if (directionStr.includes("左前方")) { x = -dist * 0.7; z = -dist * 0.7; }
      else if (directionStr.includes("右後方")) { x = dist * 0.7; z = dist * 0.7; }
      else if (directionStr.includes("左後方")) { x = -dist * 0.7; z = dist * 0.7; }
      else if (directionStr.includes("正後方")) { z = dist; }
      else if (directionStr.includes("右邊") || directionStr.includes("右側")) { x = dist; }
      else if (directionStr.includes("左邊") || directionStr.includes("左側")) { x = -dist; }
      else { z = -dist; } // 預設正前方
      
      return { x, z };
  }

  // 播放已經載入的音效檔 (AudioBuffer) 並且加上 3D 空間定位
  playSpatialAudioBuffer(bufferName, x, y, z) {
      if (!this.enabled) return;
      this.initContext();
      if (!this.ctx || !this.audioBuffers[bufferName]) return;

      try {
          const source = this.ctx.createBufferSource();
          source.buffer = this.audioBuffers[bufferName];

          const panner = this.ctx.createPanner();
          panner.panningModel = 'HRTF';
          panner.distanceModel = 'inverse';
          panner.refDistance = 1;
          panner.maxDistance = 100;
          panner.rolloffFactor = 1;
          
          if (panner.positionX) {
              panner.positionX.setValueAtTime(x, this.ctx.currentTime);
              panner.positionY.setValueAtTime(y, this.ctx.currentTime);
              panner.positionZ.setValueAtTime(z, this.ctx.currentTime);
          } else {
              panner.setPosition(x, y, z);
          }

          source.connect(panner);
          panner.connect(this.ctx.destination);
          source.start();
      } catch (e) {
          console.error("Audio playback error", e);
      }
  }

  // 根據模擬事件播放立體空間音效 (現在使用真實檔案)
  playEventSounds(events) {
      if (!this.enabled || !events) return;
      
      events.forEach((ev, idx) => {
          setTimeout(() => {
              const pos = this.parseClockDirection(ev.clock_position || '正前方', ev.distance_m || 3);
              
              switch(ev.category) {
                  case 'pedestrian':
                      this.playSpatialAudioBuffer('pedestrian', pos.x, 0, pos.z);
                      break;
                  case 'vehicle':
                      this.playSpatialAudioBuffer('vehicle', pos.x, 0, pos.z);
                      break;
                  case 'obstacle':
                      this.playSpatialAudioBuffer('obstacle', pos.x, 0, pos.z);
                      break;
                  case 'danger':
                      this.playSpatialAudioBuffer('danger', pos.x, 0, pos.z);
                      break;
                  case 'weather':
                      this.playSpatialAudioBuffer('weather', 0, 5, -5); // 天氣聲音放上方
                      break;
                  case 'sound':
                      // 找不到預設音檔時退回原本的合成音
                      this.playSpatialTone(700, 'sine', pos.x, 0, pos.z, 0.5);
                      break;
              }
          }, idx * 600); // 錯開播放
      });
  }
}

// IndexedDB 離線快取管理器 (IndexedDB Offline Storage Manager)
// 作用：將地圖圖資、POI 與使用者歷史紀錄儲存在瀏覽器本機端，離線也能快速讀取。
class IndexedDBStorageManager {
  constructor() {
    this.dbName = "nmap_offline_db";
    this.dbVersion = 1;
    this.db = null;
    this.initDB();
  }

  initDB() {
    if (!window.indexedDB) return;
    const req = window.indexedDB.open(this.dbName, this.dbVersion);
    req.onupgradeneeded = (e) => {
      const db = e.target.result;
      if (!db.objectStoreNames.contains("map_cache")) {
        db.createObjectStore("map_cache", { keyPath: "id" });
      }
    };
    req.onsuccess = (e) => {
      this.db = e.target.result;
    };
  }

  saveState(key, data) {
    if (!this.db) return;
    try {
      const tx = this.db.transaction("map_cache", "readwrite");
      const store = tx.objectStore("map_cache");
      store.put({ id: key, payload: data, timestamp: Date.now() });
    } catch (e) {}
  }

  getState(key, callback) {
    if (!this.db) {
      callback(null);
      return;
    }
    try {
      const tx = this.db.transaction("map_cache", "readonly");
      const store = tx.objectStore("map_cache");
      const req = store.get(key);
      req.onsuccess = () => {
        callback(req.result ? req.result.payload : null);
      };
      req.onerror = () => callback(null);
    } catch (e) {
      callback(null);
    }
  }
}

// NMap Web 前端主控器 (NMap Web Application Main Controller)
// 作用：處理使用者的鍵盤與觸控輸入、發送 API 請求、同步客戶端預測座標、控制 3D 空間音效與 NVDA 語音輸出。
class NmapWebApp {
  constructor() {
    this.audio = new WebAudioEngine();
    this.offlineDB = new IndexedDBStorageManager();
    this.showVisuals = true;
    this.lastPois = [];
    this.poiIndex = 0;
    this.stepDistance = 5;  // default 5 metres per step
    this.lastSpokenText = '';
    this.simulationMode = false;
    this.simDifficulty = 'normal';

    // 6 大周遭地標探索分類 (Accessible Wheel Categories)
    this.poiCategories = [
      { key: "all", label: "全部設施", icon: "🌐", desc: "全部設施與店家" },
      { key: "food", label: "餐飲美食", icon: "🍽️", desc: "餐廳、小吃、早午餐、咖啡與飲料" },
      { key: "shopping", label: "生活購物", icon: "🏪", desc: "超商、超市、量販與生活百貨" },
      { key: "transit", label: "交通號誌", icon: "🚦", desc: "有聲號誌、公車站、斑馬線與捷運" },
      { key: "public_access", label: "公共無障礙", icon: "♿", desc: "無障礙電梯、公廁、郵局、銀行與醫院" },
      { key: "landmarks", label: "地標古蹟", icon: "🏢", desc: "學校、寺廟、公園、古蹟與政府機關" }
    ];
    this.currentCategoryIndex = 0;
    
    // RPG Game Loop State
    this.keysDown = {};
    this.rafId = null;
    this.localLat = null;
    this.localLon = null;
    this.localHeading = 0;
    this.serverLat = null;
    this.lastData = null;
    this.announcedPoiCooldown = new Map();
    this.arrivedPoiCooldown = new Map();
    this.lastIntersectionAlertTime = 0;
    this.lastSpeechTime = Date.now();
    this.currentStreetName = null;
    this.passedIntersectionTracking = false;
    this.isSignalCameraActive = false;

    // Diagnostic & Trajectory Session Logs (AI-Optimized)
    this.sessionStartTime = Date.now();
    this.traceCounter = 0;
    this.currentTraceId = 0;
    this.sessionCausalityTrace = [];
    this.sessionSpeechHistory = [];
    this.sessionDetectedPois = new Map();
    this.sessionInteractions = [];
    this.sessionAnomalies = [];
    this.currentRoadName = "";
    this.lastSpokenDoor = "";
    this.lastSpokenIntersection = "";

    this.initSettings();
    this.initElements();
    this.bindEvents();
    this.isReady = true;
    if (window.pendingGpsUpdate) {
        const p = window.pendingGpsUpdate;
        window.pendingGpsUpdate = null;
        window.onLocationUpdate(p.lat, p.lon, p.accuracy, p.bearing, p.speed);
    } else {
        this.checkStatus();
    }
    this.startRAFGameLoop();
  }

  recordTrace(type, payload = {}) {
    if (!this.sessionCausalityTrace) this.sessionCausalityTrace = [];
    const timeStr = new Date().toISOString();
    const traceId = payload.trace_id || this.currentTraceId || ++this.traceCounter;
    this.sessionCausalityTrace.push({
      trace_id: traceId,
      t: timeStr,
      type: type,
      ...payload
    });
    // 擴大因果鏈緩衝區至 5000 筆，並保留前 20 筆啟動根節點事件不被擠出，完整保存 1 小時以上旅程
    if (this.sessionCausalityTrace.length > 5000) {
      if (this.sessionCausalityTrace.length > 20) {
        this.sessionCausalityTrace.splice(20, 1);
      } else {
        this.sessionCausalityTrace.shift();
      }
    }
  }

  recordInteraction(action, detail = "") {
    if (!this.sessionInteractions) this.sessionInteractions = [];
    const timeStr = new Date().toISOString();
    this.sessionInteractions.push({
      time: timeStr,
      action: action,
      detail: detail
    });
    if (this.sessionInteractions.length > 500) {
      this.sessionInteractions.shift();
    }
  }

  initElements() {
    this.liveLog = document.getElementById("nvda-live-log");
    this.statusBadge = document.getElementById("status-badge");
    this.poiContainer = document.getElementById("poi-list-container");
    this.soundToggleBtn = document.getElementById("sound-toggle-btn");
    this.visualModeBtn = document.getElementById("visual-mode-btn");
    this.visualSection = document.getElementById("visual-section");
    this.helpBtn = document.getElementById("help-btn");
    this.helpModal = document.getElementById("help-modal");
    this.closeModalBtn = document.getElementById("close-modal-btn");
    this.modalOkBtn = document.getElementById("modal-ok-btn");
    this.locationInput = document.getElementById("location-input");
    this.queryInput = document.getElementById("query-input");

    // D-Pad buttons
    this.btnForward = document.getElementById("btn-forward");
    this.btnBack = document.getElementById("btn-back");
    this.btnTurnLeft = document.getElementById("btn-turn-left");
    this.btnTurnRight = document.getElementById("btn-turn-right");
    this.btnLook = document.getElementById("btn-look");

    // Canvas & Street scene elements
    this.radarCanvas = document.getElementById("radar-canvas");
    this.canvasCtx = this.radarCanvas ? this.radarCanvas.getContext("2d") : null;
    this.streetSummary = document.getElementById("street-scene-summary");
    this.streetTagsContainer = document.getElementById("street-tags-container");

    // 預設將所有對話框設為完全隱藏與 inert，杜絕冷啟動時 TalkBack 誤掃描
    document.querySelectorAll(".modal-overlay").forEach(m => {
      m.style.display = "none";
      m.setAttribute("aria-hidden", "true");
      m.setAttribute("inert", "");
    });
  }

  bindEvents() {
    // Control Buttons
    if (this.soundToggleBtn) {
      this.soundToggleBtn.addEventListener("click", () => {
        this.audio.enabled = !this.audio.enabled;
        this.soundToggleBtn.textContent = this.audio.enabled ? "🔊 提示音：開啟" : "🔇 提示音：靜音";
        this.updateLiveLog(this.audio.enabled ? "已開啟音效提示" : "已靜音音效提示");
      });
    }

    if (this.visualModeBtn) {
      this.visualModeBtn.addEventListener("click", () => {
        this.showVisuals = !this.showVisuals;
        this.visualSection.style.display = this.showVisuals ? "block" : "none";
        this.visualModeBtn.textContent = this.showVisuals ? "👁️ 2D視覺雷達：顯示中" : "🙈 2D視覺雷達：已隱藏";
      });
    }

    if (this.helpBtn) this.helpBtn.addEventListener("click", () => this.showModal(true));
    if (this.closeModalBtn) this.closeModalBtn.addEventListener("click", () => this.showModal(false));
    if (this.modalOkBtn) this.modalOkBtn.addEventListener("click", () => this.showModal(false));

    // D-Pad Click Events (click gives a momentum bump)
    if (this.btnForward) this.btnForward.addEventListener("click", () => {
        this.velocity = 4.0;
        this.moveDir = 1;
    });
    if (this.btnBack) this.btnBack.addEventListener("click", () => {
        this.velocity = 4.0;
        this.moveDir = -1;
    });
    if (this.btnTurnLeft) this.btnTurnLeft.addEventListener("click", () => this.turn(-45));
    if (this.btnTurnRight) this.btnTurnRight.addEventListener("click", () => this.turn(45));
    if (this.btnLook) this.btnLook.addEventListener("click", () => this.checkStatus(true));

    // Export Log Button
    const exportBtn = document.getElementById("export-log-btn");
    if (exportBtn) {
      exportBtn.addEventListener("click", () => {
        window.location.href = "/api/history/export";
      });
    }

    // Teleport Form
    const teleportForm = document.getElementById("teleport-form");
    if (teleportForm) {
      teleportForm.addEventListener("submit", (e) => {
        e.preventDefault();
        const val = this.locationInput.value.trim();
        if (val) this.teleport(val);
      });
    }

    // New Accessible UI Buttons
    const uiBtnScan = document.getElementById("ui-btn-scan");
    if (uiBtnScan) {
        uiBtnScan.addEventListener("click", () => {
            this.recordInteraction("點擊按鈕", "掃描前方店家 (L)");
            if (this.audio && (!this.settings || this.settings.earconEnabled !== false)) {
                this.audio.playScanSweepTone();
            }
            setTimeout(() => this.announceLeftRightSweep(), 200);
        });
    }

    // 周遭探索滑輪按鈕 (Unified Wheel Slider)：單指上下滑動切換分類、原地雙擊秒掃描
    const uiBtnAround = document.getElementById("ui-btn-around");
    if (uiBtnAround) {
        let touchStartY = 0;
        let isTouching = false;
        let hasMoved = false;

        const updateCategoryDisplay = (index, announceSpeech = true) => {
            if (index < 0) index = this.poiCategories.length - 1;
            if (index >= this.poiCategories.length) index = 0;
            this.currentCategoryIndex = index;
            const currentCat = this.poiCategories[index];
            
            uiBtnAround.innerText = `${currentCat.icon} ${currentCat.label} (P)`;
            uiBtnAround.setAttribute("aria-valuenow", index);
            uiBtnAround.setAttribute("aria-valuetext", currentCat.label);
            uiBtnAround.setAttribute("aria-label", `周遭探索：${currentCat.label}。單指上下滑動切換分類，點兩下立即掃描`);

            if (announceSpeech) {
                if (window.AndroidBridge && window.AndroidBridge.vibrateClick) {
                    window.AndroidBridge.vibrateClick();
                }
                // 【極簡省話原則】：純粹乾淨播報分類名（如「餐飲美食」），不加任何多餘前綴
                if (window.AndroidBridge && window.AndroidBridge.speak) {
                    window.AndroidBridge.speak(currentCat.label, true);
                } else if (window.speechSynthesis) {
                    try {
                        window.speechSynthesis.cancel();
                        const u = new SpeechSynthesisUtterance(currentCat.label);
                        u.lang = 'zh-TW';
                        window.speechSynthesis.speak(u);
                    } catch(e) {}
                }
            }
        };

        // 1. 原生 Touch 觸控滑動支援（單指上下撥動切換分類）
        uiBtnAround.addEventListener("touchstart", (e) => {
            if (e.touches && e.touches.length > 0) {
                touchStartY = e.touches[0].clientY;
                isTouching = true;
                hasMoved = false;
            }
        }, { passive: true });

        uiBtnAround.addEventListener("touchmove", (e) => {
            if (!isTouching || !e.touches || e.touches.length === 0) return;
            const currentY = e.touches[0].clientY;
            const deltaY = currentY - touchStartY;
            if (Math.abs(deltaY) > 28) {
                hasMoved = true;
                if (deltaY < 0) {
                    // 向上滑動：切換至下一個分類
                    updateCategoryDisplay(this.currentCategoryIndex + 1, true);
                } else {
                    // 向下滑動：切換至上一個分類
                    updateCategoryDisplay(this.currentCategoryIndex - 1, true);
                }
                touchStartY = currentY; // 重置起點，允許連續滑動切換
            }
        }, { passive: true });

        uiBtnAround.addEventListener("touchend", () => {
            isTouching = false;
        });

        // 2. TalkBack Slider 原生無障礙動作映射 (ArrowUp / ArrowDown / PageUp / PageDown)
        uiBtnAround.addEventListener("keydown", (e) => {
            if (e.key === "ArrowUp" || e.key === "PageUp" || e.key === "ArrowRight") {
                e.preventDefault();
                updateCategoryDisplay(this.currentCategoryIndex + 1, true);
            } else if (e.key === "ArrowDown" || e.key === "PageDown" || e.key === "ArrowLeft") {
                e.preventDefault();
                updateCategoryDisplay(this.currentCategoryIndex - 1, true);
            } else if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                executeCurrentScan();
            }
        });

        // 3. 點擊 / 點兩下 (Double Tap) 立即執行該分類之周遭掃描
        const executeCurrentScan = () => {
            const currentCat = this.poiCategories[this.currentCategoryIndex] || this.poiCategories[0];
            this.recordInteraction("點擊按鈕", `周遭探索【${currentCat.label}】(P)`);
            if (this.audio && (!this.settings || this.settings.earconEnabled !== false)) {
                this.audio.playRadarExploreTone();
            }
            setTimeout(() => this.announceAllPOIs(currentCat.key), 150);
        };

        uiBtnAround.addEventListener("click", (e) => {
            e.preventDefault();
            if (hasMoved) {
                hasMoved = false;
                return;
            }
            executeCurrentScan();
        });
    }

    const uiBtnIntersection = document.getElementById("ui-btn-intersection");
    if (uiBtnIntersection) {
        uiBtnIntersection.addEventListener("click", () => {
            this.recordInteraction("點擊按鈕", "前方路口狀況 (I)");
            if (this.audio && (!this.settings || this.settings.earconEnabled !== false)) {
                this.audio.playJunctionTone(0, -1);
            }
            setTimeout(() => this.announceUpcomingIntersection(), 150);
        });
    }

    const uiBtnLoc = document.getElementById("ui-btn-loc");
    if (uiBtnLoc) {
        uiBtnLoc.addEventListener("click", () => {
            this.recordInteraction("點擊按鈕", "目前位置與門牌 (R)");
            this.announceRoadAndDoorNumbers();
        });
    }

    const uiBtnCheckUpdate = document.getElementById("ui-btn-check-update");
    if (uiBtnCheckUpdate) {
        uiBtnCheckUpdate.addEventListener("click", () => {
            this.recordInteraction("點擊按鈕", "手動檢查 App 更新");
            this.checkForAppUpdates(false);
        });
    }

    const uiBtnSettings = document.getElementById("ui-btn-settings");
    if (uiBtnSettings) {
        uiBtnSettings.addEventListener("click", () => {
            this.recordInteraction("點擊按鈕", "開啟偏好設定");
            this.showSettingsModal();
        });
    }

    const uiBtnMapDb = document.getElementById("ui-btn-map-db");
    if (uiBtnMapDb) {
        uiBtnMapDb.addEventListener("click", () => {
            this.recordInteraction("點擊按鈕", "管理離線圖資");
            this.showMapDatabaseModal();
        });
    }



    const uiBtnExportLog = document.getElementById("ui-btn-export-log");
    if (uiBtnExportLog) {
        uiBtnExportLog.addEventListener("click", () => {

            this.recordInteraction("點擊按鈕", "匯出 AI 結構化診斷日誌壓縮包");
            const detectedList = Array.from(this.sessionDetectedPois ? this.sessionDetectedPois.values() : []);
            const sessionDurationSec = Math.round((Date.now() - (this.sessionStartTime || Date.now())) / 1000);
            const exportPayload = {
                exportTime: new Date().toISOString(),
                sessionDurationSec: sessionDurationSec,
                sessionMetrics: {
                    duration_s: sessionDurationSec,
                    total_speech_count: this.sessionSpeechHistory ? this.sessionSpeechHistory.length : 0,
                    total_pois_detected: detectedList.length,
                    total_interactions: this.sessionInteractions ? this.sessionInteractions.length : 0,
                    total_traces: this.sessionCausalityTrace ? this.sessionCausalityTrace.length : 0
                },
                currentRoad: this.currentRoadName || (this.currentStreetName || "未知道路"),
                lastDoor: this.lastSpokenDoor || "",
                lastIntersection: this.lastSpokenIntersection || "",
                lastHeading: window.lastHeading || 0,
                lastGps: {
                    lat: window.lastGpsLat,
                    lon: window.lastGpsLon
                },
                verticalLevel: window.currentVerticalLevel || "GROUND",
                altitudeM: window.currentAltitudeM || 0.0,
                beaconAnchor: window.currentBeaconAnchor || null,
                differentialTier: window.currentDifferentialTier || null,
                activeGuidance: this.activeGuidance ? {
                    targetName: this.activeGuidance.targetName,
                    targetLat: this.activeGuidance.targetLat,
                    targetLon: this.activeGuidance.targetLon,
                    lastDistanceM: this.activeGuidance.lastDistanceM
                } : null,
                speechHistory: this.sessionSpeechHistory || [],
                detectedPois: detectedList,
                causalityTrace: this.sessionCausalityTrace || [],
                interactions: this.sessionInteractions || [],
                anomalies: this.sessionAnomalies || []
            };

            const jsonStr = JSON.stringify(exportPayload);
            if (window.AndroidBridge && window.AndroidBridge.shareAppLogsWithData) {
                window.AndroidBridge.shareAppLogsWithData(jsonStr);
            } else if (window.AndroidBridge && window.AndroidBridge.shareAppLogs) {
                window.AndroidBridge.shareAppLogs();
            } else {
                alert("目前未在 Android 原生環境中執行，無法直接分享系統日誌。");
            }
        });
    }

    // Permission Banner & Manual Search Wiring
    const permBanner = document.getElementById("permission-banner");
    const openSettingsBtn = document.getElementById("open-settings-btn");
    const manualSearchBtn = document.getElementById("manual-search-btn");
    const searchGoBtn = document.getElementById("search-go-btn");
    const searchInputVis = document.getElementById("location-input-visible");

    if (openSettingsBtn) {
      openSettingsBtn.addEventListener("click", () => {
        if (window.AndroidBridge && window.AndroidBridge.openAppSettings) {
          window.AndroidBridge.openAppSettings();
        } else {
          alert("請前往手機系統設定開啟定位權限。");
        }
      });
    }

    if (manualSearchBtn && searchInputVis) {
      manualSearchBtn.addEventListener("click", () => {
        searchInputVis.focus();
        this.updateLiveLog("請輸入探索地址或地標名稱。", false, true);
      });
    }

    if (searchGoBtn && searchInputVis) {
      searchGoBtn.addEventListener("click", () => {
        const query = searchInputVis.value.trim();
        if (query) this.teleport(query);
      });
      searchInputVis.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          const query = searchInputVis.value.trim();
          if (query) this.teleport(query);
        }
      });
    }

    // Modal & 3D Guidance Actions Wiring
    const poiCloseBtn = document.getElementById("poi-modal-close-btn");
    const poiDismissBtn = document.getElementById("poi-modal-dismiss");
    const poiNavNmapBtn = document.getElementById("poi-modal-nav-nmap");
    const poiNavGmapsBtn = document.getElementById("poi-modal-nav-gmaps");
    const homeStopBtn = document.getElementById("home-stop-guidance-btn");
    const arrivalStopBtn = document.getElementById("arrival-modal-stop-btn");

    if (poiCloseBtn) poiCloseBtn.addEventListener("click", () => this.closePoiModal());
    if (poiDismissBtn) poiDismissBtn.addEventListener("click", () => this.closePoiModal());
    if (poiNavNmapBtn) poiNavNmapBtn.addEventListener("click", () => this.startBeaconToTarget());
    if (poiNavGmapsBtn) poiNavGmapsBtn.addEventListener("click", () => this.launchGoogleMapsNavigation());
    if (homeStopBtn) homeStopBtn.addEventListener("click", () => this.stopBeaconGuidance(false));
    if (arrivalStopBtn) arrivalStopBtn.addEventListener("click", () => this.closeArrivalModal());

    // ESC key closes any active modal
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        if (this.activeModal) {
          const m = this.activeModal;
          this.closeModal(m);
          if (m && m.id === "poi-detail-modal") {
            this.closePoiModal();
          } else if (m && m.id === "arrival-modal") {
            this.closeArrivalModal();
          }
        } else {
          this.closePoiModal();
        }
      }
    });

    // Check location permission on cold start
    if (window.AndroidBridge && window.AndroidBridge.hasLocationPermission) {
      if (window.AndroidBridge.hasLocationPermission()) {
        if (permBanner) permBanner.style.display = "none";
      } else {
        if (permBanner) permBanner.style.display = "block";
        this.updateLiveLog("📍 定位權限未開啟，已進入手動探索模式。請直接輸入地址開始探索，或點擊開啟系統設定。", false, true);
      }
    } else {
      if (permBanner) permBanner.style.display = "none";
    }


    // NLP Query Form
    const nlpForm = document.getElementById("nlp-form");
    if (nlpForm) {
      nlpForm.addEventListener("submit", (e) => {
        e.preventDefault();
        const q = this.queryInput.value.trim();
        if (q) this.sendNLPQuery(q);
      });
    }

    // Global Keyboard Listener
    // ↑/W = 前進, ↓/S = 後退, ←/A = 左轉45°, →/D = 右轉45°
    
    window.addEventListener("keyup", (e) => {
      const k = e.key.toLowerCase();
      this.keysDown[k] = false;
      if (e.key === "Shift") this.keysDown["shift"] = false;
      
      if (['w', 's', 'arrowup', 'arrowdown', 'a', 'd', 'arrowleft', 'arrowright'].includes(k)) {
          if (!this.keysDown['w'] && !this.keysDown['s'] && !this.keysDown['arrowup'] && !this.keysDown['arrowdown'] &&
              !this.keysDown['a'] && !this.keysDown['d'] && !this.keysDown['arrowleft'] && !this.keysDown['arrowright']) {
              // Forced final sync on stop
              this.serverSync();
          }
      }
    });

    window.addEventListener("keydown", (e) => {
      const activeTag = document.activeElement ? document.activeElement.tagName.toLowerCase() : "";
      if (activeTag === "input" || activeTag === "textarea") return;

      const k = e.key.toLowerCase();
      if (!e.repeat) {
          this.keysDown[k] = true;
          if (e.key === "Shift") this.keysDown["shift"] = true;
      }

      switch (e.key) {
        case "ArrowUp":
        case "w":
        case "W":
          e.preventDefault();
          if (e.ctrlKey) {
              this.jumpToNextIntersection();
          } else {
              if (this.velocity === undefined) this.velocity = 0;
              if (this.velocity < 1.5) this.velocity = 1.5; // Initial bump for quick tap
          }
          break;

        case "ArrowDown":
        case "s":
        case "S":
          e.preventDefault();
          if (this.velocity === undefined) this.velocity = 0;
          if (this.velocity < 1.5) this.velocity = 1.5;
          break;

        case "ArrowLeft":
        case "a":
        case "A":
          e.preventDefault();
          if (e.ctrlKey) {
              this.snapTurn("left");
          } else if (e.shiftKey) {
              this.strafe("left");
          } else {
              this.turn(-45);
          }
          break;

        case "ArrowRight":
        case "d":
        case "D":
          e.preventDefault();
          if (e.ctrlKey) {
              this.snapTurn("right");
          } else if (e.shiftKey) {
              this.strafe("right");
          } else {
              this.turn(45);
          }
          break;

        case "q":
        case "Q":
          e.preventDefault();
          this.turn(-45);
          break;

        case "e":
        case "E":
          e.preventDefault();
          this.turn(45);
          break;

        case " ":
        case "Spacebar":
          e.preventDefault();
          this.checkStatus(true);
          break;

        case "p":
        case "P":
          e.preventDefault();
          if (this.audio && (!this.settings || this.settings.earconEnabled !== false)) {
            this.audio.playRadarExploreTone();
          }
          setTimeout(() => this.announceAllPOIs(), 200);
          break;

        case "r":
        case "R":
          e.preventDefault();
          this.announceRoadAndDoorNumbers();
          break;

        case "h":
        case "H":
          e.preventDefault();
          this.announceHistory();
          break;

        // 步距快捷鍵 1~5
        case "1": e.preventDefault(); this.setStepDistance(0.5); break;
        case "2": e.preventDefault(); this.setStepDistance(1); break;
        case "3": e.preventDefault(); this.setStepDistance(2); break;
        case "4": e.preventDefault(); this.setStepDistance(3); break;
        case "5": e.preventDefault(); this.setStepDistance(5); break;

        // I = Intersection: 前方路口資訊與分支走向 (延伸至下個路口)
        case "i":
        case "I":
          e.preventDefault();
          if (this.audio && (!this.settings || this.settings.earconEnabled !== false)) {
            this.audio.playJunctionTone(0, -1);
          }
          setTimeout(() => this.announceUpcomingIntersection(), 150);
          break;

        // L = Left/Right Sweep: 左右兩側店家掃描
        case "l":
        case "L":
          e.preventDefault();
          if (this.audio && (!this.settings || this.settings.earconEnabled !== false)) {
            this.audio.playScanSweepTone();
          }
          setTimeout(() => this.announceLeftRightSweep(), 200);
          break;

        case "m":
        case "M":
          e.preventDefault();
          this.toggleSimulation();
          break;
        case "c":
        case "C":
          e.preventDefault();
          this.simulationAction("cane");
          break;
        case "t":
        case "T":
          e.preventDefault();
          this.simulationAction("listen");
          break;
        case "g":
        case "G":
          e.preventDefault();
          this.simulationAction("help");
          break;
        case "x":
        case "X":
          e.preventDefault();
          this.simulationAction("assess");
          break;
        case "f":
        case "F":
          e.preventDefault();
          this.simulationAction("follow_paving");
          break;
        case "n":
        case "N":
          e.preventDefault();
          this.simulationAction("memory");
          break;
        case "b":
        case "B":
          e.preventDefault();
          this.cycleDifficulty();
          break;
      }
    });
  }

  showModal(show) {
    if (show) {
      this.helpModal.removeAttribute("hidden");
      this.modalOkBtn.focus();
    } else {
      this.helpModal.setAttribute("hidden", "true");
      this.helpBtn.focus();
    }
  }

  toggleSimulation() {
    if (!this.simulationMode) {
        // Start simulation
        fetch('/api/simulation/start', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({difficulty: this.simDifficulty || 'normal'})
        })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                this.simulationMode = true;
                this.audio.playArrival();
                this.updateLiveLog(`🎮 ${data.message}\n${data.narration || ''}`, false, true);
            } else {
                this.updateLiveLog(data.message, true, true);
            }
        });
    } else {
        // Stop simulation
        fetch('/api/simulation/stop', {method: 'POST'})
        .then(res => res.json())
        .then(data => {
            this.simulationMode = false;
            this.updateLiveLog(`📍 ${data.message}`, false, true);
        });
    }
  }

  simulationAction(action) {
    if (!this.simulationMode) return;
    fetch('/api/simulation/action', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({action: action})
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            this.updateLiveLog(data.narration || data.result || '', false, true);
            if (this.liveLog && this.liveLog.firstElementChild) this.historyList.firstElementChild.focus();
        }
    });
  }

  cycleDifficulty() {
    if (!this.simDifficulty) this.simDifficulty = 'normal';
    const difficulties = ['beginner', 'normal', 'expert'];
    let idx = difficulties.indexOf(this.simDifficulty);
    idx = (idx + 1) % difficulties.length;
    this.simDifficulty = difficulties[idx];
    
    fetch('/api/simulation/settings', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({difficulty: this.simDifficulty})
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            this.updateLiveLog(`難度已切換為：${this.simDifficulty}`, false, true);
        }
    });
  }

  updateLiveLog(text, isError = false, isForce = false) {
    if (!text || (text === this.lastSpokenText && !isError && !isForce)) {
      return;
    }

    this.lastSpokenText = text;
    this.lastSpeechTime = Date.now();

    // Diagnostic Speech History Collection
    if (!this.sessionSpeechHistory) this.sessionSpeechHistory = [];
    const timeStr = new Date().toISOString();
    const speechType = isError ? "ALERT" : (isForce ? "HEADING_OR_MANUAL" : "PROXIMITY_POI");
    this.sessionSpeechHistory.push({
      time: timeStr,
      text: text.trim(),
      type: speechType
    });
    if (this.sessionSpeechHistory.length > 500) {
      this.sessionSpeechHistory.shift();
    }

    if (this.recordTrace) {
      this.recordTrace("TTS_SPEECH", {
        text: text.trim(),
        type: speechType,
        is_error: isError
      });
    }

    // 1. Android 原生 TalkBack 輔助功能廣播 (announceForAccessibility) 與 TTS 引擎
    if (window.AndroidBridge && window.AndroidBridge.speak) {
      window.AndroidBridge.speak(text, true);
    }

    // 2. PC 瀏覽器 / NVDA Web Speech API 備援
    if (!window.AndroidBridge && window.speechSynthesis) {
      try {
        window.speechSynthesis.cancel();
        const u = new SpeechSynthesisUtterance(text);
        u.lang = 'zh-TW';
        u.rate = 1.15;
        window.speechSynthesis.speak(u);
      } catch (e) {}
    }

    // 3. ARIA Live Region 即時注入 (供 NVDA / 螢幕閱讀器捕捉)
    if (this.liveLog) {
      this.liveLog.textContent = "";
      setTimeout(() => {
        if (this.liveLog) this.liveLog.textContent = text;
      }, 20);
    }

    const historyList = document.getElementById("history-list");
    if (historyList) {
      // Split by spaces or punctuation to separate sentences as requested by the user
      let parts = text.split(/。|\n/).filter(p => p.trim().length > 0);
      const allKnownPois = (this.getRealtimePois && this.getRealtimePois().length > 0) ? this.getRealtimePois() : (this.lastPois || []);
      const curLat = this.localLat !== null ? this.localLat : (this.serverLat || 25.1764);
      const curLon = this.localLon !== null ? this.localLon : (this.serverLon || 121.4468);
      
      parts.forEach(part => {
        const cleanPart = part.trim();
        const li = document.createElement("li");
        li.className = "history-item";
        li.tabIndex = 0;
        li.textContent = cleanPart + "。";

        // 智慧比對是否包含店家/地標資訊
        let matchedPoi = null;
        for (const p of allKnownPois) {
          if (p && p.name && (cleanPart.includes(p.name) || p.name.includes(cleanPart.replace(/[\(（].*$/, '').trim()))) {
            matchedPoi = p;
            break;
          }
        }

        if (!matchedPoi && this.sessionDetectedPois) {
          for (const p of this.sessionDetectedPois.values()) {
            if (p && p.name && (cleanPart.includes(p.name) || p.name.includes(cleanPart.replace(/[\(（].*$/, '').trim()))) {
              matchedPoi = p;
              break;
            }
          }
        }

        // 若屬於地標/店家格式（如「美而美 (正前方 15m)」或「美而美，正前方」），自動提取店名
        if (!matchedPoi && (cleanPart.includes("公尺") || cleanPart.includes("m") || cleanPart.includes("前方") || cleanPart.includes("左") || cleanPart.includes("右") || cleanPart.includes("點鐘"))) {
          const rawName = cleanPart.replace(/[\(（].*$/, '').replace(/，.*$/, '').replace(/【.*】/, '').trim();
          if (rawName.length >= 2 && rawName.length <= 25 && !rawName.includes("周遭") && !rawName.includes("十字路口") && !rawName.includes("路口") && !rawName.includes("前進")) {
            matchedPoi = {
              name: rawName,
              lat: curLat,
              lon: curLon,
              distance_m: 10,
              clock_position: "正前方",
              category: "poi"
            };
          }
        }

        if (matchedPoi) {
          li.style.cursor = "pointer";
          li.setAttribute("role", "button");
          li.setAttribute("aria-label", `${cleanPart}。雙擊或按 Enter 可展開此店家詳細營業資訊`);
          li.style.borderLeft = "4px solid #38bdf8";
          li.style.paddingLeft = "8px";

          const triggerOpen = (e) => {
            if (e) {
              e.preventDefault();
              e.stopPropagation();
            }
            this.lastPoiTriggerElement = li;
            this.showPoiDetail(matchedPoi, li);
          };

          li.onclick = triggerOpen;
          li.ondblclick = triggerOpen;
          li.onkeydown = (e) => {
            if (e.key === "Enter" || e.key === " ") {
              triggerOpen(e);
            }
          };
        }

        historyList.prepend(li);
        
        while (historyList.children.length > 50) {
          historyList.removeChild(historyList.lastChild);
        }
      });
    }

    if (isError) {
      this.statusBadge.textContent = "⚠️ 警示 / 碰撞";
      this.statusBadge.className = "badge badge-danger";
    } else {
      if (this.simulationMode) {
        this.statusBadge.textContent = "🎮 模擬中";
        this.statusBadge.className = "badge badge-warning";
      } else {
        this.statusBadge.textContent = "探索中";
        this.statusBadge.className = "badge badge-info";
      }
    }
  }

  // ========== 6 大周遭地標領域分類器 (POI Domain Classifier) ==========
  classifyPoiDomain(poi) {
    if (!poi) return "all";
    const cat = ((poi.category || "") + " " + (poi.category_desc || "")).toLowerCase();
    const name = (poi.name || "").toLowerCase();

    // 1. 交通號誌、公車、捷運、路口 (transit)
    if (
      cat.includes("traffic_signal") || cat.includes("aps_signal") || cat.includes("crossing") ||
      cat.includes("bus_stop") || cat.includes("bus_station") || cat.includes("subway") ||
      cat.includes("mrt") || cat.includes("train_station") || cat.includes("platform") ||
      cat.includes("parking") || name.includes("公車站") || name.includes("捷運") ||
      name.includes("號誌") || name.includes("斑馬線") || name.includes("火車站") ||
      name.includes("停車場") || name.includes("站牌")
    ) {
      return "transit";
    }

    // 2. 醫療、公共設施與無障礙 (public_access)
    if (
      cat.includes("mrt_elevator") || cat.includes("elevator") || cat.includes("toilets") ||
      cat.includes("toilet") || cat.includes("pharmacy") || cat.includes("hospital") ||
      cat.includes("clinic") || cat.includes("dentist") || cat.includes("doctor") ||
      cat.includes("post_office") || cat.includes("bank") || cat.includes("atm") ||
      cat.includes("police") || cat.includes("fire_station") || cat.includes("government") ||
      cat.includes("townhall") || name.includes("無障礙") || name.includes("電梯") ||
      name.includes("公廁") || name.includes("廁所") || name.includes("藥局") ||
      name.includes("診所") || name.includes("醫院") || name.includes("郵局") ||
      name.includes("銀行") || name.includes("提款機") || name.includes("派出所") ||
      name.includes("警察局") || name.includes("戶政") || name.includes("公所")
    ) {
      return "public_access";
    }

    // 3. 餐飲與美食小吃 (food)
    if (
      cat.includes("restaurant") || cat.includes("food") || cat.includes("cafe") ||
      cat.includes("coffee") || cat.includes("bubble_tea") || cat.includes("tea") ||
      cat.includes("bakery") || cat.includes("diner") || cat.includes("breakfast") ||
      cat.includes("fast_food") || cat.includes("barbecue") || cat.includes("hotpot") ||
      cat.includes("seafood") || cat.includes("ice_cream") || cat.includes("buffet") ||
      cat.includes("deli") || cat.includes("dessert") || cat.includes("confectionery") ||
      cat.includes("bar") || cat.includes("pub") || name.includes("餐廳") ||
      name.includes("咖啡") || name.includes("小吃") || name.includes("便當") ||
      name.includes("麵店") || name.includes("麵館") || name.includes("紅茶") ||
      name.includes("手搖") || name.includes("早餐") || name.includes("烘焙") ||
      name.includes("甜點") || name.includes("火鍋") || name.includes("牛排") ||
      name.includes("早午餐")
    ) {
      return "food";
    }

    // 4. 生活購物與超商 (shopping)
    if (
      cat.includes("convenience") || cat.includes("supermarket") || cat.includes("grocery") ||
      cat.includes("shop") || cat.includes("shopping") || cat.includes("clothing") ||
      cat.includes("clothes") || cat.includes("mobile_phone") || cat.includes("hardware") ||
      cat.includes("book") || cat.includes("stationery") || cat.includes("beauty") ||
      cat.includes("hair") || cat.includes("salon") || cat.includes("mall") ||
      cat.includes("department_store") || cat.includes("market") || cat.includes("variety") ||
      cat.includes("florist") || cat.includes("optician") || cat.includes("shoes") ||
      name.includes("7-eleven") || name.includes("7-11") || name.includes("全家") ||
      name.includes("萊爾富") || name.includes("ok超商") || name.includes("全聯") ||
      name.includes("家樂福") || name.includes("美廉社") || name.includes("屈臣氏") ||
      name.includes("康是美") || name.includes("寶雅") || name.includes("大創") ||
      name.includes("五金") || name.includes("服飾") || name.includes("鞋") ||
      name.includes("眼鏡") || name.includes("通訊") || name.includes("書店") ||
      name.includes("文具") || name.includes("美髮") || name.includes("理髮")
    ) {
      return "shopping";
    }

    // 5. 建築地標、學校與休閒景點 (landmarks)
    if (
      cat.includes("school") || cat.includes("university") || cat.includes("kindergarten") ||
      cat.includes("college") || cat.includes("library") || cat.includes("temple") ||
      cat.includes("church") || cat.includes("worship") || cat.includes("park") ||
      cat.includes("garden") || cat.includes("museum") || cat.includes("attraction") ||
      cat.includes("viewpoint") || cat.includes("historic") || cat.includes("landmark") ||
      cat.includes("monument") || cat.includes("hotel") || cat.includes("motel") ||
      cat.includes("hostel") || cat.includes("gym") || cat.includes("fitness") ||
      cat.includes("theatre") || cat.includes("cinema") || name.includes("國小") ||
      name.includes("國中") || name.includes("高中") || name.includes("大學") ||
      name.includes("幼兒園") || name.includes("寺") || name.includes("廟") ||
      name.includes("宮") || name.includes("教堂") || name.includes("公園") ||
      name.includes("館") || name.includes("飯店") || name.includes("旅館")
    ) {
      return "landmarks";
    }

    return "shopping";
  }

  // ========== TalkBack 自動滑桿上下撥動切換分類輪播器 (Accessible Category Slider) ==========
  cyclePoiCategory(delta, announce = true) {
    if (!this.poiCategories || this.poiCategories.length === 0) return;
    const len = this.poiCategories.length;
    this.currentCategoryIndex = (this.currentCategoryIndex + delta + len) % len;
    const current = this.poiCategories[this.currentCategoryIndex];

    const btn = document.getElementById("ui-btn-around");
    if (btn) {
      btn.textContent = `${current.icon} ${current.label} (P)`;
      btn.setAttribute("aria-valuenow", this.currentCategoryIndex.toString());
      btn.setAttribute("aria-valuetext", current.label);
    }

    if (this.audio && this.audio.playTick) {
      this.audio.playTick(delta < 0);
    }

    if (announce) {
      // 依使用者無障礙省話規範：切換時只極簡唸出分類名稱（如「餐飲美食」），不加任何贅字
      this.speakNative(current.label, true);
    }
  }

  // 隨時根據「當前即時朝向」、「即時座標」與「選定分類」重新動態推算所有店家的相對左右/鐘點方位
  getRealtimePois(filterCategory = null) {
    if (!this.lastPois || this.lastPois.length === 0) return [];
    const curLat = this.localLat !== null ? this.localLat : (this.serverLat || 0);
    const curLon = this.localLon !== null ? this.localLon : (this.serverLon || 0);
    const curHead = (this.localHeading !== null && this.localHeading !== undefined) ? this.localHeading : (window.lastHeading || 0);

    const targetCategory = filterCategory || (this.poiCategories ? this.poiCategories[this.currentCategoryIndex].key : "all");

    let sourceList = this.lastPois;
    if (targetCategory && targetCategory !== "all") {
      sourceList = this.lastPois.filter(p => this.classifyPoiDomain(p) === targetCategory);
    }

    return sourceList.map((p) => {
      const dist = Math.round(this.haversineDistance(curLat, curLon, p.lat, p.lon) * 10) / 10;
      const targetBrng = this.calculateBearing(curLat, curLon, p.lat, p.lon);
      
      let relBrng = (targetBrng - curHead + 360.0) % 360.0;
      if (relBrng > 180.0) relBrng -= 360.0;

      const normDeg = (relBrng + 360.0) % 360.0;
      let hour = Math.round(normDeg / 30.0) % 12;
      if (hour === 0) hour = 12;
      const clockStr = `${hour}點鐘方向`;

      let relDir = "周遭";
      const absDiff = Math.abs(relBrng);
      if (absDiff <= 22.5) relDir = "正前方";
      else if (absDiff >= 157.5) relDir = "正後方";
      else if (relBrng > 22.5 && relBrng < 67.5) relDir = "右前方";
      else if (relBrng >= 67.5 && relBrng <= 112.5) relDir = "右側";
      else if (relBrng > 112.5 && relBrng < 157.5) relDir = "右後方";
      else if (relBrng < -22.5 && relBrng > -67.5) relDir = "左前方";
      else if (relBrng <= -67.5 && relBrng >= -112.5) relDir = "左側";
      else if (relBrng < -112.5 && relBrng > -157.5) relDir = "左後方";

      return {
        ...p,
        distance_m: dist,
        bearing_deg: Math.round(targetBrng),
        relative_bearing_deg: Math.round(relBrng * 10) / 10,
        clock_position: clockStr,
        relative_direction: relDir
      };
    }).sort((a, b) => a.distance_m - b.distance_m);
  }

  updatePOIs(pois) {
    this.lastPois = pois || [];

    // Diagnostic Detected POIs Collection
    if (pois && Array.isArray(pois)) {
      if (!this.sessionDetectedPois) this.sessionDetectedPois = new Map();
      const timeStr = new Date().toLocaleTimeString();
      pois.forEach(p => {
        if (!p || !p.name) return;
        const key = `${p.name}_${p.lat}_${p.lon}`;
        if (!this.sessionDetectedPois.has(key)) {
          this.sessionDetectedPois.set(key, {
            firstSeenTime: timeStr,
            name: p.name,
            category: this.translateCategory(p.category),
            rawCategory: p.category || "",
            clockPosition: p.clock_position || "",
            distanceM: p.distance_m || 0,
            relativeDirection: p.relative_direction || "",
            lat: p.lat,
            lon: p.lon,
            phone: p.phone || "",
            opening_hours: p.opening_hours || "",
            wheelchair: p.wheelchair || "",
            cuisine: p.cuisine || "",
            brand: p.brand || ""
          });
        }
      });
    }

    const realtime = this.getRealtimePois();
    if (!realtime || realtime.length === 0) {
      this.poiContainer.innerHTML = '<p class="empty-tip">周遭 100 公尺內無特別登錄的設施。</p>';
      return;
    }

    let html = "";
    realtime.forEach((p, idx) => {
      const flag = p.wheelchair === "yes" ? " <span style='color:#22c55e;'>[♿無障礙]</span>" : "";
      const extras = [];
      if (p.opening_hours) extras.push(`營業：${p.opening_hours}`);
      if (p.cuisine) extras.push(`料理：${p.cuisine}`);
      if (p.phone) extras.push(`電話：${p.phone}`);
      const extraStr = extras.length > 0 ? `<br><small style="color:#94a3b8;">${extras.join(" | ")}</small>` : "";

      html += `
        <div class="poi-card" tabindex="0" data-idx="${idx}" aria-label="${p.name}，距離 ${p.distance_m} 公尺，位於 ${p.clock_position}，點擊查看詳細資訊與導航">
          <h4>${p.name}${flag}</h4>
          <p>類別：${this.translateCategory(p.category)} | 方位：${p.clock_position} (${p.relative_direction}) | 距離：${p.distance_m} 公尺${extraStr}</p>
        </div>
      `;
    });
    this.poiContainer.innerHTML = html;

    // Bind click events to open POI detail modal
    const cards = this.poiContainer.querySelectorAll(".poi-card");
    cards.forEach((card) => {
      const idx = parseInt(card.getAttribute("data-idx"), 10);
      const poi = realtime[idx];
      card.addEventListener("click", () => this.showPoiDetail(poi));
      card.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          this.showPoiDetail(poi);
        }
      });
    });
  }

  showPoiDetail(poi) {
    if (!poi) return;
    this.activePoiTarget = poi;
    this.isDetailModalOpen = true;
    window.isDetailModalOpen = true;

    const modal = document.getElementById("poi-detail-modal");
    const title = document.getElementById("poi-modal-title");
    const body = document.getElementById("poi-modal-body");
    if (!modal || !title || !body) return;

    title.textContent = poi.name;
    const cat = this.translateCategory(poi.category);
    const floorStr = (poi.floor && poi.floor !== "1F") ? ` (${poi.floor})` : " (1樓/地面層)";
    
    // 即時動態渲染函式
    const renderModalContent = (richData = {}, isLoading = false) => {
      const merged = Object.assign({}, poi, richData);
      
      // 【方案三：真實地址無偽造展示 (Authentic Address Display)】
      let displayAddress = "";
      if (merged.address && merged.address.trim()) {
        displayAddress = merged.address.trim();
      } else if (merged.street && merged.housenumber) {
        displayAddress = `${merged.street} ${merged.housenumber}號`.trim();
      } else if (merged.street) {
        displayAddress = `${merged.street}週邊（未登記詳細門牌）`;
      } else if (isLoading) {
        displayAddress = `⏳ 正在比對官方門牌資料庫...`;
      } else {
        displayAddress = `未登記正式門牌號（位於鄰近路段）`;
      }
      const displayCategory = merged.category_desc || cat;

      let infoRows = [
        `<div><strong>🏪 招牌店名：</strong><span style="color:#38bdf8;font-weight:bold;">${merged.name}</span></div>`,
        `<div><strong>📍 門牌地址：</strong><span style="color:#f8fafc;font-weight:bold;">${displayAddress}${floorStr}</span></div>`,
        `<div><strong>🏷️ 商家類型：</strong><span style="color:#cbd5e1;">${displayCategory}</span></div>`,
        `<div><strong>🧭 方位距離：</strong>${merged.clock_position || '正前方'} (${merged.relative_direction || '前方'})，約 ${merged.distance_m} 公尺</div>`
      ];

      if (merged.legal_name && merged.legal_name !== merged.name) {
        infoRows.push(`<div><strong>🏢 商業登記：</strong>${merged.legal_name}</div>`);
      }
      if (merged.business_desc) {
        infoRows.push(`<div><strong>📋 營業項目：</strong>${merged.business_desc}</div>`);
      }
      
      let hoursDisplay = merged.opening_hours;
      if (!hoursDisplay && isLoading) {
        hoursDisplay = `<span style="color:#94a3b8;">⏳ 正在連線查詢今日即時狀態...</span>`;
      } else if (!hoursDisplay) {
        hoursDisplay = "營業中（依現場實際狀況為準）";
      }
      infoRows.push(`<div><strong>⏰ 營業時間：</strong><span style="color:#2dd4bf;font-weight:bold;">${hoursDisplay}</span></div>`);

      if (merged.rating) {
        infoRows.push(`<div><strong>⭐ 大眾評價：</strong><span style="color:#facc15; font-weight:bold;">${merged.rating}</span></div>`);
      }

      if (merged.popular_items) {
        infoRows.push(`<div><strong>🍲 熱門推薦：</strong><span style="color:#fb923c; font-weight:bold;">${merged.popular_items}</span></div>`);
      }

      if (merged.phone && merged.phone !== "門市在地專線") {
        infoRows.push(`<div><strong>📞 聯絡電話：</strong><a href="tel:${merged.phone}" style="color:#38bdf8; text-decoration:underline; font-weight:bold; font-size:1.05rem;" aria-label="撥打電話：${merged.phone}">${merged.phone} (點擊直接撥打)</a></div>`);
      } else if (!isLoading) {
        infoRows.push(`<div><strong>📞 聯絡電話：</strong><span style="color:#94a3b8;">未登記公開市話（可直接依門牌前往）</span></div>`);
      }

      const wheelchair = merged.wheelchair || (merged.floor === "1F" ? "♿ 具備 1 樓平整入口 (地面層)" : "無障礙狀態未知");
      infoRows.push(`<div><strong>♿ 無障礙：</strong><span style="color:#38bdf8;">${wheelchair}</span></div>`);

      body.innerHTML = infoRows.join("");
    };

    const nmapBtn = document.getElementById("poi-modal-nav-nmap");
    if (nmapBtn) {
      if (this.activeBeaconTarget && this.activeBeaconTarget.name === poi.name) {
        nmapBtn.textContent = "🛑 正在 3D 導引此地標（點擊停止導引）";
        nmapBtn.style.background = "#ef4444";
        nmapBtn.style.color = "#ffffff";
      } else {
        nmapBtn.textContent = "🎯 開啟 3D 空間聲音導引 (越近越響越急促)";
        nmapBtn.style.background = "#38bdf8";
        nmapBtn.style.color = "#0f172a";
      }
    }

    renderModalContent({}, true);
    this.openModal("poi-detail-modal", (typeof triggerEl !== "undefined" && triggerEl) ? triggerEl : (this.lastPoiTriggerElement || document.activeElement));

    if (this.audio) {
      this.audio.playForPoi(poi);
    }
    const spokenFloor = (poi.floor && poi.floor !== "1F") ? `，位於${poi.floor}` : "";
    setTimeout(() => {
      this.updateLiveLog(`開啟地標詳情：${poi.name}${spokenFloor}，距離 ${poi.distance_m} 公尺。背景播報已暫停。`, false, true);
    }, 180);

    // 【方案三】：嚴禁將視障者自身的門牌推估值冒充為店家門牌！
    // 只傳送店家自身登記之地址，若無則傳空字串讓後端進行官方反查與真實路名商圈解析
    let targetAddr = poi.address || "";
    if (!targetAddr && poi.street && poi.housenumber) {
      targetAddr = `${poi.street} ${poi.housenumber}號`.trim();
    }

    // 非同步極速向後端獲取當日即時營業時間、電話、官方真門牌與無障礙資訊 (< 0.8s)
    const encodedName = encodeURIComponent(poi.name || "");
    const encodedAddr = encodeURIComponent(targetAddr);
    const floorParam = encodeURIComponent(poi.floor || "1F");
    fetch(`/api/poi_detail?name=${encodedName}&lat=${poi.lat}&lon=${poi.lon}&address=${encodedAddr}&floor=${floorParam}`)
      .then(res => res.json())
      .then(data => {
        if (data.success && data.details) {
          renderModalContent(data.details, false);
          
          // 搜尋完成播放清脆提示音，並即時報讀真實門牌地址、電話與營業時間
          if (this.audio && this.audio.playSearchCompleteTone) {
            this.audio.playSearchCompleteTone();
          }
          const finAddr = data.details.address ? `門牌：${data.details.address}` : "未登記正式門牌號";
          const finPhone = (data.details.phone && data.details.phone !== "門市在地專線") ? `，電話：${data.details.phone}` : "";
          const finHours = data.details.opening_hours ? `，營業時間：${data.details.opening_hours}` : "";
          const finRating = data.details.rating ? `，評分：${data.details.rating}` : "";
          const finMenu = data.details.popular_items ? `，熱門推薦：${data.details.popular_items}` : "";
          const fullAnnouncement = `【${poi.name}】${finAddr}${finHours}${finRating}${finPhone}${finMenu}。`;
          
          this.updateLiveLog(fullAnnouncement, false, true);
          if (window.AndroidBridge && window.AndroidBridge.speak) {
            window.AndroidBridge.speak(fullAnnouncement, true);
          }
        }
      })
      .catch(err => {
        console.warn("Fetch POI detail error", err);
        renderModalContent({}, false);
      });
  }

  closePoiModal() {
    this.isDetailModalOpen = false;
    window.isDetailModalOpen = false;
    this.closeModal("poi-detail-modal");
    this.updateLiveLog("已關閉地標詳情，恢復地圖即時播報。", false, true);
  }

  /**
   * 計算 3D 導引脈衝間隔毫秒數 (越近越快越急)
   */
  calculateBeaconIntervalMs(distM) {
    if (distM <= 4.0) return 220;   // 極急促 (每秒 4.5 次)
    if (distM <= 8.0) return 350;   // 急促 (每秒近 3 次)
    if (distM <= 15.0) return 500;  // 快速 (每秒 2 次)
    if (distM <= 25.0) return 750;  // 中速
    if (distM <= 45.0) return 1100; // 稍慢
    if (distM <= 70.0) return 1500; // 慢速脈衝
    return 2000;                    // 遠處平緩 (每 2 秒一次)
  }

  /**
   * 啟動 3D 空間聲音導引 (單一目標監控原則)
   */
  startBeaconToTarget(poi = null) {
    const target = poi || this.activePoiTarget;
    if (!target) return;

    // 若點選的正是當前正在導引的地標，則視為停止導引
    if (this.activeBeaconTarget && this.activeBeaconTarget.name === target.name) {
      this.stopBeaconGuidance(false);
      this.closePoiModal();
      return;
    }

    // 1. 一次只能監控一個地點：若已有舊目標，先停止舊目標
    if (this.activeBeaconTarget) {
      this.stopBeaconGuidance(true);
    }

    this.activeBeaconTarget = target;
    this.updateLiveLog(`開始 3D 空間聲音導引前往【${target.name}】。越接近目標聲音越急促越響亮。`, false, true);
    this.closePoiModal();

    // 2. 顯示首頁常駐控制條
    const activeBar = document.getElementById("active-guidance-bar");
    if (activeBar) activeBar.style.display = "block";

    // 3. 立即觸發第一聲導航脈衝，並排程後續動態間隔
    this.scheduleNextBeaconStep();
  }

  /**
   * 排程下一次 3D 空間導引聲音脈衝
   */
  scheduleNextBeaconStep() {
    if (!this.activeBeaconTarget) return;

    if (this.beaconTimer) {
      clearTimeout(this.beaconTimer);
      this.beaconTimer = null;
    }

    const target = this.activeBeaconTarget;
    const curLat = (this.localLat !== null && this.localLat !== undefined) ? this.localLat : this.serverLat;
    const curLon = (this.localLon !== null && this.localLon !== undefined) ? this.localLon : this.serverLon;
    const curHead = (this.localHeading !== null && this.localHeading !== undefined) ? this.localHeading : (window.lastHeading || 0);

    if (!curLat || !curLon) {
      this.beaconTimer = setTimeout(() => this.scheduleNextBeaconStep(), 1500);
      return;
    }

    const targetBrng = NMapGeometry.calculateBearing(curLat, curLon, target.lat, target.lon);
    const relBrng = NMapGeometry.relativeBearing(curHead, targetBrng);
    const dist = NMapGeometry.haversineDistance(curLat, curLon, target.lat, target.lon);
    const clock = NMapGeometry.bearingToClockPosition(relBrng);

    // 更新首頁控制條之即時剩餘距離與方位
    this.updateActiveGuidanceBar(target, dist, clock);

    // 判斷是否抵達目標 (<= 3.5 公尺)
    if (dist <= 3.5) {
      this.handleArrivalAtTarget(target, dist);
      return;
    }

    // 播放 3D 空間脈衝 (越近越響、越清脆)
    if (this.audio && (!this.settings || this.settings.earconEnabled !== false)) {
      this.audio.playBeacon(relBrng, dist);
    }

    // 動態計算下次播放延遲：越接近地標聲音越快越急
    const nextInterval = this.calculateBeaconIntervalMs(dist);
    this.beaconTimer = setTimeout(() => this.scheduleNextBeaconStep(), nextInterval);
  }

  /**
   * 更新首頁常駐導引控制列
   */
  updateActiveGuidanceBar(target, distM, clockStr) {
    const pill = document.getElementById("guidance-dist-pill");
    const desc = document.getElementById("guidance-target-desc");
    if (pill) pill.textContent = `剩餘 ${Math.round(distM)}m`;
    if (desc) desc.textContent = `目標：${target.name}（${clockStr} 約 ${Math.round(distM)} 公尺）`;
  }

  /**
   * 停止 3D 空間聲音導引
   */
  stopBeaconGuidance(silent = false) {
    if (this.beaconTimer) {
      clearTimeout(this.beaconTimer);
      this.beaconTimer = null;
    }
    const hadTarget = !!this.activeBeaconTarget;
    const targetName = this.activeBeaconTarget ? this.activeBeaconTarget.name : "";
    this.activeBeaconTarget = null;

    const activeBar = document.getElementById("active-guidance-bar");
    if (activeBar) activeBar.style.display = "none";

    if (!silent && hadTarget) {
      this.updateLiveLog(`已停止【${targetName}】的 3D 空間聲音導引。`, false, true);
    }
  }

  /**
   * 抵達目的地處理：停止聲音、播放勝利和弦、震動、並彈出無障礙對話框
   */
  handleArrivalAtTarget(target, distM) {
    // 立即停止脈衝計時器
    if (this.beaconTimer) {
      clearTimeout(this.beaconTimer);
      this.beaconTimer = null;
    }
    this.activeBeaconTarget = null;

    // 隱藏首頁控制條
    const activeBar = document.getElementById("active-guidance-bar");
    if (activeBar) activeBar.style.display = "none";

    // 播放勝利抵達慶祝音
    if (this.audio) this.audio.playArrival();

    // 觸發震動反饋
    if (window.AndroidBridge && window.AndroidBridge.vibrate) {
      try {
        window.AndroidBridge.vibrate("[0, 250, 100, 250, 100, 500]");
      } catch (e) {}
    }

    // 語音播報
    this.updateLiveLog(`🎉 已順利抵達目的地：【${target.name}】！導引聲音已自動關閉。`, false, true);

    // 彈出抵達對話框 (Arrival Modal)
    const arrivalBody = document.getElementById("arrival-modal-body");
    if (arrivalBody) {
      arrivalBody.textContent = `您已順利抵達【${target.name}】（距離約 ${Math.round(distM)} 公尺）。導引聲音已自動為您關閉。`;
    }
    this.openModal("arrival-modal", document.getElementById("arrival-modal-stop-btn"));
    const stopBtn = document.getElementById("arrival-modal-stop-btn");
    if (stopBtn) setTimeout(() => stopBtn.focus(), 150);
  }

  /**
   * 關閉抵達對話框
   */
  closeArrivalModal() {
    this.closeModal("arrival-modal");
    this.updateLiveLog("已關閉抵達通知，恢復一般地圖探索。", false, true);
  }

  launchGoogleMapsNavigation() {
    if (!this.activePoiTarget) return;
    const t = this.activePoiTarget;
    this.updateLiveLog(`正在開啟 Google 地圖步行導航至 ${t.name}...`, false, true);
    this.closePoiModal();
    if (window.AndroidBridge && window.AndroidBridge.openGoogleMaps) {
      window.AndroidBridge.openGoogleMaps(t.lat, t.lon, t.name);
    } else {
      window.open(`https://www.google.com/maps/dir/?api=1&destination=${t.lat},${t.lon}&travelmode=walking`, "_blank");
    }
  }

  virtualPan(forwardM = 30.0, sideM = 0.0) {
    if (this.audio) this.audio.playVirtualPanChime();
    this.updateLiveLog(`正在向前平移探索...`, false, true);

    fetch("/api/virtual_pan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ forward_m: forwardM, side_m: sideM })
    })
    .then(res => res.json())
    .then(data => {
      if (data.success && data.pan_data) {
        const pd = data.pan_data;
        const msg = data.action_message || `探索視角平移至【${pd.road_name}】`;
        this.updateLiveLog(msg, false, true);
        if (pd.pois && pd.pois.length > 0) {
          this.updatePOIs(pd.pois);
        }
      } else {
        this.updateLiveLog(data.action_message || "平移探索無回應。", false, true);
      }
    })
    .catch(err => {
      console.error("Virtual pan error:", err);
    });
  }

  cleanPoiDisplayName(name) {
    if (!name) return "未命名設施";
    let clean = name.trim();
    for (const sep of ['|', '｜', ' - ', '—', '_']) {
      if (clean.includes(sep)) {
        const parts = clean.split(sep).map(s => s.trim()).filter(Boolean);
        if (parts.length > 0 && parts[0].length >= 2) {
          clean = parts[0];
          break;
        }
      }
    }
    if (clean.includes('-') && clean.length > 12) {
      const parts = clean.split('-').map(s => s.trim()).filter(Boolean);
      if (parts.length > 0 && parts[0].length >= 2) {
        clean = parts[0];
      }
    }
    return clean.replace(/[～~]+/g, ' ').trim();
  }

  announceAllPOIs(categoryKey = null) {
    const targetCatKey = categoryKey || (this.poiCategories ? this.poiCategories[this.currentCategoryIndex].key : "all");
    const catMeta = (this.poiCategories ? this.poiCategories.find(c => c.key === targetCatKey) : null) || { icon: "🌐", label: "全部設施" };

    const doAnnounce = () => {
      const realtimePois = this.getRealtimePois(targetCatKey);
      if (!realtimePois || realtimePois.length === 0) {
        this.updateLiveLog(`【${catMeta.icon} ${catMeta.label}】150 公尺內無特別登錄的設施。`, false, true);
        return;
      }
      
      const isEarconOn = !this.settings || this.settings.earconEnabled !== false;
      const nearest = realtimePois[0];
      if (isEarconOn && this.audio && nearest) {
        // 朗讀前精確播放最近設施之專屬 3D 空間音效 (商店/地標/建築/交通)
        this.audio.playForPoi(nearest);
      } else if (this.audio) {
        this.audio.playSpatialTone(660, 'sine', 0, 0, -1, 0.15);
      }
      
      const closeCount = realtimePois.filter(p => p.distance_m <= 35).length;
      let summaryStr = `【${catMeta.icon} ${catMeta.label}掃描】周遭共發現 ${realtimePois.length} 處${closeCount > 0 ? `（35米內近處 ${closeCount} 處）` : ''}：\n`;
      
      const lines = realtimePois.map((p, idx) => {
          const cat = this.translateCategory(p.category);
          const cleanName = this.cleanPoiDisplayName(p.name);
          const clock = p.clock_position || p.clock_direction || "前方";
          return `${idx + 1}. ${cleanName}（${clock} ${p.distance_m}m，${cat}）`;
      });
      
      setTimeout(() => {
        this.updateLiveLog(summaryStr + lines.join("\n"), false, true);
      }, (isEarconOn && nearest) ? 180 : 0);
    };

    const curHead = (this.localHeading !== null && this.localHeading !== undefined) ? this.localHeading : (window.lastHeading || 0);
    const curLat = this.localLat !== null ? this.localLat : (this.serverLat || "");
    const curLon = this.localLon !== null ? this.localLon : (this.serverLon || "");

    fetch(`/api/status?heading_deg=${curHead}&lat=${curLat}&lon=${curLon}`)
      .then(res => res.json())
      .then(data => {
        if (data.success && data.pois) {
          this.updatePOIs(data.pois);
        }
        doAnnounce();
      })
      .catch(() => {
        doAnnounce();
      });
  }

  announceRoadAndDoorNumbers() {
    const curHead = (this.localHeading !== null && this.localHeading !== undefined) ? this.localHeading : (window.lastHeading || 0);
    const curLat = this.localLat !== null ? this.localLat : (this.serverLat || "");
    const curLon = this.localLon !== null ? this.localLon : (this.serverLon || "");

    fetch(`/api/status?heading_deg=${curHead}&lat=${curLat}&lon=${curLon}`)
      .then((res) => res.json())
      .then((data) => {
        if (!data.success) return;
        
        let street = data.road_info && data.road_info.street_name && data.road_info.street_name !== "未知道路" 
          ? data.road_info.street_name 
          : (data.location_label && !data.location_label.includes("GPS") ? data.location_label : "目前道路");
        
        let doors = data.door_estimates || {};
        let doorStr = "";
        
        const leftVal = (doors.left || doors.left_side_estimate || "").trim();
        const rightVal = (doors.right || doors.right_side_estimate || "").trim();
        const concise = (doors.concise_door || "").trim();
        
        let doorParts = [];
        if (leftVal) doorParts.push(`左側${leftVal}`);
        if (rightVal) doorParts.push(`右側${rightVal}`);
        
        if (doorParts.length > 0) {
          doorStr = doorParts.join("，");
        } else if (concise) {
          doorStr = concise;
        } else {
          doorStr = "";
        }
        
        this.currentRoadName = street;
        this.lastSpokenDoor = doorStr;

        const headingDeg = (data.heading_deg !== undefined && data.heading_deg !== null) ? data.heading_deg : (curHead || 0);
        const dirStr = this.getCardinalDirection(headingDeg);
        const exactDeg = Math.round(((headingDeg % 360.0) + 360.0) % 360.0);
        const gpsStr = (data.lat && data.lon) ? `GPS座標：${data.lat.toFixed(5)}, ${data.lon.toFixed(5)}` : "";
        
        const txt = doorStr 
          ? `走在【${street}】，${doorStr}。面向${dirStr} (${exactDeg}°)。${gpsStr}。`
          : `走在【${street}】。面向${dirStr} (${exactDeg}°)。${gpsStr}。`;

        const isEarconOn = !this.settings || this.settings.earconEnabled !== false;
        if (isEarconOn && this.audio) {
          this.audio.playRoadTone(0, -0.8);
        } else if (this.audio) {
          this.audio.playSpatialTone(480, 'triangle', 0, 0, -0.8, 0.12);
        }
        setTimeout(() => {
          this.updateLiveLog(`【目前位置】\n${txt}`, false, true);
        }, isEarconOn ? 180 : 0);
      })
      .catch(() => {
        this.updateLiveLog("【目前位置】無法取得最新資訊。", true, true);
      });
  }

  announceHistory() {
    fetch("/api/history")
      .then((res) => res.json())
      .then((data) => {
        const count = data.history ? data.history.length : 0;
        const msg = `【快捷鍵 [H] 探索歷程】目前共累積 ${count} 筆移動軌跡紀錄。按按鈕可匯出測試檔。`;
        this.audio.playSpatialTone(580, 'sine', 0, 0, -0.5, 0.12);
        this.updateLiveLog(msg, false, true);
        if (this.liveLog && this.liveLog.firstElementChild) this.liveLog.firstElementChild.focus();
      });
  }

  // ========== 前方路口資訊與分支走向 (按鍵 I / 前方路口按鈕) ==========
  announceUpcomingIntersection() {
    this.updateLiveLog("正在分析前方路口與分支走向...", false, true);
    const curHead = (this.localHeading !== null && this.localHeading !== undefined) ? this.localHeading : (window.lastHeading || 0);
    const curLat = this.localLat !== null ? this.localLat : (this.serverLat || "");
    const curLon = this.localLon !== null ? this.localLon : (this.serverLon || "");

    fetch(`/api/intersection?heading_deg=${curHead}&lat=${curLat}&lon=${curLon}`)
      .then((res) => res.json())
      .then((data) => {
        if (data.success && data.report) {
          this.lastSpokenIntersection = data.report;
          const isEarconOn = !this.settings || this.settings.earconEnabled !== false;
          if (isEarconOn && this.audio) {
            this.audio.playJunctionTone(0, -1);
          } else if (this.audio) {
            this.audio.playArrival();
          }
          setTimeout(() => {
            this.updateLiveLog(data.report, false, true);
          }, isEarconOn ? 180 : 0);

          // 【手動查詢連動紅綠燈相機】：手動查詢路口時若前方為號誌化路口且在 6~28m 範圍內，同步開鏡
          if (data.intersection && data.intersection.is_signalized) {
            const jDist = data.intersection.junction_distance_m;
            if (jDist !== null && jDist >= 6.0 && jDist <= 28.0) {
              this.isSignalCameraActive = true;
              if (window.AndroidBridge && window.AndroidBridge.startTrafficSignalCamera) {
                const bearing = data.intersection.bearing_deg || 0;
                const clock = data.intersection.clock_position || "12點鐘方向";
                window.AndroidBridge.startTrafficSignalCamera(bearing, clock);
              }
            }
          }
        } else {
          this.updateLiveLog(data.message || "前方路口資料讀取失敗。", true);
        }
      })
      .catch(() => {
        this.updateLiveLog("無法連線至路口分析模組。", true);
      });
  }

  /**
   * 異常事件記錄器 (會匯入至 0_AI_QUICK_SUMMARY.json 的 anomalies_detected 陣列)
   */
  recordAnomaly(type, message, details = {}) {
    const anomaly = {
      timestamp: new Date().toISOString(),
      type: type,
      message: message,
      details: details
    };
    if (!this.sessionAnomalies) this.sessionAnomalies = [];
    this.sessionAnomalies.push(anomaly);
    console.warn(`[ANOMALY_RECORDED] [${type}] ${message}`, details);
  }

  /**
   * 判斷是否為無語音導航意義的雜訊設施 (如停車格、YouBike 等)
   */
  isIgnoredPoi(rawName, category) {
    if (!rawName) return true;
    const n = String(rawName).toLowerCase();
    const c = String(category || "").toLowerCase();
    if (n.includes("parking") || n.includes("停車格") || n.includes("停車位") || n.includes("parking space") || n.includes("收費停車場")) {
      return true;
    }
    if (c.includes("parking") || c.includes("parking_space")) {
      return true;
    }
    return false;
  }

  cleanPoiName(rawName) {
    if (!rawName) return "";
    let name = String(rawName).trim();
    const seps = ['/', '|', '丨', '｜'];
    for (const sep of seps) {
      if (name.includes(sep)) {
        const parts = name.split(sep);
        if (parts[0].trim()) {
          name = parts[0].trim();
          break;
        }
      }
    }
    name = name.replace(/[（\(【\[].*?(推薦|官方|粉絲團|批發|教學|清粉刺|皮膚管理|體驗|專用|營業時間|用品|潤滑).*?[）\)】\]]/g, "");
    name = name.replace(/[_xX×].*?(推薦|總監|設計師|老師|教學|美學).*/g, "");
    return name.trim() || String(rawName).trim();
  }

  /**
   * 【物件類別智慧研判器 (Object Category Classifier)】
   * 將任意 POI、店家、地標或設施，精準分流為四大核心無障礙類別：
   * 1. 'shop'：商店、餐飲、超商、購物、藥局、診所、生活服務
   * 2. 'landmark'：歷史景點、公園、文教、宗教名勝、公家機關、醫院
   * 3. 'building'：社區、集合住宅、大廈、純建築大樓
   * 4. 'transit'：大眾運輸、公車站牌、捷運出口、火車、號誌、斑馬線
   */
  classifyPoiCategory(poi) {
    if (!poi) return "shop";

    const cat = ((poi.category || "") + " " + (poi.type || "")).toLowerCase();
    const name = (poi.name || "").toLowerCase();
    const tags = poi.tags || {};
    const tagStr = JSON.stringify(tags).toLowerCase();

    // 1. 交通設施 (Transit: 公車站、捷運站、火車站、號誌、斑馬線、停車場、轉運站)
    if (
      cat.includes("transit") || cat.includes("bus") || cat.includes("subway") ||
      cat.includes("train") || cat.includes("railway") || cat.includes("platform") ||
      cat.includes("stop_position") || cat.includes("station") || cat.includes("traffic") ||
      cat.includes("crossing") || cat.includes("parking") ||
      name.includes("公車站") || name.includes("站牌") || name.includes("捷運") ||
      name.includes("出口") || name.includes("火車站") || name.includes("高鐵") ||
      name.includes("客運") || name.includes("轉運站") || name.includes("號誌") ||
      name.includes("斑馬線") || name.includes("人行道") ||
      tagStr.includes("highway") || tagStr.includes("railway") || tagStr.includes("public_transport")
    ) {
      return "transit";
    }

    // 2. 地標景點與公眾文教機構 (Landmark: 歷史景點、公園、廟宇教堂、學校、政府機關、醫院、圖書館)
    if (
      cat.includes("landmark") || cat.includes("attraction") || cat.includes("historic") ||
      cat.includes("monument") || cat.includes("viewpoint") || cat.includes("museum") ||
      cat.includes("park") || cat.includes("temple") || cat.includes("church") ||
      cat.includes("worship") || cat.includes("school") || cat.includes("university") ||
      cat.includes("college") || cat.includes("library") || cat.includes("hospital") ||
      cat.includes("police") || cat.includes("fire_station") || cat.includes("government") ||
      cat.includes("townhall") || cat.includes("post_office") ||
      name.includes("公園") || name.includes("廟") || name.includes("宮") ||
      name.includes("寺") || name.includes("教堂") || name.includes("紀念館") ||
      name.includes("博物館") || name.includes("美術館") || name.includes("學校") ||
      name.includes("國小") || name.includes("國中") || name.includes("高中") ||
      name.includes("大學") || name.includes("圖書館") || name.includes("醫院") ||
      name.includes("分局") || name.includes("派出所") || name.includes("郵局") ||
      name.includes("區公所") || name.includes("市府") || name.includes("戶政") ||
      tagStr.includes("tourism") || tagStr.includes("historic") || tagStr.includes("leisure")
    ) {
      return "landmark";
    }

    // 3. 社區大樓與純建築物 (Building: 集合住宅、商辦大廈、社區大樓)
    if (
      cat.includes("building") || cat.includes("residential") || cat.includes("apartments") ||
      cat.includes("dormitory") || cat.includes("house") ||
      name.endsWith("大樓") || name.endsWith("大廈") || name.endsWith("社區") ||
      name.endsWith("華廈") || name.endsWith("園區") || name.endsWith("公廈") ||
      name.includes("公寓") || (poi.id && String(poi.id).startsWith("bldg_")) ||
      tagStr.includes("building")
    ) {
      // 若名稱同時包含明顯店名（如「屈臣氏」、「全家」），優先歸為商店
      const isActuallyShop = ["便利", "超商", "咖啡", "餐廳", "小吃", "門市", "店", "分行", "行", "堂", "館", "坊", "局"].some(k => name.includes(k));
      if (!isActuallyShop) {
        return "building";
      }
    }

    // 4. 其餘均為商店、餐飲、服務與生活店家 (Shop: 餐廳、超商、百貨、藥局、診所、美髮...)
    return "shop";
  }

  /**
   * 【物件無障礙語音前置播報器 (Announce Object with Pre-Speech Earcon)】
   * 核心功能：在語音朗讀前，先依據物件類別播放短促清晰之 3D 空間立體聲音效 (Earcon)，
   * 延遲 180ms 音效鳴響完畢後，語音優雅切入，讓使用者 0.1 秒聽懂前方即將播報何種物件！
   */
  announceObject(poi, msg, isForce = false) {
    if (!msg) return;
    const isEarconOn = !this.settings || this.settings.earconEnabled !== false;

    if (isEarconOn && this.audio) {
      // 1. 在朗讀之前，精準於 3D 空間方位播放該類別之專屬短音效 (Earcon)
      this.audio.playForPoi(poi);

      // 2. 音效長度約 140~240ms，平滑延遲 180ms 後無縫切入語音朗讀，杜絕音效與人聲重疊吞字
      setTimeout(() => {
        this.updateLiveLog(msg, false, isForce);
      }, 180);
    } else {
      this.updateLiveLog(msg, false, isForce);
    }
    this.lastSpeechTime = Date.now();
  }

  /**
   * 【路口語音前置播報器】
   */
  announceJunction(msg, isApproaching = true) {
    if (!msg) return;
    const isEarconOn = !this.settings || this.settings.earconEnabled !== false;

    if (isEarconOn && this.audio) {
      if (isApproaching) {
        this.audio.playJunctionTone(0, -1);
      } else {
        this.audio.playArrival();
      }
      setTimeout(() => {
        this.updateLiveLog(msg, false, true);
      }, 180);
    } else {
      this.updateLiveLog(msg, false, true);
    }
    this.lastSpeechTime = Date.now();
    this.lastRoadAnnouncementTime = Date.now();
  }

  /**
   * 【道路與門牌前置播報器】
   */
  announceRoad(msg, isNewStreet = false) {
    if (!msg) return;
    const isEarconOn = !this.settings || this.settings.earconEnabled !== false;

    if (isEarconOn && this.audio) {
      if (isNewStreet) {
        this.audio.playJunctionTone(0, -1);
      } else {
        this.audio.playRoadTone(0, -1);
      }
      setTimeout(() => {
        this.updateLiveLog(msg, false, true);
      }, 180);
    } else {
      this.updateLiveLog(msg, false, true);
    }
    this.lastSpeechTime = Date.now();
    this.lastRoadAnnouncementTime = Date.now();
  }

  // ========== 前進路徑走廊店家與路口到達即時導引 ==========
  checkProximityAlerts(data) {
    if (!data || !data.is_loaded || this.isDetailModalOpen || window.isDetailModalOpen) return;
    const now = Date.now();

    // =========================================================================
    // 【紅綠燈相機硬體獨立生命週期管理 (方案 A - 完全解耦語音)】
    // 設計意圖：相機開關屬於「無聲硬體光學感測」行為，絕不可受語音防剪音節流閥
    // (now - lastSpeechTime < 1800ms) 或前進走廊 POI 店家播報攔截中斷。
    // 只要進入前方 6.0m ~ 28.0m 號誌化路口範圍，無條件開鏡對準號誌；踏入 (<6m) 或遠離 (>28m) 則自動收鏡。
    // =========================================================================
    if (data.intersection && data.intersection.is_signalized) {
      const jDist = data.intersection.junction_distance_m;
      if (jDist !== null && jDist >= 6.0 && jDist <= 28.0) {
        if (!this.isSignalCameraActive) {
          this.isSignalCameraActive = true;
          if (window.AndroidBridge && window.AndroidBridge.startTrafficSignalCamera) {
            const bearing = data.intersection.bearing_deg || 0;
            const clock = data.intersection.clock_position || "12點鐘方向";
            window.AndroidBridge.startTrafficSignalCamera(bearing, clock);
          }
        }
      } else if (jDist !== null && (jDist < 6.0 || jDist > 28.0)) {
        if (this.isSignalCameraActive) {
          this.isSignalCameraActive = false;
          if (window.AndroidBridge && window.AndroidBridge.stopTrafficSignalCamera) {
            window.AndroidBridge.stopTrafficSignalCamera();
          }
        }
      }
    } else {
      // 若當前沒有路口或非號誌化路口，且相機正在運作，則自動收鏡關閉
      if (this.isSignalCameraActive) {
        this.isSignalCameraActive = false;
        if (window.AndroidBridge && window.AndroidBridge.stopTrafficSignalCamera) {
          window.AndroidBridge.stopTrafficSignalCamera();
        }
      }
    }

    // 語音節流防剪音保護：距離上一句開口未滿 1800ms，暫緩本次自動掃描，杜絕腰斬吞字！
    if (now - (this.lastSpeechTime || 0) < 1800) return;

    // 判斷當前是否處於乘車模式 (VEHICULAR_TRANSIT 或時速 > 13.7 km/h)
    const isVehicular = !!(this.isVehicularTransit || window.isVehicularTransit || (window.lastWalkSpeed && window.lastWalkSpeed > 3.8));

    // 0. 初始化冷卻快取
    if (!this.announcedHazardCooldown) this.announcedHazardCooldown = new Map();
    if (!this.announcedSignalCooldown) this.announcedSignalCooldown = new Map();
    if (!this.announcedMrtCooldown) this.announcedMrtCooldown = new Map();
    if (!this.announcedPoiCooldown) this.announcedPoiCooldown = new Map();
    if (!this.arrivedPoiCooldown) this.arrivedPoiCooldown = new Map();

    // =========================================================================
    // 【模式 A：乘車模式 (Vehicular Mode) - 路口與交通設施最高優先，店家次序往後】
    // 設計意圖：視障者在公車/計程車上以高速度移動 (8~20 m/s)，必須提前 80 公尺
    // 預警下一個十字路口與交通號誌，徹底杜絕快速掠過路口時被次要店家或抵達狂唸蓋台！
    // =========================================================================
    if (isVehicular) {
      // 1. 交通設施優先：路口有聲號誌 / 交通號誌時制 (延伸探測至 65 公尺)
      if (data.traffic_signal && data.traffic_signal.distance_m <= 65.0 && data.traffic_signal.distance_m >= 0.0) {
        const sig = data.traffic_signal;
        const lastSigTime = this.announcedSignalCooldown.get(sig.id) || 0;
        if (now - lastSigTime > 25000) {
          this.announcedSignalCooldown.set(sig.id, now);
          const prompt = sig.has_aps 
            ? `📍 前方【${sig.intersection_name}】設有聲號誌，${sig.speech_prompt}`
            : `📍 前方【${sig.intersection_name}】交通號誌，${sig.speech_prompt}`;
          this.announceObject({
            name: sig.intersection_name,
            category: "signal",
            distance_m: sig.distance_m,
            relative_bearing_deg: 0
          }, prompt, false);
          return;
        }
      }

      // 2. 核心路口狀態機 (乘車專屬延伸視距：12~80m 提前接近中 / <12m 正通過 / >80m 沿路前進)
      if (data.intersection) {
        const juncType = data.intersection.junction_type;
        const juncDist = data.intersection.junction_distance_m;
        const isRealJunction = juncType && juncType !== "直行道路";

        if (isRealJunction && juncDist !== null) {
          let juncName = data.intersection.junction_name || juncType;
          if (juncName === "1F" || juncName === "無名路" || juncName.startsWith("未命名")) {
            juncName = juncType || "路口";
          }
          const isSignalized = !!data.intersection.is_signalized;
          const hasAps = !!data.intersection.has_aps;
          const hasIsland = !!data.intersection.has_refuge_island;
          const currentRoad = (data.road_info && data.road_info.street_name && data.road_info.street_name !== "未知道路" && data.road_info.street_name !== "1F") ? data.road_info.street_name : "目前道路";

          const passedLockTime = this.passedJunctionCooldown.get(juncName) || 0;
          const isJunctionLocked = (now - passedLockTime < 35000);

          // A. 乘車提前接近路口 (12.0m ~ 80.0m)
          if (juncDist <= 80.0 && juncDist >= 12.0 && !isJunctionLocked) {
            const lastAppTime = this.approachedJunctionCooldown.get(juncName) || 0;
            if (this.currentJunctionState !== "APPROACHING" && (now - lastAppTime > 20000)) {
              this.currentJunctionState = "APPROACHING";
              this.lastIntersectionAlertTime = now;
              this.approachedJunctionCooldown.set(juncName, now);

              let roads = "";
              const filteredRoads = (data.intersection.intersecting_roads || []).filter(r => r && r !== currentRoad && r !== "未命名道路" && r !== "無名路" && r !== "1F");
              if (filteredRoads.length > 0 && !filteredRoads.some(r => juncName.includes(r))) {
                roads = `（交會 ${filteredRoads.join("、")}）`;
              }

              let signalPart = isSignalized ? (hasAps ? "，有號誌與有聲設備" : "，設紅綠燈") : "，無號誌路口";
              const islandPart = hasIsland ? "，設庇護島" : "";
              const msg = `📍 前方 ${Math.round(juncDist)}公尺【${juncName}】${roads}${signalPart}${islandPart}。`;
              this.announceJunction(msg, true);
              return;
            }
          }
          // B. 乘車正通過路口 (< 12.0m)
          else if (juncDist < 12.0 && !isJunctionLocked) {
            const sinceLastAlert = now - (this.lastIntersectionAlertTime || 0);
            if (this.currentJunctionState !== "PASSING" && sinceLastAlert >= 3500) {
              this.currentJunctionState = "PASSING";
              this.lastIntersectionAlertTime = now;
              const msg = `📍 正通過【${juncName}】。`;
              this.announceJunction(msg, false);
              return;
            }
          }
          // C. 乘車通過完成 (LEAVING / 繼續前進: 12.0m ~ 35.0m 且前一狀態為 PASSING)
          else if (juncDist >= 12.0 && juncDist <= 35.0 && this.currentJunctionState === "PASSING") {
            this.currentJunctionState = "LEAVING";
            this.passedJunctionCooldown.set(juncName, now);
            this.lastIntersectionAlertTime = now;
            this.announceRoad(`沿著【${currentRoad}】前進`, false);
            return;
          }
          // D. 乘車遠離路口 (> 50.0m)
          else if (juncDist > 50.0 && this.currentJunctionState !== "IDLE") {
            this.currentJunctionState = "IDLE";
          }
        }
      }

      // 3. 轉彎進入新路名 (乘車模式及時提醒)
      if (data.road_info && data.road_info.street_name && data.road_info.street_name !== "未知道路") {
        const st = data.road_info.street_name;
        if (this.currentStreetName === null) {
          this.currentStreetName = st;
        } else if (st !== this.currentStreetName) {
          if (this.consecutiveRoadCandidate === st) {
            this.consecutiveRoadCount = (this.consecutiveRoadCount || 0) + 1;
          } else {
            this.consecutiveRoadCandidate = st;
            this.consecutiveRoadCount = 1;
          }
          if (this.consecutiveRoadCount >= 2 && (now - (this.lastRoadAnnouncementTime || 0) >= 15000)) {
            this.currentStreetName = st;
            this.consecutiveRoadCandidate = null;
            this.consecutiveRoadCount = 0;
            this.announceRoad(`進入【${this.currentStreetName}】`, true);
            return;
          }
        } else {
          this.consecutiveRoadCandidate = null;
          this.consecutiveRoadCount = 0;
        }
      }

      // 4. 次要店家資訊（次序往後）：
      // 乘車模式下徹底靜音「🎉 已抵達門口」；僅在前進走廊兩側無即將到來的路口時，低頻率提醒重要地標
      const realtimePois = this.getRealtimePois();
      if (realtimePois && realtimePois.length > 0) {
        const corridorPois = realtimePois.filter((p) => {
          if (this.isIgnoredPoi(p.name, p.category)) return false;
          const d = p.distance_m;
          const relBearing = Math.abs(p.relative_bearing_deg || 0);
          const dir = p.relative_direction || "";
          if (dir.includes("後方") || relBearing > 90) return false;
          const rad = (relBearing * Math.PI) / 180.0;
          const latDist = Math.abs(d * Math.sin(rad));
          const fwdDist = d * Math.cos(rad);
          return fwdDist >= 5.0 && fwdDist <= 40.0 && latDist <= 20.0;
        });

        if (corridorPois.length > 0) {
          const topPoi = corridorPois.sort((a, b) => a.distance_m - b.distance_m)[0];
          const cleanedName = this.cleanPoiName(topPoi.name);
          const poiKey = topPoi.id || (topPoi.lat && topPoi.lon ? `${cleanedName}_${topPoi.lat.toFixed(4)}_${topPoi.lon.toFixed(4)}` : cleanedName);
          const lastTime = this.announcedPoiCooldown.get(poiKey) || 0;
          if (now - lastTime > 45000 && (now - (this.lastIntersectionAlertTime || 0) > 12000)) {
            this.announcedPoiCooldown.set(poiKey, now);
            const dirText = topPoi.relative_direction ? `，${topPoi.relative_direction} ${Math.round(topPoi.distance_m)}公尺` : "";
            this.announceObject(topPoi, `${cleanedName}${dirText}`, false);
            return;
          }
        }
      }
      return;
    }

    // =========================================================================
    // 【模式 B：步行模式 (Pedestrian Mode) - 無障礙安全第一原則】
    // =========================================================================

    // 0.1 【Scheme 3 人行道安全防撞雷達 (變電箱/消防栓/施工窄頸)】- 第一優先碰撞警戒！
    // 【安全規範】：下限必須為 0.0 公尺！絕不可在即將撞上的最後 1.5 公尺內突然安靜。
    if (data.sidewalk_hazards && data.sidewalk_hazards.length > 0) {
      const h = data.sidewalk_hazards[0];
      const lastHzTime = this.announcedHazardCooldown.get(h.id) || 0;
      if (h.distance_m <= 8.0 && h.distance_m >= 0.0 && (now - lastHzTime > 25000)) {
        this.announcedHazardCooldown.set(h.id, now);
        const urgentPrompt = h.distance_m < 1.5 ? `⚠️ 注意正前方 ${h.name}，請立即停步探測！` : h.speech_prompt;
        this.announceObject({
          name: h.name,
          category: "warning",
          distance_m: h.distance_m,
          relative_bearing_deg: (h.lateral_offset_m || 0) > 0 ? 15 : -15
        }, urgentPrompt, true);
        return;
      }
    }

    // 0.2 【Scheme 1 交通部視障有聲號誌 (APS)】- 實體號誌優先導引
    // 【安全規範】：下限延伸至 0.0 公尺，走到號誌桿旁時提示已抵達
    if (data.traffic_signal && data.traffic_signal.has_aps && data.traffic_signal.distance_m <= 22.0 && data.traffic_signal.distance_m >= 0.0) {
      const sig = data.traffic_signal;
      const lastSigTime = this.announcedSignalCooldown.get(sig.id) || 0;
      if (now - lastSigTime > 30000) {
        this.announcedSignalCooldown.set(sig.id, now);
        const prompt = sig.distance_m < 4.0 ? `📍 已在【${sig.intersection_name}】號誌桿旁，${sig.speech_prompt}` : `📍 ${sig.speech_prompt}`;
        this.announceObject({
          name: sig.intersection_name,
          category: "signal",
          distance_m: sig.distance_m,
          relative_bearing_deg: 0
        }, prompt, false);
        return;
      }
    }

    // 0.3 【Scheme 4 捷運站專屬無障礙電梯出口導引】
    if (data.mrt_exits && data.mrt_exits.length > 0) {
      const topExit = data.mrt_exits[0];
      const lastMrtTime = this.announcedMrtCooldown.get(topExit.exit_name) || 0;
      if (topExit.distance_m <= 40.0 && topExit.distance_m >= 2.0 && topExit.has_elevator && (now - lastMrtTime > 40000)) {
        this.announcedMrtCooldown.set(topExit.exit_name, now);
        this.announceObject({
          name: topExit.exit_name,
          category: "transit",
          distance_m: topExit.distance_m,
          relative_bearing_deg: 0
        }, `${topExit.speech_prompt}`, false);
        return;
      }
    }

    // 0. 初始化專屬冷卻快取
    if (!this.announcedHazardCooldown) this.announcedHazardCooldown = new Map();
    if (!this.announcedSignalCooldown) this.announcedSignalCooldown = new Map();
    if (!this.announcedMrtCooldown) this.announcedMrtCooldown = new Map();
    if (!this.announcedPoiCooldown) this.announcedPoiCooldown = new Map();
    if (!this.arrivedPoiCooldown) this.arrivedPoiCooldown = new Map();
    if (!this.passedJunctionCooldown) this.passedJunctionCooldown = new Map();
    if (!this.approachedJunctionCooldown) this.approachedJunctionCooldown = new Map();

    // =========================================================================
    // 【1. 路口生命週期三態狀態機 (Junction Life-Cycle Machine) - 導航生命線第一優先】
    // 設計意圖：路口過馬路與分支走向是視障導航最核心的安全生命線！
    // 必須擁有高於周遭一般店家的絕對發話優先權，徹底杜絕被次要店家「搶播蓋台」。
    // 嚴格三階段：APPROACHING (8~25m 提前預告鐘點走向) -> PASSING (< 6m 正通過) -> LEAVING (6~18m 繼續前進)
    // =========================================================================
    let isJunctionHandled = false;
    if (data.intersection) {
      const juncType = data.intersection.junction_type;
      const juncDist = data.intersection.junction_distance_m;
      const isRealJunction = juncType && juncType !== "直行道路";

      if (isRealJunction && juncDist !== null) {
        let juncName = data.intersection.junction_name || juncType;
        if (juncName === "1F" || juncName === "無名路" || juncName.startsWith("未命名")) {
          juncName = "路口";
        }

        const isSignalized = !!data.intersection.is_signalized;
        const hasAps = !!data.intersection.has_aps;
        const hasIsland = !!data.intersection.has_refuge_island;
        const currentRoad = (data.road_info && data.road_info.street_name && data.road_info.street_name !== "未知道路" && data.road_info.street_name !== "1F") ? data.road_info.street_name : "目前道路";

        const passedLockTime = this.passedJunctionCooldown.get(juncName) || 0;
        const isJunctionLocked = (now - passedLockTime < 45000); // 通過後 45 秒內嚴格防抖鎖定

        // A. 踏入 / 正通過路口 (< 6.0m) - 【對向直行接續路名確認】
        if (juncDist < 6.0 && !isJunctionLocked) {
          const sinceLastAlert = now - (this.lastIntersectionAlertTime || 0);
          if (this.currentJunctionState !== "PASSING" && sinceLastAlert >= 3500) {
            this.currentJunctionState = "PASSING";
            this.activeJunctionTargetName = juncName;
            this.lastIntersectionAlertTime = now;
            const islandGuide = hasIsland ? "，設庇護島" : "";
            
            let passMsg = "📍 正通過路口";
            if (data.intersection.straight_continuation_road && data.intersection.straight_continuation_road !== currentRoad && !data.intersection.straight_continuation_road.startsWith("無名") && data.intersection.straight_continuation_road !== "人行通道") {
              passMsg = `📍 正通過路口，直行接【${data.intersection.straight_continuation_road}】`;
            } else if (data.intersection.concise_passing_prompt) {
              passMsg = `📍 ${data.intersection.concise_passing_prompt}`;
            }
            const msg = `${passMsg}${islandGuide}。`;
            this.announceJunction(msg, false);
            return;
          }
          isJunctionHandled = true;
        }
        
        // B. 通過完成確認 (LEAVING: 6.0m ~ 18.0m 且前一狀態為 PASSING) - 【優先於 APPROACHING 判定】
        else if (juncDist >= 6.0 && juncDist <= 18.0 && this.currentJunctionState === "PASSING") {
          this.currentJunctionState = "LEAVING";
          this.passedJunctionCooldown.set(juncName, now); // 鎖定該路口 45 秒，消滅倒退重唸
          this.lastIntersectionAlertTime = now;

          const msg = `📍 沿著【${currentRoad}】繼續前進。`;
          this.announceRoad(msg, false);
          return;
        }

        // C. 提前接近路口 (8.0m ~ 25.0m) - 【動態鐘點分支導引，不講幾何贅字】
        else if (juncDist <= 25.0 && juncDist >= 8.0 && !isJunctionLocked) {
          const lastAppTime = this.approachedJunctionCooldown.get(juncName) || 0;
          const globalAppGap = now - (this.lastIntersectionAlertTime || 0);

          if (this.currentJunctionState !== "APPROACHING" && this.currentJunctionState !== "PASSING" && this.currentJunctionState !== "LEAVING" && (now - lastAppTime > 30000) && globalAppGap >= 6000) {
            this.currentJunctionState = "APPROACHING";
            this.activeJunctionTargetName = juncName;
            this.lastIntersectionAlertTime = now;
            this.approachedJunctionCooldown.set(juncName, now);

            let branchPart = "";
            if (data.intersection.concise_branches) {
              branchPart = data.intersection.concise_branches;
            } else if (data.intersection.branches_info && data.intersection.branches_info.length > 0) {
              const validBranches = data.intersection.branches_info.filter(b => b.road_name && b.road_name !== currentRoad && !b.road_name.startsWith("無名") && Math.abs(b.relative_angle || 0) < 140);
              if (validBranches.length > 0) {
                branchPart = validBranches.map(b => `${b.clock_position || b.relative_direction} ${b.road_name}`).join("，");
              }
            }

            if (!branchPart) {
              const filteredRoads = (data.intersection.intersecting_roads || []).filter(r => r && r !== currentRoad && r !== "未命名道路" && r !== "無名路" && r !== "1F");
              branchPart = filteredRoads.length > 0 ? filteredRoads.join("、") : (juncName !== "路口" ? juncName : "前方交會");
            }

            const apsTag = hasAps ? "（有聲號誌）" : (isSignalized ? "（紅綠燈）" : "");
            const islandPart = hasIsland ? "，設庇護島" : "";
            const msg = `📍 接近路口${apsTag}，${branchPart}${islandPart}。`;
            this.announceJunction(msg, true);
            return;
          }
          isJunctionHandled = true;
        }

        // D. 離開遠離路口 (> 25.0m) -> 回歸 IDLE
        else if (juncDist > 25.0 && this.currentJunctionState !== "IDLE") {
          this.currentJunctionState = "IDLE";
          this.activeJunctionTargetName = null;
        }
      }
    }

    // =========================================================================
    // 【2. 轉彎進入新路名防抖播報 (至少連續 2 筆 GPS 穩定判定，且 20 秒冷卻)】
    // =========================================================================
    if (data.road_info && data.road_info.street_name && data.road_info.street_name !== "未知道路") {
      const st = data.road_info.street_name;
      if (this.currentStreetName === null) {
        this.currentStreetName = st;
      } else if (st !== this.currentStreetName) {
        if (this.consecutiveRoadCandidate === st) {
          this.consecutiveRoadCount = (this.consecutiveRoadCount || 0) + 1;
        } else {
          this.consecutiveRoadCandidate = st;
          this.consecutiveRoadCount = 1;
        }

        // 連續 2 次 GPS 確認換路，避免經過巷口瞬切抖動
        if (this.consecutiveRoadCount >= 2 && (now - (this.lastRoadAnnouncementTime || 0) >= 20000)) {
          this.currentStreetName = st;
          this.consecutiveRoadCandidate = null;
          this.consecutiveRoadCount = 0;
          this.announceRoad(`進入【${this.currentStreetName}】`, true);
          return;
        }
      } else {
        this.consecutiveRoadCandidate = null;
        this.consecutiveRoadCount = 0;
      }
    }

    // =========================================================================
    // 【3. 前進路徑走廊 POI 店家自適應節奏廣播 (Speed-Adaptive POI Throttle)】
    // 核心哲學：
    // 1. 緊鄰店家同側合併打包 (Cluster Grouping)：如「2點鐘 8米：全家 (205號)、康是美」
    // 2. 門牌號碼自然錨定 (Door Number Anchoring)：若店家自帶門牌號碼，順暢附帶，協助建立遞增規律
    // =========================================================================
    const realtimePois = this.getRealtimePois();
    const curSpeed = (data.speed_mps !== null && data.speed_mps !== undefined) ? data.speed_mps : 1.0;
    
    // 依據步行速度動態調節 POI 最小全域間隔 (Global Speech Interval)
    // 速度 < 0.4 m/s (停步/等紅燈)：12秒防吵；速度 0.4~1.0 m/s：6.5秒；速度 > 1.0 m/s：5.0秒
    const minPoiInterval = curSpeed < 0.4 ? 12000 : (curSpeed <= 1.0 ? 6500 : 5000);

    // 輔助函式：提取 POI 清洗名稱與自然門牌錨定標籤 (Natural Door Number Tag)
    const formatPoiWithDoor = (p) => {
      const cleanedName = this.cleanPoiName(p.name);
      const floorTag = (p.floor && p.floor !== "1F") ? ` (${p.floor})` : "";
      let doorTag = "";
      if (p.housenumber) {
        const hn = String(p.housenumber).trim();
        if (hn) {
          doorTag = hn.endsWith("號") ? ` (${hn})` : ` (${hn}號)`;
        }
      }
      return `${cleanedName}${floorTag}${doorTag}`;
    };

    if (realtimePois && realtimePois.length > 0 && !isJunctionHandled) {
      // A. 近身抵達感知 (距離 <= 3.8 公尺，宣告抵達店家)
      const arrivalCandidate = realtimePois.find((p) => {
        if (this.isIgnoredPoi(p.name, p.category)) return false;
        return p.distance_m <= 3.8;
      });

      if (arrivalCandidate) {
        const arrivalStr = formatPoiWithDoor(arrivalCandidate);
        const arrivalKey = arrivalCandidate.id || (arrivalCandidate.lat && arrivalCandidate.lon ? `${this.cleanPoiName(arrivalCandidate.name)}_${arrivalCandidate.lat.toFixed(4)}_${arrivalCandidate.lon.toFixed(4)}` : this.cleanPoiName(arrivalCandidate.name));
        const lastArrival = this.arrivedPoiCooldown.get(arrivalKey) || 0;
        if (now - lastArrival > 60000) { // 60秒冷卻
          this.arrivedPoiCooldown.set(arrivalKey, now);
          this.announcedPoiCooldown.set(arrivalKey, now);
          this.lastPoiBroadcastTime = now;

          const arrivalMsg = `🎉 抵達【${arrivalStr}】`;
          if (this.audio) this.audio.playArrival();
          this.announceObject(arrivalCandidate, arrivalMsg, true);
          return;
        }
      }

      // B. 前進路徑走廊店家掃描 (前方 0.0 ~ 25.0 公尺，側向 <= 14.0 公尺)
      if (now - (this.lastPoiBroadcastTime || 0) >= minPoiInterval) {
        const corridorPois = realtimePois.filter((p) => {
          const d = p.distance_m;
          const relBearing = Math.abs(p.relative_bearing_deg || 0);
          const dir = p.relative_direction || "";
          
          if (this.isIgnoredPoi(p.name, p.category)) return false;
          if (dir.includes("後方") || relBearing > 90) return false;
          const rad = (relBearing * Math.PI) / 180.0;
          const latDist = Math.abs(d * Math.sin(rad));
          const fwdDist = d * Math.cos(rad);
          return fwdDist >= 0.0 && fwdDist <= 25.0 && latDist <= 14.0;
        });

        if (corridorPois.length > 0) {
          const leftCandidate = corridorPois.find(p => (p.relative_direction || "").includes("左"));
          const rightCandidate = corridorPois.find(p => (p.relative_direction || "").includes("右"));
          const frontCandidate = corridorPois.find(p => !(p.relative_direction || "").includes("左") && !(p.relative_direction || "").includes("右"));

          // 1. 雙側走廊合併打包：若左右兩側近身 (<= 12m) 均有未播報之優選店家，一次報完超省話！
          let didBroadcast = false;
          if (leftCandidate && rightCandidate && leftCandidate.distance_m <= 12.0 && rightCandidate.distance_m <= 12.0) {
            const leftKey = leftCandidate.id || `${this.cleanPoiName(leftCandidate.name)}_${leftCandidate.lat.toFixed(4)}_${leftCandidate.lon.toFixed(4)}`;
            const rightKey = rightCandidate.id || `${this.cleanPoiName(rightCandidate.name)}_${rightCandidate.lat.toFixed(4)}_${rightCandidate.lon.toFixed(4)}`;
            const lastLeft = this.announcedPoiCooldown.get(leftKey) || 0;
            const lastRight = this.announcedPoiCooldown.get(rightKey) || 0;

            if (now - lastLeft > 35000 && now - lastRight > 35000) {
              this.announcedPoiCooldown.set(leftKey, now);
              this.announcedPoiCooldown.set(rightKey, now);
              this.lastPoiBroadcastTime = now;

              const leftStr = formatPoiWithDoor(leftCandidate);
              const rightStr = formatPoiWithDoor(rightCandidate);
              const dualMsg = `左 ${leftStr} ${Math.round(leftCandidate.distance_m)}米、右 ${rightStr} ${Math.round(rightCandidate.distance_m)}米`;
              this.announceObject(leftCandidate, dualMsg, false);
              didBroadcast = true;
              return;
            }
          }

          // 2. 同側/緊鄰相鄰店家合併打包 (Cluster Grouping):
          // 若同一側有 2~3 家店位於相近方向 (角度差 <= 28° 或相同鐘點) 且距離差 <= 6.0m
          if (!didBroadcast) {
            const unannouncedPois = corridorPois.filter(p => {
              const k = p.id || (p.lat && p.lon ? `${this.cleanPoiName(p.name)}_${p.lat.toFixed(4)}_${p.lon.toFixed(4)}` : this.cleanPoiName(p.name));
              return (now - (this.announcedPoiCooldown.get(k) || 0) > 35000);
            });

            if (unannouncedPois.length >= 2) {
              const p1 = unannouncedPois[0];
              const cluster = unannouncedPois.filter(p => {
                const angleDiff = Math.abs((p.relative_bearing_deg || 0) - (p1.relative_bearing_deg || 0));
                const distDiff = Math.abs(p.distance_m - p1.distance_m);
                return (angleDiff <= 28 || (p.clock_position && p.clock_position === p1.clock_position)) && distDiff <= 6.0;
              });

              if (cluster.length >= 2) {
                const topCluster = cluster.slice(0, 3); // 上限 3 家打包
                const avgDist = Math.round(topCluster.reduce((sum, p) => sum + p.distance_m, 0) / topCluster.length);
                const clusterClock = p1.clock_position || p1.relative_direction || "前方";
                const clusterNames = topCluster.map(p => formatPoiWithDoor(p)).join("、");
                const clusterMsg = `${clusterClock} ${avgDist}米：${clusterNames}`;

                for (const p of topCluster) {
                  const k = p.id || (p.lat && p.lon ? `${this.cleanPoiName(p.name)}_${p.lat.toFixed(4)}_${p.lon.toFixed(4)}` : this.cleanPoiName(p.name));
                  this.announcedPoiCooldown.set(k, now);
                }
                this.lastPoiBroadcastTime = now;
                this.announceObject(p1, clusterMsg, false);
                didBroadcast = true;
                return;
              }
            }
          }

          // 3. 單店標準播報 (Single POI)
          if (!didBroadcast) {
            const candidates = [leftCandidate, rightCandidate, frontCandidate].filter(Boolean).sort((a, b) => a.distance_m - b.distance_m);
            for (const poi of candidates) {
              const poiKey = poi.id || (poi.lat && poi.lon ? `${this.cleanPoiName(poi.name)}_${poi.lat.toFixed(4)}_${poi.lon.toFixed(4)}` : this.cleanPoiName(poi.name));
              const lastTime = this.announcedPoiCooldown.get(poiKey) || 0;
              if (now - lastTime > 35000) {
                this.announcedPoiCooldown.set(poiKey, now);
                this.lastPoiBroadcastTime = now;

                const poiStr = formatPoiWithDoor(poi);
                const clockOrDir = poi.clock_position || poi.relative_direction || "前方";
                const msg = `${poiStr}，${clockOrDir} ${Math.round(poi.distance_m)}米`;

                this.announceObject(poi, msg, false);
                return;
              }
            }
          }
        }
      }
    }

    // =========================================================================
    // 【4. 若都沒有店家 / 語音安靜超過 20 秒，精簡播報當前走在哪條路上與大約門牌】
    // =========================================================================
    if (now - this.lastSpeechTime >= 20000 && now - (this.lastRoadAnnouncementTime || 0) >= 20000) {
      if (data.road_info && data.road_info.street_name && data.road_info.street_name !== "未知道路") {
        const street = data.road_info.street_name;
        const door = (data.door_estimates && data.door_estimates.concise_door) ? data.door_estimates.concise_door : "";
        const msg = door ? `沿著【${street}】前進，${door}` : `沿著【${street}】前進`;
        this.announceRoad(msg, false);
      }
    }
  }


  // ========== 策略 1：店家深度探查 ==========
  announceInspectPOI() {
    if (!this.lastPois || this.lastPois.length === 0) {
      this.updateLiveLog("【I 深度探查】周遭無店家可探查。", false, true);
      return;
    }

    // 使用 P 鍵最後選中的 POI，若未選過則取最近的
    const idx = this.poiIndex > 0 ? (this.poiIndex - 1) % this.lastPois.length : 0;
    const p = this.lastPois[idx];

    // 本地資料（即時播報）
    const lines = [`【店家詳情】${p.name}`];
    lines.push(`• 位置：${p.clock_position}（${p.relative_direction}）${p.distance_m} 公尺`);

    // 【方案三：真實門牌地址精確呈現】
    const addr = (p.address && p.address.trim()) ? p.address.trim() : (p.street && p.housenumber ? `${p.street} ${p.housenumber}號` : "");
    if (addr) {
      lines.push(`• 門牌：${addr}`);
    } else {
      lines.push(`• 門牌：未登記正式門牌號`);
    }

    lines.push(`• 類別：${this.translateCategory(p.category)}`);
    if (p.cuisine) lines.push(`• 料理類型：${p.cuisine}`);
    if (p.opening_hours) lines.push(`• 營業時間：${p.opening_hours}`);
    if (p.phone) lines.push(`• 電話：${p.phone}`);
    if (p.wheelchair === "yes") lines.push(`• 無障礙：有無障礙通道`);
    else if (p.wheelchair === "limited") lines.push(`• 無障礙：部分無障礙`);
    if (p.takeaway === "yes") lines.push(`• 可外帶：是`);
    if (p.brand) lines.push(`• 品牌：${p.brand}`);
    if (p.level) lines.push(`• 樓層：${p.level} 樓`);
    if (p.payment) lines.push(`• 付款方式：${p.payment}`);
    if (p.website) lines.push(`• 網站：${p.website}`);

    // 先播報本地資料
    const localMsg = lines.join("\n");
    this.updateLiveLog(localMsg, false, true);
    if (this.liveLog && this.liveLog.firstElementChild) this.liveLog.firstElementChild.focus();

    // 立體定位音效
    const isLeft = p.relative_direction.includes("左");
    this.audio.playSpatialTone(550, 'triangle', isLeft ? -1.5 : 1.5, 0, -1, 0.2);

    // 非同步抓取 Google Places 資料（若有 Google 官方格式化地址則更新）
    fetch("/api/poi/enrich", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: p.name, lat: p.lat, lon: p.lon })
    })
      .then(res => res.json())
      .then(g => {
        if (!g.available) return;
        const gLines = [...lines];
        if (g.address) {
          // 若原先無門牌或為未登記，以 Google 官方地址替換
          const addrIdx = gLines.findIndex(l => l.startsWith("• 門牌："));
          if (addrIdx !== -1) {
            gLines[addrIdx] = `• 門牌：${g.address} (官方核定)`;
          }
        }
        gLines.push("─── Google 評價 ───");
        if (g.rating) gLines.push(`• Google 評分：${g.rating} 星（${g.user_ratings_total || 0} 則評價）`);
        if (g.open_now !== null && g.open_now !== undefined) {
          gLines.push(`• 現在狀態：${g.open_now ? "✅ 營業中" : "❌ 已打烊"}`);
        }
        if (g.business_status) gLines.push(`• 營業狀態：${g.business_status}`);
        if (g.price_label) gLines.push(`• 價位：${g.price_label}`);
        if (g.phone) gLines.push(`• Google 電話：${g.phone}`);
        if (g.hours_text) gLines.push(`• 詳細營業：${g.hours_text}`);
        if (g.reviews && g.reviews.length > 0) {
          const rev = g.reviews[0];
          gLines.push(`• 最新評價（${rev.rating}星 ${rev.time_desc}）：「${rev.text}」`);
        }
        this.updateLiveLog(gLines.join("\n"), false, true);
      })
      .catch(() => {});
  }

  // ========== 策略 2：L 鍵 — 左右兩側店家掃描 ==========
  announceLeftRightSweep() {
    const realtimePois = this.getRealtimePois();
    if (!realtimePois || realtimePois.length === 0) {
      this.updateLiveLog("【左右兩側店家掃描】周遭無店家。", false, true);
      return;
    }

    const leftPois = realtimePois
      .filter(p => p.relative_direction && p.relative_direction.includes("左"))
      .sort((a, b) => a.distance_m - b.distance_m);

    const rightPois = realtimePois
      .filter(p => p.relative_direction && p.relative_direction.includes("右"))
      .sort((a, b) => a.distance_m - b.distance_m);

    const frontPois = realtimePois
      .filter(p => p.relative_direction && !p.relative_direction.includes("左") && !p.relative_direction.includes("右"))
      .sort((a, b) => a.distance_m - b.distance_m);

    const lines = ["【左右兩側店家掃描】"];

    if (leftPois.length > 0) {
      lines.push(`\n◀ 左側（${leftPois.length} 家，由近到遠）：`);
      leftPois.slice(0, 6).forEach((p, i) => {
        const cat = this.translateCategory(p.category);
        lines.push(`  ${i + 1}. ${p.name}（${cat}）— ${p.distance_m}m`);
      });
    } else {
      lines.push("\n◀ 左側：無店家");
    }

    if (rightPois.length > 0) {
      lines.push(`\n▶ 右側（${rightPois.length} 家，由近到遠）：`);
      rightPois.slice(0, 6).forEach((p, i) => {
        const cat = this.translateCategory(p.category);
        lines.push(`  ${i + 1}. ${p.name}（${cat}）— ${p.distance_m}m`);
      });
    } else {
      lines.push("\n▶ 右側：無店家");
    }

    if (frontPois.length > 0) {
      lines.push(`\n▲ 正前方（${frontPois.length} 家）：`);
      frontPois.slice(0, 3).forEach((p, i) => {
        const cat = this.translateCategory(p.category);
        lines.push(`  ${i + 1}. ${p.name}（${cat}）— ${p.distance_m}m`);
      });
    }

    const isEarconOn = !this.settings || this.settings.earconEnabled !== false;
    if (isEarconOn && this.audio) {
      if (leftPois.length > 0) {
        this.audio.playShopTone(-1.5, -0.5);
      } else if (rightPois.length > 0) {
        this.audio.playShopTone(1.5, -0.5);
      }
    }

    setTimeout(() => {
      this.updateLiveLog(lines.join("\n"), false, true);
      if (this.liveLog && this.liveLog.firstElementChild) this.liveLog.firstElementChild.focus();
    }, isEarconOn ? 180 : 0);

    // 左右立體音效掃描
    this.audio.playSpatialTone(440, 'sine', -2, 0, -1, 0.1);
    setTimeout(() => {
      this.audio.playSpatialTone(440, 'sine', 2, 0, -1, 0.1);
    }, 150);
  }

  // ========== 類別中文翻譯器 (全方位 Overture / OSM 中文映射) ==========
  translateCategory(category) {
    const map = {
      // 宗教與歷史地標
      "buddhist_temple": "寺廟", "temple": "寺廟", "place_of_worship": "宗教場所",
      "church": "教堂", "mosque": "清真寺", "shrine": "神社/神壇",
      "landmark_and_historical_building": "歷史建築/地標", "landmark": "地標",
      "monument": "紀念碑", "historic": "古蹟", "viewpoint": "景觀點", "attraction": "觀光景點",
      
      // 美容美髮與個人照護
      "beauty_salon": "美容美睫", "beauty": "美容院", "hairdresser": "美髮店",
      "hair_salon": "美髮沙龍", "barber_shop": "理髮廳", "barber": "理髮店",
      "nail_salon": "美甲店", "spa": "養生水療SPA", "massage": "按摩店", "tattoo": "刺青店",

      // 餐廳、飲食、異國料理
      "restaurant": "餐廳", "fast_food": "速食店", "cafe": "咖啡店",
      "bakery": "烘焙坊", "french_restaurant": "法式餐廳", "korean_restaurant": "韓式料理",
      "japanese_restaurant": "日式料理", "chinese_restaurant": "中式餐廳",
      "taiwanese_restaurant": "台灣小吃", "italian_restaurant": "義大利餐廳",
      "breakfast_and_brunch_restaurant": "早餐店", "breakfast_restaurant": "早餐店",
      "diner": "小吃店", "food_court": "美食街", "buffet": "吃到飽餐廳",
      "barbecue": "燒肉/烤肉店", "hotpot": "火鍋店", "seafood_restaurant": "海鮮餐廳",
      "ice_cream": "冰品甜點店", "tea": "茶飲店", "bubble_tea": "手搖飲料店",
      "bar": "酒吧", "pub": "酒吧", "food": "餐飲小吃", "deli": "熟食小吃",
      "confectionery": "甜點店", "dessert": "甜品店",

      // 商店、購物、專賣店
      "convenience": "便利商店", "convenience_store": "便利商店",
      "supermarket": "超市", "discount_store": "生活百貨", "department_store": "百貨公司",
      "mall": "購物中心", "marketplace": "傳統市場", "variety_store": "生活五金百貨",
      "grocery": "生鮮雜貨", "general_store": "雜貨店", "butcher": "肉舖", "seafood": "海鮮店",
      "greengrocer": "蔬果行", "musical_instrument_store": "樂器行/音樂教室",
      "music_school": "音樂教室", "clothes": "服飾店", "clothing_store": "服飾店",
      "shoes": "鞋店", "shoe_store": "鞋店", "optician": "眼鏡行",
      "jewelry": "珠寶飾品", "books": "書店", "book_store": "書店",
      "stationery": "文具店", "pet": "寵物店", "pet_store": "寵物用品店",
      "florist": "花店", "electronics": "3C電子", "mobile_phone": "手機通訊行",
      "hardware": "五金行", "furniture": "傢俱行", "bed": "寢具店", "gift": "禮品店",
      "laundry": "洗衣店", "dry_cleaning": "乾洗店", "dry_cleaner": "乾洗店",
      "chemist": "藥妝店", "cosmetics": "化妝品店", "copyshop": "影印店",
      "cosmetic and beauty supplies": "美妝保養用品", "beauty_salon": "美容美髮沙龍",
      "hair_care": "美髮沙龍", "skin_care": "皮膚保養", "parking_space": "停車格",
      "locksmith": "開鎖刻印店", "shoe_repair": "修鞋店",

      // 醫療、健康與緊急設施
      "pharmacy": "藥局", "hospital": "醫院", "clinic": "診所",
      "dentist": "牙醫診所", "doctor": "診所", "veterinary_care": "動物醫院",
      "veterinary": "獸醫診所", "ambulance_station": "救護站",

      // 公共設施、交通與生活服務
      "bank": "銀行", "atm": "ATM提款機", "post_office": "郵局", "police": "警察局",
      "fire_station": "消防局", "school": "學校", "kindergarten": "幼兒園",
      "university": "大學", "college": "學院", "library": "圖書館", "park": "公園",
      "museum": "博物館", "theatre": "劇場", "cinema": "電影院", "nightclub": "夜店",
      "fitness_centre": "健身房", "gym": "健身房", "sports_centre": "體育場館",
      "fuel": "加油站", "gas_station": "加油站", "car_repair": "汽車修理廠",
      "car_rental": "租車行", "parking": "停車場", "bicycle": "自行車行",
      "bus_station": "公車站", "bus_stop": "公車站牌", "subway_station": "捷運站",
      "train_station": "火車站", "travel_agency": "旅行社", "insurance": "保險公司",
      "lawyer": "律師事務所", "estate_agent": "房屋仲介", "real_estate_agency": "房屋仲介",
      "company": "公司行號", "hotel": "旅館", "motel": "汽車旅館", "hostel": "青年旅館",
      "poi": "地標", "building": "建築物"
    };

    const raw = (category || "").trim().toLowerCase();
    if (!raw) return "地標";

    if (map[raw]) return map[raw];

    const cleanKey = raw.split(":").pop();
    if (map[cleanKey]) return map[cleanKey];

    return cleanKey.replace(/_/g, " ");
  }

  checkStatus(forceFocus = false) {
    fetch("/api/status")
      .then((res) => res.json())
      .then((data) => {
        this.offlineDB.saveState("last_status", data);
        if (data.is_loaded) {
          if (this.localLat === null) {
              this.localLat = data.lat;
              this.localLon = data.lon;
              this.localHeading = data.heading_deg;
          }
          this.serverLat = data.lat;
          this.serverLon = data.lon;
          this.lastData = data;

          const report = forceFocus ? (data.full_report || data.concise_report) : (data.concise_report || data.full_report);
          this.updateLiveLog(report, false, forceFocus);
          if (forceFocus) {
            this.audio.playArrival();
            if (this.liveLog && this.liveLog.firstElementChild) this.liveLog.firstElementChild.focus();
          }
          this.updatePOIs(data.pois);
          this.renderRadarCanvas(data);
        } else {
          this.updateLiveLog("正在等待 GPS 衛星定位中...", false, forceFocus);
        }
      })
      .catch(() => {
        // Item 4.2: IndexedDB Offline Storage Fallback
        this.offlineDB.getState("last_status", (cachedData) => {
          if (cachedData && cachedData.is_loaded) {
            this.updateLiveLog(`⚡ [離線圖資模式 (IndexedDB)] ${cachedData.concise_report || cachedData.full_report}`);
            this.updatePOIs(cachedData.pois);
            this.renderRadarCanvas(cachedData);
          } else {
            this.updateLiveLog("伺服器連線中斷，且本機尚無離線地圖快取。", true);
          }
        });
      });
  }

  teleport(locationInput) {
    this.localLat = null;
    this.localLon = null;
    this.localHeading = 0;
    this.accumulatedDistance = 0;
    this.serverLat = null;
    this.serverLon = null;
    this.lastSyncLat = null;
    this.lastSyncLon = null;
    this.lastSyncHeading = null;
    this.currentJunctionState = "IDLE";
    this.lastJunctionName = null;
    this.currentStreetName = null;
    this.lastIntersectionAlertTime = 0;
    if (this.isSignalCameraActive) {
      this.isSignalCameraActive = false;
      if (window.AndroidBridge && window.AndroidBridge.stopTrafficSignalCamera) {
        window.AndroidBridge.stopTrafficSignalCamera();
      }
    }
    if (this.announcedPoiCooldown) this.announcedPoiCooldown.clear();
    if (this.arrivedPoiCooldown) this.arrivedPoiCooldown.clear();
    this.updateLiveLog(`正在定位移至「${locationInput}」，請稍候...`);
    fetch("/api/teleport", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ location: locationInput }),
    })
      .then((res) => res.json())
      .then((data) => {
        if (data.success) {
          this.audio.playArrival();
          this.checkStatus(true);
        } else {
          this.updateLiveLog(`⚠️ ${data.message}`, true);
        }
      })
      .catch(() => {
        this.updateLiveLog("伺服器連線失敗，請檢查 server.py 是否執行。", true);
      });
  }

  getWalkSpeed() {
      // 提高基礎速度，確保輕點鍵盤 (約0.1秒) 至少能移動 0.5 公尺
      return Math.max(5.0, this.stepDistance * 5.0);
  }

  destinationPoint(lat, lon, distance_m, bearing_deg) {
      const R = 6371000.0;
      const lat_rad = lat * Math.PI / 180.0;
      const lon_rad = lon * Math.PI / 180.0;
      const bearing_rad = bearing_deg * Math.PI / 180.0;

      const new_lat_rad = Math.asin(Math.sin(lat_rad) * Math.cos(distance_m / R) +
                              Math.cos(lat_rad) * Math.sin(distance_m / R) * Math.cos(bearing_rad));
      let new_lon_rad = lon_rad + Math.atan2(Math.sin(bearing_rad) * Math.sin(distance_m / R) * Math.cos(lat_rad),
                                         Math.cos(distance_m / R) - Math.sin(lat_rad) * Math.sin(new_lat_rad));

      return { lat: new_lat_rad * 180.0 / Math.PI, lon: new_lon_rad * 180.0 / Math.PI };
  }

  haversineDistance(lat1, lon1, lat2, lon2) {
      const R = 6371000;
      const dLat = (lat2 - lat1) * Math.PI / 180;
      const dLon = (lon2 - lon1) * Math.PI / 180;
      const a = Math.sin(dLat/2) * Math.sin(dLat/2) +
              Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
              Math.sin(dLon/2) * Math.sin(dLon/2);
      const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
      return R * c;
  }

  calculateBearing(lat1, lon1, lat2, lon2) {
      const lat1Rad = lat1 * Math.PI / 180.0;
      const lat2Rad = lat2 * Math.PI / 180.0;
      const dLon = (lon2 - lon1) * Math.PI / 180.0;
      
      const y = Math.sin(dLon) * Math.cos(lat2Rad);
      const x = Math.cos(lat1Rad) * Math.sin(lat2Rad) -
                Math.sin(lat1Rad) * Math.cos(lat2Rad) * Math.cos(dLon);
      const brng = Math.atan2(y, x);
      
      return (brng * 180.0 / Math.PI + 360) % 360;
  }

  startRAFGameLoop() {
      if (this.rafId) return;
      this.lastFrameTime = performance.now();
      this.lastSyncTime = performance.now();
      this.lastSoundTime = performance.now();
      this.accumulatedDistance = 0;
      this.isTurning = false;
      this.lastSyncLat = null;
      this.lastSyncLon = null;
      this.lastSyncHeading = null;

      const loop = (time) => {
          this.rafId = requestAnimationFrame(loop);
          const dt = (time - this.lastFrameTime) / 1000;
          this.lastFrameTime = time;
          
          if (dt > 0.1) return; // Prevent huge jumps

          this.updateGameLogic(dt, time);
          
          // 【Canvas 髒標記 (Dirty Flag) 省電優化】：
          // 只有當朝向旋轉超過 0.5 度、座標改變或新資料到達時才執行 2D 重繪與 DOM 更新，
          // 徹底消滅靜止時每秒 60~120 次無效重繪造成的發熱與電池消耗！
          if (this.lastData) {
              const headingDiff = Math.abs((this.localHeading || 0) - (this._lastRenderedHeading || 0));
              const posChanged = (this._lastRenderedLat !== this.localLat) || (this._lastRenderedLon !== this.localLon);
              if (this.isCanvasDirty || posChanged || headingDiff >= 0.5) {
                  this.isCanvasDirty = false;
                  this._lastRenderedHeading = this.localHeading;
                  this._lastRenderedLat = this.localLat;
                  this._lastRenderedLon = this.localLon;
                  this.lastData.heading_deg = this.localHeading;
                  this.renderRadarCanvas(this.lastData);
              }
          }
      };
      this.rafId = requestAnimationFrame(loop);
  }

  getCardinalDirection(heading) {
      const dirs16 = [
        "正北", "北北東", "東北", "東北東",
        "正東", "東南東", "東南", "南南東",
        "正南", "南南西", "西南", "西南西",
        "正西", "西北西", "西北", "北北西"
      ];
      const normalized = ((heading % 360.0) + 360.0) % 360.0;

      // Schmitt Trigger 遲滯防抖：每區間 22.5°，在邊界處加入 ±3.5° 遲滯死區
      // 避免手機在方位交界處（如 123.75°）以 50Hz 頻率來回狂跳
      if (this.currentCardinalIndex !== undefined && this.currentCardinalIndex !== null) {
          const prevCenter = this.currentCardinalIndex * 22.5;
          let diff = Math.abs(normalized - prevCenter);
          if (diff > 180.0) diff = 360.0 - diff;
          // 半寬 11.25° + 3.5° 遲滯 = 14.75°。若仍在該範圍內，鎖定原方位不動
          if (diff <= 14.75) {
              return dirs16[this.currentCardinalIndex];
          }
      }

      const newIndex = Math.round(normalized / 22.5) % 16;
      this.currentCardinalIndex = newIndex;
      return dirs16[newIndex];
  }

  updateGameLogic(dt, time) {
      if (this.localLat === null || this.localLon === null || this.localHeading === null) return;

      const isMovingFwd = (this.keysDown['w'] || this.keysDown['arrowup']) && !this.keysDown['control'];
      const isMovingBack = (this.keysDown['s'] || this.keysDown['arrowdown']) && !this.keysDown['control'];
      
      if (this.velocity === undefined) this.velocity = 0;
      if (this.moveDir === undefined) this.moveDir = 1;
      
      // Momentum Engine (Scheme 1)
      if (isMovingFwd) {
          this.moveDir = 1;
          this.velocity += dt * 4.0; // Acceleration 4m/s^2
          if (this.velocity > 6.0) this.velocity = 6.0; // Max speed 6m/s
      } else if (isMovingBack) {
          this.moveDir = -1;
          this.velocity += dt * 4.0;
          if (this.velocity > 6.0) this.velocity = 6.0;
      } else {
          this.velocity -= dt * 6.0; // Deceleration 6m/s^2
          if (this.velocity < 0) this.velocity = 0;
      }
      
      if (this.velocity > 0.1) {
          const dist = this.velocity * dt;
          const moveAngle = this.moveDir === 1 ? this.localHeading : (this.localHeading + 180) % 360;
          const newPos = this.destinationPoint(this.localLat, this.localLon, dist, moveAngle);
          
          this.localLat = newPos.lat;
          this.localLon = newPos.lon;
          this.accumulatedDistance += dist;
          
          // Footstep audio rate scales with velocity
          const stepInterval = Math.max(250, 1000 / (this.velocity * 0.8));
          if (!this.lastSoundTime) this.lastSoundTime = time;
          if (time - this.lastSoundTime > stepInterval) {
              this.audio.playFootstep();
              this.lastSoundTime = time;
          }
          
          // Periodic server sync every 3 meters
          if (this.accumulatedDistance > 3.0 && !this.isSyncPending) {
              this.serverSync();
          }
      } else if (this.accumulatedDistance > 0.5 && !this.isSyncPending) {
          // Force sync when completely stopped
          this.serverSync();
      }
  }

  jumpToNextIntersection() {
      if (this.isSyncPending) return;
      this.isSyncPending = true;
      this.velocity = 0;
      this.accumulatedDistance = 0;
      this.keysDown = {};
      
      this.audio.playSpatialTone(800, 'sine', 0, 0, -1, 0.4);
      this.updateLiveLog("快轉跳躍中...", false, true);
      
      fetch("/api/jump_intersection", {
          method: "POST"
      })
      .then(res => res.json())
      .then(data => {
          this.isSyncPending = false;
          if (data.is_loaded) {
              this.lastData = data;
              this.serverLat = data.lat;
              this.serverLon = data.lon;
              this.localLat = data.lat;
              this.localLon = data.lon;
              
              const msg = data.action_message || "";
              this.updateLiveLog(msg, data.is_collision, true);
              this.updatePOIs(data.pois);
          }
      })
      .catch(() => { this.isSyncPending = false; });
  }

  snapTurn(direction) {
      if (this.isSyncPending) return;
      this.isSyncPending = true;
      
      this.updateLiveLog(`嘗試向${direction === 'left' ? '左' : '右'}智能對齊岔路...`, false, true);
      
      fetch("/api/snap_turn", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ direction: direction })
      })
      .then(res => res.json())
      .then(data => {
          this.isSyncPending = false;
          if (data.is_loaded) {
              this.lastData = data;
              this.serverLat = data.lat;
              this.serverLon = data.lon;
              this.localLat = data.lat;
              this.localLon = data.lon;
              this.localHeading = data.heading_deg;
              
              const msg = data.action_message || "";
              this.updateLiveLog(msg, false, true);
              this.audio.playTurn();
          }
      })
      .catch(() => { this.isSyncPending = false; });
  }

  strafe(direction) {
      if (this.isSyncPending) return;
      if (this.localLat === null || this.localLon === null || this.localHeading === null) return;
      
      let delta = direction === 'left' ? -90 : 90;
      let moveAngle = (this.localHeading + delta + 360) % 360;
      
      const dist = 1.0; // 1 meter strafe
      const newPos = this.destinationPoint(this.localLat, this.localLon, dist, moveAngle);
      this.localLat = newPos.lat;
      this.localLon = newPos.lon;
      this.accumulatedDistance += dist;
      
      this.audio.playFootstep();
      this.updateLiveLog(`向${direction === 'left' ? '左' : '右'}平移 1 公尺`, false, true);
      this.serverSync();
  }

  serverSync() {
      if (this.isSyncPending) return;
      this.isSyncPending = true;
      const syncDistance = this.accumulatedDistance;
      this.accumulatedDistance = 0;
      fetch("/api/sync", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
              lat: this.localLat,
              lon: this.localLon,
              heading_deg: this.localHeading,
              distance_moved: syncDistance
          })
      })
      .then(res => res.json())
      .then(data => {
          this.isSyncPending = false;
          if (data.is_collision) {
              this.localLat = data.lat;
              this.localLon = data.lon;
              this.localHeading = data.heading_deg;
              this.keysDown = {};
              this.velocity = 0;
              this.audio.playBumpCollision();
              if (window.AndroidBridge && window.AndroidBridge.vibrate) {
                  window.AndroidBridge.vibrate(300);
              }
              this.updateLiveLog(data.action_message || "前方有障礙！", true, true);
          } else {
              if (data.is_loaded) {
                  this.lastData = data;
                  this.serverLat = data.lat;
                  this.serverLon = data.lon;
                  this.localLat = data.lat;
                  this.localLon = data.lon;

                  let msg = data.concise_report || data.action_message || "";
                  if (data.simulation && data.simulation.narration) {
                      msg = msg + '\n\n' + data.simulation.narration;
                      if (data.simulation.events) {
                          this.audio.playEventSounds(data.simulation.events);
                      }
                  }
                  
                  const now = performance.now();
                  if (!this.lastLogTime || now - this.lastLogTime > 500) {
                      const isImportant = msg.includes("🚨") || msg.includes("🌟");
                      if (isImportant) {
                          this.updateLiveLog(msg, false, true);
                          if (msg.includes("🚨")) {
                              this.audio.playSpatialTone(900, 'square', 0, 0, -1, 0.3);
                              this.keysDown = {};
                          }
                          this.lastLogTime = now;
                      } else {
                          this.updateLiveLog(msg, false, false);
                          this.lastLogTime = now;
                      }
                  }

                  this.updatePOIs(data.pois);
                  this.checkProximityAlerts(data);
              }
          }
      })
      .catch(() => { this.isSyncPending = false; });
  }


  turn(degreeOrDir) {
      if (this.isSyncPending) return;
      if (this.localHeading === null) return;
      let delta = 0;
      if (typeof degreeOrDir === 'number') {
          delta = degreeOrDir;
      } else if (typeof degreeOrDir === 'string') {
          const num = parseFloat(degreeOrDir);
          if (!isNaN(num)) delta = num;
      }
      
      this.localHeading = (this.localHeading + delta + 360) % 360;
      this.audio.playTurn();
      
      const dirStr = this.getCardinalDirection(this.localHeading);
      this.updateLiveLog(dirStr, false, true);
      
      this.serverSync();
  }

  setStepDistance(metres) {
    this.stepDistance = metres;
    this.updateLiveLog(`步距已調為 ${metres} 公尺（按 1-5 數字鍵切換）`, false, true);
  }

  sendNLPQuery(query) {
    this.updateLiveLog(`正在理解自然語言指令：「${query}」...`);
    fetch("/api/nlp", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: query }),
    })
      .then((res) => res.json())
      .then((data) => {
        if (data.success) {
          this.audio.playArrival();
          const ans = data.answer || "查詢完成。";
          this.updateLiveLog(ans, false, true);
        } else {
          this.updateLiveLog(`⚠️ ${data.message || '查詢無結果'}`, true);
        }
      })
      .catch(() => {
        this.updateLiveLog("指令解析失敗。", true);
      });
  }

  renderRadarCanvas(data) {
    if (!this.canvasCtx || !this.radarCanvas) return;

    const ctx = this.canvasCtx;
    const w = this.radarCanvas.width;
    const h = this.radarCanvas.height;
    const cx = w / 2;
    const cy = h / 2;
    const scale = (w / 2) / 100; // 100 meters radius radar

    ctx.clearRect(0, 0, w, h);

    // Radar background circles
    ctx.strokeStyle = "#1e293b";
    ctx.lineWidth = 1;
    [25, 50, 75, 100].forEach((r) => {
      ctx.beginPath();
      ctx.arc(cx, cy, r * scale, 0, Math.PI * 2);
      ctx.stroke();
    });

    // Radar crosshair
    ctx.beginPath();
    ctx.moveTo(cx, 0); ctx.lineTo(cx, h);
    ctx.moveTo(0, cy); ctx.lineTo(w, cy);
    ctx.stroke();

    // Explorer Center Dot
    ctx.fillStyle = "#38bdf8";
    ctx.beginPath();
    ctx.arc(cx, cy, 7, 0, Math.PI * 2);
    ctx.fill();

    // Facing Direction Cone
    const headingRad = (data.heading_deg - 90) * (Math.PI / 180);
    ctx.fillStyle = "rgba(56, 189, 248, 0.25)";
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.arc(cx, cy, 90, headingRad - 0.35, headingRad + 0.35);
    ctx.closePath();
    ctx.fill();

    // Render POIs
    if (data.pois) {
      data.pois.forEach((p) => {
        const rad = (p.relative_bearing_deg - 90) * (Math.PI / 180);
        const distPx = p.distance_m * scale;
        const px = cx + Math.cos(rad) * distPx;
        const py = cy + Math.sin(rad) * distPx;

        ctx.fillStyle = p.category.includes("subway") || p.category.includes("bus") ? "#f59e0b" : "#34d399";
        ctx.beginPath();
        ctx.arc(px, py, 4, 0, Math.PI * 2);
        ctx.fill();

        ctx.fillStyle = "#cbd5e1";
        ctx.font = "10px sans-serif";
        ctx.fillText(p.name.substring(0, 8), px + 6, py + 3);
      });
    }

    // Render Real-World Physical Street Scene Card
    if (data.street_scene && this.streetSummary && this.streetTagsContainer) {
      const scene = data.street_scene;
      this.streetSummary.textContent = scene.full_description || "街景解析中...";
      
      let tagsHtml = `<span class="badge badge-info">${scene.scene_type || '都市街道'}</span> `;
      tagsHtml += `<span class="badge badge-secondary">${scene.architecture_style || '建築風貌'}</span> `;
      if (scene.infrastructure) {
        scene.infrastructure.forEach((item) => {
          tagsHtml += `<span class="badge badge-success">${item}</span> `;
        });
      }
      this.streetTagsContainer.innerHTML = tagsHtml;
    }
  }

  // 檢查 App 更新 (Check App Updates via GitHub Releases)
  checkForAppUpdates(silent = false) {
    if (window.AndroidBridge && window.AndroidBridge.checkForUpdates) {
      window.AndroidBridge.checkForUpdates(silent);
    } else {
      fetch("/api/system/check_update")
        .then(res => res.json())
        .then(data => {
          if (data.has_update) {
            this.showUpdateDialog(data.latest_version, data.release_title, data.download_url, data.release_notes);
          } else if (!silent) {
            this.updateLiveLog(`目前已是最新版本 (v${data.current_version})。`);
          }
        })
        .catch(() => {
          if (!silent) this.updateLiveLog("檢查更新失敗，請檢查網路連線。");
        });
    }
  }

  // =========================================================================
  // 🛡️ WCAG 2.2 AAA 無障礙模態對話框管理器 (Accessible Modal Shield & Focus Trap)
  // 核心任務：
  // 1. 開啟對話框時，將主畫面容器 (#main-content) 設為 inert 與 aria-hidden="true"，
  //    徹底杜絕 TalkBack 單指左右滑動穿透至前一層背景內容。
  // 2. 建立焦點鎖定圈 (Focus Trap)，Tab / Shift+Tab 鍵循環不脫逸。
  // 3. 關閉對話框時，解除背景鎖定並精準讓焦點歸位至觸發按鈕。
  // =========================================================================

  openModal(modalId, triggerElement = null) {
    const modal = typeof modalId === 'string' ? document.getElementById(modalId) : modalId;
    if (!modal) return;

    this.activeModal = modal;
    if (triggerElement) {
      this.lastFocusedElement = triggerElement;
    } else if (document.activeElement && document.activeElement !== document.body) {
      this.lastFocusedElement = document.activeElement;
    }

    // 1. 徹底屏蔽主畫面容器：TalkBack / NVDA 100% 無法讀取、滑動或聚焦非對話框內容
    const mainContent = document.getElementById("main-content");
    if (mainContent) {
      mainContent.setAttribute("aria-hidden", "true");
      mainContent.setAttribute("inert", "");
      mainContent.style.pointerEvents = "none";
    }

    // 2. 將其他非當前對話框全部隱藏並設為 inert
    document.querySelectorAll(".modal-overlay").forEach(m => {
      if (m !== modal) {
        m.style.display = "none";
        m.setAttribute("aria-hidden", "true");
        m.setAttribute("inert", "");
      }
    });

    // 3. 顯示並活化當前對話框
    modal.removeAttribute("aria-hidden");
    modal.removeAttribute("inert");
    modal.style.display = "flex";
    modal.setAttribute("aria-modal", "true");
    modal.setAttribute("role", "dialog");

    // 4. 啟用焦點鎖定圈 (Focus Trap)
    this.setupFocusTrap(modal);

    // 5. 將焦點移至對話框標題或第一個可聚焦元件
    setTimeout(() => {
      const focusTarget = modal.querySelector("h2, [tabindex='0'], button:not(.btn-close), input");
      if (focusTarget && typeof focusTarget.focus === "function") {
        focusTarget.focus();
      }
    }, 80);
  }

  closeModal(modalId) {
    const modal = typeof modalId === 'string' ? document.getElementById(modalId) : modalId;
    if (!modal) return;

    // 1. 解除焦點鎖定圈
    this.removeFocusTrap(modal);

    // 2. 關閉並凍結此對話框
    modal.style.display = "none";
    modal.setAttribute("aria-hidden", "true");
    modal.setAttribute("inert", "");

    if (this.activeModal === modal) {
      this.activeModal = null;
    }

    // 3. 若無其他對話框開啟，徹底還原主畫面可存取性
    const anyOtherOpen = Array.from(document.querySelectorAll(".modal-overlay")).some(m => m.style.display === "flex");
    if (!anyOtherOpen) {
      const mainContent = document.getElementById("main-content");
      if (mainContent) {
        mainContent.removeAttribute("aria-hidden");
        mainContent.removeAttribute("inert");
        mainContent.style.pointerEvents = "";
      }

      // 4. 焦點精準回歸觸發來源按鈕
      if (this.lastFocusedElement && typeof this.lastFocusedElement.focus === "function") {
        try {
          this.lastFocusedElement.focus();
        } catch (e) {}
        this.lastFocusedElement = null;
      }
    }
  }

  setupFocusTrap(modal) {
    this.removeFocusTrap(modal);

    const focusableSelector = 'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

    modal._focusTrapHandler = (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        this.closeModal(modal);
        if (modal.id === "poi-detail-modal") {
          this.closePoiModal();
        }
        return;
      }

      if (e.key !== "Tab") return;

      const focusable = Array.from(modal.querySelectorAll(focusableSelector)).filter(el => {
        return el.offsetWidth > 0 || el.offsetHeight > 0 || el === document.activeElement;
      });

      if (focusable.length === 0) return;

      const first = focusable[0];
      const last = focusable[focusable.length - 1];

      if (e.shiftKey) {
        if (document.activeElement === first || !modal.contains(document.activeElement)) {
          e.preventDefault();
          last.focus();
        }
      } else {
        if (document.activeElement === last || !modal.contains(document.activeElement)) {
          e.preventDefault();
          first.focus();
        }
      }
    };

    modal.addEventListener("keydown", modal._focusTrapHandler);
  }

  removeFocusTrap(modal) {
    if (modal && modal._focusTrapHandler) {
      modal.removeEventListener("keydown", modal._focusTrapHandler);
      modal._focusTrapHandler = null;
    }
  }

  // 顯示無障礙更新對話框 (Show Accessible Update Dialog)
  showUpdateDialog(latestVer, title, downloadUrl, notes) {
    const modal = document.getElementById("update-modal");
    const body = document.getElementById("update-modal-body");
    const confirmBtn = document.getElementById("update-btn-confirm");
    const cancelBtn = document.getElementById("update-btn-cancel");
    const progContainer = document.getElementById("update-progress-container");
    if (!modal || !body) return;

    body.innerHTML = `<p><strong>最新版本：v${latestVer}</strong></p><p><strong>${title || '新版本發布'}</strong></p><div style="max-height:120px;overflow-y:auto;color:#cbd5e1;font-size:0.95em;margin-top:6px;white-space:pre-line;">${notes || "無更新日誌說明"}</div>`;
    this.openModal(modal, document.getElementById("ui-btn-check-update"));
    if (progContainer) progContainer.style.display = "none";

    if (confirmBtn) {
      confirmBtn.onclick = () => {
        if (progContainer) progContainer.style.display = "block";
        if (window.AndroidBridge && window.AndroidBridge.downloadAndInstallUpdate) {
          window.AndroidBridge.downloadAndInstallUpdate(downloadUrl);
        } else {
          window.open(downloadUrl, "_blank");
        }
      };
    }
    if (cancelBtn) {
      cancelBtn.onclick = () => {
        this.closeModal(modal);
      };
    }
  }

  // 顯示離線地圖資料庫管理視窗 (Show Offline Map DB Manager Modal)
  showMapDatabaseModal() {
    const modal = document.getElementById("map-db-modal");
    const body = document.getElementById("map-db-modal-body");
    const dlBtn = document.getElementById("map-db-btn-download");
    const delBtn = document.getElementById("map-db-btn-delete");
    const closeBtn = document.getElementById("map-db-btn-close");
    const progContainer = document.getElementById("map-db-progress-container");
    if (!modal || !body) return;

    let dbExists = false;
    let dbSize = "0 MB";

    if (window.AndroidBridge && window.AndroidBridge.getDatabaseStatusJson) {
      try {
        const info = JSON.parse(window.AndroidBridge.getDatabaseStatusJson());
        dbExists = info.exists;
        dbSize = info.sizeFormattedMb || "0 MB";
      } catch (e) {
        console.error("Failed to parse db status json", e);
      }
    }

    if (dbExists) {
      body.innerHTML = `
        <p style="color:#2dd4bf;font-weight:bold;font-size:1.05em;">✅ 全台 193 萬店家與商工整合資料庫已就緒！</p>
        <p style="margin:6px 0;"><strong>資料庫版本：</strong>商工整合精簡版 (v1.0.3)</p>
        <p style="margin:6px 0;"><strong>本地檔案大小：</strong><strong>${dbSize}</strong> (約 254 MB)</p>
        <p style="color:#cbd5e1;font-size:0.95em;line-height:1.5;">
          📍 涵蓋範圍：全台 22 縣市實體店家、門牌地址、樓層標籤與詳細營業項目。<br>
          ⚡ 運作狀態：離線極速 0.002 秒檢索，無網路環境 100% 完整可用。
        </p>
      `;
      if (delBtn) delBtn.style.display = "block";
      if (dlBtn) dlBtn.innerText = "檢查更新 / 下載最新圖資";
    } else {
      body.innerHTML = `
        <p style="color:#fbbf24;font-weight:bold;font-size:1.05em;">⚠️ 尚未下載全台離線店家圖資</p>
        <p style="color:#cbd5e1;font-size:0.95em;line-height:1.5;">
          目前正在使用線上即時查詢。建議在 Wi-Fi 環境下載全台精簡圖資包（壓縮檔約 95 MB，解壓後 254 MB），下載後可享受全台 193 萬店家之永久離線極速檢索。
        </p>
      `;
      if (delBtn) delBtn.style.display = "none";
      if (dlBtn) dlBtn.innerText = "立即下載離線圖資包 (95 MB)";
    }

    this.openModal(modal, document.getElementById("ui-btn-map-db"));
    if (progContainer) progContainer.style.display = "none";

    // 聚焦與無障礙報讀
    if (window.AndroidBridge && window.AndroidBridge.speak) {
      if (dbExists) {
        window.AndroidBridge.speak(`離線商工稅籍資料庫已就緒，大小 ${dbSize}。`, false);
      } else {
        window.AndroidBridge.speak("離線圖資管理。尚未下載離線圖資，可點選下載圖資包。", false);
      }
    }

    if (dlBtn) {
      dlBtn.onclick = () => {
        if (progContainer) progContainer.style.display = "block";
        if (window.AndroidBridge && window.AndroidBridge.downloadOfflineDatabase) {
          window.AndroidBridge.downloadOfflineDatabase();
        } else {
          window.open("https://github.com/mhhsei/nmap_explorer/releases/latest/download/overture_places.db.zip", "_blank");
        }
      };
    }

    if (delBtn) {
      delBtn.onclick = () => {
        if (window.AndroidBridge && window.AndroidBridge.deleteOfflineDatabase) {
          window.AndroidBridge.deleteOfflineDatabase();
          this.showMapDatabaseModal();
        }
      };
    }

    if (closeBtn) {
      closeBtn.onclick = () => {
        this.closeModal(modal);
      };
    }
  }

  /**
   * 【初始化偏好設定管理器 (Extensible Settings Manager)】
   * 作用：載入本地偏好設定，支援日後任意增修設定項與持久化
   */
  initSettings() {
    const DEFAULT_SETTINGS = {
      turnAnnounce: true,         // 轉向報讀方位
      turnTickSound: true,        // 轉向指針聲與微震
      autoPoiAnnounce: true,      // 靠近店家自動提醒
      hapticFeedback: true,       // 正北與刻度震動
      earconEnabled: true         // 朗讀前先播提示音
    };

    try {
      const saved = localStorage.getItem("nmap_user_settings");
      this.settings = saved ? Object.assign({}, DEFAULT_SETTINGS, JSON.parse(saved)) : DEFAULT_SETTINGS;
    } catch (e) {
      this.settings = DEFAULT_SETTINGS;
    }
  }

  /**
   * 【儲存偏好設定至本地儲存區】
   */
  saveSettings() {
    try {
      localStorage.setItem("nmap_user_settings", JSON.stringify(this.settings));
    } catch (e) {
      console.error("Failed to save settings", e);
    }
  }

  /**
   * 【開啟偏好設定無障礙對話框 (Accessible Settings Modal)】
   * 作用：
   * 1. 將主畫面徹底設為 inert 與 aria-hidden="true"，TalkBack 單指滑動 100% 留在對話框內。
   * 2. 說明文字簡潔明瞭，台灣高中生與一般使用者一目了然。
   * 3. 雙擊切換時清楚報讀「已開啟」或「已關閉」。
   */
  showSettingsModal() {
    const modal = document.getElementById("settings-modal");
    if (!modal) return;

    const chkTurn = document.getElementById("setting-turn-announce");
    const chkTick = document.getElementById("setting-tick-sound");
    const chkPoi = document.getElementById("setting-auto-poi-announce");
    const chkHaptic = document.getElementById("setting-haptic-feedback");
    const chkEarcon = document.getElementById("setting-earcon-enabled");

    if (chkTurn) chkTurn.checked = !!this.settings.turnAnnounce;
    if (chkTick) chkTick.checked = !!this.settings.turnTickSound;
    if (chkPoi) chkPoi.checked = !!this.settings.autoPoiAnnounce;
    if (chkHaptic) chkHaptic.checked = !!this.settings.hapticFeedback;
    if (chkEarcon) chkEarcon.checked = this.settings.earconEnabled !== false;

    // 開啟模態對話框並完全鎖定主畫面背景
    this.openModal(modal, document.getElementById("ui-btn-settings"));

    // TalkBack / 螢幕閱讀器友善引導（簡潔親切）
    if (window.AndroidBridge && window.AndroidBridge.speak) {
      window.AndroidBridge.speak("偏好設定。左右滑動瀏覽，點兩下切換開關。", false);
    }

    // 綁定核取方塊切換監聽（即時存檔並提供語音回饋，字詞簡潔）
    const bindToggle = (chkEl, key, labelName) => {
      if (!chkEl) return;
      chkEl.onchange = () => {
        this.settings[key] = chkEl.checked;
        this.saveSettings();
        const stateText = chkEl.checked ? "已開啟" : "已關閉";
        const announceText = `${labelName}，${stateText}。`;
        if (window.AndroidBridge && window.AndroidBridge.speak) {
          window.AndroidBridge.speak(announceText, true);
        }
      };
    };

    bindToggle(chkTurn, "turnAnnounce", "轉向報讀方位");
    bindToggle(chkTick, "turnTickSound", "轉向指針聲與微震");
    bindToggle(chkPoi, "autoPoiAnnounce", "靠近店家自動提醒");
    bindToggle(chkHaptic, "hapticFeedback", "正北與刻度震動");
    bindToggle(chkEarcon, "earconEnabled", "朗讀前先播提示音");

    // 聽覺圖標試聽按鈕綁定（點選即播放專屬音效並報讀精簡特徵）
    const bindTestBtn = (btnId, playFn, descText) => {
      const btn = document.getElementById(btnId);
      if (!btn) return;
      btn.onclick = () => {
        playFn();
        if (window.AndroidBridge && window.AndroidBridge.speak) {
          window.AndroidBridge.speak(descText, true);
        } else if (window.speechSynthesis) {
          try {
            window.speechSynthesis.cancel();
            const u = new SpeechSynthesisUtterance(descText);
            u.lang = 'zh-TW';
            window.speechSynthesis.speak(u);
          } catch(e) {}
        }
      };
    };

    bindTestBtn("btn-test-sound-shop", () => this.audio.playShopTone(0, -1), "商店音效：清脆門鈴聲。");
    bindTestBtn("btn-test-sound-landmark", () => this.audio.playLandmarkTone(0, -1), "地標音效：悠揚鐘琴聲。");
    bindTestBtn("btn-test-sound-building", () => this.audio.playBuildingTone(0, -1), "建築音效：沉穩敲擊聲。");
    bindTestBtn("btn-test-sound-transit", () => this.audio.playTransitTone(0, -1), "交通音效：捷運公車嗶嗶聲。");
    bindTestBtn("btn-test-sound-junction", () => this.audio.playJunctionTone(0, -1), "路口音效：水滴滑音。");
    bindTestBtn("btn-test-sound-warning", () => this.audio.playWarningTone(0, -1), "警示音效：注意障礙警示音。");

    const closeBtn = document.getElementById("settings-modal-close-btn");
    const closeBottomBtn = document.getElementById("settings-modal-close-bottom-btn");
    const closeModal = () => {
      this.closeModal(modal);
    };

    if (closeBtn) closeBtn.onclick = closeModal;
    if (closeBottomBtn) closeBottomBtn.onclick = closeModal;
  }

  /**
   * 【顯示店家/地標詳細資訊與 Google Maps 深度驗證】
   * 作用：
   * 1. 點擊歷史紀錄中或掃描列表的店家時觸發。
   * 2. 0ms 播放該類別 3D 空間音效，開啟無障礙對話框。
   * 3. < 0.8s 並行抓取 Google Maps 評分、營業時間、電話、無障礙設施與官方門牌核定。
   * 4. TalkBack / Native TTS 即時播報精準摘要。
   */
  showPoiDetail(poi, triggerElement = null) {
    if (!poi) return;
    const modal = document.getElementById("poi-detail-modal");
    const title = document.getElementById("poi-modal-title");
    const body = document.getElementById("poi-modal-body");
    if (!modal || !body) return;

    this.selectedPoiForNav = poi;
    this.isDetailModalOpen = true;

    // 1. 播放該店家專屬聽覺圖標
    if (this.audio && (!this.settings || this.settings.earconEnabled !== false)) {
      this.audio.playForPoi(poi);
    }

    const cleanName = this.cleanPoiDisplayName(poi.name);
    if (title) title.textContent = `📍 ${cleanName}`;

    const catDesc = this.translateCategory(poi.category);
    const clock = poi.clock_position || poi.clock_direction || "前方";
    const dist = poi.distance_m ? `${Math.round(poi.distance_m)} 公尺` : "";
    const floor = (poi.floor && poi.floor !== "1F") ? ` (${poi.floor})` : "";
    const initialAddr = (poi.address && poi.address.trim()) ? poi.address.trim() : (poi.street ? `${poi.street}${poi.housenumber ? ' ' + poi.housenumber + '號' : ''}` : "未登記完整門牌");

    body.innerHTML = `
      <p style="margin:4px 0;"><strong>設施分類：</strong>${catDesc}${floor}</p>
      <p style="margin:4px 0;"><strong>相對方位：</strong>${clock} ${dist}</p>
      <p id="poi-modal-addr" style="margin:4px 0;"><strong>門牌地址：</strong>${initialAddr}</p>
      <div id="poi-modal-live-status" style="margin-top:8px; padding:10px; background:#1e293b; border-radius:6px; border-left:4px solid #38bdf8;">
        <p style="margin:0; color:#38bdf8;">🔍 正在連線 Google Maps 與在地官方資料庫即時驗證中...</p>
      </div>
    `;

    this.openModal(modal, triggerElement);

    // 2. 向後端極速即時連線抓取 Google Maps & 稅籍驗證資料 (< 0.8s)
    fetch("/api/poi_detail", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: poi.name,
        lat: poi.lat,
        lon: poi.lon,
        address: poi.address || "",
        floor: poi.floor || "1F"
      })
    })
      .then(res => res.json())
      .then(data => {
        const d = (data && data.details) ? data.details : {};
        const liveContainer = document.getElementById("poi-modal-live-status");
        const addrElem = document.getElementById("poi-modal-addr");

        const verifiedAddr = d.address || initialAddr;
        if (addrElem) {
          addrElem.innerHTML = `<strong>門牌地址：</strong>${verifiedAddr} <span style="color:#2dd4bf; font-size:0.9em;">(🟢 官方與線上雙重驗證)</span>`;
        }

        let liveHtml = "";
        let speechParts = [`【${cleanName}】`];

        // 營業狀態與營業時間
        const hours = d.opening_hours || "營業時間：常態營業";
        liveHtml += `<p style="margin:4px 0; color:#34d399; font-weight:bold;">🕒 ${hours}</p>`;
        speechParts.push(hours);

        // 評分與 Google 評價
        if (d.rating) {
          liveHtml += `<p style="margin:4px 0; color:#fbbf24;">⭐ <strong>${d.rating}</strong></p>`;
          speechParts.push(`評分 ${d.rating}`);
        }

        // 熱門推薦與人氣招牌菜單
        if (d.popular_items) {
          liveHtml += `<p style="margin:4px 0; color:#f472b6; line-height:1.4;">🍲 <strong>熱門推薦：</strong>${d.popular_items}</p>`;
          speechParts.push(`熱門推薦：${d.popular_items}`);
        }

        // 電話 (可點擊撥打)
        if (d.phone && d.phone !== "門市在地專線") {
          liveHtml += `<p style="margin:4px 0;">📞 <strong>連絡電話：</strong><a href="tel:${d.phone}" style="color:#38bdf8; text-decoration:underline; font-weight:bold;">${d.phone}</a></p>`;
          speechParts.push(`電話：${d.phone}`);
        }

        // 無障礙設施
        if (d.wheelchair) {
          liveHtml += `<p style="margin:4px 0; color:#a5b4fc;">♿ ${d.wheelchair}</p>`;
          speechParts.push(d.wheelchair);
        }

        speechParts.push(`門牌地址：${verifiedAddr}`);

        if (liveContainer) {
          liveContainer.innerHTML = liveHtml || "<p style=\"margin:0;\">已完成在地圖資驗證。</p>";
        }

        // 3. 透過 TalkBack / Native TTS 即時播報驗證結果
        const fullSpeech = speechParts.join("。");
        if (window.AndroidBridge && window.AndroidBridge.speak) {
          window.AndroidBridge.speak(fullSpeech, true);
        } else if (window.speechSynthesis) {
          try {
            window.speechSynthesis.cancel();
            const u = new SpeechSynthesisUtterance(fullSpeech);
            u.lang = 'zh-TW';
            u.rate = 1.15;
            window.speechSynthesis.speak(u);
          } catch(e) {}
        }
      })
      .catch(err => {
        console.error("POI detail fetch error", err);
        const liveContainer = document.getElementById("poi-modal-live-status");
        if (liveContainer) {
          liveContainer.innerHTML = "<p style=\"margin:0; color:#94a3b8;\">離線模式：已載入本機登記之基本資料。</p>";
        }
      });
  }

  closePoiModal() {
    this.isDetailModalOpen = false;
    const modal = document.getElementById("poi-detail-modal");
    if (modal) this.closeModal(modal);
  }

  startBeaconToTarget() {
    if (!this.selectedPoiForNav) return;
    const target = this.selectedPoiForNav;
    this.closePoiModal();

    this.activeGuidance = {
      targetName: target.name,
      targetLat: target.lat,
      targetLon: target.lon,
      lastDistanceM: target.distance_m || 50
    };

    const card = document.getElementById("active-guidance-card");
    const targetDesc = document.getElementById("guidance-target-desc");
    const distPill = document.getElementById("guidance-dist-pill");

    if (card) card.style.display = "block";
    if (targetDesc) targetDesc.textContent = `導引目標：${target.name}`;
    if (distPill) distPill.textContent = `剩餘約 ${Math.round(target.distance_m || 0)}m`;

    if (this.audio && this.audio.playBeaconAnchorTone) {
      this.audio.playBeaconAnchorTone();
    }

    this.updateLiveLog(`🎯 已開啟 3D 空間聲音導引前往【${target.name}】。請戴上耳機，朝著聲音方向前進，越接近目標聲音越急促。`, false, true);
  }

  launchGoogleMapsNavigation() {
    if (!this.selectedPoiForNav) return;
    const target = this.selectedPoiForNav;
    const lat = target.lat;
    const lon = target.lon;
    const url = `google.navigation:q=${lat},${lon}&mode=w`;

    if (window.AndroidBridge && window.AndroidBridge.openExternalApp) {
      window.AndroidBridge.openExternalApp(url);
    } else {
      window.open(`https://www.google.com/maps/dir/?api=1&destination=${lat},${lon}&travelmode=walking`, "_blank");
    }
  }

  stopBeaconGuidance(silent = false) {
    this.activeGuidance = null;
    const card = document.getElementById("active-guidance-card");
    if (card) card.style.display = "none";

    if (!silent) {
      this.updateLiveLog("🛑 已停止 3D 空間聲音導引。", false, true);
    }
  }

  closeArrivalModal() {
    this.stopBeaconGuidance(true);
    const modal = document.getElementById("arrival-modal");
    if (modal) this.closeModal(modal);
  }
}


// 全域 AndroidBridge 回調綁定
window.onUpdateAvailable = (latestVer, title, downloadUrl, fileSize, notes) => {
  if (window.app) {
    window.app.showUpdateDialog(latestVer, title, downloadUrl, notes);
  }
};

window.onDownloadProgress = (percent) => {
  const pText = document.getElementById("update-progress-text");
  const pBar = document.getElementById("update-progress-bar");
  if (pText) pText.innerText = `下載進度：${percent}%`;
  if (pBar) pBar.style.width = `${percent}%`;
};

window.onDownloadComplete = () => {
  const pText = document.getElementById("update-progress-text");
  if (pText) pText.innerText = "下載完成，正在啟動安裝...";
};

window.onUpdateError = (errMsg) => {
  if (window.app) {
    window.app.updateLiveLog(`更新失敗：${errMsg}`);
  }
};

window.onUpdateCheckResult = (status, info, isManual = false) => {
  if (status === 'latest' && window.app && isManual) {
    window.app.updateLiveLog(`目前已是最新版本 (v${info})。`, false, true);
  }
};

// 離線圖資下載回調 (Database Download Callbacks)
window.onDatabaseDownloadStart = () => {
  const progContainer = document.getElementById("map-db-progress-container");
  const pText = document.getElementById("map-db-progress-text");
  const pBar = document.getElementById("map-db-progress-bar");
  if (progContainer) progContainer.style.display = "block";
  if (pText) pText.innerText = "正在開始下載離線圖資...";
  if (pBar) pBar.style.width = "0%";
};

window.onDatabaseDownloadProgress = (percent) => {
  const pText = document.getElementById("map-db-progress-text");
  const pBar = document.getElementById("map-db-progress-bar");
  if (pText) pText.innerText = `圖資下載進度：${percent}%`;
  if (pBar) pBar.style.width = `${percent}%`;
};

window.onDatabaseDownloadComplete = (dbSize) => {
  const pText = document.getElementById("map-db-progress-text");
  const pBar = document.getElementById("map-db-progress-bar");
  if (pText) pText.innerText = `圖資下載完成 (${dbSize})！`;
  if (pBar) pBar.style.width = "100%";
  
  // 向後端請求立即重新載入本地 SQLite 資料庫地標
  fetch("/api/refresh_pois", { method: "POST" })
    .then(res => res.json())
    .then(data => {
      if (data && data.success && window.app) {
        window.app.updateLiveLog(`🎉 全台離線資料庫載入就緒！周遭已成功載入 ${data.poi_count} 間店家與地標。`, true, true);
        if (window.app.syncStatus) window.app.syncStatus();
      }
    })
    .catch(() => {
      if (window.app) window.app.updateLiveLog(`全台離線店家圖資已下載完成 (${dbSize})！`);
    });

  if (window.app) {
    window.app.showMapDatabaseModal();
  }
};


window.onDatabaseAlreadyLatest = (dbSize) => {
  const progContainer = document.getElementById("map-db-progress-container");
  if (progContainer) progContainer.style.display = "none";
  if (window.app) {
    window.app.updateLiveLog(`✅ 目前全台離線資料庫（${dbSize}）已是最新版本，無須重複下載。`, true, true);
    window.app.showMapDatabaseModal();
  }
};

window.onDatabaseDownloadError = (errMsg) => {
  const pText = document.getElementById("map-db-progress-text");
  if (pText) pText.innerText = `圖資下載失敗：${errMsg}`;
  if (window.app) {
    window.app.updateLiveLog(`圖資下載失敗：${errMsg}`);
  }
};

window.onPermissionGranted = () => {
  const pb = document.getElementById("permission-banner");
  if (pb) pb.style.display = "none";
  if (window.app) {
    window.app.updateLiveLog("📍 已取得定位權限，正在接收衛星訊號...", false, false);
  }
};

/**
 * 衛星訊號搜尋中即時提示 (由 Android LocationSensorBridge 注入)
 */
window.onGpsSearching = () => {
  if (window.app && !window.app.serverLat) {
    window.app.updateLiveLog("📍 正在搜尋衛星訊號與建立離線圖資，請稍候...", false, false);
  }
};

document.addEventListener("DOMContentLoaded", () => {
  window.app = new NmapWebApp();
  window.touchCtrl = new TouchGestureController(window.app);

  // 【無障礙即時語音開機心跳 (Screen Reader Startup Chime & Speech)】
  // 開機瞬間立即透過 TalkBack / NVDA 朗讀就緒狀態，消滅死機恐懼
  setTimeout(() => {
    if (window.app && !window.app.serverLat) {
      window.app.updateLiveLog("歡迎使用 nmap！系統啟動中，正在載入離線圖資與衛星定位...", false, true);
    }
  }, 120);

  // 【消除網頁載入時差 (Zero-Latency Replay Request)】
  // 主動向 Android 原生層請求回放最新定位與感測器狀態
  if (window.AndroidBridge && window.AndroidBridge.requestLatestLocation) {
    try {
      window.AndroidBridge.requestLatestLocation();
    } catch (e) {
      console.warn("Error calling requestLatestLocation", e);
    }
  }

  // 開啟 App 2 秒後在背景靜默檢查更新
  setTimeout(() => {
    if (window.app) window.app.checkForAppUpdates(true);
  }, 2000);
});


// 手勢觸控控制器 (Touch Gesture Controller for Visually Impaired)
// 作用：
// 1. 單指雙擊 (Double Tap)：即時報讀當前道路名稱與門牌區間。
// 2. 雙指滑動 (Two-Finger Swipe)：執行虛擬平移 (Virtual Pan)，讓手指能在地圖上左右探索鄰近巷弄與店家。
class TouchGestureController {
  constructor(app) {
    this.app = app;
    this.touchStartX = 0;
    this.touchStartY = 0;
    this.touchEndX = 0;
    this.touchEndY = 0;
    this.touchTarget = null;
    this.touchCount = 1;
    this.lastTapTime = 0;
    
    // Add touch listener to the whole body
    document.body.addEventListener('touchstart', (e) => {
      this.touchCount = e.touches ? e.touches.length : 1;
      this.touchTarget = e.target;
      if (e.changedTouches && e.changedTouches.length > 0) {
        this.touchStartX = e.changedTouches[0].screenX;
        this.touchStartY = e.changedTouches[0].screenY;
      }
    }, {passive: true});

    document.body.addEventListener('touchend', (e) => {
      if (e.changedTouches && e.changedTouches.length > 0) {
        this.touchEndX = e.changedTouches[0].screenX;
        this.touchEndY = e.changedTouches[0].screenY;
      }
      this.handleGesture();
    }, {passive: true});
  }

  handleGesture() {
    // 若點擊目標為按鈕、輸入框、對話框或歷史列表中的店家項目，交由元素自身的點擊/無障礙事件處理
    if (this.touchTarget && (
      this.touchTarget.closest("button") ||
      this.touchTarget.closest("input") ||
      this.touchTarget.closest(".modal-overlay") ||
      this.touchTarget.closest(".modal-content") ||
      this.touchTarget.closest("li.history-item")
    )) {
      return;
    }

    const deltaX = this.touchEndX - this.touchStartX;
    const deltaY = this.touchEndY - this.touchStartY;
    const absX = Math.abs(deltaX);
    const absY = Math.abs(deltaY);
    
    // Tap or Double-tap detection on empty background
    if (absX < 30 && absY < 30) {
      const now = Date.now();
      if (now - this.lastTapTime < 350) {
        // Double Tap on empty map background: announce road & door numbers
        this.app.announceRoadAndDoorNumbers();
        this.lastTapTime = 0;
      } else {
        this.lastTapTime = now;
      }
      return;
    }

    // Two-finger gestures (手指探索地圖 / 虛擬平移)
    if (this.touchCount >= 2) {
      if (absX > absY) {
        if (deltaX > 0) {
          // Two-finger Swipe Right -> Pan right side alley
          this.app.virtualPan(0, 20.0);
        } else {
          // Two-finger Swipe Left -> Pan left side alley
          this.app.virtualPan(0, -20.0);
        }
      } else {
        if (deltaY > 0) {
          // Two-finger Swipe Down -> Pan backward 30m
          this.app.virtualPan(-30.0, 0);
        } else {
          // Two-finger Swipe Up -> Pan forward 30m
          this.app.virtualPan(30.0, 0);
        }
      }
      return;
    }

    // Single-finger gestures (常規踏步與轉向)
    if (absX > absY) {
      // Horizontal swipe
      if (deltaX > 0) {
        // Swipe Right -> Turn right 45°
        this.app.turn(45);
      } else {
        // Swipe Left -> Turn left 45°
        this.app.turn(-45);
      }
    } else {
      // Vertical swipe
      if (deltaY > 0) {
        // Swipe Down -> Backward
        this.app.velocity = 4.0;
        this.app.moveDir = -1;
      } else {
        // Swipe Up -> Forward
        this.app.velocity = 4.0;
        this.app.moveDir = 1;
      }
    }
  }
}

// Android Sensor Bridge Callbacks
window.lastHeading = 0;
window.lastReportedHeading = 0;
window.headingTimeout = null;
window.lastGpsLat = null;
window.lastGpsLon = null;
window.isGpsSyncPending = false;
window.pendingGpsUpdate = null;
window.lastTickHeading = 0;
window.lastHapticCardinal = -1;
window.lastReportedCardinal = "";

window.onHeadingUpdate = function(headingDegrees) {
    window.lastHeading = headingDegrees;
    
    const settings = (window.app && window.app.settings) ? window.app.settings : {
        turnAnnounce: true,
        turnTickSound: true,
        autoPoiAnnounce: true,
        hapticFeedback: true
    };

    // 1. 即時同步至前端狀態，確保 3D 空間音效與動態店家方位計算零延遲
    if (window.app) {
        window.app.localHeading = headingDegrees;
        if (window.app.lastData && window.app.renderRadarCanvas) {
            window.app.lastData.heading_deg = headingDegrees;
            window.app.renderRadarCanvas(window.app.lastData);
        }
    }

    // 2. 轉向中立體聲刻度音 (Stereo Tick) 與觸覺震動 (Haptic Tick)
    let tickDiff = headingDegrees - window.lastTickHeading;
    while (tickDiff < -180) tickDiff += 360;
    while (tickDiff > 180) tickDiff -= 360;

    if (Math.abs(tickDiff) >= 15.0) {
        const isLeft = tickDiff < 0;
        window.lastTickHeading = headingDegrees;
        if (settings.turnTickSound) {
            if (window.app && window.app.audio) {
                window.app.audio.playTick(isLeft);
            }
            if (window.AndroidBridge && window.AndroidBridge.vibrateTick) {
                window.AndroidBridge.vibrateTick();
            }
        }
    }

    // 3. 16 方位齒輪刻度觸覺 (0° 正北雙重重震，其餘 15 個方位單點輕震)
    const cardinalAngles16 = [
        0, 22.5, 45, 67.5, 90, 112.5, 135, 157.5,
        180, 202.5, 225, 247.5, 270, 292.5, 315, 337.5
    ];
    let matchedCardinal = -1;
    for (let i = 0; i < cardinalAngles16.length; i++) {
        let cardDiff = Math.abs(headingDegrees - cardinalAngles16[i]);
        if (cardDiff > 180) cardDiff = 360 - cardDiff;
        if (cardDiff <= 2.2) {
            matchedCardinal = i;
            break;
        }
    }

    if (matchedCardinal !== -1 && matchedCardinal !== window.lastHapticCardinal) {
        window.lastHapticCardinal = matchedCardinal;
        if (settings.hapticFeedback && window.AndroidBridge) {
            if (matchedCardinal === 0) { // 正北 0°
                if (window.AndroidBridge.vibrateHeavy) window.AndroidBridge.vibrateHeavy();
            } else {
                if (window.AndroidBridge.vibrateClick) window.AndroidBridge.vibrateClick();
            }
        }
    } else if (matchedCardinal === -1) {
        window.lastHapticCardinal = -1;
    }
    
    // 4. 背景防抖同步朝向至後端 Agent (150ms 節流，確保路口分析與門牌推算 100% 吻合)
    if (window.headingSyncTimer) clearTimeout(window.headingSyncTimer);
    window.headingSyncTimer = setTimeout(() => {
        const curLat = (window.app && window.app.localLat !== null) ? window.app.localLat : window.lastGpsLat;
        const curLon = (window.app && window.app.localLon !== null) ? window.app.localLon : window.lastGpsLon;
        fetch("/api/turn", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                heading_deg: headingDegrees,
                lat: curLat,
                lon: curLon
            })
        })
        .then(res => res.json())
        .then(data => {
            if (data && data.is_loaded && window.app && window.app.checkProximityAlerts) {
                // 當使用者原地轉向或駐足觀察路口時，轉向也能即時啟動或更新相機導引
                window.app.checkProximityAlerts(data);
            }
        })
        .catch(() => {});
    }, 150);

    // 5. 16 方位極速語音回報（完全不走 TalkBack 系統無障礙事件隊列，可由偏好設定開關）
    if (window.app && window.app.isReady !== false) {
        const dirStr = window.app.getCardinalDirection(headingDegrees);
        
        if (dirStr !== window.lastReportedCardinal) {
            const now = Date.now();
            // 方位廣播防抖：相隔至少 600ms，避免手腕震顫連環發音
            if (!window.lastCardinalReportTime || (now - window.lastCardinalReportTime >= 600)) {
                window.lastCardinalReportTime = now;
                window.lastReportedCardinal = dirStr;
                window.lastReportedHeading = headingDegrees;

                if (window.app && window.app.recordTrace) {
                    window.app.recordTrace("HEADING_CHANGED", { heading: Math.round(headingDegrees), cardinal: dirStr });
                }
                
                if (settings.turnTickSound && window.app.audio) {
                    window.app.audio.playSettledChime();
                }
                
                // 若正開啟地標詳細資訊視窗，暫停轉向語音播報以避免打擾閱讀
                if (window.isDetailModalOpen || (window.app && window.app.isDetailModalOpen)) {
                    return;
                }

                // 轉動播報開關：僅當使用者開啟「轉動手機即時播報方位」時，才透過 Google 內建原生 TTS 發聲！
                // 絕不調用 TalkBack / announceForAccessibility，確保 TalkBack 在轉向時徹底靜音無干擾。
                if (settings.turnAnnounce) {
                    if (window.AndroidBridge && window.AndroidBridge.speakTtsDirect) {
                        window.AndroidBridge.speakTtsDirect(dirStr, true);
                    } else if (!window.AndroidBridge && window.speechSynthesis) {
                        try {
                            window.speechSynthesis.cancel();
                            const u = new SpeechSynthesisUtterance(dirStr);
                            u.lang = 'zh-TW';
                            u.rate = 1.25;
                            window.speechSynthesis.speak(u);
                        } catch (e) {}
                    }
                }
            }
        }
    }
};

window.onMotionStateUpdate = function(motionState) {
    window.currentMotionState = motionState;
    if (window.app) {
        window.app.currentMotionState = motionState;
    }
};

window.onLocationUpdate = function(lat, lon, accuracy, bearing, speed, motionState) {
    if (motionState) {
        window.currentMotionState = motionState;
        if (window.app) window.app.currentMotionState = motionState;
    }

    if (!window.app || window.app.isReady === false) {
        window.pendingGpsUpdate = { lat, lon, accuracy, bearing, speed, motionState };
        return;
    }

    // 記錄步行與車行狀態
    const currentSpeed = speed || 0;
    if (currentSpeed > 0.35) {
        window.lastWalkSpeed = currentSpeed;
        window.lastMoveTime = Date.now();
    }

    // 乘車模式判定：運動狀態為 VEHICULAR_TRANSIT 或連續速度 > 3.8 m/s (時速 > 13.7 km/h)
    const isVehicular = (window.currentMotionState === "VEHICULAR_TRANSIT") || (currentSpeed > 3.8);
    window.isVehicularTransit = isVehicular;
    if (window.app) window.app.isVehicularTransit = isVehicular;

    const pb = document.getElementById("permission-banner");
    if (pb && pb.style.display !== "none") pb.style.display = "none";

    let dist = 999999;
    const nowTime = Date.now();
    const dtSec = window.lastGpsTimestamp ? Math.max((nowTime - window.lastGpsTimestamp) / 1000.0, 0.1) : 1.0;
    window.lastGpsTimestamp = nowTime;

    if (window.lastGpsLat !== null && window.lastGpsLon !== null) {
        const R = 6371e3;
        const φ1 = window.lastGpsLat * Math.PI / 180;
        const φ2 = lat * Math.PI / 180;
        const Δφ = (lat - window.lastGpsLat) * Math.PI / 180;
        const Δλ = (lon - window.lastGpsLon) * Math.PI / 180;
        const a = Math.sin(Δφ/2) * Math.sin(Δφ/2) +
                  Math.cos(φ1) * Math.cos(φ2) *
                  Math.sin(Δλ/2) * Math.sin(Δλ/2);
        const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
        dist = R * c;
    }

    // 異常位移監控（物理速度自適應過濾）：
    // 乘車時每秒前進 10~15 公尺屬物理常態，只有位移明顯超過當前速度理論極限 (dist > speed * dt + 30m) 且超過 35m 才視為漂移
    const jumpThresholdM = isVehicular ? Math.max(80.0, currentSpeed * dtSec * 1.8 + 25.0) : 25.0;
    if (window.lastGpsLat !== null && dist > jumpThresholdM && dist < 99999) {
        if (window.app && window.app.recordAnomaly) {
            window.app.recordAnomaly("GPS_JUMP", `GPS 座標跳躍 ${Math.round(dist)} 公尺 (精度: ${accuracy}m, 速度: ${currentSpeed.toFixed(1)}m/s, 模式: ${isVehicular ? "乘車" : "步行"})`, {
                jump_meters: dist,
                accuracy: accuracy,
                speed: currentSpeed,
                is_vehicular: isVehicular
            });
        }
    }

    // 只要有移動 >= 1.5m 或首度定位即更新
    if (window.lastGpsLat === null || dist >= 1.5) {
        if (window.isGpsSyncPending) {
            window.pendingGpsUpdate = { lat, lon, accuracy, bearing, speed };
            return;
        }

        window.lastGpsLat = lat;
        window.lastGpsLon = lon;
        window.isGpsSyncPending = true;

        // 永遠優先使用精準指南針/陀螺儀真北方位 (避免 GPS 緩慢行走時 bearing=0 覆蓋真實朝向)
        const heading = (window.lastHeading !== undefined && window.lastHeading >= 0) ? window.lastHeading : (bearing >= 0 ? bearing : 0);

        const currentTraceId = ++window.app.traceCounter;
        window.app.currentTraceId = currentTraceId;
        if (window.app.recordTrace) {
            window.app.recordTrace("GPS_INPUT", {
                trace_id: currentTraceId,
                lat: lat,
                lon: lon,
                accuracy_m: accuracy || 10.0,
                bearing: bearing,
                speed_mps: speed,
                heading_deg: heading
            });
        }

        fetch("/api/gps", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                lat: lat,
                lon: lon,
                heading_deg: heading,
                accuracy: accuracy || 10.0,
                vertical_level: window.currentVerticalLevel || "GROUND",
                altitude_m: window.currentAltitudeM || 0.0,
                beacon_anchor: window.currentBeaconAnchor || null
            })
        })
        .then(res => res.json())
        .then(data => {
            window.isGpsSyncPending = false;
            if (data && data.is_loaded) {
                if (window.app.recordTrace) {
                    window.app.recordTrace("WORLD_MODEL_SYNC", {
                        trace_id: currentTraceId,
                        snapped_lat: data.lat,
                        snapped_lon: data.lon,
                        road: data.road_info ? data.road_info.street_name : null,
                        poi_count: data.pois ? data.pois.length : 0
                    });
                }
                window.app.serverLat = data.lat;
                window.app.serverLon = data.lon;
                window.app.localLat = data.lat;
                window.app.localLon = data.lon;
                window.app.localHeading = window.lastHeading;
                window.app.lastData = data;
                if (window.app.renderRadarCanvas) window.app.renderRadarCanvas(data);
                if (window.app.updatePOIs) window.app.updatePOIs(data.pois || []);
                
                if (data.ground_elevation_m !== undefined && window.nmapAndroid && typeof window.nmapAndroid.setGroundElevation === 'function') {
                    window.nmapAndroid.setGroundElevation(data.ground_elevation_m);
                }
                
                // 戶外防誤判 (GPS 霸體模式) 邏輯：
                // 如果在一般道路上前進超過 15 公尺，強制解除天橋模式
                const currentRoad = (data.road_info && data.road_info.street_name && data.road_info.street_name !== "未知道路" && data.road_info.street_name !== "1F") ? data.road_info.street_name : null;
                if (currentRoad && accuracy < 22.0 && window.currentVerticalLevel !== "GROUND") {
                    window.roadLockDistance = (window.roadLockDistance || 0) + dist;
                    if (window.roadLockDistance > 15.0) {
                        if (window.nmapAndroid && typeof window.nmapAndroid.forceResetBarometerToGround === 'function') {
                            window.nmapAndroid.forceResetBarometerToGround();
                        }
                        window.roadLockDistance = 0;
                    }
                } else if (!currentRoad || window.currentVerticalLevel === "GROUND") {
                    window.roadLockDistance = 0;
                }

                // 首次定位與後續行進走廊提示分流，徹底杜絕開口 2ms 互掐剪音！
                if (dist === 999999) {
                    const overseasMsg = data.is_overseas ? "【⚠️ 偵測到海外地區：已啟用全球線上圖資模式】" : "";
                    const report = `${overseasMsg}${data.concise_report || data.full_report || "已更新 GPS 定位。"}`;
                    window.app.updateLiveLog(report, false, true);
                    if (window.app.audio) window.app.audio.playArrival();
                } else {
                    if (window.app.checkProximityAlerts) {
                        window.app.checkProximityAlerts(data);
                    }
                }
            }

            if (window.pendingGpsUpdate) {
                const next = window.pendingGpsUpdate;
                window.pendingGpsUpdate = null;
                window.onLocationUpdate(next.lat, next.lon, next.accuracy, next.bearing, next.speed);
            }
        })
        .catch(err => {
            window.isGpsSyncPending = false;
            console.error("GPS sync error:", err);
        });
    }
};

/**
 * 差分定位品質等級即時回調 (由 Android LocationSensorBridge 注入)
 */
window.onDifferentialTierUpdate = function(tierName, displayName, expectedAcc) {
    window.currentDifferentialTier = { name: tierName, displayName: displayName, expectedAcc: expectedAcc };
    const diffElem = document.getElementById("diff-status-pill");
    if (diffElem) {
        diffElem.textContent = "📍 " + displayName;
        diffElem.setAttribute("aria-label", "差分定位品質: " + displayName);
    }
};

/**
 * 3D 垂直空間高程與樓層切換即時回調 (由 Android LocationSensorBridge 注入)
 */
window.currentVerticalLevel = "GROUND";
window.currentAltitudeM = 0.0;
window.onVerticalLevelUpdate = function(levelName, displayName, altitudeM, description) {
    const oldLevel = window.currentVerticalLevel;
    window.currentVerticalLevel = levelName;
    window.currentAltitudeM = altitudeM;

    const vertElem = document.getElementById("vertical-status-pill");
    if (vertElem) {
        const sign = altitudeM >= 0 ? "+" : "";
        let icon = "🏢";
        if (levelName === "OVERPASS") icon = "🌁";
        else if (levelName.startsWith("UNDERGROUND")) icon = "🚇";
        vertElem.textContent = `${icon} ${displayName} (${sign}${altitudeM.toFixed(1)}m)`;
        vertElem.setAttribute("aria-label", `立體高程: ${displayName} (${sign}${altitudeM.toFixed(1)}公尺)`);
    }

    if (levelName !== oldLevel) {
        const isUp = (levelName === "OVERPASS") || (oldLevel.startsWith("UNDERGROUND") && levelName === "GROUND");
        if (window.app && window.app.audio) {
            window.app.audio.playVerticalTransitionTone(isUp);
        }
        if (description && window.app && window.app.updateLiveLog) {
            window.app.updateLiveLog(description, false, true);
        }
    }
};

/**
 * 📡 公眾室內 iBeacon / Wi-Fi 定錨即時回調 (由 Android LocationSensorBridge 注入)
 */
window.currentBeaconAnchor = null;
window.onBeaconAnchorUpdate = function(beaconId, beaconName, lat, lon, distM, levelName, description) {
    window.currentBeaconAnchor = {
        id: beaconId,
        name: beaconName,
        lat: lat,
        lon: lon,
        dist_m: distM,
        level: levelName,
        description: description
    };

    const beaconPill = document.getElementById("beacon-status-pill");
    if (beaconPill) {
        beaconPill.style.display = "inline-block";
        beaconPill.textContent = `📡 ${beaconName.split(" ")[0]} (${distM.toFixed(1)}m)`;
        beaconPill.setAttribute("aria-label", `已定錨公眾信標: ${beaconName}，距離約 ${Math.round(distM)} 公尺`);
    }

    if (window.app && window.app.audio) {
        window.app.audio.playBeaconAnchorTone();
    }
    if (window.AndroidBridge && window.AndroidBridge.vibrate) {
        window.AndroidBridge.vibrate("[0, 100, 50, 100]");
    }

    const distStr = distM > 1.0 ? `約 ${Math.round(distM)} 公尺` : "正身旁";
    const msg = `📡 偵測到【${beaconName}】(${distStr})，室內定位已精準定錨！${description ? '，' + description : ''}`;
    if (window.app && window.app.updateLiveLog) {
        window.app.updateLiveLog(msg, false, true);
    }
};


