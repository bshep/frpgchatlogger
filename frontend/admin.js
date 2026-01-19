import 'bootstrap/dist/css/bootstrap.min.css';
import 'bootstrap';

const isProduction = import.meta.env.PROD;
const BACKEND_URL = isProduction ? document.location.protocol + "//" + document.location.host : "http://localhost:8000";

// --- DOM Elements ---
const configForm = document.getElementById('config-form');
const allowedUsersTextarea = document.getElementById('allowed-users');
const allowedGuildsTextarea = document.getElementById('allowed-guilds');
const adminUsersTextarea = document.getElementById('admin-users');
const analysisAllowedUsersTextarea = document.getElementById('analysis_allowed_users');
const analysisAllowedGuildsTextarea = document.getElementById('analysis_allowed_guilds');
const channelsTextarea = document.getElementById('monitored-channels');
const schedulerPollingIntervalInput = document.getElementById('scheduler-polling-interval');
const analysisChunkSizeInput = document.getElementById('analysis-chunk-size');
const conversionApInput = document.getElementById('conversion_rate_ap_to_gold');
const conversionOjInput = document.getElementById('conversion_rate_oj_to_gold');
const conversionAcInput = document.getElementById('conversion_rate_ac_to_gold');
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
        
        const getConfigValue = (key, defaultValue = '') => configs.find(c => c.key === key)?.value || defaultValue;

        allowedUsersTextarea.value = getConfigValue('allowed_users').split(',').join('\n');
        allowedGuildsTextarea.value = getConfigValue('allowed_guilds').split(',').join('\n');
        adminUsersTextarea.value = getConfigValue('admin_users').split(',').join('\n');
        analysisAllowedUsersTextarea.value = getConfigValue('analysis_allowed_users').split(',').join('\n');
        analysisAllowedGuildsTextarea.value = getConfigValue('analysis_allowed_guilds').split(',').join('\n');
        channelsTextarea.value = getConfigValue('channels_to_track').split(',').join('\n');
        schedulerPollingIntervalInput.value = getConfigValue('scheduler_polling_interval', '5');
        analysisChunkSizeInput.value = getConfigValue('analysis_chunk_size', '50');
        conversionApInput.value = getConfigValue('conversion_rate_ap_to_gold', '60');
        conversionOjInput.value = getConfigValue('conversion_rate_oj_to_gold', '10');
        conversionAcInput.value = getConfigValue('conversion_rate_ac_to_gold', '25');

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

    const getTaValue = (ta) => ta.value.split('\n').filter(u => u.trim()).join(',');

    const configs = [
        { key: 'allowed_users', value: getTaValue(allowedUsersTextarea) },
        { key: 'allowed_guilds', value: getTaValue(allowedGuildsTextarea) },
        { key: 'admin_users', value: getTaValue(adminUsersTextarea) },
        { key: 'analysis_allowed_users', value: getTaValue(analysisAllowedUsersTextarea) },
        { key: 'analysis_allowed_guilds', value: getTaValue(analysisAllowedGuildsTextarea) },
        { key: 'channels_to_track', value: getTaValue(channelsTextarea) },
        { key: 'scheduler_polling_interval', value: schedulerPollingIntervalInput.value },
        { key: 'analysis_chunk_size', value: analysisChunkSizeInput.value },
        { key: 'conversion_rate_ap_to_gold', value: conversionApInput.value },
        { key: 'conversion_rate_oj_to_gold', value: conversionOjInput.value },
        { key: 'conversion_rate_ac_to_gold', value: conversionAcInput.value }
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