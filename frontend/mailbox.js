const isProduction = import.meta.env.PROD;
console.log(`Environment: ${isProduction ? 'Production' : 'Development'}`);

const BACKEND_URL = isProduction ? document.location.protocol + "//" + document.location.host : "http://localhost:8000";
const LOCAL_STORAGE_KEY = 'frpg_mailbox_monitor_users';

document.addEventListener('DOMContentLoaded', () => {
    const updateListBtn = document.getElementById('update-list-btn');
    const usernamesTextarea = document.getElementById('usernames');
    const resultsTableBody = document.querySelector('#status-table tbody');
    const loadingIndicator = document.getElementById('loading-indicator');
    let pollingInterval;

    function sanitizeUsername(username) {
        if (!username) return '';
        let cleaned = username.trim();
        if (cleaned.startsWith('@')) {
            cleaned = cleaned.substring(1);
        }
        if (cleaned.endsWith(':')) {
            cleaned = cleaned.slice(0, -1);
        }
        return cleaned;
    }

    // Save current textarea content to localStorage
    function saveUsersToLocalStorage(users) {
        localStorage.setItem(LOCAL_STORAGE_KEY, JSON.stringify(users));
    }

    // Load users from localStorage
    function loadUsersFromLocalStorage() {
        const storedUsers = localStorage.getItem(LOCAL_STORAGE_KEY);
        return storedUsers ? JSON.parse(storedUsers) : [];
    }

    async function fetchMailboxStatuses() {
        try {
            const response = await fetch(`${BACKEND_URL}/api/mailbox-status`);
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || 'An unknown error occurred while fetching statuses.');
            }
            const statuses = await response.json();
            displayResults(statuses);
        } catch (error) {
            console.error('Error fetching mailbox statuses:', error);
            // Stop polling on error to avoid flooding the console
            if (pollingInterval) clearInterval(pollingInterval);
        } finally {
            loadingIndicator.style.display = 'none';
        }
    }

    function displayResults(statuses) {
        const usernamesFromText = usernamesTextarea.value.split('\n').map(u => u.trim()).filter(u => u);
        resultsTableBody.innerHTML = ''; // Clear previous results

        if (usernamesFromText.length === 0) {
            resultsTableBody.innerHTML = '<tr><td colspan="3">No users are being monitored.</td></tr>';
            return;
        }

        usernamesFromText.forEach(username => {
            const row = document.createElement('tr');
            const result = statuses[username];
            let detailsCell, lastUpdatedCell, rowClass = '';

            if (result) {
                rowClass = getStatusClass(result.status);
                detailsCell = `<td>${result.current_items} / ${result.max_items} (${(result.fill_ratio * 100).toFixed(1)}%)</td>`;
                const lastUpdated = new Date(result.last_updated + 'Z'); // Assume UTC
                lastUpdatedCell = `<td>${lastUpdated.toLocaleString()}</td>`;
            } else {
                rowClass = getStatusClass('UNKNOWN'); // Use a default class for unknown status
                detailsCell = '<td>Waiting for next server update...</td>';
                lastUpdatedCell = '<td>N/A</td>';
            }

            row.className = rowClass;
            row.innerHTML = `<td>${escapeHTML(username)}</td>${detailsCell}${lastUpdatedCell}`;
            resultsTableBody.appendChild(row);
        });
    }
    
    updateListBtn.addEventListener('click', async () => {
        const rawUsernames = usernamesTextarea.value.split('\n');
        const sanitizedUsernames = rawUsernames.map(u => sanitizeUsername(u)).filter(u => u);
        
        if (sanitizedUsernames.length > 5) {
            alert('You can only monitor up to 5 users at a time.');
            return;
        }

        // Update the textarea with the sanitized usernames for immediate feedback
        usernamesTextarea.value = sanitizedUsernames.join('\n');
        saveUsersToLocalStorage(sanitizedUsernames); // Save to local storage

        loadingIndicator.style.display = 'block';

        try {
            const response = await fetch(`${BACKEND_URL}/api/mailbox/preferences`, { // Changed endpoint
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ usernames: sanitizedUsernames }),
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || 'An unknown error occurred while updating the list.');
            }
            
            // After successfully updating the list, fetch the latest statuses immediately
            await fetchMailboxStatuses();

        } catch (error) {
            console.error('Error updating monitored users:', error);
            alert(`Error: ${error.message}`);
            loadingIndicator.style.display = 'none';
        }
    });

    async function loadMonitoredUsers() {
        loadingIndicator.style.display = 'block';
        const storedUsers = loadUsersFromLocalStorage();
        if (storedUsers.length > 0) {
            usernamesTextarea.value = storedUsers.join('\n');
            await fetchMailboxStatuses(); // Initial fetch with local storage users
            loadingIndicator.style.display = 'none';
        } else {
            // If local storage is empty, try fetching from backend (if user is logged in)
            try {
                const response = await fetch(`${BACKEND_URL}/api/mailbox/preferences`); // Changed endpoint
                if (response.ok) {
                    const data = await response.json();
                    if (data.usernames && data.usernames.length > 0) {
                        usernamesTextarea.value = data.usernames.join('\n');
                        saveUsersToLocalStorage(data.usernames); // Save to local storage
                    }
                } else {
                    // Handle case where user is not logged in or no preferences
                    console.warn('Could not fetch user preferences from backend, possibly not logged in.');
                }
                await fetchMailboxStatuses();
            } catch (error) {
                console.error('Error loading monitored users from backend:', error);
            } finally {
                loadingIndicator.style.display = 'none';
            }
        }
    }


    function getStatusClass(status) {
        switch (status) {
            case 'GREEN': return 'table-success';
            case 'YELLOW': return 'table-warning';
            case 'RED': return 'table-danger';
            default: return 'table-secondary'; // For 'Unknown' or other statuses
        }
    }

    function escapeHTML(str) {
        const p = document.createElement('p');
        p.appendChild(document.createTextNode(str));
        return p.innerHTML;
    }

    // --- Main Execution ---
    loadMonitoredUsers();
    // Start polling for status updates every 2 seconds
    pollingInterval = setInterval(fetchMailboxStatuses, 5000);
});
