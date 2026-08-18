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

// Item 4.2: Client-side IndexedDB Offline Storage Manager
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

// App Logic Controller
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
        uiBtnScan.addEventListener("click", () => this.announceLeftRightSweep());
    }

    const uiBtnAround = document.getElementById("ui-btn-around");
    if (uiBtnAround) {
        uiBtnAround.addEventListener("click", () => this.announceAllPOIs());
    }

    const uiBtnIntersection = document.getElementById("ui-btn-intersection");
    if (uiBtnIntersection) {
        uiBtnIntersection.addEventListener("click", () => this.announceUpcomingIntersection());
    }

    const uiBtnLoc = document.getElementById("ui-btn-loc");
    if (uiBtnLoc) {
        uiBtnLoc.addEventListener("click", () => this.announceRoadAndDoorNumbers());
    }

    const uiBtnExportLog = document.getElementById("ui-btn-export-log");
    if (uiBtnExportLog) {
        uiBtnExportLog.addEventListener("click", () => {
            if (window.AndroidBridge && window.AndroidBridge.shareAppLogs) {
                window.AndroidBridge.shareAppLogs();
            } else {
                alert("目前未在 Android 原生環境中執行，無法直接分享系統日誌。");
            }
        });
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
    if (text === this.lastSpokenText && !isError && !isForce) {
      return;
    }

    if (window.speechSynthesis) {
      window.speechSynthesis.cancel();
    }

    this.lastSpokenText = text;
    this.lastSpeechTime = Date.now();

    if (this.liveLog) {
      // Small timeout forces aria-live to trigger even if text hasn't changed or if it changed rapidly
      this.liveLog.textContent = "";
      setTimeout(() => {
        this.liveLog.textContent = text;
      }, 50);
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

  updatePOIs(pois) {
    this.lastPois = pois || [];
    if (!pois || pois.length === 0) {
      this.poiContainer.innerHTML = '<p class="empty-tip">周遭 100 公尺內無特別登錄的設施。</p>';
      return;
    }

    let html = "";
    pois.forEach((p) => {
      const flag = p.wheelchair === "yes" ? " <span style='color:#22c55e;'>[無障礙]</span>" : "";
      const extras = [];
      if (p.opening_hours) extras.push(`營業：${p.opening_hours}`);
      if (p.cuisine) extras.push(`料理：${p.cuisine}`);
      if (p.phone) extras.push(`電話：${p.phone}`);
      const extraStr = extras.length > 0 ? `<br>${extras.join(" | ")}` : "";

      html += `
        <div class="poi-card" tabindex="0" aria-label="${p.name}，距離 ${p.distance_m} 公尺，位於 ${p.clock_position}，${p.category}">
          <h4>${p.name}${flag}</h4>
          <p>類別：${p.category} | 方位：${p.clock_position} (${p.relative_direction}) | 距離：${p.distance_m} 公尺${extraStr}</p>
        </div>
      `;
    });
    this.poiContainer.innerHTML = html;
  }

  announceAllPOIs() {
    if (!this.lastPois || this.lastPois.length === 0) {
      this.updateLiveLog("【周遭掃描】100 公尺內無特別設施標籤。", false, true);
      return;
    }
    
    this.audio.playSpatialTone(660, 'sine', 0, 0, -1, 0.15);
    
    let msg = `【周遭共發現 ${this.lastPois.length} 家店】\n`;
    const lines = this.lastPois.map(p => {
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
        
        let street = data.road_info && data.road_info.street_name ? data.road_info.street_name : "未知道路";
        let doors = data.door_estimates || {};
        let doorStr = "";
        
        const leftValid = doors.left && doors.left !== "無門牌資料";
        const rightValid = doors.right && doors.right !== "無門牌資料";
        
        if (leftValid && rightValid) {
          doorStr = `左側門牌約為 ${doors.left}，右側約為 ${doors.right}`;
        } else if (leftValid) {
          doorStr = `左側門牌約為 ${doors.left}`;
        } else if (rightValid) {
          doorStr = `右側門牌約為 ${doors.right}`;
        } else {
          doorStr = "附近無門牌資料";
        }
        
        let gpsStr = `GPS座標：${data.lat.toFixed(5)}, ${data.lon.toFixed(5)}`;
        const txt = `目前在 ${street}。${doorStr}。${gpsStr}。`;
        
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

    // 1. 接近中的店家（嚴格限制在 3 ~ 5.5 公尺前夕才播報，極簡只讀店名 + 簡潔方位）
    if (data.pois && data.pois.length > 0) {
      const nearbyPassing = data.pois.filter((p) => {
        const d = p.distance_m;
        const dir = p.relative_direction || "";
        // 3.0 ~ 5.5 公尺（即將經過前夕）才朗讀，且非背後
        return d <= 5.5 && d >= 0.5 && (!dir.includes("後方") || d <= 3.0);
      });

      if (nearbyPassing.length > 0) {
        for (const poi of nearbyPassing) {
          const lastTime = this.announcedPoiCooldown.get(poi.name) || 0;
          if (now - lastTime > 60000) { // 60秒冷卻，避免同店家重複疲勞轟炸
            this.announcedPoiCooldown.set(poi.name, now);

            // 空間立體音效：往該店家方位（左耳/右耳/前方）發出提示音
            const clock = poi.clock_position || "12點鐘方向";
            const dirCoords = this.audio.parseClockDirection(poi.relative_direction || clock, poi.distance_m || 4);
            this.audio.playSpatialTone(660, 'triangle', dirCoords.x, 0, dirCoords.z, 0.15);

            // 省話模式：極簡只讀店名 + 簡潔方位 (如：「全家便利商店，右側」)
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
          if (data.intersection.intersecting_roads && data.intersection.intersecting_roads.length > 0) {
            roads = `，即將交會 ${data.intersection.intersecting_roads.join("、")}`;
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

  // ========== 類別中文翻譯器 ==========
  translateCategory(category) {
    const map = {
      "convenience": "便利商店", "supermarket": "超市", "restaurant": "餐廳",
      "fast_food": "速食店", "cafe": "咖啡店", "bank": "銀行",
      "atm": "ATM提款機", "pharmacy": "藥局", "hospital": "醫院",
      "clinic": "診所", "dentist": "牙醫診所", "police": "警察局",
      "post_office": "郵局", "school": "學校", "park": "公園",
      "library": "圖書館", "bar": "酒吧", "pub": "酒吧",
      "bakery": "烘焙坊", "butcher": "肉舖", "clothes": "服飾店",
      "shoes": "鞋店", "electronics": "3C電子", "mobile_phone": "手機通訊行",
      "hairdresser": "美髮店", "beauty": "美容院", "laundry": "洗衣店",
      "optician": "眼鏡行", "jewelry": "珠寶飾品", "books": "書店",
      "stationery": "文具店", "pet": "寵物店", "florist": "花店",
      "car_repair": "汽車修理", "bicycle": "自行車店", "sports": "運動用品",
      "fuel": "加油站", "car_rental": "租車", "parking": "停車場",
      "kindergarten": "幼兒園", "university": "大學", "college": "學院",
      "place_of_worship": "宗教場所", "theatre": "劇場", "cinema": "電影院",
      "nightclub": "夜店", "marketplace": "市場", "department_store": "百貨公司",
      "mall": "購物中心", "chemist": "藥妝店", "cosmetics": "化妝品店",
      "tattoo": "刺青店", "massage": "按摩店", "dry_cleaning": "乾洗店",
      "travel_agency": "旅行社", "insurance": "保險公司", "lawyer": "律師事務所",
      "estate_agent": "房仲", "company": "公司行號",
      "doctor": "診所", "hotel": "旅館", "museum": "博物館",
      "attraction": "觀光景點", "fitness_centre": "健身房",
      "ice_cream": "冰淇淋店", "tea": "茶飲店", "bubble_tea": "手搖飲",
      "copyshop": "影印店", "variety_store": "生活百貨", "hardware": "五金行",
      "furniture": "傢俱店", "bed": "寢具店", "gift": "禮品店",
      "food": "食品店", "seafood": "海鮮店", "greengrocer": "蔬果店",
      "deli": "熟食店", "confectionery": "糖果甜點店",
      "poi": "地標"
    };
    const raw = category || "";
    // Try exact match, then strip prefix ("shop:clothes" → "clothes")
    return map[raw] || map[raw.split(":").pop()] || raw;
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
          this.updateLiveLog("地圖尚未初始化。請在上方輸入框輸入地址（如：淡水區北新路177號）並點擊【開始定位】。", false, forceFocus);
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
      const dirs = ["正北", "東北", "正東", "東南", "正南", "西南", "正西", "西北"];
      const index = Math.round(heading / 45) % 8;
      return dirs[index];
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
      this.updateLiveLog(`面向${dirStr}`, false, true);
      
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
}

document.addEventListener("DOMContentLoaded", () => {
  window.app = new NmapWebApp();
  window.touchCtrl = new TouchGestureController(window.app);
});
class TouchGestureController {
  constructor(app) {
    this.app = app;
    this.touchStartX = 0;
    this.touchStartY = 0;
    this.touchEndX = 0;
    this.touchEndY = 0;
    
    // Add touch listener to the whole body
    document.body.addEventListener('touchstart', (e) => {
      this.touchStartX = e.changedTouches[0].screenX;
      this.touchStartY = e.changedTouches[0].screenY;
    }, {passive: true});

    document.body.addEventListener('touchend', (e) => {
      this.touchEndX = e.changedTouches[0].screenX;
      this.touchEndY = e.changedTouches[0].screenY;
      this.handleGesture();
    }, {passive: true});
  }

  handleGesture() {
    const deltaX = this.touchEndX - this.touchStartX;
    const deltaY = this.touchEndY - this.touchStartY;
    
    // Ignore small taps or jitters (if it's a tap, NVDA might consume it, but just in case)
    if (Math.abs(deltaX) < 50 && Math.abs(deltaY) < 50) return;

    if (Math.abs(deltaX) > Math.abs(deltaY)) {
      // Horizontal swipe
      if (deltaX > 0) {
        // Swipe Right
        this.app.turn(45);
      } else {
        // Swipe Left
        this.app.turn(-45);
      }
    } else {
      // Vertical swipe
      if (deltaY > 0) {
        // Swipe Down (Backward)
        this.app.velocity = 4.0;
        this.app.moveDir = -1;
      } else {
        // Swipe Up (Forward)
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

window.onHeadingUpdate = function(headingDegrees) {
    window.lastHeading = headingDegrees;
    
    if (window.app && window.app.isReady !== false && window.lastGpsLat !== null) {
        let diff = Math.abs(headingDegrees - window.lastReportedHeading);
        if (diff > 180) diff = 360 - diff;
        
        // When turning body/phone by >= 30 degrees, update and announce direction swiftly
        if (diff >= 30) {
            if (window.headingTimeout) clearTimeout(window.headingTimeout);
            window.headingTimeout = setTimeout(() => {
                window.lastReportedHeading = window.lastHeading;
                window.app.localHeading = window.lastHeading;
                
                if (window.app.audio) window.app.audio.playTurn();
                const dirStr = window.app.getCardinalDirection(window.lastHeading);
                window.app.updateLiveLog(`面向${dirStr}`, false, true);
                
                window.app.serverSync();
            }, 350);
        }
    }
};

window.onLocationUpdate = function(lat, lon, accuracy, bearing, speed) {
    if (!window.app || window.app.isReady === false) {
        window.pendingGpsUpdate = { lat, lon, accuracy, bearing, speed };
        return;
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

    // Update if first GPS fix or moved >= 2.0m
    if (window.lastGpsLat === null || dist >= 2.0) {
        if (window.isGpsSyncPending) {
            window.pendingGpsUpdate = { lat, lon, accuracy, bearing, speed };
            return;
        }

        window.lastGpsLat = lat;
        window.lastGpsLon = lon;
        window.isGpsSyncPending = true;

        const heading = (bearing !== undefined && bearing >= 0) ? bearing : window.lastHeading;

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
                window.app.serverLat = data.lat;
                window.app.serverLon = data.lon;
                window.app.localLat = data.lat;
                window.app.localLon = data.lon;
                window.app.localHeading = data.heading_deg;
                window.app.lastData = data;
                if (window.app.renderRadarCanvas) window.app.renderRadarCanvas(data);
                if (window.app.updatePOIs) window.app.updatePOIs(data.pois || []);

                // Check proximity alerts for approaching POIs (<=15m) and intersections (<=18m)
                if (window.app.checkProximityAlerts) {
                    window.app.checkProximityAlerts(data);
                }

                // Announce if first fix or major jump (> 50m)
                if (dist > 50 || dist === 999999) {
                    const report = data.concise_report || data.full_report || "已更新 GPS 定位。";
                    window.app.updateLiveLog(report, false, true);
                    window.app.audio.playArrival();
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

