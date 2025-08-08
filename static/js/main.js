document.addEventListener('DOMContentLoaded', () => {

    // --- GENERAL UTILITY FUNCTIONS ---
    
    /**
     * Updates the date and time displayed on the page.
     */
    function updateDateTime() {
        const now = new Date();
        const dateElement = document.getElementById('currentDate');
        const timeElement = document.getElementById('currentTime');
        
        if (dateElement) dateElement.textContent = now.toLocaleDateString('en-CA');
        if (timeElement) timeElement.textContent = now.toLocaleTimeString('en-GB');
    }

    /**
     * Displays a temporary message in the message box.
     * @param {string} message - The text to display.
     * @param {string} [type='info'] - The type of message ('success', 'error', 'info').
     */
    function showMessage(message, type = 'info') {
        const msgBox = document.getElementById('messageBox');
        if (!msgBox) return;

        msgBox.textContent = message;
        msgBox.className = 'show';

        const colors = {
            error: '#dc2626',
            success: '#16a34a',
            info: '#2563eb'
        };
        msgBox.style.backgroundColor = colors[type] || colors.info;

        setTimeout(() => {
            msgBox.className = '';
        }, 1500); 
    }

    window.showMessage = showMessage;

    // --- RESIZABLE INPUT FUNCTIONALITY ---
    let isResizing = false;
    let currentResizeContainer = null;
    let startX = 0;
    let startWidth = 0;

    /**
     * Wraps an input in a resizable container and adds a resize handle.
     * @param {HTMLElement} input - The input element to make resizable.
     */
    function makeInputResizable(input) {
        if (input.closest('.resizable-input-container')) return; // Already resizable

        const container = document.createElement('div');
        container.className = 'resizable-input-container';

        const handle = document.createElement('div');
        handle.className = 'resize-handle';

        input.parentNode.insertBefore(container, input);
        container.appendChild(input);
        container.appendChild(handle);

        input.classList.add('resizable-input');

        handle.addEventListener('mousedown', (e) => {
            e.preventDefault();
            isResizing = true;
            currentResizeContainer = container;
            startX = e.clientX;
            startWidth = parseInt(window.getComputedStyle(container).width, 10);
            handle.classList.add('dragging');
            document.body.style.cursor = 'ew-resize';
            document.body.style.userSelect = 'none';
        });
    }

    document.addEventListener('mousemove', (e) => {
        if (!isResizing || !currentResizeContainer) return;

        const newWidth = startWidth + (e.clientX - startX);
        if (newWidth >= 60) {
            currentResizeContainer.style.width = newWidth + 'px';
        }
    });

    document.addEventListener('mouseup', () => {
        if (isResizing) {
            isResizing = false;
            document.body.style.cursor = '';
            document.body.style.userSelect = '';

            if (currentResizeContainer) {
                const handle = currentResizeContainer.querySelector('.resize-handle');
                if (handle) handle.classList.remove('dragging');
            }
            currentResizeContainer = null;
        }
    });

    // --- MUSIC PLAYER FUNCTIONALITY ---
    const playButton = document.getElementById('playMusicButton');
    const music = document.getElementById('africanMusic');
    const musicTracks = [
        'static/music/African Journey.mp3',
        'static/music/Batacumbele.mp3',
        'static/music/Drums.Chant.mp3',
        'static/music/Flute.Drums.mp3'
    ];

    function playRandomMusic() {
        const randomIndex = Math.floor(Math.random() * musicTracks.length);
        music.src = musicTracks[randomIndex];
        
        const playPromise = music.play();
        if (playPromise !== undefined) {
            playPromise.then(() => {
                playButton.textContent = 'Pause African Music ⏸️';
            }).catch(error => {
                console.error('Playback was blocked by the browser:', error);
                playButton.textContent = 'Play African Music 🎵';
                showMessage('Playback was blocked. Click again to try.', 'error');
            });
        }
    }

    if (playButton && music) {
        playButton.addEventListener('click', () => {
            if (music.paused) {
                playRandomMusic();
            } else {
                music.pause();
                playButton.textContent = 'Play African Music 🎵';
            }
        });

        music.addEventListener('ended', playRandomMusic);
    }

    // --- FORM DATA PERSISTENCE ---
    const storageKey = 'componentFormData';
    const form = document.querySelector('form[action="/run_lp"]');

    function loadSavedData() {
        if (!form) return;
        
        try {
            const savedData = localStorage.getItem(storageKey);
            if (savedData) {
                const data = JSON.parse(savedData);
                Object.keys(data).forEach(inputName => {
                    const input = form.querySelector(`[name="${inputName}"]`);
                    if (input) input.value = data[inputName];
                });
                showMessage('Previous data restored successfully!', 'success');
            }
        } catch (e) {
            console.error("Error loading data from localStorage:", e);
            localStorage.removeItem(storageKey);
        }
    }

    function saveData() {
        if (!form) return;
        
        const formData = new FormData(form);
        const dataObject = {};
        formData.forEach((value, key) => {
            dataObject[key] = value;
        });
        
        try {
            localStorage.setItem(storageKey, JSON.stringify(dataObject));
        } catch (e) {
            console.error("Error saving data to localStorage:", e);
        }
    }

    // --- RESTORE LAST VALUE FUNCTIONALITY ---
    function restoreLastValue(inputElement) {
        let lastValue = inputElement.value;

        inputElement.addEventListener('blur', () => {
            const currentValue = inputElement.value.trim();
            if (currentValue === '') {
                inputElement.value = lastValue;
            } else {
                lastValue = currentValue;
            }
        });
    }

    // --- DYNAMIC ROW CREATION ---
    function addComponentRow() {
        const componentsTbody = document.getElementById('components-tbody');
        if (!componentsTbody) {
            console.error("Components table body not found.");
            return;
        }

        const componentsTheadRow = document.querySelector('#components-table thead tr:last-child');
        const propertyHeaders = [];
        
        if (componentsTheadRow) {
            const costHeaderIndex = Array.from(componentsTheadRow.cells).findIndex(th => th.textContent.trim() === 'Cost');
            if (costHeaderIndex === -1) {
                console.error("Could not find 'Cost' header to determine property start index.");
                return;
            }
            
            for (let i = costHeaderIndex + 1; i < componentsTheadRow.cells.length; i++) {
                propertyHeaders.push(componentsTheadRow.cells[i].textContent.trim());
            }
        }

        const newComponentIndex = componentsTbody.children.length + 1;
        const newComponentName = `NewComponent${newComponentIndex}`;
        const newComponentTag = `NC${newComponentIndex}`;

        const newRow = document.createElement('tr');

        // Helper function to create input cell
        function createInputCell(name, value, className = 'text-left') {
            const cell = document.createElement('td');
            cell.classList.add('text-left');
            const input = document.createElement('input');
            input.type = 'text';
            input.name = name;
            input.value = value;
            input.className = className;
            cell.appendChild(input);
            return { cell, input };
        }

        // TAG input field
        const { cell: tagCell, input: tagInput } = createInputCell(`component_${newComponentTag}_name`, newComponentTag);
        tagInput.addEventListener('blur', saveData);
        newRow.appendChild(tagCell);

        // Component Name input field
        const { cell: nameCell, input: nameInput } = createInputCell(`component_${newComponentTag}_tag`, newComponentName);
        nameInput.addEventListener('blur', saveData);
        newRow.appendChild(nameCell);

        // Standard input fields
        const inputFields = [
            { name: `component_${newComponentTag}_min_comp`, value: '0' },
            { name: `component_${newComponentTag}_availability`, value: '0' },
            { name: `component_${newComponentTag}_factor`, value: '1' },
            { name: `component_${newComponentTag}_cost`, value: '25.00' }
        ];

        inputFields.forEach(field => {
            const { cell, input } = createInputCell(field.name, field.value, 'resizable-component-input numeric-input text-left');
            newRow.appendChild(cell);
            makeInputResizable(input);
            restoreLastValue(input);
        });

        // Property inputs
        propertyHeaders.forEach(prop => {
            let value;
            if (['SUL', 'ARO', 'BEN', 'OXY', 'OLEFIN'].includes(prop)) {
                value = '';
            } else if (['RON', 'MON'].includes(prop)) {
                value = 'inf';
            } else {
                value = '0';
            }
            
            const { cell, input } = createInputCell(`component_${newComponentTag}_property_${prop}`, value, 'resizable-component-input numeric-input text-left');
            newRow.appendChild(cell);
            makeInputResizable(input);
            restoreLastValue(input);
        });

        componentsTbody.appendChild(newRow);
        showMessage(`New component '${newComponentTag}' added!`, 'success');
    }

    // --- BRENT PRICE FUNCTIONALITY ---
    async function fetchPrice() {
        const priceElement = document.getElementById("price");
        if (!priceElement) return;

        try {
            const response = await fetch("/get_brent_price");
            const data = await response.json();
            priceElement.textContent = data.price ? `$${data.price}` : "Error loading price";
        } catch (error) {
            priceElement.textContent = "Error fetching data";
        }
    }

    // --- CHART FUNCTIONALITY ---
    async function fetchBrentChartData() {
        try {
            const response = await fetch("/get_brent_chart_data");
            const data = await response.json();
            if (data.labels && data.values) {
                drawBrentChart(data.labels, data.values);
            }
        } catch (error) {
            console.error('Network error:', error);
        }
    }

    function drawBrentChart(labels, values) {
        const canvas = document.getElementById('brent-chart');
        if (!canvas) return;

        const ctx = canvas.getContext('2d');
        new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: '',
                    data: values,
                    borderColor: 'white',
                    tension: 0.4,
                    fill: false,
                    pointRadius: 0,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false }
                },
                scales: {
                    y: {
                        beginAtZero: false,
                        grid: { color: 'rgba(255, 255, 255, 0.2)' },
                        ticks: { color: 'white' }
                    },
                    x: { display: false }
                }
            }
        });
    }

    // --- INITIALIZATION ---
    updateDateTime();
    setInterval(updateDateTime, 1000);

    fetchPrice();
    setInterval(fetchPrice, 60000);
    fetchBrentChartData();

    // Form setup
    if (form) {
        form.addEventListener('keydown', (event) => {
            if (event.key === 'Enter') event.preventDefault();
        });
        form.addEventListener('input', saveData);
        form.addEventListener('submit', saveData);
    }

    // Make existing inputs resizable and add restore functionality
    document.querySelectorAll('.resizable-component-input').forEach(makeInputResizable);
    document.querySelectorAll('.numeric-input').forEach(restoreLastValue);

    // Add component button
    const addComponentButton = document.getElementById('addComponentButton');
    if (addComponentButton) {
        addComponentButton.addEventListener('click', addComponentRow);
    }

    // Load saved data and set timezone
    loadSavedData();
    
    const userTimezoneInput = document.getElementById('user_timezone_input');
    if (userTimezoneInput) {
        userTimezoneInput.value = Intl.DateTimeFormat().resolvedOptions().timeZone;
    }

    // Apply field rules for spec table
    const fieldRules = {
        'SUL': { minEmpty: true },
        'ARO': { minEmpty: true },
        'BEN': { minEmpty: true },
        'OXY': { minEmpty: true },
        'OLEFIN': { minEmpty: true },
        'RVP': { minValue: '0' },
        'RON': { maxValue: 'inf', maxReadonly: true },
        'MON': { maxValue: 'inf', maxReadonly: true }
    };

    document.querySelectorAll('#specs-tbody tr').forEach(row => {
        const propertyName = row.cells[0]?.textContent.trim();
        const rule = fieldRules[propertyName];
        
        if (rule) {
            if (rule.minEmpty) {
                row.querySelectorAll('input[name$="_min"]').forEach(input => {
                    input.value = '';
                    input.readOnly = true;
                    input.classList.add('bg-gray-200', 'cursor-not-allowed');
                });
            }
            if (rule.minValue) {
                row.querySelectorAll('input[name$="_min"]').forEach(input => {
                    input.value = rule.minValue;
                });
            }
            if (rule.maxValue && rule.maxReadonly) {
                row.querySelectorAll('input[name$="_max"]').forEach(input => {
                    input.value = rule.maxValue;
                    input.readOnly = true;
                    input.classList.add('bg-gray-200', 'cursor-not-allowed');
                });
            }
        }
    });

    // Handle special field classes
    document.querySelectorAll('.empty-field').forEach(input => {
        input.value = '';
        input.readOnly = true;
        input.classList.add('bg-gray-200', 'cursor-not-allowed');
    });

    document.querySelectorAll('.readonly-field').forEach(input => {
        input.readOnly = true;
        input.classList.add('bg-gray-200', 'cursor-not-allowed');
    });

    console.log('Application initialized successfully!');
    showMessage('Application loaded successfully!', 'success');
});
