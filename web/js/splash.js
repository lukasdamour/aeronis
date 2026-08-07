(function () {
    const MIN_DISPLAY_MS = 2200;
    const shownAt = Date.now();
    let hidden = false;

    function reveal() {
        if (hidden) return;
        hidden = true;
        const splash = document.getElementById('splash-screen');
        if (!splash) return;
        splash.classList.add('splash-hidden');
        splash.addEventListener('transitionend', () => splash.remove(), { once: true });
    }

    window.markMapReady = function () {
        const elapsed = Date.now() - shownAt;
        setTimeout(reveal, Math.max(0, MIN_DISPLAY_MS - elapsed));
    };

    setTimeout(reveal, 8000);
})();