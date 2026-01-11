import 'bootstrap/dist/css/bootstrap.min.css';
import 'bootstrap';

const isProduction = import.meta.env.PROD;
console.log(`Environment: ${isProduction ? 'Production' : 'Development'}`);

const BACKEND_URL = isProduction ? document.location.protocol + "//" + document.location.host : "http://localhost:8000";
const CHAT_LOG_ELEMENT = document.getElementById('chat-log');
const MENTIONS_LOG_ELEMENT = document.getElementById('mentions-log');
const CONFIG_FORM = document.getElementById('config-form');
const MENTION_SOUND = document.getElementById('mention-sound');
const CHANNEL_TABS = document.getElementById('channel-tabs');

let activeChannel = 'trade'; // Default active channel

let currentUserConfig = {
  username: "SuperJ",
  channel: "trade", // This will now be primarily controlled by the active tab
  play_alert: true,
  polling_interval: 30
};

let localMentionsCache = []; // Initialize local cache for mentions

// On DOMContentLoaded
document.addEventListener('DOMContentLoaded', () => {
  loadConfigFromLocalStorage();
  fetchBackendConfig();
  startPolling();

  // Attempt to "unlock" audio context on first user interaction
  const unlockAudio = () => {
    if (MENTION_SOUND.paused) {
      MENTION_SOUND.play().then(() => {
        MENTION_SOUND.pause();
        MENTION_SOUND.currentTime = 0;
      }).catch(error => {
        console.warn("Audio autoplay prevented, user interaction needed:", error);
      });
    }
    document.removeEventListener('click', unlockAudio);
    document.removeEventListener('touchend', unlockAudio);
  };
  document.addEventListener('click', unlockAudio);
  document.addEventListener('touchend', unlockAudio);
});

// --- Tab Navigation ---
CHANNEL_TABS.addEventListener('click', (e) => {
  e.preventDefault();
  const clickedTab = e.target.closest('[data-channel]');
  if (clickedTab && clickedTab.dataset.channel !== activeChannel) {
    // Update active channel
    activeChannel = clickedTab.dataset.channel;

    // Update active class on tabs
    CHANNEL_TABS.querySelectorAll('.nav-link').forEach(tab => tab.classList.remove('active'));
    clickedTab.classList.add('active');

    // Fetch new channel data immediately
    fetchChatLog();
  }
});

// --- Configuration Management ---
function loadConfigFromLocalStorage() {
  const storedConfig = localStorage.getItem('userConfig');
  if (storedConfig) {
    currentUserConfig = JSON.parse(storedConfig);
    // Update form fields
    document.getElementById('username').value = currentUserConfig.username;
    document.getElementById('channel').value = currentUserConfig.channel;
    document.getElementById('polling-interval').value = currentUserConfig.polling_interval;
    document.getElementById('play-alert').checked = currentUserConfig.play_alert;
  }

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

CONFIG_FORM.addEventListener('submit', async (e) => {
  e.preventDefault();
  const formData = new FormData(CONFIG_FORM);
  const newConfig = {
    username: formData.get('username'),
    channel: formData.get('channel'), // Note: this channel setting is now less relevant for display
    polling_interval: parseInt(formData.get('polling_interval'), 10),
    play_alert: formData.get('play_alert') === 'on' ? true : false,
  };

  const oldUsername = currentUserConfig.username;
  currentUserConfig = newConfig;
  localStorage.setItem('userConfig', JSON.stringify(currentUserConfig));

  if (oldUsername !== newConfig.username) {
    localMentionsCache = [];
    localStorage.removeItem('localMentionsCache');
    fetchMentions();
  }
  
  restartPolling();
});

// --- Chat Log Display ---
async function fetchChatLog() {
  try {
    const response = await fetch(`${BACKEND_URL}/api/messages?limit=200&channel=${activeChannel}`);
    const messages = await response.json();
    CHAT_LOG_ELEMENT.innerHTML = ''; // Clear existing
    messages.forEach(msg => { // Most recent first
      const messageElement = document.createElement('a');
      messageElement.href = "#"; // Make it look like a list item
      messageElement.classList.add('list-group-item', 'list-group-item-action');
      
      const timestamp = new Date(msg.timestamp).toLocaleTimeString(undefined, { timeZone: 'America/Chicago' });
      messageElement.innerHTML = `
        <div class="d-flex w-100 justify-content-between">
          <small class="timestamp">${timestamp}</small>
        </div>
        <p class="mb-1 message-content">${msg.message_html}</p>
      `;
      CHAT_LOG_ELEMENT.appendChild(messageElement);
    });
    CHAT_LOG_ELEMENT.scrollTop = 0; // Auto-scroll to top
  } catch (error) {
    console.error(`Error fetching chat log for ${activeChannel}:`, error);
    CHAT_LOG_ELEMENT.innerHTML = `<p>Error loading chat log for ${activeChannel}.</p>`;
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
      newMention.timestamp = new Date(newMention.timestamp);
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
      const timestamp = new Date(mention.timestamp).toLocaleTimeString(undefined, { timeZone: 'America/Chicago' });
      mentionElement.innerHTML = `
        <div class="flex-grow-1">
            <div class="d-flex w-100 justify-content-between">
                <small class="timestamp">${timestamp}</small>
                <small class="channel">(${mention.channel})</small>
            </div>
            <p class="mb-1 message-content">${mention.message_html}</p>
        </div>
        <button type="button" class="btn btn-danger btn-sm ms-2" data-action="delete-mention" data-mention-id="${mention.id}">
            &times;
        </button>
      `;
      MENTIONS_LOG_ELEMENT.appendChild(mentionElement);
    });
    MENTIONS_LOG_ELEMENT.scrollTop = 0;
}

MENTIONS_LOG_ELEMENT.addEventListener('click', async (e) => {
  const deleteButton = e.target.closest('[data-action="delete-mention"]');
  if (deleteButton) {
    const mentionId = parseInt(deleteButton.dataset.mentionId, 10);
      try {
        const response = await fetch(`${BACKEND_URL}/api/mentions/${mentionId}`, { method: 'DELETE' });
        if (response.ok) {
          const mentionIndex = localMentionsCache.findIndex(m => m.id === mentionId);
          if (mentionIndex !== -1) {
            localMentionsCache[mentionIndex].is_hidden = true;
            localStorage.setItem('localMentionsCache', JSON.stringify(localMentionsCache));
            displayMentions();
          }
          console.log(`Mention ID ${mentionId} hidden.`);
        } else {
          const errorData = await response.json();
          alert(`Failed to hide mention: ${errorData.detail || response.statusText}`);
        }
      } catch (error) {
        console.error(`Error hiding mention ID ${mentionId}:`, error);
        alert('Failed to hide mention.');
      }
  }
});

// --- Polling ---
let pollingIntervalId;

function startPolling() {
  stopPolling();
  pollingIntervalId = setInterval(() => {
    fetchChatLog();
    fetchMentions();
  }, currentUserConfig.polling_interval * 1000);
  console.log(`Polling started with interval: ${currentUserConfig.polling_interval} seconds`);
}

function stopPolling() {
  if (pollingIntervalId) {
    clearInterval(pollingIntervalId);
    console.log("Polling stopped.");
  }
}

function restartPolling() {
  stopPolling();
  startPolling();
}

// Initial fetch when script loads
fetchChatLog();
fetchMentions();
