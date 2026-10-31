/* ==========================================================================
   BananaBot Web Panel — Client Interactions & Ergonomics
   Optimized for Telegram Mini App (Mobile) & Desktop (Windows/Browsers)
   ========================================================================== */

(function () {
  'use strict';

  // ── Telegram WebApp Setup & Haptic Feedback ─────────────────────────────
  const tg = window.Telegram && window.Telegram.WebApp;

  function triggerHaptic(type) {
    try {
      if (tg && tg.HapticFeedback) {
        if (type === 'success') {
          tg.HapticFeedback.notificationOccurred('success');
        } else if (type === 'warning' || type === 'error') {
          tg.HapticFeedback.notificationOccurred('error');
        } else {
          tg.HapticFeedback.impactOccurred('light');
        }
      }
    } catch (e) {}
  }

  // ── Client Error Tracking (Telegram Mini App & Browser) ─────────────────
  const reportedSignatures = new Set();
  let errorCountThisSession = 0;
  const MAX_ERRORS_PER_SESSION = 5;

  window.reportClientError = function (errorInfo) {
    if (errorCountThisSession >= MAX_ERRORS_PER_SESSION) return;

    try {
      const message = String((errorInfo && (errorInfo.message || errorInfo.error)) || 'Unknown Error');
      const errorType = String((errorInfo && (errorInfo.type || errorInfo.errorType)) || 'ClientError');
      const stack = String((errorInfo && errorInfo.stack) || '');
      const url = String((errorInfo && errorInfo.url) || window.location.href);
      const line = (errorInfo && errorInfo.line) || 0;
      const col = (errorInfo && errorInfo.col) || 0;

      // Filter noise: browser extension errors, ResizeObserver warnings, Script error
      if (url.indexOf('chrome-extension://') !== -1 || url.indexOf('moz-extension://') !== -1) return;
      if (message.indexOf('ResizeObserver loop') !== -1 || message === 'Script error.') return;

      const signature = `${message}@${line}:${col}`;
      if (reportedSignatures.has(signature)) return;
      reportedSignatures.add(signature);
      errorCountThisSession++;

      const payload = {
        message: message.substring(0, 500),
        error_type: errorType.substring(0, 100),
        stack: stack.substring(0, 3000),
        url: url.substring(0, 500),
        line: line,
        col: col,
        platform: (tg && tg.platform) || 'browser',
        tg_version: (tg && tg.version) || '',
        viewport: `${window.innerWidth}x${window.innerHeight}`,
        user_agent: navigator.userAgent.substring(0, 255),
      };

      const endpoint = window.__BANANABOT_ERROR_ENDPOINT || '/panel/api/log-client-error/';

      if (navigator.sendBeacon) {
        const blob = new Blob([JSON.stringify(payload)], { type: 'application/json' });
        navigator.sendBeacon(endpoint, blob);
      } else {
        fetch(endpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
          keepalive: true,
        }).catch(function () {});
      }
    } catch (e) {
      // Prevent reporting recursion
    }
  };

  window.addEventListener('error', function (event) {
    window.reportClientError({
      message: event.message,
      errorType: (event.error && event.error.name) || 'UnhandledError',
      stack: (event.error && event.error.stack) || '',
      url: event.filename || window.location.href,
      line: event.lineno,
      col: event.colno,
    });
  });

  window.addEventListener('unhandledrejection', function (event) {
    const reason = event.reason;
    window.reportClientError({
      message: reason instanceof Error ? reason.message : String(reason),
      errorType: (reason && reason.name) || 'UnhandledPromiseRejection',
      stack: (reason && reason.stack) || '',
      url: window.location.href,
    });
  });

  // ── Sidebar Toggle & Drawer Control ─────────────────────────────────────
  window.toggleSidebar = function () {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('overlay');
    if (!sidebar) return;

    const isOpen = sidebar.classList.toggle('open');
    if (overlay) {
      overlay.classList.toggle('open', isOpen);
    }
    triggerHaptic('light');

    if (isOpen) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
  };

  // Close sidebar on ESC key
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
      const sidebar = document.getElementById('sidebar');
      if (sidebar && sidebar.classList.contains('open')) {
        window.toggleSidebar();
      }
    }
  });

  // ── Modern Toast Notification System ────────────────────────────────────
  window.showToast = function (message, type = 'info', duration = 3200) {
    let container = document.getElementById('toastContainer');
    if (!container) {
      container = document.createElement('div');
      container.id = 'toastContainer';
      container.className = 'toast-container';
      document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;

    let icon = '<i class="fa fa-circle-info" style="color:var(--primary);"></i>';
    if (type === 'success') {
      icon = '<i class="fa fa-circle-check" style="color:var(--success);"></i>';
    } else if (type === 'danger' || type === 'error') {
      icon = '<i class="fa fa-triangle-exclamation" style="color:var(--danger);"></i>';
    } else if (type === 'warning') {
      icon = '<i class="fa fa-circle-exclamation" style="color:var(--warning);"></i>';
    }

    toast.innerHTML = `${icon} <span>${message}</span>`;
    container.appendChild(toast);
    triggerHaptic(type === 'error' || type === 'danger' ? 'error' : 'success');

    setTimeout(() => {
      toast.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
      toast.style.opacity = '0';
      toast.style.transform = 'translateY(10px) scale(0.95)';
      setTimeout(() => toast.remove(), 300);
    }, duration);
  };

  // ── Clipboard Copy System with Visual Feedback ──────────────────────────
  window.copyToClipboard = function (text, message) {
    if (!text) return;
    const msg = message || 'متن در حافظه کپی شد!';

    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(
        () => showToast(msg, 'success'),
        () => fallbackCopy(text, msg)
      );
    } else {
      fallbackCopy(text, msg);
    }
  };

  function fallbackCopy(text, msg) {
    const textArea = document.createElement('textarea');
    textArea.value = text;
    textArea.style.position = 'fixed';
    textArea.style.left = '-999999px';
    textArea.style.top = '-999999px';
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();

    try {
      const successful = document.execCommand('copy');
      if (successful) {
        showToast(msg, 'success');
      } else {
        showToast('خطا در کپی کردن متن', 'danger');
      }
    } catch (err) {
      showToast('خطا در کپی کردن متن', 'danger');
    }
    document.body.removeChild(textArea);
  }

  // Intercept click on any element with data-copy attribute
  document.addEventListener('click', function (e) {
    const copyTarget = e.target.closest('[data-copy]');
    if (copyTarget) {
      e.preventDefault();
      const text = copyTarget.getAttribute('data-copy');
      const label = copyTarget.getAttribute('data-copy-label') || 'کپی شد';
      window.copyToClipboard(text, label);
    }
  });

  // ── Auto-dismiss Alerts with Height Collapse ─────────────────────────────
  document.querySelectorAll('.alert').forEach(el => {
    setTimeout(() => {
      el.style.transition = 'opacity 0.35s ease, transform 0.35s ease, max-height 0.35s ease, margin 0.35s ease, padding 0.35s ease';
      el.style.opacity = '0';
      el.style.transform = 'translateY(-6px)';
      el.style.maxHeight = '0';
      el.style.margin = '0';
      el.style.padding = '0';
      setTimeout(() => el.remove(), 350);
    }, 4500);
  });

  // ── Active Navigation Auto-Highlighting ──────────────────────────────────
  function initActiveNav() {
    const currentPath = window.location.pathname;
    const normalize = (path) => path.replace(/\/+$/, '') || '/';
    const currentNorm = normalize(currentPath);

    document.querySelectorAll('.nav-item, .bottom-nav-item').forEach(link => {
      const href = link.getAttribute('href');
      if (!href || href.startsWith('#') || href.startsWith('javascript:')) return;

      try {
        const linkNorm = normalize(new URL(link.href, window.location.origin).pathname);
        if (linkNorm === currentNorm) {
          link.classList.add('active');
        }
      } catch (e) {}
    });
  }

  // ── Form Double-Submit Protection ────────────────────────────────────────
  document.querySelectorAll('form').forEach(form => {
    form.addEventListener('submit', function () {
      const submitBtn = form.querySelector('button[type="submit"]:not(.no-disable)');
      if (submitBtn) {
        submitBtn.style.opacity = '0.7';
        submitBtn.style.pointerEvents = 'none';
        const originalText = submitBtn.innerHTML;
        setTimeout(() => {
          submitBtn.style.opacity = '';
          submitBtn.style.pointerEvents = '';
          submitBtn.innerHTML = originalText;
        }, 8000);
      }
    });
  });

  // Initialize on DOMContentLoaded
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initActiveNav);
  } else {
    initActiveNav();
  }
})();
