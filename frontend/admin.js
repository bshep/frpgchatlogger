import 'bootstrap/dist/css/bootstrap.min.css';
import 'bootstrap';

const isProduction = import.meta.env.PROD;
const BACKEND_URL = isProduction ? document.location.protocol + "//" + document.location.host : "http://localhost:8000";

// --- DOM Elements ---
const configForm = document.getElementById('config-form');
const allowedUsersTextarea = document.getElementById('allowed-users');
const allowedGuildsTextarea = document.getElementById('allowed-guilds');
const adminUsersTextarea = document.getElementById('admin-users');
const channelsTextarea = document.getElementById('monitored-channels');
const schedulerPollingIntervalInput = document.getElementById('scheduler-polling-interval');
const analysisChunkSizeInput = document.getElementById('analysis-chunk-size');
const saveStatus = document.getElementById('save-status');

// --- Initialization ---
document.addEventListener('DOMContentLoaded', initializeAdminPage);

function initializeAdminPage() {
    fetchConfig();
    configForm.addEventListener('submit', handleConfigSave);
}

async function fetchConfig() {
    try {
        const response = await fetch(`${BACKEND_URL}/api/config`);
        if (!response.ok) {
            throw new Error('Failed to fetch configuration.');
        }
        const configs = await response.json();
        
        // Find and populate each config value
        const allowedUsers = configs.find(c => c.key === 'allowed_users')?.value || '';
        const allowedGuilds = configs.find(c => c.key === 'allowed_guilds')?.value || '';
        const adminUsers = configs.find(c => c.key === 'admin_users')?.value || '';
        const channels = configs.find(c => c.key === 'channels_to_track')?.value || '';
        const pollingInterval = configs.find(c => c.key === 'scheduler_polling_interval')?.value || '5';
        const analysisChunkSize = configs.find(c => c.key === 'analysis_chunk_size')?.value || '50';

        allowedUsersTextarea.value = allowedUsers.split(',').join('\n');
        allowedGuildsTextarea.value = allowedGuilds.split(',').join('\n');
        adminUsersTextarea.value = adminUsers.split(',').join('\n');
        channelsTextarea.value = channels.split(',').join('\n');
        schedulerPollingIntervalInput.value = pollingInterval;
        analysisChunkSizeInput.value = analysisChunkSize;

    } catch (error) {
        console.error('Error fetching config:', error);
        saveStatus.textContent = 'Error loading configuration.';
        saveStatus.className = 'text-danger';
    }
}

async function handleConfigSave(event) {
    event.preventDefault();
    saveStatus.textContent = 'Saving...';
    saveStatus.className = 'text-info';

    const configs = [
        { key: 'allowed_users', value: allowedUsersTextarea.value.split('\n').filter(u => u.trim()).join(',') },
        { key: 'allowed_guilds', value: allowedGuildsTextarea.value.split('\n').filter(g => g.trim()).join(',') },
        { key: 'admin_users', value: adminUsersTextarea.value.split('\n').filter(u => u.trim()).join(',') },
        { key: 'channels_to_track', value: channelsTextarea.value.split('\n').filter(c => c.trim()).join(',') },
        { key: 'scheduler_polling_interval', value: schedulerPollingIntervalInput.value },
        { key: 'analysis_chunk_size', value: analysisChunkSizeInput.value }
    ];

    try {
        const response = await fetch(`${BACKEND_URL}/api/config`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ configs: configs }),
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.detail || 'Failed to save configuration.');
        }

        saveStatus.textContent = 'Configuration saved successfully!';
        saveStatus.className = 'text-success';
    } catch (error) {
        console.error('Error saving config:', error);
        saveStatus.textContent = `Error: ${error.message}`;
        saveStatus.className = 'text-danger';
    } finally {
        setTimeout(() => {
            saveStatus.textContent = '';
        }, 5000);
    }
}
