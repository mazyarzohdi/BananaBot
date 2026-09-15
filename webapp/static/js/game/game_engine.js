/**
 * Game Engine: Tap Mechanics, Floating Numbers, Energy Recovery & Turbo Mode
 */
const GameEngine = {
  pendingTaps: 0,
  syncTimer: null,
  energyRecoveryTimer: null,

  // Turbo Rocket & Combo State
  isTurboActive: false,
  turboTimeLeft: 0,
  turboTimerInterval: null,
  rocketSpawnTimeout: null,
  rocketDespawnTimeout: null,
  activeRocketEl: null,

  init() {
    this.bindTapEvents();
    this.startEnergyLoop();
    this.startSyncLoop();
    this.scheduleNextRocket(true);
  },

  bindTapEvents() {
    const tapBtn = document.getElementById('coreTapBtn');
    if (!tapBtn) return;

    tapBtn.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      this.handleTap(e.clientX, e.clientY);
    });
  },

  scheduleNextRocket(isInitial = false) {
    if (this.rocketSpawnTimeout) {
      clearTimeout(this.rocketSpawnTimeout);
    }

    const delay = isInitial
      ? Math.floor(Math.random() * 6000) + 8000
      : Math.floor(Math.random() * 20000) + 20000;

    this.rocketSpawnTimeout = setTimeout(() => {
      this.spawnTurboRocket();
    }, delay);
  },

  spawnTurboRocket() {
    if (this.isTurboActive || this.activeRocketEl) return;

    const wrapper = document.querySelector('.tap-zone-wrapper');
    if (!wrapper) {
      this.scheduleNextRocket(false);
      return;
    }

    const angle = Math.random() * Math.PI * 2;
    const radius = 120 + Math.random() * 15;
    const x = Math.round(Math.cos(angle) * radius);
    const y = Math.round(Math.sin(angle) * radius);

    const rocket = document.createElement('div');
    rocket.className = 'turbo-rocket-floater';
    rocket.setAttribute('title', 'کلیک کنید برای فعال‌سازی توربو (3X)!');
    rocket.innerHTML = '🚀';

    rocket.style.left = `calc(50% + ${x}px - 27px)`;
    rocket.style.top = `calc(50% + ${y}px - 27px)`;

    const onRocketClick = (e) => {
      e.stopPropagation();
      e.preventDefault();

      this.triggerBurst(rocket.offsetLeft + 27, rocket.offsetTop + 27, wrapper);

      if (this.rocketDespawnTimeout) clearTimeout(this.rocketDespawnTimeout);
      rocket.remove();
      this.activeRocketEl = null;

      this.activateTurbo();
    };

    rocket.addEventListener('pointerdown', onRocketClick);
    wrapper.appendChild(rocket);
    this.activeRocketEl = rocket;

    if (window.soundEngine) {
      window.soundEngine.playMorseTap(true);
      window.soundEngine.vibrate(25);
    }

    this.rocketDespawnTimeout = setTimeout(() => {
      if (this.activeRocketEl === rocket) {
        rocket.classList.add('fade-out');
        setTimeout(() => {
          if (rocket.parentNode) rocket.parentNode.removeChild(rocket);
          this.activeRocketEl = null;
          this.scheduleNextRocket(false);
        }, 400);
      }
    }, 7500);
  },

  triggerBurst(x, y, parent) {
    const burst = document.createElement('div');
    burst.className = 'rocket-burst-ring';
    burst.style.left = `${x}px`;
    burst.style.top = `${y}px`;
    parent.appendChild(burst);
    setTimeout(() => burst.remove(), 600);
  },

  activateTurbo() {
    if (this.isTurboActive) return;

    this.isTurboActive = true;
    this.turboTimeLeft = 15;

    const indicator = document.getElementById('turboActiveIndicator');
    const timerDisplay = document.getElementById('turboTimerDisplay');
    const coreBtn = document.getElementById('coreTapBtn');

    if (indicator) indicator.style.display = 'flex';
    if (coreBtn) coreBtn.classList.add('turbo-mode');

    if (window.soundEngine) {
      window.soundEngine.playTurboActivation();
      window.soundEngine.vibrate([50, 80, 120]);
    }
    if (window.GameApp) {
      window.GameApp.showToast('🚀 حالت توربو ۳ برابری (Turbo 3X) به مدت ۱۵ ثانیه فعال شد!', 'turbo');
      window.GameApp.renderCoreStats();
    }

    if (this.turboTimerInterval) clearInterval(this.turboTimerInterval);

    this.turboTimerInterval = setInterval(() => {
      this.turboTimeLeft--;
      if (timerDisplay) timerDisplay.textContent = `${this.turboTimeLeft}s`;

      if (this.turboTimeLeft <= 0) {
        clearInterval(this.turboTimerInterval);
        this.isTurboActive = false;
        if (indicator) indicator.style.display = 'none';
        if (coreBtn) coreBtn.classList.remove('turbo-mode');

        if (window.GameApp) {
          window.GameApp.renderCoreStats();
          window.GameApp.showToast('پایان حالت توربو.', 'info');
        }
        this.scheduleNextRocket(false);
      }
    }, 1000);
  },

  handleTap(clientX, clientY) {
    const user = window.GameApp ? window.GameApp.user : null;
    if (!user) return;

    if (user.energy <= 0) {
      if (window.soundEngine) window.soundEngine.playError();
      if (window.GameApp) {
        window.GameApp.showToast('⚡ انرژی شما تمام شده! کمی صبر کنید تا شارژ شود.', 'danger');
      }
      return;
    }

    if (window.soundEngine) {
      window.soundEngine.playMorseTap(this.isTurboActive);
      window.soundEngine.vibrate(15);
    }

    const multiplier = this.isTurboActive ? 3 : 1;
    const gained = (user.tap_power || 1) * multiplier;

    user.energy = Math.max(0, user.energy - 1);
    user.balance += gained;
    user.total_score += gained;
    this.pendingTaps += 1;

    this.spawnFloatingNumber(clientX, clientY, gained);

    if (window.GameApp) {
      window.GameApp.renderCoreStats();
    }

    if (this.pendingTaps >= 20) {
      this.flushSync();
    }
  },

  spawnFloatingNumber(x, y, gained) {
    const floatEl = document.createElement('div');
    floatEl.className = 'floating-tap-number';
    floatEl.textContent = `+${gained}`;

    const offsetX = (Math.random() - 0.5) * 40;
    const posX = (x || window.innerWidth / 2) + offsetX;
    const posY = (y || window.innerHeight / 2) - 20;

    floatEl.style.left = `${posX}px`;
    floatEl.style.top = `${posY}px`;

    if (this.isTurboActive) {
      floatEl.style.color = '#fbbf24';
      floatEl.style.textShadow = '0 0 16px rgba(245, 158, 11, 0.85)';
    }

    document.body.appendChild(floatEl);

    setTimeout(() => {
      if (floatEl && floatEl.parentNode) {
        floatEl.parentNode.removeChild(floatEl);
      }
    }, 750);
  },

  startEnergyLoop() {
    if (this.energyRecoveryTimer) clearInterval(this.energyRecoveryTimer);

    this.energyRecoveryTimer = setInterval(() => {
      const user = window.GameApp ? window.GameApp.user : null;
      if (!user) return;

      if (user.energy < user.max_energy) {
        const step = (user.energy_recovery_rate || 4) * 0.2;
        user.energy = Math.min(user.max_energy, user.energy + step);
      }

      if (user.passive_rate > 0) {
        const passiveStep = user.passive_rate * 0.2;
        user.balance += passiveStep;
        user.total_score += passiveStep;
      }

      if (window.GameApp) {
        window.GameApp.renderCoreStats();
      }
    }, 200);
  },

  startSyncLoop() {
    if (this.syncTimer) clearInterval(this.syncTimer);

    this.syncTimer = setInterval(() => {
      this.flushSync();
    }, 2500);

    window.addEventListener('beforeunload', () => {
      this.flushSync();
    });
  },

  async flushSync() {
    const user = window.GameApp ? window.GameApp.user : null;
    if (!user || this.pendingTaps === 0) return;

    const tapsToSend = this.pendingTaps;
    this.pendingTaps = 0;

    try {
      const response = await window.GameAPI.syncTaps(tapsToSend, this.isTurboActive);
      if (response && response.success && response.user) {
        if (window.GameApp) {
          window.GameApp.updateUserData(response.user);
        }
      }
    } catch (err) {
      console.warn('Sync delayed, will retry:', err);
      this.pendingTaps += tapsToSend;
    }
  }
};

window.GameEngine = GameEngine;
