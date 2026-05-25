/**
 * Settings - Manages application settings with localStorage persistence
 */

class Settings {
    constructor() {
        this.defaults = {
            // Trading settings
            autoSellOnStopLoss: true,
            autoSellOnTakeProfit: true,

            // Chart settings
            defaultTimeframe: '5Min',
            defaultSymbol: 'SPY',

            // UI settings
            soundAlerts: true,
            showTooltips: true,
            tradingPanelSide: 'right',  // 'left' or 'right'
            theme: 'dark',

            // Position settings
            defaultPositionSize: 1000,
            showPnLInHeader: true
        };

        this.settings = this.load();
    }

    /**
     * Load settings from localStorage
     * @returns {Object} Settings object
     */
    load() {
        try {
            const stored = localStorage.getItem('tradingSettings');
            if (stored) {
                return { ...this.defaults, ...JSON.parse(stored) };
            }
        } catch (error) {
            console.error('Error loading settings:', error);
        }

        return { ...this.defaults };
    }

    /**
     * Save settings to localStorage
     */
    save() {
        try {
            localStorage.setItem('tradingSettings', JSON.stringify(this.settings));
            window.EventBus.emit('settings:changed', this.settings);
        } catch (error) {
            console.error('Error saving settings:', error);
        }
    }

    /**
     * Get a setting value
     * @param {string} key - Setting key
     * @returns {*} Setting value
     */
    get(key) {
        return this.settings[key] ?? this.defaults[key];
    }

    /**
     * Set a setting value
     * @param {string} key - Setting key
     * @param {*} value - Setting value
     */
    set(key, value) {
        this.settings[key] = value;
        this.save();
    }

    /**
     * Update multiple settings at once
     * @param {Object} updates - Object with key-value pairs to update
     */
    update(updates) {
        Object.assign(this.settings, updates);
        this.save();
    }

    /**
     * Reset all settings to defaults
     */
    reset() {
        this.settings = { ...this.defaults };
        this.save();
    }

    /**
     * Get all settings
     * @returns {Object} All settings
     */
    getAll() {
        return { ...this.settings };
    }
}

// Create singleton instance
window.Settings = new Settings();

// Global functions for settings modal
window.openSettings = function() {
    const modal = document.getElementById('settingsModal');
    if (modal) {
        modal.style.display = 'flex';

        // Populate settings
        document.getElementById('autoSellSL').checked = window.Settings.get('autoSellOnStopLoss');
        document.getElementById('autoSellTP').checked = window.Settings.get('autoSellOnTakeProfit');
        document.getElementById('defaultTimeframe').value = window.Settings.get('defaultTimeframe');
        document.getElementById('soundAlerts').checked = window.Settings.get('soundAlerts');
        document.getElementById('showTooltips').checked = window.Settings.get('showTooltips');
    }
};

window.closeSettings = function() {
    const modal = document.getElementById('settingsModal');
    if (modal) {
        modal.style.display = 'none';
    }
};

window.saveSettings = function() {
    // Get values from form
    window.Settings.update({
        autoSellOnStopLoss: document.getElementById('autoSellSL').checked,
        autoSellOnTakeProfit: document.getElementById('autoSellTP').checked,
        defaultTimeframe: document.getElementById('defaultTimeframe').value,
        soundAlerts: document.getElementById('soundAlerts').checked,
        showTooltips: document.getElementById('showTooltips').checked
    });

    window.closeSettings();

    // Show confirmation
    console.log('Settings saved successfully');
};
