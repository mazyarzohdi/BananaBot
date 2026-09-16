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
    const lbContainer = document.getElementById('leaderboardList');
    const winnersContainer = document.getElementById('pastWinnersList');

    // Show shimmer skeleton if empty or currently loading
    if (lbContainer && (!lbContainer.children.length || lbContainer.querySelector('.loading-spinner'))) {
      this.renderLeaderboardSkeleton(lbContainer);
    }
    if (winnersContainer && (!winnersContainer.children.length || winnersContainer.querySelector('.loading-spinner'))) {
      this.renderPastWinnersSkeleton(winnersContainer);
    }

    try {
      const data = await window.GameAPI.getLeaderboard();
      if (data && data.success) {
        this.seasonData = data.season;
        this.renderSeasonCountdown(data.season);
        this.renderLeaderboard(data.leaderboard);
        this.renderPastWinners(data.pastWinners);
        if (data.prizes) {
          this.renderPrizes(data.prizes);
        }
      } else {
        throw new Error(data?.error || 'خطا در دریافت جدول رده‌بندی');
      }
    } catch (err) {
      console.error('Failed to load leaderboard:', err);
      if (lbContainer && (!lbContainer.children.length || lbContainer.querySelector('.skeleton-card-row'))) {
        lbContainer.innerHTML = `
          <div class="empty-card" style="text-align: center; padding: 25px 15px;">
            <p style="color: var(--text-secondary); font-size: 13px;">هنوز اطلاعاتی برای این هفته ثبت نشده یا در حال بارگذاری مجدد است...</p>
          </div>
        `;
      }
    }
  },

  renderLeaderboardSkeleton(container) {
    if (!container) return;
    container.innerHTML = Array(5).fill(0).map((_, i) => `
      <div class="skeleton-card-row">
        <div class="skeleton-shimmer skeleton-box" style="width: 38px; height: 32px; border-radius: 6px;"></div>
        <div class="skeleton-shimmer skeleton-circle" style="width: 36px; height: 36px;"></div>
        <div class="skeleton-body">
          <div class="skeleton-shimmer skeleton-text title" style="width: ${35 + (i * 8)}%;"></div>
          <div class="skeleton-shimmer skeleton-text sub" style="width: 50%;"></div>
        </div>
        <div class="skeleton-shimmer skeleton-box" style="width: 64px; height: 22px; border-radius: 4px;"></div>
      </div>
    `).join('');
  },

  renderPastWinnersSkeleton(container) {
    if (!container) return;
    container.innerHTML = Array(3).fill(0).map(() => `
      <div class="skeleton-card-row" style="padding: 16px 12px;">
        <div class="skeleton-shimmer skeleton-circle" style="width: 42px; height: 42px;"></div>
        <div class="skeleton-body">
          <div class="skeleton-shimmer skeleton-text title" style="width: 40%;"></div>
          <div class="skeleton-shimmer skeleton-text sub" style="width: 65%;"></div>
          <div class="skeleton-shimmer skeleton-text sub" style="width: 50%; margin-top: 4px;"></div>
        </div>
        <div class="skeleton-shimmer skeleton-box" style="width: 70px; height: 24px; border-radius: 4px;"></div>
      </div>
    `).join('');
  },

  renderSeasonCountdown(season) {
    if (!season) return;

    const isIntermission = !!season.is_intermission;

    const seasonBadge = document.getElementById('seasonNumberBadge');
    if (seasonBadge) {
      if (isIntermission) {
        seasonBadge.textContent = 'دوره وقفه ۲۴ ساعته مسابقه';
        seasonBadge.className = 'badge badge-cyan';
      } else {
        seasonBadge.textContent = `مسابقه هفته ${season.season_number}`;
        seasonBadge.className = 'badge badge-amber';
      }
    }

    const countdownLabel = document.getElementById('seasonCountdownLabel');
    if (countdownLabel) {
      if (isIntermission) {
        countdownLabel.innerHTML = `<i class="fa fa-hourglass-start" style="color: #38bdf8;"></i> آغاز مسابقه فصل ${season.season_number}: <strong>شنبه شب ساعت ۲۳:۵۹:۵۹</strong>`;
      } else {
        countdownLabel.innerHTML = '<i class="fa fa-clock" style="color: #fbbf24;"></i> پایان مسابقه: <strong>جمعه شب ساعت ۲۳:۵۹:۵۹</strong>';
      }
    }

    const intermissionSubBadge = document.getElementById('intermissionSubBadge');
    if (intermissionSubBadge) {
      intermissionSubBadge.style.display = isIntermission ? 'inline' : 'none';
    }

    // Intermission Winners Showcase
    const intermissionSection = document.getElementById('intermissionWinnersSection');
    const intermissionGrid = document.getElementById('intermissionWinnersGrid');
    const intermissionHeading = document.getElementById('intermissionWinnersHeading');

    if (intermissionSection) {
      if (isIntermission) {
        intermissionSection.style.display = 'block';
        if (intermissionHeading && season.previous_season_number) {
          intermissionHeading.textContent = `برندگان برتر مسابقه هفته ${season.previous_season_number} (فصل گذشته)`;
        }
        if (intermissionGrid) {
          const winners = season.intermission_winners || [];
          if (winners.length === 0) {
            intermissionGrid.innerHTML = `
              <div style="grid-column: 1 / -1; text-align: center; padding: 18px 10px; color: var(--text-secondary); font-size: 13px;">
                هنوز دوره‌ای به پایان نرسیده یا در فصل گذشته امتیازی ثبت نشده است.
              </div>
            `;
          } else {
            intermissionGrid.innerHTML = winners.map(w => {
              const medal = w.rank === 1 ? '🥇' : (w.rank === 2 ? '🥈' : '🥉');
              const cls = w.rank === 1 ? 'gold' : (w.rank === 2 ? 'silver' : 'bronze');
              const rankTitle = w.rank === 1 ? 'رتبه اول (طلا)' : (w.rank === 2 ? 'رتبه دوم (نقره)' : 'رتبه سوم (برنز)');
              return `
                <div class="winner-card ${cls}">
                  <div style="font-size: 32px; margin-bottom: 4px;">${medal}</div>
                  <div class="winner-rank-badge">${rankTitle}</div>
                  <div class="winner-user-name">
                    <i class="fab fa-telegram" style="color: #38bdf8; font-size: 12px;"></i>
                    <span>${w.nickname}</span>
                  </div>
                  <div class="winner-user-score">${Math.floor(w.score).toLocaleString()} امتیاز</div>
                  <div class="winner-user-prize">${w.prize_title}</div>
                </div>
              `;
            }).join('');
          }
        }
      } else {
        intermissionSection.style.display = 'none';
      }
    }

    if (this.timerInterval) clearInterval(this.timerInterval);

    const targetTimestamp = isIntermission ? (season.start_time || Date.now()) : (season.end_time || Date.now());

    const updateTimer = () => {
      const now = Date.now();
      const diff = Math.max(0, targetTimestamp - now);

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
  },

  renderPrizes(prizes) {
    if (!prizes || !Array.isArray(prizes)) return;
    prizes.forEach(p => {
      const el = document.getElementById(`activePrizeTitle${p.rank}`);
      if (el && p.title) {
        el.textContent = p.title;
      }
    });
  }
};

window.LeaderboardModule = LeaderboardModule;
