class LayoutManager {
    constructor() {
        this.resizer = document.getElementById('resizeHandle');
        this.panel = document.querySelector('.trading-panel');
        this.container = document.querySelector('.main-content');
        this.chartContainer = document.getElementById('chartContainer');

        // Bottom panels resize
        this.bottomResizeHandle = document.getElementById('bottomResizeHandle');
        this.bottomPanelsContainer = document.getElementById('bottomPanelsContainer');

        this.isResizing = false;
        this.isResizingBottom = false;
        this.lastDownX = 0;
        this.lastDownY = 0;

        this.init();
        this.initBottomResize();
    }

    init() {
        if (!this.resizer || !this.panel) return;

        this.resizer.addEventListener('mousedown', (e) => {
            this.isResizing = true;
            this.lastDownX = e.clientX;
            this.resizer.classList.add('active');
            document.body.style.cursor = 'col-resize';
            document.body.style.userSelect = 'none'; // Prevent text selection

            // Disable pointer events on iframes/charts to prevent event stealing
            if (this.chartContainer) this.chartContainer.style.pointerEvents = 'none';
        });

        document.addEventListener('mousemove', (e) => {
            if (!this.isResizing) return;

            // Use window width for stability
            const containerWidth = window.innerWidth;

            // Calculate new width from the right edge
            // e.clientX is distance from left. So (Total - Left) = Right width.
            const newPanelWidth = containerWidth - e.clientX;

            // Constrain width
            // Leave at least 50px for chart (containerWidth - 50)
            if (newPanelWidth > 250 && newPanelWidth < (containerWidth - 50)) {
                this.panel.style.width = `${newPanelWidth}px`;
            }
        });

        document.addEventListener('mouseup', () => {
            if (this.isResizing) {
                this.isResizing = false;
                this.resizer.classList.remove('active');
                document.body.style.cursor = '';
                document.body.style.userSelect = '';

                // Re-enable pointer events
                if (this.chartContainer) this.chartContainer.style.pointerEvents = '';

                // Trigger chart resize
                if (window.dispatchEvent) {
                    window.dispatchEvent(new Event('resize'));
                }
            }
        });
    }

    initBottomResize() {
        if (!this.bottomResizeHandle || !this.bottomPanelsContainer) return;

        this.bottomResizeHandle.addEventListener('mousedown', (e) => {
            this.isResizingBottom = true;
            this.lastDownY = e.clientY;
            this.bottomResizeHandle.classList.add('active');
            document.body.style.cursor = 'ns-resize';
            document.body.style.userSelect = 'none';

            // Disable pointer events on chart
            if (this.chartContainer) this.chartContainer.style.pointerEvents = 'none';
        });

        document.addEventListener('mousemove', (e) => {
            if (!this.isResizingBottom) return;

            // Calculate new height based on mouse movement
            const deltaY = this.lastDownY - e.clientY; // Positive when dragging up
            const currentHeight = this.bottomPanelsContainer.offsetHeight;
            const newHeight = currentHeight + deltaY;

            // Constrain height between 100px and 600px
            if (newHeight >= 100 && newHeight <= 600) {
                this.bottomPanelsContainer.style.height = `${newHeight}px`;
                this.lastDownY = e.clientY;

                // Trigger chart resize
                if (window.dispatchEvent) {
                    window.dispatchEvent(new Event('resize'));
                }
            }
        });

        document.addEventListener('mouseup', () => {
            if (this.isResizingBottom) {
                this.isResizingBottom = false;
                this.bottomResizeHandle.classList.remove('active');
                document.body.style.cursor = '';
                document.body.style.userSelect = '';

                // Re-enable pointer events
                if (this.chartContainer) this.chartContainer.style.pointerEvents = '';
            }
        });
    }
}

// Make globally available
window.LayoutManager = LayoutManager;
