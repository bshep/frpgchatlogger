import 'bootstrap/dist/css/bootstrap.min.css';
import 'bootstrap';

const isProduction = import.meta.env.PROD;
console.log(`Environment: ${isProduction ? 'Production' : 'Development'}`);

const BACKEND_URL = isProduction ? document.location.protocol + "//" + document.location.host : "http://localhost:8000";

let originalAnalysisData = null;
let originalConfigData = null;
let originalModNames = null;

document.addEventListener('DOMContentLoaded', () => {
    updateResults();

    const modTradesToggle = document.getElementById('mod-trades-toggle');
    if (modTradesToggle) {
        modTradesToggle.addEventListener('change', (event) => {
            filterModTrades(event.target.checked);
        });
    }

    const filterBtn = document.getElementById('filter-btn');
    if (filterBtn) {
        filterBtn.addEventListener('click', () => {
            const startDateValue = document.getElementById('start-date').value;
            const endDateValue = document.getElementById('end-date').value;

            // JS Date objects parse YYYY-MM-DD as UTC, so add T00:00:00 to treat them as local time
            const startDate = startDateValue ? new Date(startDateValue + 'T00:00:00') : null;
            const endDate = endDateValue ? new Date(endDateValue + 'T23:59:59') : null;

            if (!originalAnalysisData) return;

            const filteredData = {
                trades: originalAnalysisData.trades.filter(rec => {
                    const recDate = new Date(rec.timestamp);
                    if (startDate && recDate < startDate) return false;
                    if (endDate && recDate > endDate) return false;
                    return true;
                }),
                transactions: originalAnalysisData.transactions.filter(rec => {
                    const recDate = new Date(rec.timestamp);
                    if (startDate && recDate < startDate) return false;
                    if (endDate && recDate > endDate) return false;
                    return true;
                })
            };

            renderAnalysis(filteredData, originalConfigData, originalModNames);
        });
    }
});

function filterModTrades(showModsOnly) {
    const accordionItems = document.querySelectorAll('#results .accordion-item');

    accordionItems.forEach(item => {
        const rows = item.querySelectorAll('tbody tr');
        let visibleModRows = 0;
        let itemContainsModTrade = false; // Flag to check if the item originally contains any mod trades

        rows.forEach(row => {
            const isModTrade = row.dataset.isModTrade === 'true';
            if (isModTrade) {
                itemContainsModTrade = true; // Mark that this item originally contains a mod trade
            }

            if (showModsOnly) {
                if (isModTrade) {
                    row.style.display = '';
                    visibleModRows++;
                } else {
                    row.style.display = 'none';
                }
            } else {
                row.style.display = '';
            }
        });

        if (showModsOnly) {
            if (visibleModRows > 0) {
                item.style.display = '';
            } else {
                item.style.display = 'none';
            }
        } else {
            item.style.display = '';
        }

        // Add/remove 'has-mod-trade' class based on whether the item originally contained a mod trade
        // This class is for static highlighting of the accordion item
        if (itemContainsModTrade) {
            item.classList.add('has-mod-trade');
        } else {
            item.classList.remove('has-mod-trade');
        }
    });
}

function renderAnalysis(data, configData, modNames) {
    const resultsContainer = document.getElementById('results');
    resultsContainer.innerHTML = ''; // Clear previous results

    // --- Config & Normalization Helpers ---
    const getConfigValue = (key, defaultValue) => {
        const item = configData.find(c => c.key === key);
        return item ? item.value : defaultValue;
    };

    const rates = {
        ap: parseFloat(getConfigValue('conversion_rate_ap_to_gold', '60')),
        oj: parseFloat(getConfigValue('conversion_rate_oj_to_gold', '10')),
        ac: parseFloat(getConfigValue('conversion_rate_ac_to_gold', '25'))
    };

    const normalizePriceToGpk = (priceStr, qtyStr) => {
        if (typeof priceStr !== 'string' || !priceStr) return null;
        if (!qtyStr) return null;

        let priceLower = priceStr.toLowerCase();
        const numericValue = parseFloat(priceLower.match(/(\d+\.?\d*)/)?.[0]);

        if (isNaN(numericValue)) return null;

        let perK = priceLower.includes('k'); // Is the price already "per 1000"?
        let perEa = false;

        if (qtyStr < 20 || priceLower.includes('ea')) {
            perEa = true;
            priceLower = priceLower.replace('ea','').replace('each','')
        } 
        // perK = true;
        // if (priceLower.includes('ea'))
            // perK = false;

        if (priceLower.includes('ap')) {
            // Rate is "gold per 1000 AP". So 1 AP = rate / 1000 gold.
            return perK ? numericValue * (rates.ap / 1000) : perEa ? numericValue / qtyStr : numericValue * (rates.ap / (qtyStr/1000));
        } else if (priceLower.includes('oj')) {
            return perK ? numericValue * (rates.oj / 1000) : perEa ? numericValue / qtyStr : numericValue * (rates.oj / (qtyStr/1000));
        } else if (priceLower.includes('ac')) {
            return perK ? numericValue * (rates.ac / 1000) : perEa ? numericValue / qtyStr : numericValue * (rates.ac / (qtyStr/1000));
        } else if (priceLower.includes('g')) {
            // Gold is the base currency. If 'k' is present, it's already gpk.
            return perK ? numericValue : perEa ? numericValue / qtyStr : numericValue / (qtyStr/1000);
        }
        return null; // Can't determine currency
    };

    // --- Filter and Transform Data ---
    const processData = (records) => {
        return records
            .filter(rec => rec.price && rec.price.toLowerCase() !== 'nyp')
            .map(rec => {
                const normalized_price_gpk = normalizePriceToGpk(rec.price, rec.quantity);
                return { ...rec, normalized_price_gpk };
            })
            .filter(rec => rec.normalized_price_gpk !== null);
    };

    const processedTrades = processData(data.trades || []);
    const processedTransactions = processData(data.transactions || []);

    // --- Grouping Logic ---
    const groupBy = (array, key) => {
        return array.reduce((result, currentValue) => {
            const groupKey = currentValue[key] || 'Unknown Item';
            (result[groupKey] = result[groupKey] || []).push(currentValue);
            return result;
        }, {});
    };

    const groupedTrades = groupBy(processedTrades, 'item');
    const groupedTransactions = groupBy(processedTransactions, 'item');

    // --- Rendering Function for a Group ---
    const createGroupHtml = (groupData, groupTitle, type, modNames) => {
        let html = `<h2 class="mt-4">${groupTitle}</h2><div class="accordion" id="${type}Accordion">`;

        if (Object.keys(groupData).length === 0) {
            html += `<p>No valid ${type.toLowerCase()} found to display for the selected filters.</p></div>`;
            return html;
        }

        let i = 0;
        for (const item in groupData) {
            const records = groupData[item];
            const count = records.length;
            
            const prices = records.map(r => r.normalized_price_gpk);
            const avgPrice = prices.length > 0 ? (prices.reduce((a, b) => a + b, 0) / prices.length).toFixed(2) : 'N/A';

            const collapseId = `${type}Collapse${i}`;
            
            html += `
                <div class="accordion-item">
                    <h2 class="accordion-header" id="heading${collapseId}">
                        <button class="accordion-button collapsed py-2" type="button" data-bs-toggle="collapse" data-bs-target="#${collapseId}" aria-expanded="false" aria-controls="${collapseId}">
                            <div class="d-flex justify-content-between w-100">
                                <strong>${item}</strong>
                                <small class="text-muted">(${count} ${type}, Avg. Price: ${avgPrice} gpk)</small>
                            </div>
                        </button>
                    </h2>
                    <div id="${collapseId}" class="accordion-collapse collapse" aria-labelledby="heading${collapseId}" data-bs-parent="#${type}Accordion">
                        <div class="accordion-body py-1">
                            <table class="table table-striped table-sm">
                                <thead>
                                    <tr>
                                        <th>${type === 'Trades' ? 'Type' : 'Seller'}</th>
                                        <th>${type === 'Trades' ? 'Sender' : 'Buyer'}</th>
                                        <th>Quantity</th>
                                        <th>Original Price</th>
                                        <th>Price (gpk)</th>
                                        <th>Timestamp</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    ${records.map(rec => {
                                        const traderName = type === 'Trades' ? rec.sender : rec.seller;
                                        const isModTrade = modNames.includes(traderName);
                                        return `
                                        <tr class="${isModTrade ? 'mod-trade' : ''}" data-is-mod-trade="${isModTrade}">
                                            <td>${rec.type || rec.seller || ''}</td>
                                            <td>${rec.sender || rec.buyer || ''}</td>
                                            <td>${rec.quantity || ''}</td>
                                            <td>${rec.price || ''}</td>
                                            <td>${rec.normalized_price_gpk.toFixed(2)}</td>
                                            <td>${new Date(rec.timestamp+"-06:00").toLocaleString(undefined, { timeZone: 'America/Chicago' }) || ''}</td>
                                        </tr>
                                    `}).join('')}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            `;
            i++;
        }
        html += '</div>';
        return html;
    };

    const tradesHtml = createGroupHtml(groupedTrades, 'Trade Offers', 'Trades', modNames);
    const transactionsHtml = createGroupHtml(groupedTransactions, 'Completed Transactions', 'Transactions', modNames);

    resultsContainer.innerHTML = transactionsHtml + tradesHtml;
    
    // After rendering, apply the current filter state
    const modTradesToggle = document.getElementById('mod-trades-toggle');
    if (modTradesToggle) {
        filterModTrades(modTradesToggle.checked);
    }
}

function updateResults() {
    const resultsContainer = document.getElementById('results');
    resultsContainer.innerHTML = '<p>Loading results...</p>';

    // Fetch analysis results, configuration, and chat mods in parallel
    Promise.all([
        fetch(BACKEND_URL + '/api/get-analysis-results').then(res => res.json()),
        fetch(BACKEND_URL + '/api/config').then(res => res.json()),
        fetch(BACKEND_URL + '/api/chat-mods').then(res => res.json())
    ])
    .then(([data, configData, modNames]) => {
        // Store original data
        originalAnalysisData = data;
        originalConfigData = configData;
        originalModNames = modNames;

        // Initial render
        renderAnalysis(originalAnalysisData, originalConfigData, originalModNames);
    })
    .catch(error => {
        resultsContainer.innerHTML = `<p>Error fetching results: ${error}</p>`;
        console.error('Error:', error);
    });
}

