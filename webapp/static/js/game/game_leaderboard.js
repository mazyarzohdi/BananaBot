/**
 * Game Leaderboard & Weekly Season Countdown Module (Friday Night Settlement)
 */
const LeaderboardModule = {
  seasonData: null,
  timerInterval: null,
  activeSubtab: 'current',

  init() {
    this.bindEvents();
    this.fetchData();
  },

  bindEvents() {
    const btnCurrent = document.getElementById('btnShowCurrentLb');
    const btnPast = document.getElementById('btnShowPastWinners');
    const containerCurrent = document.getElementById('currentLbContainer');
    const containerPast = document.getElementById('pastWinnersContainer');

    if (btnCurrent && btnPast) {
      btnCurrent.addEventListener('click', () => {
        btnCurrent.classList.add('active');
        btnPast.classList.remove('active');
        if (containerCurrent) containerCurrent.style.display = 'block';
        if (containerPast) containerPast.style.display = 'none';
        this.activeSubtab = 'current';
      });

      btnPast.addEventListener('click', () => {
        btnPast.classList.add('active');
        btnCurrent.classList.remove('active');
        if (containerCurrent) containerCurrent.style.display = 'none';
        if (containerPast) containerPast.style.display = 'block';
        this.activeSubtab = 'past';
      });
    }
  },

  async fetchData() {
    try {
      const data = await window.GameAPI.getLeaderboard();
      if (data && data.success) {
        this.seasonData = data.season;
        this.renderSeasonCountdown(data.season);
        this.renderLeaderboard(data.leaderboard);
        this.renderPastWinners(data.pastWinners);
      }
    } catch (err) {
      console.error('Failed to load leaderboard:', err);
    }
  },

  renderSeasonCountdown(season) {
    if (!season) return;

    const seasonBadge = document.getElementById('seasonNumberBadge');
    if (seasonBadge) {
      seasonBadge.textContent = `مسابقه هفته ${season.season_number}`;
    }

    if (this.timerInterval) clearInterval(this.timerInterval);

    const updateTimer = () => {
      const now = Date.now();
      const diff = Math.max(0, season.end_time - now);

      const d = Math.floor(diff / (1000 * 60 * 60 * 24));
      const h = Math.floor((diff / (1000 * 60 * 60)) % 24);
      const m = Math.floor((diff / (1000 * 60)) % 60);
      const s = Math.floor((diff / 1000) % 60);

      const elD = document.getElementById('cdDays');
      const elH = document.getElementById('cdHours');
      const elM = document.getElementById('cdMinutes');
      const elS = document.getElementById('cdSeconds');

      if (elD) elD.textContent = String(d).padStart(2, '0');
      if (elH) elH.textContent = String(h).padStart(2, '0');
      if (elM) elM.textContent = String(m).padStart(2, '0');
      if (elS) elS.textContent = String(s).padStart(2, '0');

      // Also update topbar banner countdown if present
      const topbarTimer = document.getElementById('topbarFridayCountdown');
      if (topbarTimer) {
        topbarTimer.textContent = `${d} روز و ${h} ساعت تا پایان مسابقه جمعه شب`;
      }

      if (diff <= 0) {
        clearInterval(this.timerInterval);
        setTimeout(() => {
          this.fetchData();
          if (window.GameApp) window.GameApp.fetchInitialState();
        }, 2000);
      }
    };

    updateTimer();
    this.timerInterval = setInterval(updateTimer, 1000);
  },

  renderLeaderboard(list) {
    const container = document.getElementById('leaderboardList');
    if (!container) return;

    const currentTelegramId = window.GameApp && window.GameApp.user ? window.GameApp.user.telegram_id : null;
    const currentUserScore = window.GameApp && window.GameApp.user ? window.GameApp.user.total_score : 0;
    const currentUserRank = window.GameApp && window.GameApp.user ? window.GameApp.user.user_rank : '-';

    const myRankEl = document.getElementById('myStandingRank');
    const myScoreEl = document.getElementById('myStandingScore');
    if (myRankEl) myRankEl.textContent = `# ${currentUserRank}`;
    if (myScoreEl) myScoreEl.textContent = `${Math.floor(currentUserScore).toLocaleString()} امتیاز`;

    if (!list || list.length === 0) {
      container.innerHTML = `
        <div class="empty-card" style="text-align: center; padding: 30px 15px;">
          <i class="fa fa-trophy fa-2x" style="color: var(--text-muted); margin-bottom: 10px;"></i>
          <p style="color: var(--text-secondary); font-size: 13.5px;">هنوز امتیازی در این هفته ثبت نشده است! اولین نفری باشید که کلیک می‌کند.</p>
        </div>
      `;
      return;
    }

    container.innerHTML = list.map((item, index) => {
      const rank = index + 1;
      let medal = '';
      let rankColor = 'var(--text-muted)';

      if (rank === 1) {
        rankColor = '#fbbf24';
        medal = '🥇 ';
      } else if (rank === 2) {
        rankColor = '#cbd5e1';
        medal = '🥈 ';
      } else if (rank === 3) {
        rankColor = '#fb923c';
        medal = '🥉 ';
      }

      const isMe = item.telegram_id === currentTelegramId;

      return `
        <div class="service-row" style="padding: 12px 8px; ${isMe ? 'background: rgba(99, 102, 241, 0.12); border: 1px solid rgba(99, 102, 241, 0.3); border-radius: var(--radius-sm); margin: 3px 0;' : ''}">
          <div style="width: 44px; text-align: center; font-size: 15px; font-weight: 800; color: ${rankColor}; flex-shrink: 0;">
            ${medal}#${rank}
          </div>
          <div class="service-info">
            <div style="display: flex; align-items: center; gap: 6px; flex-wrap: wrap;">
              <i class="fab fa-telegram" style="color: #38bdf8; font-size: 13px;"></i>
              <span class="service-name">${item.nickname}</span>
              ${isMe ? '<span class="badge badge-green" style="font-size: 11px;">شما</span>' : ''}
            </div>
            <div class="service-meta" style="font-size: 12px; color: var(--text-muted); margin-top: 2px;">
              خودکار: +${item.passive_rate || 0}/ثانیه | هر ضربه: +${item.tap_power || 1}
            </div>
          </div>
          <div style="text-align: left; flex-shrink: 0;">
            <span style="font-size: 15px; font-weight: 800; color: #818cf8;">${Math.floor(item.total_score).toLocaleString()}</span>
            <span style="font-size: 11px; color: var(--text-muted);">امتیاز</span>
          </div>
        </div>
      `;
    }).join('');
  },

  renderPastWinners(winners) {
    const container = document.getElementById('pastWinnersList');
    if (!container) return;

    if (!winners || winners.length === 0) {
      container.innerHTML = `
        <div class="empty-card" style="text-align: center; padding: 30px 15px;">
          <i class="fa fa-award fa-2x" style="color: var(--text-muted); margin-bottom: 10px;"></i>
          <p style="color: var(--text-secondary); font-size: 13.5px;">هنوز دوره‌ای به پایان نرسیده است. برندگان هر جمعه شب ساعت ۲۳:۵۹ مشخص می‌شوند!</p>
        </div>
      `;
      return;
    }

    container.innerHTML = winners.map(w => {
      const medal = w.rank === 1 ? '🥇' : w.rank === 2 ? '🥈' : '🥉';
      return `
        <div class="service-row" style="padding: 14px 8px;">
          <div style="font-size: 24px; width: 44px; text-align: center; flex-shrink: 0;">
            ${medal}
          </div>
          <div class="service-info">
            <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
              <i class="fab fa-telegram" style="color: #38bdf8; font-size: 13px;"></i>
              <span class="service-name">${w.nickname}</span>
              <span class="badge badge-amber">هفته ${w.season_number}</span>
            </div>
            <div class="service-meta" style="color: #fbbf24; font-weight: 600; font-size: 12.5px; margin-top: 3px;">
              ${w.prize_title}
            </div>
            <div class="service-meta" style="font-size: 11.5px; color: #a5b4fc; letter-spacing: 0.5px; margin-top: 2px;">
              کد تحویل هدیه: <strong>${w.prize_code}</strong>
            </div>
          </div>
          <div style="text-align: left; flex-shrink: 0;">
            <span style="font-size: 15px; font-weight: 800; color: #818cf8;">${Math.floor(w.score).toLocaleString()}</span>
            <span style="font-size: 11px; color: var(--text-muted);">امتیاز</span>
          </div>
        </div>
      `;
    }).join('');
  }
};

window.LeaderboardModule = LeaderboardModule;
