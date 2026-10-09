/* Account state comes from Django on every page; no browser completion flags. */
(() => {
    'use strict';
    const config = document.getElementById('onboarding-config');
    if (!config) return;
    const endpoint = config.dataset.endpoint;
    const csrf = config.querySelector('[name=csrfmiddlewaretoken]').value;
    const mascotAssets = JSON.parse(document.getElementById('onboarding-mascot-assets')?.textContent || '{}');
    let state, layer, card, target, confirmation = false, busy = false, previousFocus;
    let resizeObserver, frame;

    async function request(payload) {
        const response = await fetch(endpoint, {
            method: payload ? 'POST' : 'GET', credentials: 'same-origin', cache: 'no-store',
            headers: payload ? {'Content-Type': 'application/json', 'X-CSRFToken': csrf} : {},
            body: payload ? JSON.stringify(payload) : undefined,
        });
        if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) {
            throw new Error('Unable to save your tutorial. Check your connection and try again.');
        }
        return response.json();
    }
    function close() {
        resizeObserver?.disconnect();
        layer?.remove();
        layer = card = target = null;
        previousFocus?.focus({preventScroll: true});
    }
    function error(message) {
        if (!card) return;
        let notice = card.querySelector('[role=alert]');
        if (!notice) {
            notice = document.createElement('p');
            notice.className = 'onboarding-error';
            notice.setAttribute('role', 'alert');
            card.append(notice);
        }
        notice.textContent = message;
        position();
    }
    async function act(action, step) {
        if (busy) return;
        busy = true;
        card?.querySelectorAll('button').forEach(button => { button.disabled = true; });
        try {
            state = await request({action, ...(step === undefined ? {} : {step})});
            confirmation = false;
            if (!state.active) { close(); return; }
            if (action === 'replay') {
                if (document.body.classList.contains('nav-open')) document.querySelector('.mobile-menu-toggle')?.click();
                if (document.querySelector('[data-nav].open')) document.querySelector('[data-nav-toggle]')?.click();
                document.querySelectorAll('.desktop-account-menu[open]').forEach(menu => { menu.open = false; });
            }
            const destination = state.steps[state.step].url;
            if (location.pathname !== destination) { location.assign(destination); return; }
            render();
        } catch (e) {
            // A failed save never dismisses the tour or pretends it was completed.
            if (!card) render(true);
            error(e.message);
        } finally {
            busy = false;
            card?.querySelectorAll('button').forEach(button => { button.disabled = false; });
        }
    }
    function button(label, action, primary = false) {
        const node = document.createElement('button');
        node.type = 'button';
        node.textContent = label;
        if (primary) node.className = 'onboarding-primary';
        node.addEventListener('click', action);
        return node;
    }
    function visible(node) {
        const rect = node.getBoundingClientRect();
        const style = getComputedStyle(node);
        return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' &&
            style.display !== 'none' && rect.right > 0 && rect.left < innerWidth;
    }
    function selectTarget(selector) {
        if (!selector) return null;
        // Try selectors in declared order, including alternatives for narrow screens.
        for (const part of selector.split(',')) {
            const found = [...document.querySelectorAll(part)].find(visible);
            if (found) return found;
        }
        return document.querySelector('main h1');
    }
    function setMascot(pose) {
        const mascot = layer?.querySelector('.onboarding-goat');
        if (!mascot) return;
        mascot.dataset.requestedPose = pose;
        if (pose === 'point_auto') return; // Direction is resolved from the actual target after layout.
        const source = mascotAssets[pose];
        if (source && mascot.dataset.pose !== pose) {
            mascot.hidden = true;
            mascot.dataset.pose = pose;
            // Reuse the same image node and URL; normal static-file caching also
            // reuses downloaded stickers across Next/Back and page navigation.
            mascot.src = source;
        }
    }
    function positionMascot(cut, viewport) {
        const mascot = layer.querySelector('.onboarding-goat');
        if (!mascot) return;
        const {w, h, ox, oy, gap} = viewport;
        const pointing = mascot.dataset.requestedPose === 'point_auto';
        let pointLeft = false;
        if (pointing) {
            if (!cut) { mascot.hidden = true; return; }
            pointLeft = (cut.left + cut.right) / 2 < ox + w / 2;
            setMascot(pointLeft ? 'goat_point_left.png' : 'goat_point_right.png');
            mascot.dataset.requestedPose = 'point_auto';
        }
        if (!mascot.complete || !mascot.naturalWidth) { mascot.hidden = true; return; }
        const mobile = w <= 768;
        const width = mobile ? 90 : Math.min(170, Math.max(85, w * .11));
        const height = width * mascot.naturalHeight / mascot.naturalWidth;
        const c = card.getBoundingClientRect();
        const sideY = c.top + Math.max(0, (c.height - height) / 2);
        const left = {x: c.left - width - gap, y: sideY};
        const right = {x: c.right + gap, y: sideY};
        const alignedX = pointing ? (pointLeft ? c.right - width : c.left) : c.left + (c.width - width) / 2;
        const above = {x: alignedX, y: c.top - height - gap};
        const below = {x: alignedX, y: c.bottom + gap};
        const preferred = pointing && pointLeft ? right : left;
        const other = preferred === right ? left : right;
        const candidates = mobile ? [above, below] : [preferred, above, below, other];
        const overlaps = (rect, x, y) => rect && x < rect.right + gap && x + width > rect.left - gap &&
            y < rect.bottom + gap && y + height > rect.top - gap;
        const placement = candidates.find(({x, y}) =>
            x >= ox + gap && y >= oy + gap && x + width <= ox + w - gap && y + height <= oy + h - gap &&
            !overlaps(cut, x, y) && !overlaps(c, x, y) &&
            (!pointing || (pointLeft ? (cut.left + cut.right) / 2 < x + width / 2 : (cut.left + cut.right) / 2 > x + width / 2))
        );
        mascot.hidden = !placement;
        if (placement) {
            // Only the decorative sibling moves. Never resize the card, scroll,
            // retarget the spotlight, or cover its controls to make room for art.
            Object.assign(mascot.style, {left: `${placement.x}px`, top: `${placement.y}px`, width: `${width}px`});
        }
    }
    function render(failedStart = false) {
        resizeObserver?.disconnect();
        if (!layer) {
            previousFocus = document.activeElement;
            layer = document.createElement('div');
            layer.className = 'onboarding-layer';
            for (let i = 0; i < 4; i++) {
                const shade = document.createElement('div');
                shade.className = 'onboarding-shade';
                layer.append(shade);
            }
            const ring = document.createElement('div');
            ring.className = 'onboarding-ring';
            layer.append(ring);
            card = document.createElement('section');
            card.className = 'onboarding-card';
            card.setAttribute('role', 'dialog');
            card.setAttribute('aria-modal', 'true');
            card.setAttribute('aria-labelledby', 'onboarding-title');
            card.setAttribute('aria-describedby', 'onboarding-description');
            card.tabIndex = -1;
            layer.append(card);
            const mascot = document.createElement('img');
            mascot.className = 'onboarding-goat';
            mascot.alt = '';
            mascot.setAttribute('aria-hidden', 'true');
            mascot.draggable = false;
            mascot.decoding = 'async';
            mascot.hidden = true;
            mascot.addEventListener('load', schedulePosition);
            mascot.addEventListener('error', () => { mascot.hidden = true; });
            layer.append(mascot);
            document.body.append(layer);
        }
        card.replaceChildren();
        const current = state?.steps[state.step];
        setMascot(confirmation ? 'goat_skip_fastforward.png' : failedStart ? 'goat_warning_attention.png' : current?.mascot || 'goat_information.png');
        const progress = document.createElement('div');
        progress.className = 'onboarding-progress';
        progress.textContent = current ? `Step ${state.step + 1} of ${state.steps.length}` : 'GoHMoTech tutorial';
        const title = document.createElement('h2');
        title.id = 'onboarding-title';
        const description = document.createElement('p');
        description.id = 'onboarding-description';
        title.textContent = confirmation ? 'Skip tutorial?' : current?.title || 'Take the tour';
        description.textContent = confirmation ? 'You can access the tutorial again later from the Help section.' : current?.text || 'Start a guided tour of your account.';
        const actions = document.createElement('div');
        actions.className = 'onboarding-actions';
        if (failedStart) {
            actions.append(button('Close', close), button('Try Again', () => act('replay'), true));
        } else if (confirmation) {
            actions.append(button('Continue Tutorial', () => { confirmation = false; render(); }),
                button('Skip Tutorial', () => act('skip'), true));
        } else {
            if (state.step > 0) actions.append(button('Back', () => act('step', state.step - 1)));
            const last = state.step === state.steps.length - 1;
            actions.append(button(last ? 'Finish' : state.step === 0 ? 'Start Tutorial' : 'Next',
                () => last ? act('finish') : act('step', state.step + 1), true));
        }
        card.append(progress, title, description, actions);
        if (!confirmation && !failedStart) {
            const skip = button('Skip Tutorial', () => { confirmation = true; render(); });
            skip.className = 'onboarding-skip';
            card.append(skip);
        }
        target = !confirmation && !failedStart ? selectTarget(current?.target) : null;
        if (target) {
            target.scrollIntoView({block: 'center', inline: 'nearest', behavior: 'instant'});
            resizeObserver = new ResizeObserver(schedulePosition);
            resizeObserver.observe(target);
        }
        position();
        card.focus({preventScroll: true});
    }
    function box(node, x, y, width, height) {
        Object.assign(node.style, {left: `${x}px`, top: `${y}px`, width: `${Math.max(0, width)}px`, height: `${Math.max(0, height)}px`});
    }
    function position() {
        if (!layer) return;
        const viewport = window.visualViewport;
        const w = viewport?.width || innerWidth, h = viewport?.height || innerHeight;
        const ox = viewport?.offsetLeft || 0, oy = viewport?.offsetTop || 0;
        const gap = 12;
        card.style.width = `${Math.min(360, w - 24)}px`;
        card.style.maxHeight = `${h - 24}px`;
        const cw = card.offsetWidth;
        let ch = card.offsetHeight;
        let rect = target?.getBoundingClientRect();
        let cut = rect ? {left: Math.max(ox, rect.left - 5), top: Math.max(oy, rect.top - 5),
            right: Math.min(ox + w, rect.right + 5), bottom: Math.min(oy + h, rect.bottom + 5)} : null;
        let x = ox + (w - cw) / 2, y = oy + (h - ch) / 2;
        if (cut && cut.right > cut.left && cut.bottom > cut.top) {
            if (cut.right + cw + gap <= ox + w - gap) {
                x = cut.right + gap; y = Math.max(oy + gap, Math.min(cut.top, oy + h - ch - gap));
            } else if (cut.left - cw - gap >= ox + gap) {
                x = cut.left - cw - gap; y = Math.max(oy + gap, Math.min(cut.top, oy + h - ch - gap));
            } else {
                const below = oy + h - cut.bottom - gap * 2, above = cut.top - oy - gap * 2;
                // Large panels on phones: spotlight their first heading/control so both
                // the actual feature and card remain visible without overlap.
                if (Math.max(above, below) < Math.min(ch, 180)) {
                    const smaller = target.querySelector('h1, h2, a, summary, small, span');
                    if (smaller && smaller !== target && visible(smaller)) {
                        target = smaller;
                        target.scrollIntoView({block: 'start', behavior: 'instant'});
                        position(); return;
                    }
                }
                const useBelow = below >= ch || below >= above;
                card.style.maxHeight = `${Math.max(60, useBelow ? below : above)}px`;
                ch = card.offsetHeight;
                x = Math.max(ox + gap, Math.min(cut.left, ox + w - cw - gap));
                y = useBelow ? cut.bottom + gap : cut.top - ch - gap;
            }
        } else { cut = null; }
        card.style.left = `${x}px`; card.style.top = `${y}px`;
        const shades = layer.querySelectorAll('.onboarding-shade');
        const ring = layer.querySelector('.onboarding-ring');
        ring.hidden = !cut;
        if (cut) {
            box(shades[0], ox, oy, w, cut.top - oy);
            box(shades[1], ox, cut.bottom, w, oy + h - cut.bottom);
            box(shades[2], ox, cut.top, cut.left - ox, cut.bottom - cut.top);
            box(shades[3], cut.right, cut.top, ox + w - cut.right, cut.bottom - cut.top);
            box(ring, cut.left, cut.top, cut.right - cut.left, cut.bottom - cut.top);
        } else {
            box(shades[0], ox, oy, w, h);
            for (let i = 1; i < 4; i++) box(shades[i], 0, 0, 0, 0);
        }
        positionMascot(cut, {w, h, ox, oy, gap});
    }
    function schedulePosition() {
        cancelAnimationFrame(frame);
        frame = requestAnimationFrame(position);
    }
    document.addEventListener('keydown', event => {
        if (!card) return;
        if (event.key === 'Escape' && !busy) {
            event.preventDefault(); confirmation = !confirmation; render();
        }
        if (event.key === 'Tab') {
            const buttons = [...card.querySelectorAll('button:not(:disabled)')];
            const first = buttons[0], last = buttons.at(-1);
            if (!card.contains(document.activeElement)) {
                event.preventDefault(); first?.focus();
            } else if (event.shiftKey && (document.activeElement === first || document.activeElement === card)) {
                event.preventDefault(); last?.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault(); first?.focus();
            }
        }
    });
    document.querySelectorAll('[data-onboarding-replay]').forEach(node => {
        node.addEventListener('click', () => act('replay'));
    });
    window.addEventListener('resize', () => { if (layer && state) render(); });
    window.addEventListener('scroll', schedulePosition, true);
    window.visualViewport?.addEventListener('resize', schedulePosition);
    window.visualViewport?.addEventListener('scroll', schedulePosition);
    async function sync() {
        if (busy || document.hidden) return;
        try {
            const previous = state;
            state = await request();
            if (!state.active) { if (layer) close(); return; }
            // Welcome appears on the user's landing page. Later steps resume at
            // their real page, even after a refresh or a new browser login.
            if (state.step > 0 && location.pathname !== state.steps[state.step].url) {
                location.assign(state.steps[state.step].url); return;
            }
            if (!layer || previous?.step !== state.step || previous?.role !== state.role) render();
        } catch (_) { /* Keep the existing interface usable if onboarding is unavailable. */ }
    }
    document.addEventListener('visibilitychange', sync);
    window.addEventListener('pageshow', event => { if (event.persisted) sync(); });
    sync();
})();
