(function () {
    'use strict';
    let refreshing = false;
    window.refreshDashboardMetrics = async function () {
        if (refreshing || document.hidden) return;
        refreshing = true;
        try {
            const response = await fetch(location.pathname, {credentials: 'same-origin', cache: 'no-store', signal: AbortSignal.timeout(15000)});
            if (!response.ok || response.redirected) throw new Error('Dashboard update unavailable');
            const updated = new DOMParser().parseFromString(await response.text(), 'text/html');
            const nextScene = updated.getElementById('canvas-container-3d');
            const currentScene = document.getElementById('canvas-container-3d');
            if (nextScene && currentScene) {
                currentScene.dataset.lightState = nextScene.dataset.lightState;
                window.goatHouseViewer?.setLightState(nextScene.dataset.lightState === 'on');
            }
            ['.hero-banner', '.dash-section', '[data-dashboard-events]'].forEach(selector => {
                const current = document.querySelectorAll(selector), next = updated.querySelectorAll(selector);
                current.forEach((element, index) => {
                    if (element.querySelector('#canvas-container-3d') || !next[index]) return;
                    if (element.innerHTML !== next[index].innerHTML) element.innerHTML = next[index].innerHTML;
                });
            });
        } finally { refreshing = false; }
    };
    function loadScript(src) {
        return new Promise((resolve, reject) => {
            const script = document.createElement('script');
            script.src = src; script.onload = resolve; script.onerror = reject;
            document.head.appendChild(script);
        });
    }
    let loading = false;
    window.initializeDashboardViewer = function (container) {
        const observer = window.IntersectionObserver ? new IntersectionObserver(entries => {
            if (entries[0].isIntersecting) initialize();
        }, {rootMargin: '150px'}) : null;
        async function initialize() {
            if (loading || window.goatHouseViewer || document.hidden) return;
            loading = true;
            try {
                if (!window.THREE) await loadScript('https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js');
                if (!window.createApprovedGoatHouseViewer) await loadScript('/static/js/goat_house_viewer.js?v=2');
                window.goatHouseViewer = window.createApprovedGoatHouseViewer(container);
                if (observer) observer.disconnect();
            } catch (error) { console.warn('3D viewer could not load', error); }
            finally { loading = false; }
        }
        if (observer) observer.observe(container); else initialize();
        function resume() {
            if (observer && !window.goatHouseViewer) observer.observe(container);
            const rect = container.getBoundingClientRect();
            if (rect.bottom >= -150 && rect.top <= innerHeight + 150) initialize();
        }
        window.addEventListener('pageshow', resume);
        document.addEventListener('visibilitychange', resume);
    };
    const container = document.getElementById('canvas-container-3d');
    if (container) window.initializeDashboardViewer(container);
})();
