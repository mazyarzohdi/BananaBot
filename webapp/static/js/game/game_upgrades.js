/**
 * Game Upgrades & Servers Module
 */
const UpgradesModule = {
  currentFilter: 'all',

  init() {
    this.bindFilterEvents();
    this.renderUpgrades();
  },

  bindFilterEvents() {
    const filterButtons = document.querySelectorAll('.filter-tab');
    filterButtons.forEach(btn => {
      btn.addEventListener('click', () => {
        filterButtons.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        this.currentFilter = btn.getAttribute('data-filter') || 'all';
        this.renderUpgrades();
      });
    });
  },

  renderUpgrades() {
    const container = document.getElementById('upgradesList');
    if (!container) return;

    const user = window.GameApp ? window.GameApp.user : null;
    if (!user || !user.upgrades) {
      container.innerHTML = `<div class="loading-spinner">در حال بارگذاری ارتقاها...</div>`;
      return;
    }

    const filtered = user.upgrades.filter(item => {
      if (this.currentFilter === 'all') return true;
      return item.category === this.currentFilter;
    });

    if (filtered.length === 0) {
      container.innerHTML = `<div class="loading-spinner">موردی در این دسته‌بندی یافت نشد.</div>`;
      return;
    }

    container.innerHTML = filtered.map(item => {
      const canAfford = user.balance >= item.nextCost && !item.isMaxLevel;
      const isMax = item.isMaxLevel;

      let statHighlight = '';
      if (item.effectType === 'tap_power') {
        statHighlight = `+${item.effectValue} امتیاز در هر ضربه`;
      } else if (item.effectType === 'energy_capacity') {
        statHighlight = `+${item.energyValue} سقف انرژی و شارژ سریع‌تر`;
      } else if (item.effectType === 'passive_rate') {
        statHighlight = `+${item.passiveRate} امتیاز در هر ثانیه (خودکار)`;
      }

      return `
        <div class="service-row" style="padding: 14px 10px; margin-bottom: 6px;">
          <div class="service-icon" style="font-size: 22px; width: 44px; height: 44px; background: rgba(99, 102, 241, 0.12); color: #818cf8; border-radius: var(--radius-sm); display: flex; align-items: center; justify-content: center; flex-shrink: 0;">
            ${item.icon}
          </div>
          <div class="service-info">
            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 2px;">
              <span class="service-name">${item.title}</span>
              <span class="badge ${isMax ? 'badge-amber' : 'badge-blue'}">سطح ${item.currentLevel}</span>
            </div>
            <div class="service-meta" style="font-size: 12px; color: var(--text-muted);">
              ${item.description} — <strong style="color: #a5b4fc;">${statHighlight}</strong>
            </div>
          </div>
          <div style="flex-shrink: 0;">
            <button class="btn ${canAfford ? 'btn-primary' : 'btn-outline'} btn-sm buy-btn" 
                    data-upgrade-id="${item.id}"
                    style="min-width: 90px; padding: 8px 12px; font-size: 12px; font-weight: 700;"
                    ${!canAfford ? 'disabled' : ''}>
              ${isMax ? 'تکمیل' : `${item.nextCost.toLocaleString()} امتیاز`}
            </button>
          </div>
        </div>
      `;
    }).join('');

    container.querySelectorAll('.buy-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const upgradeId = btn.getAttribute('data-upgrade-id');
        this.handleBuy(upgradeId);
      });
    });
  },

  async handleBuy(upgradeId) {
    if (!window.GameApp || !window.GameApp.user) return;

    try {
      const response = await window.GameAPI.buyUpgrade(upgradeId);
      if (response && response.success && response.user) {
        if (window.soundEngine) {
          window.soundEngine.playUpgrade();
          window.soundEngine.vibrate(40);
        }
        window.GameApp.updateUserData(response.user);
        window.GameApp.showToast('ارتقا با موفقیت انجام شد! 🎉', 'success');
      }
    } catch (err) {
      if (window.soundEngine) window.soundEngine.playError();
      if (window.GameApp) {
        window.GameApp.showToast(err.message || 'خطا در ارتقا', 'danger');
      }
    }
  }
};

window.UpgradesModule = UpgradesModule;
