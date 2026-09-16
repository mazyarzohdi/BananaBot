/**
 * Game API Client for BananaBot Web Panel (Django CSRF Compatible)
 */
function getCookie(name) {
  let cookieValue = null;
  if (document.cookie && document.cookie !== '') {
    const cookies = document.cookie.split(';');
    for (let i = 0; i < cookies.length; i++) {
      const cookie = cookies[i].trim();
      if (cookie.substring(0, name.length + 1) === (name + '=')) {
        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
        break;
      }
    }
  }
  return cookieValue;
}

const GameAPI = {
  // Compute base path from template config or current window location
  getBaseUrl() {
    if (window.GAME_API_BASE) {
      return window.GAME_API_BASE;
    }
    const path = window.location.pathname;
    const segments = path.split('/').filter(Boolean);
    if (segments.length > 0 && segments[0] !== 'api') {
      return `/${segments[0]}/api/game`;
    }
    return '/api/game';
  },

  async request(endpoint, options = {}) {
    const csrfToken = getCookie('csrftoken') || (document.querySelector('[name=csrfmiddlewaretoken]')?.value) || '';
    const headers = {
      'Content-Type': 'application/json',
      'X-CSRFToken': csrfToken,
      ...(options.headers || {})
    };

    const url = `${this.getBaseUrl()}${endpoint}`;
    try {
      const response = await fetch(url, {
        ...options,
        headers
      });

      const data = await response.json();
      if (!response.ok || data.success === false) {
        throw new Error(data.error || 'خطا در ارتباط با سرور بازی');
      }
      return data;
    } catch (err) {
      console.error(`Game API error on ${endpoint}:`, err);
      throw err;
    }
  },

  async getState() {
    return this.request('/state/');
  },

  async syncTaps(taps, comboBoost = false) {
    return this.request('/sync/', {
      method: 'POST',
      body: JSON.stringify({ taps, comboBoost })
    });
  },

  async buyUpgrade(upgradeId) {
    return this.request('/upgrade/', {
      method: 'POST',
      body: JSON.stringify({ upgradeId })
    });
  },

  async getLeaderboard() {
    return this.request('/leaderboard/');
  },

  async setNickname(nickname) {
    return this.request('/nickname/', {
      method: 'POST',
      body: JSON.stringify({ nickname })
    });
  }
};

window.GameAPI = GameAPI;
