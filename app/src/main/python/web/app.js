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

  // Item 3.3: 3D Spatial HRTF PannerNode Audio Cue
  playSpatialTone(frequency = 440, type = 'sine', x = 0, y = 0, z = -1, duration = 0.15) {
    if (!this.enabled) return;
    this.initContext();
    if (!this.ctx) return;

    try {
      const osc = this.ctx.createOscillator();
      const gain = this.ctx.createGain();
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

      osc.type = type;
      osc.frequency.setValueAtTime(frequency, this.ctx.currentTime);

      gain.gain.setValueAtTime(0.3, this.ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, this.ctx.currentTime + duration);

      osc.connect(gain);
      gain.connect(panner);
      panner.connect(this.ctx.destination);

      osc.start();
      osc.stop(this.ctx.currentTime + duration);
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

  playBeacon(relBearing = 0, distM = 5) {
    if (!this.enabled) return;
    const rad = relBearing * Math.PI / 180.0;
    const distAudio = Math.max(0.5, Math.min(10.0, distM));
    const x = distAudio * Math.sin(rad);
    const z = -distAudio * Math.cos(rad);
    this.playSpatialTone(880, 'sine', x, 0, z, 0.15);
  }

  playArrival() {
    if (!this.enabled) return;
    this.initContext();
    if (!this.ctx) return;

    try {
      [523, 659, 784].forEach((freq, i) => {
        setTimeout(() => {
          this.playSpatialTone(freq, 'sine', (i - 1) * 0.5, 0, -1, 0.12);
        }, i * 70);
      });
    } catch (e) {}
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

    
    // RPG Game Loop State
    this.keysDown = {};
    this.rafId = null;
    this.localLat = null;
    this.localLon = null;
    this.localHeading = 0;
    this.serverLat = null;
    this.lastData = null;
    this.announcedPoiCooldown = new Map();
    this.lastIntersectionAlertTime = 0;
    this.lastSpeechTime = Date.now();
    this.currentStreetName = null;
    this.passedIntersectionTracking = false;

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
    if (this.sessionCausalityTrace.length > 1500) {
      this.sessionCausalityTrace.shift();
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
            this.recordInteraction("點擊按鈕", "左右兩側掃描 (F)");
            this.announceLeftRightSweep();
        });
    }

    const uiBtnAround = document.getElementById("ui-btn-around");
    if (uiBtnAround) {
        uiBtnAround.addEventListener("click", () => {
            this.recordInteraction("點擊按鈕", "周遭設施探索 (Enter)");
            this.announceAllPOIs();
        });
    }

    const uiBtnIntersection = document.getElementById("ui-btn-intersection");
    if (uiBtnIntersection) {
        uiBtnIntersection.addEventListener("click", () => {
            this.recordInteraction("點擊按鈕", "前方路口狀況 (I)");
            this.announceUpcomingIntersection();
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

    // Modal Actions Wiring
    const poiCloseBtn = document.getElementById("poi-modal-close-btn");
    const poiDismissBtn = document.getElementById("poi-modal-dismiss");
    const poiNavNmapBtn = document.getElementById("poi-modal-nav-nmap");
    const poiNavGmapsBtn = document.getElementById("poi-modal-nav-gmaps");

    if (poiCloseBtn) poiCloseBtn.addEventListener("click", () => this.closePoiModal());
    if (poiDismissBtn) poiDismissBtn.addEventListener("click", () => this.closePoiModal());
    if (poiNavNmapBtn) poiNavNmapBtn.addEventListener("click", () => this.startBeaconToTarget());
    if (poiNavGmapsBtn) poiNavGmapsBtn.addEventListener("click", () => this.launchGoogleMapsNavigation());

    // ESC key closes modal
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        this.closePoiModal();
      }
    });

    // Check location permission on cold start
    if (window.AndroidBridge && window.AndroidBridge.hasLocationPermission) {
      if (!window.AndroidBridge.hasLocationPermission()) {
        if (permBanner) permBanner.style.display = "block";
        this.updateLiveLog("📍 定位權限未開啟，已進入手動探索模式。請直接輸入地址開始探索，或點擊開啟系統設定。", false, true);
      }
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
          this.announceAllPOIs();
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

        // I = Intersection: 前方路口資訊與分支走向
        case "i":
        case "I":
          e.preventDefault();
          this.announceUpcomingIntersection();
          break;

        // L = Left/Right Sweep: 左右兩側店家掃描
        case "l":
        case "L":
          e.preventDefault();
          this.announceLeftRightSweep();
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
      // Many Chinese phrases might use space or '。' for separation in our system
      let parts = text.split(/。|\n/).filter(p => p.trim().length > 0);
      
      parts.forEach(part => {
        const li = document.createElement("li");
        li.className = "history-item";
        li.tabIndex = 0;
        // Append a period to make the screen reader pause nicely
        li.textContent = part.trim() + "。";
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

  // 隨時根據「當前即時朝向」與「即時座標」重新動態推算所有店家的相對左右/鐘點方位
  getRealtimePois() {
    if (!this.lastPois || this.lastPois.length === 0) return [];
    const curLat = this.localLat !== null ? this.localLat : (this.serverLat || 0);
    const curLon = this.localLon !== null ? this.localLon : (this.serverLon || 0);
    const curHead = (this.localHeading !== null && this.localHeading !== undefined) ? this.localHeading : (window.lastHeading || 0);

    return this.lastPois.map((p) => {
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
    const modal = document.getElementById("poi-detail-modal");
    const title = document.getElementById("poi-modal-title");
    const body = document.getElementById("poi-modal-body");
    if (!modal || !title || !body) return;

    title.textContent = poi.name;
    const cat = this.translateCategory(poi.category);
    const wheelchair = poi.wheelchair === "yes" ? "♿ 具備無障礙通行" : (poi.wheelchair === "no" ? "⚠️ 無無障礙設施" : "無障礙狀態未知");
    
    let infoRows = [
      `<div><strong>📍 類別：</strong>${cat}</div>`,
      `<div><strong>🧭 方位：</strong>${poi.clock_position || '正前方'} (${poi.relative_direction || '前方'})</div>`,
      `<div><strong>📏 距離：</strong>約 ${poi.distance_m} 公尺 (座標: ${poi.lat.toFixed(5)}, ${poi.lon.toFixed(5)})</div>`,
      `<div><strong>♿ 無障礙：</strong>${wheelchair}</div>`
    ];

    if (poi.opening_hours) {
      infoRows.push(`<div><strong>⏰ 營業時間：</strong>${poi.opening_hours}</div>`);
    }
    if (poi.phone) {
      infoRows.push(`<div><strong>📞 電話：</strong><a href="tel:${poi.phone}" style="color:#38bdf8; text-decoration:underline;">${poi.phone}</a></div>`);
    }
    if (poi.cuisine) {
      infoRows.push(`<div><strong>🍽️ 料理風味：</strong>${poi.cuisine}</div>`);
    }

    body.innerHTML = infoRows.join("");
    modal.style.display = "flex";
    body.focus();

    if (this.audio) this.audio.playSpatialTone(660, 'sine', 0, 0, -1, 0.1);
    this.updateLiveLog(`開啟地標詳情：${poi.name}，距離 ${poi.distance_m} 公尺，位於 ${poi.clock_position}`, false, true);
  }

  closePoiModal() {
    const modal = document.getElementById("poi-detail-modal");
    if (modal) modal.style.display = "none";
    this.updateLiveLog("已關閉地標詳情對話框。", false, true);
  }

  startBeaconToTarget() {
    if (!this.activePoiTarget) return;
    const target = this.activePoiTarget;
    this.updateLiveLog(`已設定【${target.name}】為目標。開始 3D 空間聲音導引。`, false, true);
    this.closePoiModal();

    if (this.beaconInterval) clearInterval(this.beaconInterval);
    
    // Play beacon step every 3 seconds
    const playBeaconStep = () => {
      if (!this.activePoiTarget || !this.localLat || !this.localLon) return;
      const targetBrng = NMapGeometry.calculateBearing(this.localLat, this.localLon, target.lat, target.lon);
      const relBrng = NMapGeometry.relativeBearing(this.localHeading || 0, targetBrng);
      const dist = NMapGeometry.haversineDistance(this.localLat, this.localLon, target.lat, target.lon);
      
      if (dist <= 3.0) {
        if (this.audio) this.audio.playArrival();
        this.updateLiveLog(`🎉 已抵達目標：${target.name}！`, false, true);
        clearInterval(this.beaconInterval);
        this.beaconInterval = null;
        return;
      }
      
      if (this.audio) this.audio.playBeacon(relBrng, dist);
    };

    playBeaconStep();
    this.beaconInterval = setInterval(playBeaconStep, 3000);
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

  announceAllPOIs() {
    const realtimePois = this.getRealtimePois();
    if (!realtimePois || realtimePois.length === 0) {
      this.updateLiveLog("【周遭掃描】100 公尺內無特別設施標籤。", false, true);
      return;
    }
    
    this.audio.playSpatialTone(660, 'sine', 0, 0, -1, 0.15);
    
    let msg = `【周遭共發現 ${realtimePois.length} 家店】\n`;
    const lines = realtimePois.map(p => {
        const cat = this.translateCategory(p.category);
        return `${p.name} (${p.relative_direction} ${p.distance_m}m，${cat})`;
    });
    
    msg += lines.join("\n");
    this.updateLiveLog(msg, false, true);
  }

  announceRoadAndDoorNumbers() {
    fetch("/api/status")
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
        
        if (leftVal && rightVal) {
          doorStr = `，左側${leftVal}，右側${rightVal}`;
        } else if (leftVal) {
          doorStr = `，左側${leftVal}`;
        } else if (rightVal) {
          doorStr = `，右側${rightVal}`;
        } else if (concise) {
          doorStr = `，${concise}`;
        } else {
          doorStr = "";
        }
        
        this.currentRoadName = street;
        this.lastSpokenDoor = doorStr;

        const headingDeg = (data.heading_deg !== undefined && data.heading_deg !== null) ? data.heading_deg : (this.localHeading || 0);
        const dirStr = this.getCardinalDirection(headingDeg);
        const exactDeg = Math.round(((headingDeg % 360.0) + 360.0) % 360.0);
        const gpsStr = `GPS座標：${data.lat.toFixed(5)}, ${data.lon.toFixed(5)}`;
        
        const txt = `走在【${street}】${doorStr}。面向${dirStr} (${exactDeg}°)。${gpsStr}。`;
        
        this.audio.playSpatialTone(480, 'triangle', 0, 0, -0.8, 0.12);
        this.updateLiveLog(`【目前位置】\n${txt}`, false, true);
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
    fetch("/api/intersection")
      .then((res) => res.json())
      .then((data) => {
        if (data.success && data.report) {
          this.lastSpokenIntersection = data.report;
          this.audio.playArrival();
          this.updateLiveLog(data.report, false, true);
        } else {
          this.updateLiveLog(data.message || "前方路口資料讀取失敗。", true);
        }
      })
      .catch(() => {
        this.updateLiveLog("無法連線至路口分析模組。", true);
      });
  }

  // ========== 接近感知播報 (店家 3~5m / 接近與通過路口 / 20s 靜默路名門牌) ==========
  checkProximityAlerts(data) {
    if (!data || !data.is_loaded) return;
    const now = Date.now();

    // 1. 接近中的店家（以即時推算之方位與距離判斷，嚴格限制在 2.5 ~ 6.0 公尺前夕才播報）
    const realtimePois = this.getRealtimePois();
    if (realtimePois && realtimePois.length > 0) {
      const nearbyPassing = realtimePois.filter((p) => {
        const d = p.distance_m;
        const dir = p.relative_direction || "";
        // 2.0 ~ 6.0 公尺（即將經過前夕）才朗讀，且非背後
        return d <= 6.0 && d >= 0.5 && (!dir.includes("後方") || d <= 3.0);
      });

      if (nearbyPassing.length > 0) {
        for (const poi of nearbyPassing) {
          const lastTime = this.announcedPoiCooldown.get(poi.name) || 0;
          if (now - lastTime > 60000) { // 60秒冷卻，避免同店家重複疲勞轟炸
            this.announcedPoiCooldown.set(poi.name, now);

            // 精確 3D 空間立體聲：以相對夾角精確計算左右耳座標 (x, z)
            const rad = (poi.relative_bearing_deg || 0) * Math.PI / 180.0;
            const distAudio = Math.max(0.5, Math.min(10.0, poi.distance_m || 3.0));
            const x = distAudio * Math.sin(rad);
            const z = -distAudio * Math.cos(rad);
            this.audio.playSpatialTone(660, 'triangle', x, 0, z, 0.15);

            // 省話模式：極簡只讀店名 + 即時動態方位 (如：「全家便利商店，右側」或「星巴克，左前方」)
            const dirText = poi.relative_direction ? `，${poi.relative_direction}` : "";
            const msg = `${poi.name}${dirText}`;
            this.updateLiveLog(msg, false, true);
            this.lastSpeechTime = now;
            return; // 每次只報讀最接近的一間，避免語音塞車
          }
        }
      }
    }

    // 2. 接近路口提示 (15公尺以內) 與 過了路口立即播報走在哪條馬路
    if (data.intersection) {
      const juncType = data.intersection.junction_type;
      const juncDist = data.intersection.junction_distance_m;
      
      // A. 接近路口（<= 15m）
      if (juncType && juncType !== "直行道路" && juncDist !== null && juncDist <= 15.0) {
        this.passedIntersectionTracking = true;
        if (now - this.lastIntersectionAlertTime > 45000) { // 45秒冷卻
          this.lastIntersectionAlertTime = now;
          this.audio.playSpatialTone(550, 'sine', 0, 0, -1, 0.2);

          let roads = "";
          const currentRoad = (data.road_info && data.road_info.street_name && data.road_info.street_name !== "未知道路") ? data.road_info.street_name : "";
          const filteredRoads = (data.intersection.intersecting_roads || []).filter(r => r && r !== currentRoad && r !== "未命名道路");
          if (filteredRoads.length > 0) {
            roads = `，即將交會 ${filteredRoads.join("、")}`;
          }
          const msg = `📍 接近【${juncType}】（約 ${Math.round(juncDist)} 公尺）${roads}。`;
          this.updateLiveLog(msg, false, true);
          this.lastSpeechTime = now;
          return;
        }
      }
      
      // B. 過了路口（從 <=15m 走到 >18m 或路口消失）-> 馬上告訴使用者走在哪條馬路上
      if (this.passedIntersectionTracking && (juncDist === null || juncDist > 18.0)) {
        this.passedIntersectionTracking = false;
        this.lastSpeechTime = now;
        this.audio.playArrival();
        const currentRoad = (data.road_info && data.road_info.street_name && data.road_info.street_name !== "未知道路") ? data.road_info.street_name : "目前道路";
        const msg = `過路口，走在【${currentRoad}】`;
        this.updateLiveLog(msg, false, true);
        return;
      }
    }

    // 3. 轉彎進入新路名即時播報
    if (data.road_info && data.road_info.street_name && data.road_info.street_name !== "未知道路") {
      const st = data.road_info.street_name;
      if (this.currentStreetName !== null && st !== this.currentStreetName) {
        this.currentStreetName = st;
        this.lastSpeechTime = now;
        this.audio.playArrival();
        this.updateLiveLog(`進入【${this.currentStreetName}】`, false, true);
        return;
      } else if (this.currentStreetName === null) {
        this.currentStreetName = st;
      }
    }

    // 4. 若都沒有店家 / 語音安靜超過 20 秒，精簡播報當前走在哪條路上與大約門牌號碼
    if (now - this.lastSpeechTime >= 20000) {
      if (data.road_info && data.road_info.street_name && data.road_info.street_name !== "未知道路") {
        this.lastSpeechTime = now;
        const street = data.road_info.street_name;
        const door = (data.door_estimates && data.door_estimates.concise_door) ? data.door_estimates.concise_door : "";
        const msg = door ? `${street}，${door}` : `走在${street}`;
        this.audio.playSpatialTone(480, 'sine', 0, 0, -1, 0.1);
        this.updateLiveLog(msg, false, true);
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

    // 本地 OSM 資料（即時播報）
    const lines = [`【店家詳情】${p.name}`];
    lines.push(`• 位置：${p.clock_position}（${p.relative_direction}）${p.distance_m} 公尺`);
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

    // 非同步抓取 Google Places 資料
    fetch("/api/poi/enrich", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: p.name, lat: p.lat, lon: p.lon })
    })
      .then(res => res.json())
      .then(g => {
        if (!g.available) return;
        const gLines = [...lines];
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
    if (!this.lastPois || this.lastPois.length === 0) {
      this.updateLiveLog("【L 左右掃描】周遭無店家。", false, true);
      return;
    }

    const leftPois = this.lastPois
      .filter(p => p.relative_direction && p.relative_direction.includes("左"))
      .sort((a, b) => a.distance_m - b.distance_m);

    const rightPois = this.lastPois
      .filter(p => p.relative_direction && p.relative_direction.includes("右"))
      .sort((a, b) => a.distance_m - b.distance_m);

    const frontPois = this.lastPois
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

    this.updateLiveLog(lines.join("\n"), false, true);
    if (this.liveLog && this.liveLog.firstElementChild) this.liveLog.firstElementChild.focus();

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
          
          if (this.lastData) {
              this.lastData.heading_deg = this.localHeading;
              this.renderRadarCanvas(this.lastData);
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
      const index = Math.round(normalized / 22.5) % 16;
      return dirs16[index];
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

  // 顯示無障礙更新對話框 (Show Accessible Update Dialog)
  showUpdateDialog(latestVer, title, downloadUrl, notes) {
    const modal = document.getElementById("update-modal");
    const body = document.getElementById("update-modal-body");
    const confirmBtn = document.getElementById("update-btn-confirm");
    const cancelBtn = document.getElementById("update-btn-cancel");
    const progContainer = document.getElementById("update-progress-container");
    if (!modal || !body) return;

    body.innerHTML = `<p><strong>最新版本：v${latestVer}</strong></p><p><strong>${title || '新版本發布'}</strong></p><div style="max-height:120px;overflow-y:auto;color:#cbd5e1;font-size:0.95em;margin-top:6px;white-space:pre-line;">${notes || "無更新日誌說明"}</div>`;
    modal.style.display = "flex";
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
        modal.style.display = "none";
      };
    }
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

window.onUpdateCheckResult = (status, info) => {
  if (status === 'latest' && window.app) {
    window.app.updateLiveLog(`目前已是最新版本 (v${info})。`);
  }
};

document.addEventListener("DOMContentLoaded", () => {
  window.app = new NmapWebApp();
  window.touchCtrl = new TouchGestureController(window.app);
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
    this.touchCount = 1;
    this.lastTapTime = 0;
    
    // Add touch listener to the whole body
    document.body.addEventListener('touchstart', (e) => {
      this.touchCount = e.touches ? e.touches.length : 1;
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
    const deltaX = this.touchEndX - this.touchStartX;
    const deltaY = this.touchEndY - this.touchStartY;
    const absX = Math.abs(deltaX);
    const absY = Math.abs(deltaY);
    
    // Tap or Double-tap detection
    if (absX < 30 && absY < 30) {
      const now = Date.now();
      if (now - this.lastTapTime < 350) {
        // Double Tap: announce road & door numbers
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
        if (window.app && window.app.audio) {
            window.app.audio.playTick(isLeft);
        }
        if (window.AndroidBridge && window.AndroidBridge.vibrateTick) {
            window.AndroidBridge.vibrateTick();
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
        if (window.AndroidBridge) {
            if (matchedCardinal === 0) { // 正北 0°
                if (window.AndroidBridge.vibrateHeavy) window.AndroidBridge.vibrateHeavy();
            } else {
                if (window.AndroidBridge.vibrateClick) window.AndroidBridge.vibrateClick();
            }
        }
    } else if (matchedCardinal === -1) {
        window.lastHapticCardinal = -1;
    }
    
    // 4. 即時極簡 16 方位語音回報 (省話模式：只報方位，如「北北東」、「正東」)
    if (window.app && window.app.isReady !== false) {
        const now = Date.now();
        const isWalking = (now - (window.lastMoveTime || 0) < 3000) && ((window.lastWalkSpeed || 0) >= 0.4);
        const dirStr = window.app.getCardinalDirection(headingDegrees);
        
        if (dirStr !== window.lastReportedCardinal) {
            if (window.headingTimeout) clearTimeout(window.headingTimeout);
            const debounceMs = isWalking ? 550 : 200;
            
            window.headingTimeout = setTimeout(() => {
                const speechInterval = Date.now() - (window.app.lastSpeechTime || 0);
                
                // 行走中若 2 秒內剛朗讀過店家/路口，不打斷語音
                if (isWalking && speechInterval < 2000) {
                    window.lastReportedCardinal = dirStr;
                    window.lastReportedHeading = window.lastHeading;
                    return;
                }

                window.lastReportedCardinal = dirStr;
                window.lastReportedHeading = window.lastHeading;
                
                if (window.app.audio) window.app.audio.playSettledChime();
                
                // 極簡省話：只報方位本身 (例如：「正北」、「北北東」、「東南」)
                window.app.updateLiveLog(dirStr, false, true);
            }, debounceMs);
        }
    }
};

window.onLocationUpdate = function(lat, lon, accuracy, bearing, speed) {
    if (!window.app || window.app.isReady === false) {
        window.pendingGpsUpdate = { lat, lon, accuracy, bearing, speed };
        return;
    }

    // 記錄步行狀態 (供轉向防打斷演算法使用)
    if ((speed !== undefined && speed > 0.35)) {
        window.lastWalkSpeed = speed;
        window.lastMoveTime = Date.now();
    }

    let dist = 999999;
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
                accuracy: accuracy || 10.0
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

                // 檢查周遭接近店家提示
                if (window.app.checkProximityAlerts) {
                    window.app.checkProximityAlerts(data);
                }

                // 首度定位或大跳躍播報
                if (dist > 50 || dist === 999999) {
                    const overseasMsg = data.is_overseas ? "【⚠️ 偵測到海外地區：已啟用全球線上圖資模式】" : "";
                    const report = `${overseasMsg}${data.concise_report || data.full_report || "已更新 GPS 定位。"}`;
                    window.app.updateLiveLog(report, false, true);
                    if (window.app.audio) window.app.audio.playArrival();
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

