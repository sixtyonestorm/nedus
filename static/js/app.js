// Albion Market Flipper JavaScript

// Global variables
let lastUpdateTime = new Date();
let connectionStatus = false;
let autoRefreshInterval = null;

// Initialize application
document.addEventListener('DOMContentLoaded', function() {
    initializeApp();
    setupEventListeners();
    startAutoRefresh();
});

function initializeApp() {
    console.log('Albion Market Flipper initialized');
    updateLastUpdateTime();
    
    // Initialize tooltips
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function(tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });
    
    // Initialize modals
    const modalList = [].slice.call(document.querySelectorAll('.modal'));
    modalList.map(function(modalEl) {
        return new bootstrap.Modal(modalEl);
    });
}

function setupEventListeners() {
    // Handle form submissions with loading states
    const forms = document.querySelectorAll('form');
    forms.forEach(form => {
        form.addEventListener('submit', function(e) {
            const submitBtn = form.querySelector('button[type="submit"]');
            if (submitBtn) {
                submitBtn.disabled = true;
                submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Processing...';
            }
        });
    });
    
    // Handle quantity input validation
    const quantityInputs = document.querySelectorAll('input[name="quantity"]');
    quantityInputs.forEach(input => {
        input.addEventListener('input', function() {
            const max = parseInt(this.max);
            const value = parseInt(this.value);
            
            if (value > max) {
                this.value = max;
            }
            if (value < 1) {
                this.value = 1;
            }
        });
    });
    
    // Handle filter form auto-submit
    const filterInputs = document.querySelectorAll('.auto-submit input, .auto-submit select');
    filterInputs.forEach(input => {
        input.addEventListener('change', function() {
            // Debounce the form submission
            clearTimeout(this.autoSubmitTimeout);
            this.autoSubmitTimeout = setTimeout(() => {
                this.closest('form').submit();
            }, 500);
        });
    });
}

function startAutoRefresh() {
    // Only auto-refresh on dashboard and arbitrage pages
    const currentPage = window.location.pathname;
    if (currentPage === '/' || currentPage === '/arbitrage') {
        autoRefreshInterval = setInterval(refreshData, 10000); // 10 seconds
    }
}

function refreshData() {
    fetch('/api/status')
        .then(response => response.json())
        .then(data => {
            updateStatus(data);
            updateLastUpdateTime();
        })
        .catch(error => {
            console.error('Error refreshing data:', error);
            connectionStatus = false;
            updateConnectionIndicator();
        });
}

function updateStatus(data) {
    connectionStatus = data.connection_established;
    
    // Update connection indicator
    updateConnectionIndicator();
    
    // Update player info
    const playerElement = document.querySelector('.player-info');
    if (playerElement && data.current_player) {
        playerElement.textContent = data.current_player;
    }
    
    // Update location info
    const locationElement = document.querySelector('.location-info');
    if (locationElement && data.current_location) {
        locationElement.textContent = data.current_location;
    }
    
    // Update data counts with animation
    updateCountWithAnimation('.offers-count', data.offers_count);
    updateCountWithAnimation('.requests-count', data.requests_count);
}

function updateConnectionIndicator() {
    const indicators = document.querySelectorAll('.connection-indicator');
    indicators.forEach(indicator => {
        if (connectionStatus) {
            indicator.className = 'connection-indicator fas fa-circle text-success';
            indicator.title = 'Connected';
        } else {
            indicator.className = 'connection-indicator fas fa-circle text-danger';
            indicator.title = 'Disconnected';
        }
    });
}

function updateCountWithAnimation(selector, newValue) {
    const element = document.querySelector(selector);
    if (element) {
        const currentValue = parseInt(element.textContent.replace(/,/g, '')) || 0;
        if (currentValue !== newValue) {
            element.classList.add('fade-in');
            element.textContent = newValue.toLocaleString();
            
            setTimeout(() => {
                element.classList.remove('fade-in');
            }, 300);
        }
    }
}

function updateLastUpdateTime() {
    lastUpdateTime = new Date();
    const timeElements = document.querySelectorAll('.last-update-time');
    timeElements.forEach(element => {
        element.textContent = lastUpdateTime.toLocaleTimeString();
    });
}

// Utility functions
function formatSilver(amount) {
    return new Intl.NumberFormat().format(amount);
}

function formatROI(roi) {
    return roi.toFixed(1) + '%';
}

function showNotification(message, type = 'info') {
    // Create notification element
    const notification = document.createElement('div');
    notification.className = `alert alert-${type} alert-dismissible fade show position-fixed`;
    notification.style.cssText = 'top: 20px; right: 20px; z-index: 9999; min-width: 300px;';
    notification.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;
    
    // Add to DOM
    document.body.appendChild(notification);
    
    // Auto-remove after 5 seconds
    setTimeout(() => {
        if (notification.parentNode) {
            notification.remove();
        }
    }, 5000);
}

// Export functions
function exportTableToCSV(tableId, filename) {
    const table = document.getElementById(tableId);
    if (!table) return;
    
    let csv = [];
    const rows = table.querySelectorAll('tr');
    
    rows.forEach(row => {
        const cells = row.querySelectorAll('th, td');
        const rowData = Array.from(cells).map(cell => {
            let text = cell.textContent.trim();
            // Escape quotes and wrap in quotes if contains comma
            if (text.includes(',') || text.includes('"')) {
                text = '"' + text.replace(/"/g, '""') + '"';
            }
            return text;
        });
        csv.push(rowData.join(','));
    });
    
    // Create and download file
    const csvContent = csv.join('\n');
    const blob = new Blob([csvContent], { type: 'text/csv' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename || 'albion_market_data.csv';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);
}

// Sorting functions
function sortTable(tableId, columnIndex, isNumeric = false) {
    const table = document.getElementById(tableId);
    if (!table) return;
    
    const tbody = table.querySelector('tbody');
    const rows = Array.from(tbody.querySelectorAll('tr'));
    
    // Determine sort direction
    const currentSort = table.dataset.sortColumn;
    const currentDir = table.dataset.sortDirection || 'asc';
    const newDir = (currentSort === columnIndex.toString() && currentDir === 'asc') ? 'desc' : 'asc';
    
    // Sort rows
    rows.sort((a, b) => {
        const aVal = a.cells[columnIndex].textContent.trim();
        const bVal = b.cells[columnIndex].textContent.trim();
        
        let comparison;
        if (isNumeric) {
            const aNum = parseFloat(aVal.replace(/[^0-9.-]/g, ''));
            const bNum = parseFloat(bVal.replace(/[^0-9.-]/g, ''));
            comparison = aNum - bNum;
        } else {
            comparison = aVal.localeCompare(bVal);
        }
        
        return newDir === 'asc' ? comparison : -comparison;
    });
    
    // Update table
    rows.forEach(row => tbody.appendChild(row));
    
    // Update sort indicators
    table.dataset.sortColumn = columnIndex;
    table.dataset.sortDirection = newDir;
    
    // Update header indicators
    const headers = table.querySelectorAll('th');
    headers.forEach((header, index) => {
        header.classList.remove('sort-asc', 'sort-desc');
        if (index === columnIndex) {
            header.classList.add(`sort-${newDir}`);
        }
    });
}

// Filter functions
function filterTable(tableId, filterValue, columnIndex) {
    const table = document.getElementById(tableId);
    if (!table) return;
    
    const rows = table.querySelectorAll('tbody tr');
    const filter = filterValue.toLowerCase();
    
    rows.forEach(row => {
        const cell = row.cells[columnIndex];
        const text = cell ? cell.textContent.toLowerCase() : '';
        row.style.display = text.includes(filter) ? '' : 'none';
    });
}

// Market data processing
function calculateROI(buyPrice, sellPrice) {
    if (buyPrice <= 0) return 0;
    return ((sellPrice - buyPrice) / buyPrice) * 100;
}

function calculateProfit(buyPrice, sellPrice, quantity) {
    return (sellPrice - buyPrice) * quantity;
}

// Clean up when page unloads
window.addEventListener('beforeunload', function() {
    if (autoRefreshInterval) {
        clearInterval(autoRefreshInterval);
    }
});

// Handle offline/online events
window.addEventListener('online', function() {
    showNotification('Connection restored', 'success');
    if (!autoRefreshInterval) {
        startAutoRefresh();
    }
});

window.addEventListener('offline', function() {
    showNotification('Connection lost', 'warning');
    if (autoRefreshInterval) {
        clearInterval(autoRefreshInterval);
        autoRefreshInterval = null;
    }
});

// Keyboard shortcuts
document.addEventListener('keydown', function(e) {
    // Ctrl/Cmd + R for manual refresh
    if ((e.ctrlKey || e.metaKey) && e.key === 'r') {
        e.preventDefault();
        refreshData();
        showNotification('Data refreshed manually', 'info');
    }
    
    // Escape to close modals
    if (e.key === 'Escape') {
        const openModals = document.querySelectorAll('.modal.show');
        openModals.forEach(modal => {
            const modalInstance = bootstrap.Modal.getInstance(modal);
            if (modalInstance) {
                modalInstance.hide();
            }
        });
    }
});

// Debug mode
if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') {
    window.AlbionMarketDebug = {
        refreshData,
        updateStatus,
        exportTableToCSV,
        sortTable,
        filterTable,
        showNotification
    };
    console.log('Debug mode enabled. Access functions via window.AlbionMarketDebug');
}
