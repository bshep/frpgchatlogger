import 'bootstrap/dist/css/bootstrap.min.css';
import 'bootstrap';

const BACKEND_URL = document.location.protocol + "//" + document.location.host;
const CHAT_LOG_ELEMENT = document.getElementById('chat-log');
const MENTIONS_LOG_ELEMENT = document.getElementById('mentions-log');
const CONFIG_FORM = document.getElementById('config-form');
const MENTION_SOUND = document.getElementById('mention-sound');

let currentUserConfig = {
  username: "SuperJ",
  channel: "trade",
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

  const oldUsername = currentUserConfig.username;

  currentUserConfig = newConfig;
  localStorage.setItem('userConfig', JSON.stringify(currentUserConfig));

  // If username changed, clear local cache and re-fetch all mentions for the new user
  if (oldUsername !== newConfig.username) {
    localMentionsCache = [];
    localStorage.removeItem('localMentionsCache');
    // Also re-fetch mentions immediately for the new user
    fetchMentions();
  }

  // Update backend config for channel ONLY
  try {
    await fetch(`${BACKEND_URL}/api/config?key=channel&value=${newConfig.channel}`, { method: 'POST' });
    alert('Configuration saved!');
    restartPolling(); // Restart polling to use new interval or channel
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
    console.error("Error fetching chat log:", error);
    CHAT_LOG_ELEMENT.innerHTML = '<p>Error loading chat log.</p>';
  }
}

// --- Mentions Display ---
async function fetchMentions() {
  try {
    let latestTimestamp = null;
    if (localMentionsCache.length > 0) {
      // Find the latest timestamp of *visible* mentions in the cache to ask for newer mentions
      const visibleMentions = localMentionsCache.filter(m => !m.is_hidden);
      if (visibleMentions.length > 0) {
        latestTimestamp = visibleMentions.reduce((maxTs, mention) => 
            (mention.timestamp > maxTs ? mention.timestamp : maxTs), visibleMentions[0].timestamp
        );
      }
    }

    let url = `${BACKEND_URL}/api/mentions?username=${currentUserConfig.username}`;
    if (latestTimestamp) {
      url += `&since=${latestTimestamp.toISOString()}`;
    }

    const response = await fetch(url);
    const newMentions = await response.json();
    
    let playSound = false;
    if (newMentions.length > 0 && currentUserConfig.play_alert) {
      playSound = true;
    }

    // Merge new mentions with local cache, ensuring no duplicates and chronological order
    newMentions.forEach(newMention => {
      newMention.timestamp = new Date(newMention.timestamp); // Convert timestamp string to Date object
      newMention.is_hidden = newMention.is_hidden || false; // Ensure is_hidden property exists
      if (!localMentionsCache.some(m => m.id === newMention.id)) {
        localMentionsCache.push(newMention);
      } else {
        // Update existing mention in cache in case is_hidden state changed on backend
        const existingIndex = localMentionsCache.findIndex(m => m.id === newMention.id);
        if (existingIndex !== -1) {
            localMentionsCache[existingIndex] = newMention;
        }
      }
    });

    // Sort the cache by timestamp (most recent first for display)
    localMentionsCache.sort((a, b) => b.timestamp.getTime() - a.timestamp.getTime());

    localStorage.setItem('localMentionsCache', JSON.stringify(localMentionsCache));

    displayMentions(); // Render all visible mentions from cache

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
    localMentionsCache.forEach(mention => { // Most recent first
      if (mention.is_hidden) return; // Skip hidden mentions
      const mentionElement = document.createElement('div'); // Use div for individual mentions with delete button
      mentionElement.id = `mention-${mention.id}`; // Add ID for easy removal
      mentionElement.classList.add('list-group-item', 'list-group-item-action', 'd-flex', 'justify-content-between', 'align-items-start');
      const timestamp = mention.timestamp.toLocaleTimeString(undefined, { timeZone: 'America/Chicago' }); // Format in Chicago time      
      mentionElement.innerHTML = `
        <div class="flex-grow-1">
            <div class="d-flex w-100 justify-content-between">
                <small class="timestamp">${timestamp}</small>
            </div>
            <p class="mb-1 message-content">${mention.message_html}</p>
        </div>
        <button type="button" class="btn btn-danger btn-sm ms-2" data-action="delete-mention" data-mention-id="${mention.id}">
            &times;
        </button>
      `;
      MENTIONS_LOG_ELEMENT.appendChild(mentionElement);
    });
    MENTIONS_LOG_ELEMENT.scrollTop = 0; // Auto-scroll to top
}

// Event delegation for deleting individual mentions
MENTIONS_LOG_ELEMENT.addEventListener('click', async (e) => {
  const deleteButton = e.target.closest('[data-action="delete-mention"]');
  if (deleteButton) {
    const mentionId = parseInt(deleteButton.dataset.mentionId, 10);
    // if (confirm(`Are you sure you want to hide mention ID ${mentionId}?`)) 
      {
      try {
        const response = await fetch(`${BACKEND_URL}/api/mentions/${mentionId}`, { method: 'DELETE' });
        if (response.ok) {
          // Update local cache: set is_hidden to true
          const mentionIndex = localMentionsCache.findIndex(m => m.id === mentionId);
          if (mentionIndex !== -1) {
            localMentionsCache[mentionIndex].is_hidden = true;
            localStorage.setItem('localMentionsCache', JSON.stringify(localMentionsCache));
            displayMentions(); // Re-render to reflect the change (hide the mention)
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

