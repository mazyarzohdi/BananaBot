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
      this.renderSkeleton(container);
      return;
    }

    const filtered = user.upgrades.filter(item => {
      if (this.currentFilter === 'all') return true;
      return item.category === this.currentFilter;
    });

    if (filtered.length === 0) {
      container.innerHTML = `
        <div class="empty-card" style="text-align: center; padding: 30px 15px;">
          <i class="fa fa-layer-group fa-2x" style="color: var(--text-muted); margin-bottom: 10px;"></i>
          <p style="color: var(--text-secondary); font-size: 13.5px;">موردی در این دسته‌بندی یافت نشد.</p>
        </div>
      `;
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
        <div class="service-row upgrade-card-${item.id}" style="padding: 14px 10px; margin-bottom: 6px; transition: all 0.3s ease;">
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
                    style="min-width: 96px; padding: 8px 12px; font-size: 12px; font-weight: 700;"
                    ${!canAfford ? 'disabled' : ''}>
              <span class="btn-text">${isMax ? 'تکمیل' : `${item.nextCost.toLocaleString()} امتیاز`}</span>
            </button>
          </div>
        </div>
      `;
    }).join('');

    container.querySelectorAll('.buy-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const upgradeId = btn.getAttribute('data-upgrade-id');
        this.handleBuy(upgradeId, btn);
      });
    });
  },

  renderSkeleton(container) {
    if (!container) return;
    container.innerHTML = Array(4).fill(0).map(() => `
      <div class="skeleton-card-row">
        <div class="skeleton-shimmer skeleton-icon"></div>
        <div class="skeleton-body">
          <div class="skeleton-shimmer skeleton-text title"></div>
          <div class="skeleton-shimmer skeleton-text sub"></div>
        </div>
        <div class="skeleton-shimmer skeleton-btn"></div>
      </div>
    `).join('');
  },

  async handleBuy(upgradeId, btnElement) {
    if (!window.GameApp || !window.GameApp.user) return;

    if (btnElement) {
      btnElement.classList.add('btn-loading');
      btnElement.disabled = true;
    }

    try {
      const response = await window.GameAPI.buyUpgrade(upgradeId);
      if (response && response.success && response.user) {
        if (window.soundEngine) {
          window.soundEngine.playUpgrade();
          window.soundEngine.vibrate(40);
        }
        window.GameApp.updateUserData(response.user);
        window.GameApp.showToast('ارتقا با موفقیت انجام شد! 🎉', 'success');

        const card = document.querySelector(`.upgrade-card-${upgradeId}`);
        if (card) {
          card.classList.add('upgrade-success-flash');
          setTimeout(() => card.classList.remove('upgrade-success-flash'), 600);
        }
      } else {
        throw new Error(response?.error || 'خطا در ارتقا');
      }
    } catch (err) {
      if (window.soundEngine) window.soundEngine.playError();
      if (window.GameApp) {
        window.GameApp.showToast(err.message || 'خطا در ارتقا', 'danger');
      }
    } finally {
      if (btnElement && document.body.contains(btnElement)) {
        btnElement.classList.remove('btn-loading');
        btnElement.disabled = false;
      }
    }
  }
};

window.UpgradesModule = UpgradesModule;
