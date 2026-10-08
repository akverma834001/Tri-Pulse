/**
 * UI Utilities for Project Pulse.
 * Toasts, confirmation modals, navigation header, demo banner, and 7-step walkthrough.
 */

import { api } from './api.js';

// --- Toast Notifications ---
let toastContainer = null;

export function showToast(message, type = 'info') {
  if (!toastContainer) {
    toastContainer = document.createElement('div');
    toastContainer.className = 'toast-container';
    toastContainer.setAttribute('aria-live', 'polite');
    document.body.appendChild(toastContainer);
  }

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.textContent = message;

  toastContainer.appendChild(toast);
  setTimeout(() => {
    toast.remove();
  }, 4000);
}

// --- Confirm Modal ---
export function showConfirm(title, message, onConfirm) {
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.setAttribute('role', 'dialog');
  overlay.setAttribute('aria-modal', 'true');

  const content = document.createElement('div');
  content.className = 'modal-content';

  const h3 = document.createElement('h3');
  h3.className = 'card-title';
  h3.textContent = title;

  const p = document.createElement('p');
  p.className = 'card-subtitle';
  p.textContent = message;

  const btnRow = document.createElement('div');
  btnRow.style.display = 'flex';
  btnRow.style.justifyContent = 'flex-end';
  btnRow.style.gap = '0.75rem';
  btnRow.style.marginTop = '1.5rem';

  const cancelBtn = document.createElement('button');
  cancelBtn.className = 'btn btn-secondary';
  cancelBtn.textContent = 'Cancel';
  cancelBtn.onclick = () => overlay.remove();

  const confirmBtn = document.createElement('button');
  confirmBtn.className = 'btn btn-danger';
  confirmBtn.textContent = 'Confirm';
  confirmBtn.onclick = () => {
    overlay.remove();
    onConfirm();
  };

  btnRow.appendChild(cancelBtn);
  btnRow.appendChild(confirmBtn);
  content.appendChild(h3);
  content.appendChild(p);
  content.appendChild(btnRow);
  overlay.appendChild(content);

  document.body.appendChild(overlay);
  confirmBtn.focus();
}

// --- Navigation & Demo Banner ---
export async function setupAppLayout(activePage = 'dashboard') {
  let currentUser = null;
  try {
    currentUser = await api.get('/api/me');
  } catch {
    // Not logged in or on login page
    return;
  }

  // Demo Banner if demo user
  if (currentUser && currentUser.is_demo) {
    const banner = document.createElement('div');
    banner.className = 'demo-banner';
    banner.innerHTML = `
      <span>DEMO DATA — NOT REAL HEALTH DATA</span>
      <div style="display:flex; gap:0.5rem; align-items:center;">
        <button class="demo-banner-btn" id="demo-guide-btn">Demo Guide</button>
        <button class="demo-banner-btn" id="demo-reset-btn">Reset Demo</button>
      </div>
    `;
    document.body.prepend(banner);

    document.getElementById('demo-guide-btn')?.addEventListener('click', () => {
      openDemoWalkthrough();
    });

    document.getElementById('demo-reset-btn')?.addEventListener('click', async () => {
      try {
        await api.post('/api/demo/reset');
        showToast('Demo data reset to fresh state', 'success');
        setTimeout(() => window.location.reload(), 600);
      } catch (err) {
        showToast(err.message, 'error');
      }
    });
  }

  // Set active class on navbar links
  const navLinks = document.querySelectorAll('.nav-link');
  navLinks.forEach(link => {
    if (link.dataset.page === activePage) {
      link.classList.add('active');
    }
  });

  // Logout button
  const logoutBtn = document.getElementById('logout-btn');
  if (logoutBtn) {
    logoutBtn.addEventListener('click', async (e) => {
      e.preventDefault();
      try {
        await api.post('/api/auth/logout');
        window.location.href = '/login.html';
      } catch (err) {
        showToast(err.message, 'error');
      }
    });
  }
}

// --- 7-Step Interactive Demo Walkthrough ---
const DEMO_STEPS = [
  {
    step: 1,
    title: "1. Demo Mode Initialized",
    text: "Demo user loaded with multi-week signals (Rohan, 27). Pre-seeded data passed through the real pipeline.",
    action: "View Signals",
    link: "/dashboard.html",
  },
  {
    step: 2,
    title: "2. Pulse Above Baseline",
    text: "Notice average pulse in recent days is 82 BPM vs frozen baseline 74 BPM (+11%). Rule E fired.",
    action: "View Insights",
    link: "/insights.html",
  },
  {
    step: 3,
    title: "3. Combined Pattern & Evidence",
    text: "Expand the 'Why am I seeing this?' box on Rule G to inspect evidence: 4 late-night orders (circular avg 23:41) + pulse elevation.",
    action: "See Recommendation",
    link: "/insights.html",
  },
  {
    step: 4,
    title: "4. Recommended Wind-Down",
    text: "Based on the late-night routine, the silent engine recommends an Evening Wind-Down (5 min).",
    action: "Open Intervention",
    link: "/intervention.html?type=winddown_5min",
  },
  {
    step: 5,
    title: "5. Active Intervention Player",
    text: "Visible timer, checklist, accessibility live updates, and gentle pacing. (Use 'Fast Forward' to jump ahead for presentations).",
    action: "Next Step",
    link: null,
  },
  {
    step: 6,
    title: "6. Outcome & Feeling Check",
    text: "When completed, record how you feel: 'Calmer', 'Same', or 'Worse'. The database logs the transition.",
    action: "Back to Dashboard",
    link: "/dashboard.html",
  },
  {
    step: 7,
    title: "7. Learned Personalization",
    text: "The completion rate updates (e.g. 2 of 3 completed). If rated worse twice, the engine mutes it automatically.",
    action: "Finish Guide",
    link: null,
  },
];

let currentTourStep = 0;

export function openDemoWalkthrough() {
  currentTourStep = 0;
  renderTourModal();
}

function renderTourModal() {
  let modal = document.getElementById('demo-tour-modal');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'demo-tour-modal';
    modal.className = 'modal-overlay';
    document.body.appendChild(modal);
  }

  const stepData = DEMO_STEPS[currentTourStep];
  modal.innerHTML = `
    <div class="modal-content">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.75rem;">
        <span class="badge badge-info">Step ${stepData.step} of 7</span>
        <button id="tour-close-btn" style="background:none; border:none; color:var(--text-muted); font-size:1.25rem; cursor:pointer;">&times;</button>
      </div>
      <h3 class="card-title">${stepData.title}</h3>
      <p class="card-subtitle" style="margin-top:0.5rem; line-height:1.6;">${stepData.text}</p>
      
      <div style="display:flex; justify-content:space-between; align-items:center; margin-top:1.5rem;">
        <button id="tour-prev-btn" class="btn btn-secondary btn-sm" ${currentTourStep === 0 ? 'disabled' : ''}>Previous</button>
        <button id="tour-next-btn" class="btn btn-primary btn-sm">${stepData.action}</button>
      </div>
    </div>
  `;

  document.getElementById('tour-close-btn').onclick = () => modal.remove();
  document.getElementById('tour-prev-btn').onclick = () => {
    if (currentTourStep > 0) {
      currentTourStep--;
      renderTourModal();
    }
  };
  document.getElementById('tour-next-btn').onclick = () => {
    if (stepData.link) {
      modal.remove();
      window.location.href = stepData.link;
    } else if (currentTourStep < DEMO_STEPS.length - 1) {
      currentTourStep++;
      renderTourModal();
    } else {
      modal.remove();
      showToast('Demo Walkthrough completed!', 'success');
    }
  };
}
