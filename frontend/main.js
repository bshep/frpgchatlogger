import 'bootstrap/dist/css/bootstrap.min.css';
import 'bootstrap';

const isProduction = import.meta.env.PROD;
console.log(`Environment: ${isProduction ? 'Production' : 'Development'}`);

const BACKEND_URL = isProduction ? document.location.protocol + "//" + document.location.host : "http://localhost:8000";
const SESSION_COOKIE_NAME = "frpg_chatterbot_session";

// --- DOM Elements ---
const CHAT_LOG_ELEMENT = document.getElementById('chat-log');
const MENTIONS_LOG_ELEMENT = document.getElementById('mentions-log');
const CONFIG_FORM = document.getElementById('config-form');
const MENTION_SOUND = document.getElementById('mention-sound');
const CHANNEL_TABS = document.getElementById('channel-tabs');
const CHAT_SEARCH_BAR = document.getElementById('chat-search-bar');
const CHANNEL_VIEW = document.getElementById('channel-view');
const ADVANCED_SEARCH_VIEW = document.getElementById('advanced-search-view');
const ADVANCED_SEARCH_FORM = document.getElementById('advanced-search-form');
const ADVANCED_SEARCH_INPUT = document.getElementById('advanced-search-input');
const ADVANCED_SEARCH_RESULTS = document.getElementById('advanced-search-results');
const ADVANCED_SEARCH_CHANNEL_FILTER = document.getElementById('advanced-search-channel-filter');
const ADVANCED_SEARCH_TAB = document.getElementById('advanced-search-tab');
const AUTH_STATUS_MESSAGE = document.getElementById('auth-status-message');
const DISCORD_LOGIN_BUTTON = document.getElementById('discord-login-button');
const DISCORD_LOGOUT_BUTTON = document.getElementById('discord-logout-button');
const ADMIN_PAGE_LINK = document.getElementById('admin-page-link');
const ANALYSIS_PAGE_LINK = document.getElementById('analysis-page-link');
const MARK_ALL_AS_READ_BTN = document.getElementById('mark-all-as-read-btn');

// --- State ---
let activeChannel = 'trade';
let authStatus = {
  loggedIn: false,
  isAllowed: false,
  isAdmin: false,
  isAnalysisAllowed: false,
  username: ''
};
let currentUserConfig = {
  username: "YourUsername",
  play_alert: false,
  polling_interval: 5, // in seconds
};
let localMentionsCache = [];
let chatLogPollingIntervalId;
let mentionPollingIntervalId;

// --- Initialization ---
document.addEventListener('DOMContentLoaded', initializeApp);

async function initializeApp() {
  loadConfigFromLocalStorage();
  fetchBackendConfig();
  await checkAuthStatus();
  updateUIForAuth();
  
  // Initial data fetch and polling
  fetchMentions();
  startMentionPolling();

  if (CHANNEL_VIEW.style.display !== 'none') {
    fetchChatLog();
    startChatLogPolling();
  }
  
  addEventListeners();
  setupAudioUnlock();
}

function handleMessageContentClick(event) {
  let target = event.target;

  if (!target.dataset.action) {
    target = target.closest('span');
  }

  if (target.dataset.action === 'user-link' || target.dataset.action === "item-link") {
    if (!event.shiftKey && !event.altKey ) {
      // Perform search
      event.preventDefault();

      const searchTerm = target.dataset.searchTerm;

      const advancedSearchTab = document.querySelector('[data-channel="advanced-search"]');
      if (advancedSearchTab) {
        advancedSearchTab.click();
      }
      
      ADVANCED_SEARCH_INPUT.value = searchTerm;
      if (ADVANCED_SEARCH_FORM.requestSubmit) {
        ADVANCED_SEARCH_FORM.requestSubmit();
      } else {
        ADVANCED_SEARCH_FORM.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
      }
    } else if (event.altKey) {
      event.preventDefault();

      let searchTerm = target.dataset.searchTerm;
      if (target.dataset.action === 'user-link') {
        searchTerm = "@" + searchTerm + ":";
      } else if (target.dataset.action === 'item-link') {
        searchTerm = "((" + searchTerm + "))";
      }

      navigator.clipboard.writeText(searchTerm);
    } else {
      // Open profile in new tab
      event.preventDefault();
      window.open(target.dataset.pageUrl, '_blank', 'noopener,noreferrer');
    }
  }
}

function addEventListeners() {
  CHAT_SEARCH_BAR.addEventListener('input', applyChatFilter);
  CHANNEL_TABS.addEventListener('click', handleTabClick);
  ADVANCED_SEARCH_FORM.addEventListener('submit', handleAdvancedSearch);
  CONFIG_FORM.addEventListener('submit', handleConfigFormSubmit);
  DISCORD_LOGOUT_BUTTON.addEventListener('click', logout);
  MENTIONS_LOG_ELEMENT.addEventListener('click', handleMentionsClick);
  MARK_ALL_AS_READ_BTN.addEventListener('click', markAllAsRead);

  // Add the new listener for user links
  CHAT_LOG_ELEMENT.addEventListener('click', handleMessageContentClick);
  ADVANCED_SEARCH_RESULTS.addEventListener('click', handleMessageContentClick);
  MENTIONS_LOG_ELEMENT.addEventListener('click', handleMessageContentClick);
}

function markAllAsRead() {
  const visibleMentions = MENTIONS_LOG_ELEMENT.querySelectorAll('[data-action="mark-as-read"]');
  visibleMentions.forEach(button => {
    button.click();
  });
}

function setupAudioUnlock() {
  const unlockAudio = () => {
    if (MENTION_SOUND.paused) {
      MENTION_SOUND.muted = true;
      MENTION_SOUND.play().catch(e => console.warn("Audio autoplay failed.", e)).then(() => {
        MENTION_SOUND.pause();
        MENTION_SOUND.currentTime = 0;
        MENTION_SOUND.muted = false;
      });
    }
    document.removeEventListener('click', unlockAudio);
    document.removeEventListener('touchend', unlockAudio);
  };
  document.addEventListener('click', unlockAudio);
  document.addEventListener('touchend', unlockAudio);
}

// --- Search, Filter, and Tab Navigation ---
function applyChatFilter() {
  const query = CHAT_SEARCH_BAR.value.toLowerCase();
  const messages = CHAT_LOG_ELEMENT.querySelectorAll('.list-group-item');
  messages.forEach(message => {
    const messageText = message.textContent.toLowerCase();
    message.style.display = messageText.includes(query) ? 'block' : 'none';
  });
}

// --- Authentication and UI ---
async function checkAuthStatus() {
  try {
    const response = await fetch(`${BACKEND_URL}/api/me`);
    if (response.ok) {
      const userData = await response.json();
      authStatus.loggedIn = true;
      authStatus.isAllowed = userData.is_allowed;
      authStatus.isAdmin = userData.is_admin;
      authStatus.isAnalysisAllowed = userData.is_analysis_allowed;
      authStatus.username = userData.username;
    } else {
      authStatus.loggedIn = false;
      authStatus.isAllowed = false;
      authStatus.isAnalysisAllowed = false;
    }
  } catch (error) {
    console.error("Auth check failed:", error);
    authStatus.loggedIn = false;
    authStatus.isAllowed = false;
    authStatus.isAnalysisAllowed = false;
  }
}

function updateUIForAuth() {
  if (authStatus.loggedIn) {
    AUTH_STATUS_MESSAGE.textContent = `Logged in as: ${authStatus.username}`;
    DISCORD_LOGIN_BUTTON.style.display = 'none';
    DISCORD_LOGOUT_BUTTON.style.display = 'block';

    if (authStatus.isAllowed) {
      AUTH_STATUS_MESSAGE.textContent += ' (Authorized)';
      ADVANCED_SEARCH_TAB.style.display = 'block';
    } else {
      AUTH_STATUS_MESSAGE.textContent += ' (Not Authorized)';
      ADVANCED_SEARCH_TAB.style.display = 'none';
    }

    if (authStatus.isAdmin) {
      ADMIN_PAGE_LINK.style.display = 'block';
    } else {
      ADMIN_PAGE_LINK.style.display = 'none';
    }

    if (authStatus.isAnalysisAllowed) {
      ANALYSIS_PAGE_LINK.style.display = 'block';
    } else {
      ANALYSIS_PAGE_LINK.style.display = 'none';
    }

  } else {
    AUTH_STATUS_MESSAGE.textContent = 'Not logged in.';
    DISCORD_LOGIN_BUTTON.style.display = 'block';
    DISCORD_LOGOUT_BUTTON.style.display = 'none';
    ADVANCED_SEARCH_TAB.style.display = 'none';
    ADMIN_PAGE_LINK.style.display = 'none';
    ANALYSIS_PAGE_LINK.style.display = 'none';
  }
}

async function logout() {
  try {
    await fetch(`${BACKEND_URL}/api/logout`, { method: 'POST' });
  } catch (error) {
    console.error("Logout request failed:", error);
  } finally {
    // Always reload to reflect the new (logged-out) state
    window.location.reload();
  }
}

// --- Event Handlers ---
function handleTabClick(e) {
  e.preventDefault();
  const clickedTab = e.target.closest('[data-channel]');
  if (clickedTab) {
    const channel = clickedTab.dataset.channel;
    
    CHANNEL_TABS.querySelectorAll('.nav-link').forEach(tab => tab.classList.remove('active'));
    clickedTab.classList.add('active');

    if (channel === 'advanced-search') {
      // Switch to advanced search view
      activeChannel = 'none';
      CHANNEL_VIEW.style.display = 'none';
      ADVANCED_SEARCH_VIEW.style.display = 'block';
      stopChatLogPolling();
    } else {
      // Switch to a channel view
      CHANNEL_VIEW.style.display = 'block';
      ADVANCED_SEARCH_VIEW.style.display = 'none';
      if (activeChannel !== channel) {
        activeChannel = channel;
        CHAT_SEARCH_BAR.value = '';
        fetchChatLog();
        restartChatLogPolling(); // Restart polling only if it was stopped
      }
    }
  }
}

async function handleAdvancedSearch(e) {
  e.preventDefault();
  const query = ADVANCED_SEARCH_INPUT.value;
  const channel = ADVANCED_SEARCH_CHANNEL_FILTER.value;
  if (!query) return;

  ADVANCED_SEARCH_RESULTS.innerHTML = '<p class="text-center">Searching...</p>';
  try {
    let url = `${BACKEND_URL}/api/search?q=${encodeURIComponent(query)}`;
    if (channel) {
      url += `&channel=${encodeURIComponent(channel)}`;
    }
    const response = await fetch(url);
    if (!response.ok) {
        if (response.status === 401 || response.status === 403) {
            throw new Error("You are not authorized to perform this search.");
        }
        throw new Error(`Search failed with status ${response.status}`);
    }
    const results = await response.json();
    renderMessages(ADVANCED_SEARCH_RESULTS, results);
    if (results.length === 0) {
      ADVANCED_SEARCH_RESULTS.innerHTML = '<p class="text-center">No results found.</p>';
    }
  } catch (error) {
    console.error('Advanced search failed:', error);
    ADVANCED_SEARCH_RESULTS.innerHTML = `<p class="text-center text-danger">${error.message}</p>`;
  }
}
// --- Generic Message Renderer ---
function enhanceLinks(element) {
  element.querySelectorAll('a').forEach(link => {
    const originalHref = link.href;

    const span = document.createElement('span');
    span.textContent = link.textContent;
    span.className = link.className;
    
    // Add data attributes for the event handler
    span.style.cursor = "pointer";

    if (originalHref.includes('item.php')) {
      span.dataset.action = 'item-link';
      span.dataset.pageUrl = originalHref.replace('item.php', 'index.php#!/item.php');
      span.dataset.searchTerm = link.textContent.trim();
      link.childNodes.forEach( child => {
        if (child.tagName === 'IMG') {
          span.dataset.searchTerm = child.alt;
        }
        span.appendChild(child);
      });
    } else if (originalHref.includes('profile.php')) {
      span.dataset.action = 'user-link';
      span.dataset.pageUrl = originalHref.replace('profile.php', 'index.php#!/profile.php');
      span.dataset.searchTerm = link.textContent.trim();
      if (span.dataset.searchTerm.startsWith("@")) {
        span.dataset.searchTerm = span.dataset.searchTerm.replace('@','')
        span.style.color = "teal";
      }
    }
    link.parentNode.replaceChild(span, link);
  });
}
// --- Generic Message Renderer ---
function renderMessages(element, messages) {
  element.innerHTML = '';
  const selectedTab = document.getElementById('channel-tabs').getElementsByClassName("active")[0].dataset.channel || 'trade';
  messages.forEach(msg => {
    const messageElement = document.createElement('div');
    messageElement.classList.add('list-group-item', 'list-group-item-action');
    const timestamp = new Date(msg.timestamp+"-06:00").toLocaleString(undefined, { timeZone: 'America/Chicago' });
    const channelInfo = selectedTab === 'advanced-search' ? `<small class="channel">(${msg.channel})</small>` : '';

    // Create a temporary div to manipulate message HTML
    const tempDiv = document.createElement('div');
    tempDiv.innerHTML = msg.message_html;

    // Enhance links within the message content
    enhanceLinks(tempDiv);
    
    msg.message_html = tempDiv.innerHTML;

    messageElement.innerHTML = `
      <div class="d-flex w-100 justify-content-between">
        <small class="timestamp">${timestamp}</small>
        ${channelInfo}
      </div>
      <p class="mb-1 message-content">${msg.message_html}</p>
    `;
    element.appendChild(messageElement);
  });

  if ( element.scrollTop < 50 ) {
    element.scrollTop = 0;
  }
}

// --- Configuration Management ---
function loadConfigFromLocalStorage() {
  const storedConfig = localStorage.getItem('userConfig');
  if (storedConfig) {
    currentUserConfig = JSON.parse(storedConfig);
  }

  // Update form fields
  document.getElementById('username').value = currentUserConfig.username;
  document.getElementById('polling-interval').value = currentUserConfig.polling_interval;
  document.getElementById('play-alert').checked = currentUserConfig.play_alert;

  const storedMentions = localStorage.getItem('localMentionsCache');
  if (storedMentions) {
    localMentionsCache = JSON.parse(storedMentions);
    // Ensure timestamps are Date objects and is_hidden property exists
    localMentionsCache.forEach(m => {
      m.timestamp = new Date(m.timestamp);
      m.is_hidden = m.is_hidden || false; // Ensure is_hidden is set for old entries
    });
  }
}

async function fetchBackendConfig() {
  try {
    const channelRes = await fetch(`${BACKEND_URL}/api/config`);
    if (channelRes.ok) {
      const backendConfigs = await channelRes.json();
      // Could be used for other global settings in future
    }
  } catch (error) {
    console.error("Error fetching backend config:", error);
  }
}

// --- Data Fetching and Rendering ---
// --- Search, Filter, and Tab Navigation ---
function handleConfigFormSubmit(e) {
  e.preventDefault();
  const formData = new FormData(CONFIG_FORM);
  const oldUsername = currentUserConfig.username;
  currentUserConfig.username = formData.get('username');
  currentUserConfig.polling_interval = parseInt(formData.get('polling_interval'), 10);
  currentUserConfig.play_alert = formData.get('play_alert') === 'on';

  localStorage.setItem('userConfig', JSON.stringify(currentUserConfig));

  if (oldUsername !== currentUserConfig.username) {
    localMentionsCache = [];
    localStorage.removeItem('localMentionsCache');
    fetchMentions();
  }
  restartChatLogPolling();
  restartMentionPolling();
}

// --- Chat Log Display ---
async function fetchChatLog() {
  if (activeChannel === 'advanced-search') return; // Don't fetch for advanced search tab
  try {
    // The limit is now handled by the backend based on auth status
    const response = await fetch(`${BACKEND_URL}/api/messages?channel=${activeChannel}`);
    const messages = await response.json();
    renderMessages(CHAT_LOG_ELEMENT, messages);
    applyChatFilter();
  } catch (error) {
    console.error(`Error fetching chat log for ${activeChannel}:`, error);
    CHAT_LOG_ELEMENT.innerHTML = `<p class="text-danger">Error loading chat log for ${activeChannel}.</p>`;
  }
}

// --- Mentions Display ---
async function fetchMentions() {
  try {
    let latestTimestamp = null;
    if (localMentionsCache.length > 0) {
      const visibleMentions = localMentionsCache.filter(m => !m.is_hidden);
      if (visibleMentions.length > 0) {
        latestTimestamp = visibleMentions.reduce((maxTs, mention) => 
            (new Date(mention.timestamp) > new Date(maxTs) ? mention.timestamp : maxTs), visibleMentions[0].timestamp
        );
      }
    }

    let url = `${BACKEND_URL}/api/mentions?username=${currentUserConfig.username}`;
    if (latestTimestamp) {
      url += `&since=${new Date(latestTimestamp).toISOString()}`;
    }

    const response = await fetch(url);
    const newMentions = await response.json();
    
    let playSound = false;
    if (newMentions.length > 0 && currentUserConfig.play_alert) {
      playSound = true;
    }

    newMentions.forEach(newMention => {
      newMention.timestamp = new Date(newMention.timestamp+"-06:00");
      newMention.is_hidden = newMention.is_hidden || false;
      if (!localMentionsCache.some(m => m.id === newMention.id)) {
        localMentionsCache.push(newMention);
      } else {
        const existingIndex = localMentionsCache.findIndex(m => m.id === newMention.id);
        if (existingIndex !== -1) {
            localMentionsCache[existingIndex] = newMention;
        }
      }
    });

    localMentionsCache.sort((a, b) => b.timestamp.getTime() - a.timestamp.getTime());
    localStorage.setItem('localMentionsCache', JSON.stringify(localMentionsCache));
    displayMentions();

    if (playSound) {
      MENTION_SOUND.play();
    }
  } catch (error) {
    console.error("Error fetching mentions:", error);
    MENTIONS_LOG_ELEMENT.innerHTML = '<p>Error loading mentions.</p>';
  }
}

function displayMentions() {
    MENTIONS_LOG_ELEMENT.innerHTML = ''; // Clear existing
    localMentionsCache.forEach(mention => {
      if (mention.is_hidden) return;
      const mentionElement = document.createElement('div');
      mentionElement.id = `mention-${mention.id}`;
      mentionElement.classList.add('list-group-item', 'list-group-item-action', 'd-flex', 'justify-content-between', 'align-items-start');
      const timestamp = new Date(mention.timestamp).toLocaleString(undefined, { timeZone: 'America/Chicago' });
      mentionElement.innerHTML = `
        <div class="flex-grow-1">
            <div class="d-flex w-100 justify-content-between">
                <small class="timestamp">${timestamp}</small>
                <small class="channel">(${mention.channel})</small>
            </div>
            <p class="mb-1 message-content">${mention.message_html}</p>
        </div>
        <button type="button" class="btn btn-success btn-sm ms-2" data-action="mark-as-read" data-mention-id="${mention.id}">
            &#10003; <!-- Checkmark icon -->
        </button>
      `;
      MENTIONS_LOG_ELEMENT.appendChild(mentionElement);
    });
    if (MENTIONS_LOG_ELEMENT.scrollTop < 50 ) {
      MENTIONS_LOG_ELEMENT.scrollTop = 0;
    }
}

async function handleMentionsClick(e) {
  const markAsReadButton = e.target.closest('[data-action="mark-as-read"]');
  if (markAsReadButton) {
    const mentionId = parseInt(markAsReadButton.dataset.mentionId, 10);
      try {
        const response = await fetch(`${BACKEND_URL}/api/mentions/${mentionId}`, { method: 'DELETE' });
        if (response.ok) {
          const mentionIndex = localMentionsCache.findIndex(m => m.id === mentionId);
          if (mentionIndex !== -1) {
            localMentionsCache[mentionIndex].is_hidden = true; // Still hide the message
            localStorage.setItem('localMentionsCache', JSON.stringify(localMentionsCache));
            displayMentions();
          }
          console.log(`Mention ID ${mentionId} marked as read.`);
        } else {
          const errorData = await response.json();
          alert(`Failed to mark mention as read: ${errorData.detail || response.statusText}`);
        }
      } catch (error) {
        console.error(`Error marking mention ID ${mentionId} as read:`, error);
        alert('Failed to mark mention as read.');
      }
  }
}

// --- Polling ---
function startChatLogPolling() {
  stopChatLogPolling();
  chatLogPollingIntervalId = setInterval(fetchChatLog, currentUserConfig.polling_interval * 1000);
  console.log(`Chat log polling started with interval: ${currentUserConfig.polling_interval} seconds`);
}

function stopChatLogPolling() {
  if (chatLogPollingIntervalId) {
    clearInterval(chatLogPollingIntervalId);
    chatLogPollingIntervalId = null;
    console.log("Chat log polling stopped.");
  }
}

function restartChatLogPolling() {
  stopChatLogPolling();
  startChatLogPolling();
}

function startMentionPolling() {
  stopMentionPolling();
  mentionPollingIntervalId = setInterval(fetchMentions, currentUserConfig.polling_interval * 1000);
  console.log(`Mention polling started with interval: ${currentUserConfig.polling_interval} seconds`);
}

function stopMentionPolling() {
  if (mentionPollingIntervalId) {
    clearInterval(mentionPollingIntervalId);
    mentionPollingIntervalId = null;
    console.log("Mention polling stopped.");
  }
}

function restartMentionPolling() {
  stopMentionPolling();
  startMentionPolling();
}

// Initial fetch when script loads
