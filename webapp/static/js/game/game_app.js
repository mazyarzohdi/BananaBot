/**
 * Main Game Orchestrator & Dashboard Integration (BananaBot WebApp)
 */
const GameApp = {
  user: null,
  activeTab: 'tab-arena',

  async init() {
    this.bindNavigation();
    this.bindSoundToggle();
    this.bindNicknameModal();

    // Initialize submodules
    if (window.UpgradesModule) window.UpgradesModule.init();
    if (window.LeaderboardModule) window.LeaderboardModule.init();
    if (window.GameEngine) window.GameEngine.init();

    // Fetch initial user state and season data
    await this.fetchInitialState();
  },

  bindNavigation() {
    document.querySelectorAll('.game-nav-btn[data-game-tab]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        const targetTab = btn.getAttribute('data-game-tab');
        this.switchTab(targetTab);
      });
    });
  },

  switchTab(tabId) {
    this.activeTab = tabId;

    // Update tab buttons
    document.querySelectorAll('.game-nav-btn[data-game-tab]').forEach(btn => {
      btn.classList.toggle('active', btn.getAttribute('data-game-tab') === tabId);
    });

    // Update tab content views
    document.querySelectorAll('.game-tab-view').forEach(view => {
      view.classList.toggle('active', view.id === tabId);
    });

    if (tabId === 'tab-upgrades' && window.UpgradesModule) {
      window.UpgradesModule.renderUpgrades();
    } else if (tabId === 'tab-leaderboard' && window.LeaderboardModule) {
      window.LeaderboardModule.fetchData();
    }
  },

  bindSoundToggle() {
    const btn = document.getElementById('soundToggleBtn');
    const icon = document.getElementById('soundIcon');
    if (!btn || !icon || !window.soundEngine) return;

    const updateIcon = () => {
      if (window.soundEngine.enabled) {
        icon.className = 'fa fa-volume-high';
        btn.setAttribute('title', 'صدا فعال است (برای قطع کلیک کنید)');
      } else {
        icon.className = 'fa fa-volume-xmark';
        btn.setAttribute('title', 'صدا قطع است (برای وصل کلیک کنید)');
      }
    };

    updateIcon();

    btn.addEventListener('click', () => {
      window.soundEngine.toggle();
      updateIcon();
      this.showToast(window.soundEngine.enabled ? 'صدا وصل شد.' : 'صدا قطع شد.', 'info');
    });
  },

  bindNicknameModal() {
    const editBtn = document.getElementById('editNicknameBtn');
    const modal = document.getElementById('nicknameModal');
    const saveBtn = document.getElementById('saveNicknameBtn');
    const cancelBtn = document.getElementById('cancelNicknameBtn');
    const input = document.getElementById('nicknameInput');

    if (editBtn && modal && saveBtn && input) {
      editBtn.addEventListener('click', () => {
        input.value = this.user ? this.user.nickname : '';
        modal.classList.add('open');
      });

      if (cancelBtn) {
        cancelBtn.addEventListener('click', () => {
          modal.classList.remove('open');
        });
      }

      saveBtn.addEventListener('click', async () => {
        const val = input.value.trim();
        if (val.length < 2 || val.length > 24) {
          this.showToast('نام مستعار باید بین ۲ تا ۲۴ کاراکتر باشد.', 'danger');
          return;
        }
        try {
          const res = await window.GameAPI.setNickname(val);
          if (res && res.success && res.user) {
            this.updateUserData(res.user);
            modal.classList.remove('open');
            this.showToast('نام مستعار با موفقیت تغییر یافت.', 'success');
          }
        } catch (e) {
          this.showToast(e.message || 'خطا در ثبت نام مستعار', 'danger');
        }
      });
    }
  },

  async fetchInitialState() {
    try {
      const res = await window.GameAPI.getState();
      if (res && res.success && res.user) {
        this.updateUserData(res.user);
        if (res.season && window.LeaderboardModule) {
          window.LeaderboardModule.renderSeasonCountdown(res.season);
        }
      }
    } catch (err) {
      console.warn('Initial game state fetch failed:', err);
    }
  },

  updateUserData(userData) {
    this.user = userData;
    this.renderCoreStats();

    if (window.UpgradesModule && this.activeTab === 'tab-upgrades') {
      window.UpgradesModule.renderUpgrades();
    }
  },

  renderCoreStats() {
    if (!this.user) return;

    const balanceInt = Math.floor(this.user.balance || 0);
    const scoreInt = Math.floor(this.user.total_score || 0);
    const energyInt = Math.floor(this.user.energy || 0);
    const maxEnergy = Math.floor(this.user.max_energy || 1000);

    // Topbar & quick balance displays
    const topbarBal = document.getElementById('topbarGameBalance');
    if (topbarBal) topbarBal.textContent = balanceInt.toLocaleString();

    // Energy numbers & fill
    const curEnergyEl = document.getElementById('currentEnergyDisplay');
    const maxEnergyEl = document.getElementById('maxEnergyDisplay');
    const energyFill = document.getElementById('energyFill');

    if (curEnergyEl) curEnergyEl.textContent = energyInt;
    if (maxEnergyEl) maxEnergyEl.textContent = maxEnergy;
    if (energyFill) {
      const pct = Math.max(0, Math.min(100, (energyInt / maxEnergy) * 100));
      energyFill.style.width = `${pct}%`;
    }

    // KPI Cards
    const kpiBalance = document.getElementById('kpiBalance');
    const seasonScore = document.getElementById('seasonScoreDisplay');
    const passiveRate = document.getElementById('passiveRateDisplay');
    const tapPower = document.getElementById('tapPowerDisplay');
    const myRank = document.getElementById('myRankDisplay');

    if (kpiBalance) kpiBalance.textContent = balanceInt.toLocaleString();
    if (seasonScore) seasonScore.textContent = scoreInt.toLocaleString();
    if (passiveRate) passiveRate.textContent = this.user.passive_rate || 0;

    if (tapPower) {
      const isTurbo = window.GameEngine && window.GameEngine.isTurboActive;
      const effectivePower = (this.user.tap_power || 1) * (isTurbo ? 3 : 1);
      tapPower.textContent = effectivePower;
      if (isTurbo) {
        tapPower.style.color = '#fbbf24';
      } else {
        tapPower.style.color = '';
      }
    }

    if (myRank) myRank.textContent = this.user.user_rank ? `#${this.user.user_rank}` : '-';

    // Nickname displays
    const nickEls = document.querySelectorAll('.game-user-nickname');
    nickEls.forEach(el => {
      el.textContent = this.user.nickname || 'کاربر گرامی';
    });
  },

  showToast(message, type = 'info') {
    let container = document.getElementById('toastContainer');
    if (!container) {
      container = document.createElement('div');
      container.id = 'toastContainer';
      container.className = 'toast-container';
      document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    toast.className = `alert alert-${type === 'turbo' ? 'warning' : type}`;
    toast.style.cssText = 'box-shadow: 0 8px 24px rgba(0,0,0,0.5); animation: toastIn 0.3s ease; margin-top: 8px;';
    toast.innerHTML = `<span>${message}</span>`;

    container.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateY(-10px)';
      toast.style.transition = 'all 0.3s ease';
      setTimeout(() => toast.remove(), 300);
    }, 3200);
  }
};

window.GameApp = GameApp;

// Auto-initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
  if (document.getElementById('coreTapBtn')) {
    GameApp.init();
  }
});
