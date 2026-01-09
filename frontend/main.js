const BACKEND_URL = "http://localhost:8000";
const CHAT_LOG_ELEMENT = document.getElementById('chat-log');
const MENTIONS_LOG_ELEMENT = document.getElementById('mentions-log');
const CONFIG_FORM = document.getElementById('config-form');
const CLEAR_MENTIONS_BUTTON = document.getElementById('clear-mentions');
const MENTION_SOUND = document.getElementById('mention-sound');

let currentUserConfig = {
  username: "SuperJ", // Default, will be overwritten by localStorage or backend
  channel: "trade",    // Default
  play_alert: true,    // Default
  polling_interval: 30 // Default
};

// --- Tab Functionality ---
window.openTab = (evt, tabName) => {
  let tabContents = document.getElementsByClassName("tab-content");
  for (let i = 0; i < tabContents.length; i++) {
    tabContents[i].style.display = "none";
  }
  let tabButtons = document.getElementsByClassName("tab-button");
  for (let i = 0; i < tabButtons.length; i++) {
    tabButtons[i].className = tabButtons[i].className.replace(" active", "");
  }
  document.getElementById(tabName).style.display = "block";
  evt.currentTarget.className += " active";
};

// Open default tab on load
document.addEventListener('DOMContentLoaded', () => {
  document.querySelector('.tab-button').click();
  loadConfigFromLocalStorage();
  fetchBackendConfig(); // Fetch initial config from backend and sync
  startPolling();

  // Attempt to "unlock" audio context on first user interaction
  const unlockAudio = () => {
    if (MENTION_SOUND.paused) {
      MENTION_SOUND.play().then(() => {
        MENTION_SOUND.pause();
        MENTION_SOUND.currentTime = 0; // Reset for next play
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
}

async function fetchBackendConfig() {
  try {
    const channelRes = await fetch(`${BACKEND_URL}/api/config`);
    if (channelRes.ok) {
      const backendConfigs = await channelRes.json();
      const channelConfig = backendConfigs.find(c => c.key === 'channel');
      if (channelConfig) {
        currentUserConfig.channel = channelConfig.value;
        document.getElementById('channel').value = channelConfig.value;
        localStorage.setItem('userConfig', JSON.stringify(currentUserConfig));
      }
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
    channel: formData.get('channel'),
    polling_interval: parseInt(formData.get('polling_interval'), 10),
    play_alert: formData.get('play_alert') === 'on' ? true : false,
  };

  currentUserConfig = newConfig;
  localStorage.setItem('userConfig', JSON.stringify(currentUserConfig));

  // Update backend config for channel ONLY
  try {
    await fetch(`${BACKEND_URL}/api/config?key=channel&value=${newConfig.channel}`, { method: 'POST' });
    alert('Configuration saved!');
    restartPolling();
  } catch (error) {
    console.error("Error saving config to backend:", error);
    alert('Failed to save configuration to backend.');
  }
});


// --- Chat Log Display ---
async function fetchChatLog() {
  try {
    const response = await fetch(`${BACKEND_URL}/api/messages?limit=200&channel=${currentUserConfig.channel}`);
    const messages = await response.json();
    CHAT_LOG_ELEMENT.innerHTML = ''; // Clear existing
    messages.forEach(msg => { // Most recent first
      const messageElement = document.createElement('div');
      messageElement.classList.add('chat-message');
      
      const timestamp = new Date(msg.timestamp).toLocaleTimeString();
      messageElement.innerHTML = `
        <span class="timestamp">${timestamp}</span>
        <span class="username">${msg.username}:</span>
        <span class="message-content">${msg.message_html}</span>
      `;
      CHAT_LOG_ELEMENT.appendChild(messageElement);
    });
    CHAT_LOG_ELEMENT.scrollTop = 0; // Auto-scroll to top
  } catch (error) {
    console.error("Error fetching chat log:", error);
    CHAT_LOG_ELEMENT.innerHTML = '<p>Error loading chat log.</p>';
  }
}

// --- Mentions Display ---
async function fetchMentions() {
  try {
    const response = await fetch(`${BACKEND_URL}/api/mentions?username=${currentUserConfig.username}`);
    const mentions = await response.json();
    
    // Check for new mentions and play sound
    const oldMentionCount = MENTIONS_LOG_ELEMENT.children.length;
    if (mentions.length > oldMentionCount && currentUserConfig.play_alert) {
        MENTION_SOUND.play();
    }

    MENTIONS_LOG_ELEMENT.innerHTML = ''; // Clear existing
    mentions.forEach(mention => { // Most recent first
      const mentionElement = document.createElement('div');
      mentionElement.classList.add('mention-message');
      const timestamp = new Date(mention.timestamp).toLocaleTimeString();
      mentionElement.innerHTML = `
        <span class="timestamp">${timestamp}</span>
        <span class="username">${mention.mentioned_user}:</span>
        <span class="message-content">${mention.message_html}</span>
      `;
      MENTIONS_LOG_ELEMENT.appendChild(mentionElement);
    });
    MENTIONS_LOG_ELEMENT.scrollTop = 0; // Auto-scroll to top
  } catch (error) {
    console.error("Error fetching mentions:", error);
    MENTIONS_LOG_ELEMENT.innerHTML = '<p>Error loading mentions.</p>';
  }
}

CLEAR_MENTIONS_BUTTON.addEventListener('click', async () => {
  if (confirm('Are you sure you want to clear all mentions?')) {
    try {
      await fetch(`${BACKEND_URL}/api/mentions?username=${currentUserConfig.username}`, { method: 'DELETE' });
      MENTIONS_LOG_ELEMENT.innerHTML = '<p>All mentions cleared.</p>';
      fetchMentions(); // Refresh mentions list
    } catch (error) {
      console.error("Error clearing mentions:", error);
      alert('Failed to clear mentions.');
    }
  }
});


// --- Polling ---
let pollingIntervalId;

function startPolling() {
  stopPolling(); // Ensure no duplicate intervals
  pollingIntervalId = setInterval(() => {
    fetchChatLog();
    fetchMentions();
  }, currentUserConfig.polling_interval * 1000); // Convert seconds to milliseconds
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
