document.addEventListener('DOMContentLoaded', () => {

    // --- GENERAL UTILITY FUNCTIONS ---
    
    /**
     * Updates the date and time displayed on the page.
     */
    function updateDateTime() {
        const now = new Date();
        document.getElementById('currentDate').textContent = now.toLocaleDateString('en-CA');
        document.getElementById('currentTime').textContent = now.toLocaleTimeString('en-GB');
    }

    /**
     * Displays a temporary message in the message box.
     * @param {string} message - The text to display.
     * @param {string} [type='info'] - The type of message ('success', 'error', 'info').
     */
    function showMessage(message, type = 'info') {
        const msgBox = document.getElementById('messageBox');
        if (!msgBox) {
            console.error('Message box element not found!');
            return;
        }

        msgBox.textContent = message;
        msgBox.className = 'show';

        if (type === 'error') {
            msgBox.style.backgroundColor = '#dc2626';
        } else if (type === 'success') {
            msgBox.style.backgroundColor = '#16a34a';
        } else {
            msgBox.style.backgroundColor = '#2563eb';
        }

        // Automatically hide the message after 1.5 seconds
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
    // --- MUSIC PLAYER FUNCTIONALITY ---
const playButton = document.getElementById('playMusicButton');
const music = document.getElementById('africanMusic');
const musicTracks = [
    'static/music/African Journey.mp3',
    'static/music/Batacumbele.mp3',
    'static/music/Drums.Chant.mp3',
    'static/music/Flute.Drums.mp3'
];

/**
 * Plays a random track from the musicTracks array.
 */
function playRandomMusic() {
    const randomIndex = Math.floor(Math.random() * musicTracks.length);
    const selectedTrack = musicTracks[randomIndex];
    music.src = selectedTrack;
    
    // Attempt to play the music and handle the promise it returns
    const playPromise = music.play();
    if (playPromise !== undefined) {
        playPromise.then(() => {
            // Playback started successfully, so update the button text.
            playButton.textContent = 'Pause African Music ⏸️';
        }).catch(error => {
            // Playback was prevented by the browser.
            console.error('Playback was blocked by the browser:', error);
            // Revert button text and show a message to the user.
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

    music.addEventListener('ended', () => {
        playRandomMusic();
    });
}
    // --- FORM DATA PERSISTENCE ---
    const storageKey = 'componentFormData';
    const form = document.querySelector('form[action="/run_lp"]');

    /**
     * Loads saved form data from localStorage.
     */
    function loadSavedData() {
        if (!form) {
            console.error("Form not found.");
            return;
        }
        try {
            const savedData = localStorage.getItem(storageKey);
            if (savedData) {
                const data = JSON.parse(savedData);
                for (const inputName in data) {
                    const input = form.querySelector(`[name="${inputName}"]`);
                    if (input) {
                        input.value = data[inputName];
                    }
                }
                showMessage('Previous data restored successfully!', 'success');
            }
        } catch (e) {
            console.error("Error loading data from localStorage:", e);
            localStorage.removeItem(storageKey);
        }
    }

    /**
     * Saves the current form data to localStorage.
     */
    function saveData() {
        if (!form) {
            return;
        }
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
    /**
     * Attaches event listeners to an input element to restore its last known value
     * if the user clears the field. This function is corrected to handle backspace issue.
     * @param {HTMLElement} inputElement - The input element to monitor.
     */
    function restoreLastValue(inputElement) {
        let lastValue = inputElement.value; // Store the initial value.

        // Listen for the 'blur' event, which is the most reliable time to check.
        inputElement.addEventListener('blur', () => {
            const currentValue = inputElement.value.trim();
            if (currentValue === '') {
                inputElement.value = lastValue;
                console.log(`Input restored to last value: ${lastValue}`);
            } else {
                lastValue = currentValue;
            }
        });
    }


    // --- DYNAMIC ROW CREATION ---
    /**
     * Adds a new component row dynamically to the component table.
     */
    function addComponentRow() {
        const componentsTbody = document.getElementById('components-tbody');
        if (!componentsTbody) {
            console.error("Components table body not found.");
            return;
        }

        const componentsTheadRow = document.querySelector('#components-table thead tr:last-child');
        const propertyHeaders = [];
        if (componentsTheadRow) {
            // Dynamically find the index of the "Cost" header
            let costHeaderIndex = Array.from(componentsTheadRow.cells).findIndex(th => th.textContent.trim() === 'Cost');
            if (costHeaderIndex === -1) {
                console.error("Could not find 'Cost' header to determine property start index.");
                return;
            }
            // Start iterating from the cell after "Cost"
            for (let i = costHeaderIndex + 1; i < componentsTheadRow.cells.length; i++) {
                propertyHeaders.push(componentsTheadRow.cells[i].textContent.trim());
            }
        }

        const newComponentIndex = componentsTbody.children.length + 1;
        const newComponentName = `NewComponent${newComponentIndex}`;
        const newComponentTag = `NC${newComponentIndex}`;

        const newRow = document.createElement('tr');

        // TAG input field (This column is always visible)
        let cell = document.createElement('td');
        cell.classList.add('text-left');
        let tagInput = document.createElement('input');
        tagInput.type = 'text';
        tagInput.name = `component_${newComponentTag}_name`;
        tagInput.value = newComponentTag;
        tagInput.classList.add('text-left');
        tagInput.addEventListener('blur', saveData);
        cell.appendChild(tagInput);
        newRow.appendChild(cell);

        // Component Name input field
        cell = document.createElement('td');
        cell.classList.add('text-left');
        let nameInput = document.createElement('input');
        nameInput.type = 'text';
        nameInput.name = `component_${newComponentTag}_tag`;
        nameInput.value = newComponentName;
        nameInput.classList.add('text-left');
        nameInput.addEventListener('blur', saveData);
        cell.appendChild(nameInput);
        newRow.appendChild(cell);

        // Inputs for Min Comp, Availability, Factor, Cost
        const inputFields = [
            { name: `component_${newComponentTag}_min_comp`, value: '0' },
            { name: `component_${newComponentTag}_availability`, value: '0' },
            { name: `component_${newComponentTag}_factor`, value: '1' },
            { name: `component_${newComponentTag}_cost`, value: '25.00' }
        ];

        inputFields.forEach(field => {
            cell = document.createElement('td');
            cell.classList.add('text-left');
            const input = document.createElement('input');
            input.type = 'text';
            input.name = field.name;
            input.value = field.value;
            input.className = 'resizable-component-input numeric-input text-left';
            cell.appendChild(input);
            newRow.appendChild(cell);
            makeInputResizable(input);
            restoreLastValue(input);
        });

        // Inputs for properties
        propertyHeaders.forEach(prop => {
            cell = document.createElement('td');
            cell.classList.add('text-left');
            const input = document.createElement('input');
            input.type = 'text';
            input.name = `component_${newComponentTag}_property_${prop}`;
            
            // Set initial values based on the rules provided
            if (['SUL', 'ARO', 'BEN', 'OXY', 'OLEFIN'].includes(prop)) {
                input.value = '';
            } else if (['RON', 'MON'].includes(prop)) {
                input.value = 'inf';
            } else {
                input.value = '0';
            }
            
            input.className = 'resizable-component-input numeric-input text-left';
            cell.appendChild(input);
            newRow.appendChild(cell);
            makeInputResizable(input);
            restoreLastValue(input);
        });

        componentsTbody.appendChild(newRow);
        showMessage(`New component '${newComponentTag}' added!`, 'success');
        
        // --- REMOVED: expandable column logic for new rows
    }

    /**
     * Fetches the Brent crude oil price from the server and updates the UI.
     */
    async function fetchPrice() {
        const priceElement = document.getElementById("price");

        try {
            const response = await fetch("/get_brent_price");
            const data = await response.json();
            if (data.price) {
                priceElement.textContent = `$${data.price}`;
            } else {
                priceElement.textContent = "Error loading price";
            }
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
            } else {
                console.error('Server error: No chart data received.');
            }
        } catch (error) {
            console.error('Network error:', error);
        }
    }

    function drawBrentChart(labels, values) {
        const ctx = document.getElementById('brent-chart').getContext('2d');
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
                    legend: {
                        display: false 
                    }
                },
                scales: {
                    y: {
                        beginAtZero: false,
                        grid: {
                            color: 'rgba(255, 255, 255, 0.2)'
                        },
                        ticks: {
                            color: 'white'
                        }
                    },
                    x: {
                        display: false
                    }
                }
            }
        });
    }


    // --- INITIALIZATION ---
    updateDateTime();
    setInterval(updateDateTime, 1000);

    // Initial fetch for Brent price and then auto-refresh
    fetchPrice();
    setInterval(fetchPrice, 60000); 

    // Call the function to draw the chart on page load
    fetchBrentChartData();

    // Add listener to prevent form submission on 'Enter' key press
    if (form) {
        form.addEventListener('keydown', (event) => {
            if (event.key === 'Enter') {
                event.preventDefault();
            }
        });
    }

    // Make inputs resizable and restore last value
    document.querySelectorAll('.resizable-component-input').forEach(input => {
        makeInputResizable(input);
    });
    document.querySelectorAll('.numeric-input').forEach(input => {
        restoreLastValue(input);
    });

    // Add event listener for the new component button
    const addComponentButton = document.getElementById('addComponentButton');
    if (addComponentButton) {
        addComponentButton.addEventListener('click', addComponentRow);
    }

    // Handle form data persistence
    if (form) {
        form.addEventListener('input', saveData);
        form.addEventListener('submit', saveData);
    }
    
    loadSavedData();
    
    const userTimezoneInput = document.getElementById('user_timezone_input');
    if (userTimezoneInput) {
        userTimezoneInput.value = Intl.DateTimeFormat().resolvedOptions().timeZone;
    }

    console.log('Application initialized successfully!');
    showMessage('Application loaded successfully!', 'success');
    
    // Update spec table inputs based on the new rules
    document.querySelectorAll('#specs-tbody tr').forEach(row => {
        const propertyName = row.cells[0].textContent.trim();
        
        // Find all min and max input fields for this property
        const minInputs = row.querySelectorAll('input[name$="_min"]');
        const maxInputs = row.querySelectorAll('input[name$="_max"]');
        
        // Apply rules
        switch (propertyName) {
            case 'SUL':
            case 'ARO':
            case 'BEN':
            case 'OXY':
            case 'OLEFIN':
                minInputs.forEach(input => {
                    input.value = '';
                    input.readOnly = true;
                    input.classList.add('bg-gray-200', 'cursor-not-allowed');
                });
                break;
            case 'RVP':
                minInputs.forEach(input => {
                    input.value = '0';
                });
                break;
            case 'RON':
            case 'MON':
                maxInputs.forEach(input => {
                    input.value = 'inf';
                    input.readOnly = true;
                    input.classList.add('bg-gray-200', 'cursor-not-allowed');
                });
                break;
            default:
                // For other properties, let the existing behavior be.
                break;
        }
    });

    // Make a specific set of fields empty and locked on load (existing logic)
    document.querySelectorAll('.empty-field').forEach(input => {
        input.value = '';
        input.readOnly = true;
        input.classList.add('bg-gray-200', 'cursor-not-allowed');
    });

    // Make specific fields inf and locked (existing logic)
    document.querySelectorAll('.readonly-field').forEach(input => {
        input.readOnly = true;
        input.classList.add('bg-gray-200', 'cursor-not-allowed');
    });

});

