import 'bootstrap/dist/css/bootstrap.min.css';
import 'bootstrap';

const isProduction = import.meta.env.PROD;
console.log(`Environment: ${isProduction ? 'Production' : 'Development'}`);

const BACKEND_URL = isProduction ? document.location.protocol + "//" + document.location.host : "http://localhost:8000";

document.addEventListener('DOMContentLoaded', () => {
    updateResults();
});

document.getElementById('analyze-btn').addEventListener('click', () => {
    const startDate = document.getElementById('start-date').value;
    const endDate = document.getElementById('end-date').value;

    const resultsContainer = document.getElementById('results');
    resultsContainer.innerHTML = '<p>Triggering analysis...</p>';

    fetch(BACKEND_URL + '/api/trigger-analysis', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            start_date: startDate,
            end_date: endDate
        })
    })
    .then(response => {
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return response.json();
    })
    .then(() => {
        resultsContainer.innerHTML = '<p>Analysis triggered. Fetching results...</p>';
        updateResults(); // Fetch and display the new results
    })
    .catch(error => {
        resultsContainer.innerHTML = `<p>Error during analysis trigger: ${error}</p>`;
        console.error('Error:', error);
    });
});

function updateResults() {
    const resultsContainer = document.getElementById('results');
    resultsContainer.innerHTML = '<p>Loading results...</p>';

    fetch(BACKEND_URL + '/api/get-analysis-results')
    .then(response => {
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return response.json();
    })
    .then(data => {
        resultsContainer.innerHTML = `
            <h2>Trade Offers</h2>
            <table class="table table-striped table-sm">
                <thead>
                    <tr>
                        <th>Type</th>
                        <th>Sender</th>
                        <th>Item</th>
                        <th>Quantity</th>
                        <th>Price</th>
                        <th>Timestamp</th>
                    </tr>
                </thead>
                <tbody>
                    ${data.trades.length > 0 ? data.trades.map(trade => `
                        <tr>
                            <td>${trade.type || ''}</td>
                            <td>${trade.sender || ''}</td>
                            <td>${trade.item || ''}</td>
                            <td>${trade.quantity || ''}</td>
                            <td>${trade.price || ''}</td>
                            <td>${new Date(trade.timestamp+"-06:00").toLocaleString(undefined, { timeZone: 'America/Chicago' }) || ''}</td>
                        </tr>
                    `).join('') : '<tr><td colspan="6">No trades found.</td></tr>'}
                </tbody>
            </table>

            <h2>Transactions</h2>
            <table class="table table-striped table-sm">
                <thead>
                    <tr>
                        <th>Seller</th>
                        <th>Buyer</th>
                        <th>Item</th>
                        <th>Quantity</th>
                        <th>Price</th>
                        <th>Timestamp</th>
                    </tr>
                </thead>
                <tbody>
                    ${data.transactions.length > 0 ? data.transactions.map(txn => `
                        <tr>
                            <td>${txn.seller || ''}</td>
                            <td>${txn.buyer || ''}</td>
                            <td>${txn.item || ''}</td>
                            <td>${txn.quantity || ''}</td>
                            <td>${txn.price || ''}</td>
                            <td>${new Date(txn.timestamp+"-06:00").toLocaleString(undefined, { timeZone: 'America/Chicago' }) || ''}</td>
                        </tr>
                    `).join('') : '<tr><td colspan="6">No transactions found.</td></tr>'}
                </tbody>
            </table>
        `;
    })
    .catch(error => {
        resultsContainer.innerHTML = `<p>Error fetching results: ${error}</p>`;
        console.error('Error:', error);
    });
}