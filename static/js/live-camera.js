/* Render latest JPEGs using bounded requests; retain optional SSE/MJPEG support.
 * Native <img> MJPEG does not expose per-frame events or a reliable EOF event. */
(function () {
    'use strict';
    document.querySelectorAll('[data-live-camera]').forEach(img => {
        const panel = img.parentElement.querySelector('[data-camera-state]');
        let active = false, visible = true, controller = null, timer = null;
        let failures = 0, objectUrl = null, generation = 0;
        let lastProgressLog = performance.now();
        let bitrateStep = 0;
        const reducedProfiles = [{width: 320, quality: 40, fps: 4}, {width: 320, quality: 40, fps: 2}];
        const decoder = new TextDecoder();
        const setState = text => {
            img.dataset.liveState = text;
            if (panel) {
                panel.textContent = text;
                panel.style.display = text === 'Live' ? 'none' : 'flex';
            }
        };
        function stop() {
            active = false;
            generation++;
            clearTimeout(timer);
            timer = null;
            if (controller) controller.abort();
            controller = null;
            if (objectUrl) URL.revokeObjectURL(objectUrl);
            objectUrl = null;
            img.removeAttribute('src');
        }
        function schedule(quick = false) {
            if (!active) return;
            const delay = Math.min(30000, 2000 * Math.pow(2, Math.min(failures++, 4)));
            setState(failures > 3 ? 'Offline — retrying...' : 'Reconnecting...');
            timer = setTimeout(connect, quick ? 250 : delay);
        }
        async function connect() {
            if (!active) return;
            const run = ++generation;
            const connectionController = new AbortController();
            controller = connectionController;
            let lastFrame = performance.now();
            const watchdog = setInterval(() => {
                if (performance.now() - lastFrame > 15000) {
                    console.warn('Camera delivery stale', img.dataset.cameraId, img.dataset.frameSequence);
                    connectionController.abort();
                }
            }, 1000);
            let reader;
            async function renderPacket(packet, requestedAt, streamStartedAt) {
                const {frame, sequence, capturedAt} = packet;
                if (sequence === img.dataset.frameSequence) return;
                const age = (performance.now() - requestedAt) / 1000 - (capturedAt - streamStartedAt);
                if (Number.isFinite(age)) {
                    img.dataset.frameAgeSeconds = Math.max(0, age).toFixed(3);
                    if (age > 3) {
                        bitrateStep = Math.min(reducedProfiles.length, bitrateStep + 1);
                        const error = new Error('Camera delivery backlog');
                        error.name = 'StaleCameraFrame';
                        throw error;
                    }
                }
                const url = URL.createObjectURL(new Blob([frame], {type: 'image/jpeg'}));
                const decoded = new Image(); decoded.src = url;
                try { await decoded.decode(); } catch (error) { URL.revokeObjectURL(url); throw error; }
                if (!active || generation !== run) { URL.revokeObjectURL(url); return; }
                if (connectionController.signal.aborted || (Number.isFinite(age) &&
                    (performance.now() - requestedAt) / 1000 - (capturedAt - streamStartedAt) > 3)) {
                    URL.revokeObjectURL(url);
                    const error = new Error('Camera decode deadline'); error.name = 'StaleCameraFrame'; throw error;
                }
                img.src = url;
                img.parentElement.style.aspectRatio = `${decoded.naturalWidth} / ${decoded.naturalHeight}`;
                if (objectUrl) URL.revokeObjectURL(objectUrl);
                objectUrl = url;
                img.dataset.frameSequence = sequence;
                img.dataset.framesDisplayed = String(Number(img.dataset.framesDisplayed || 0) + 1);
                lastFrame = performance.now(); failures = 0; setState('Live');
                if (lastFrame - lastProgressLog >= 30000) {
                    console.info('Camera frames displayed', img.dataset.cameraId,
                                 img.dataset.frameSequence, img.dataset.framesDisplayed);
                    lastProgressLog = lastFrame;
                }
            }
            try {
                const feedUrl = new URL(img.dataset.feedUrl, location.href);
                const polling = img.dataset.cameraTransport !== 'sse';
                feedUrl.searchParams.set('transport', polling ? 'jpeg' : 'sse');
                if (bitrateStep) {
                    const profile = reducedProfiles[bitrateStep - 1];
                    Object.entries(profile).forEach(([key, value]) => feedUrl.searchParams.set(key, String(value)));
                }
                img.dataset.previewFps = feedUrl.searchParams.get('fps') || '6';
                if (polling) {
                    img.dataset.transport = 'jpeg-poll';
                    const interval = 1000 / Math.max(1, Math.min(25, Number(img.dataset.previewFps) || 6));
                    while (active && generation === run) {
                        const requestedAt = performance.now();
                        // Abort the whole retry generation if one transfer stalls.
                        // No second image request can queue behind the first one.
                        let expired = false;
                        const deadline = setTimeout(() => { expired = true; connectionController.abort(); }, 3000);
                        try {
                            const response = await fetch(feedUrl, {
                                signal: connectionController.signal, credentials: 'same-origin', cache: 'no-store'
                            });
                            if (!response.ok || response.status === 204) throw new Error('Frame unavailable');
                            const frame = new Uint8Array(await response.arrayBuffer());
                            if (!frame.length || frame.length > 4 * 1024 * 1024) throw new Error('Invalid camera frame');
                            await renderPacket({frame, sequence: response.headers.get('X-Frame-Sequence'),
                                capturedAt: Number(response.headers.get('X-Frame-Captured-At'))},
                                requestedAt, Number(response.headers.get('X-Stream-Started-At')));
                        } catch (error) {
                            if (expired) {
                                bitrateStep = Math.min(reducedProfiles.length, bitrateStep + 1);
                                error.name = 'StaleCameraFrame';
                            }
                            throw error;
                        } finally {
                            clearTimeout(deadline);
                        }
                        await new Promise(resolve => setTimeout(resolve, Math.max(0, interval - (performance.now() - requestedAt))));
                    }
                    return;
                }
                const requestedAt = performance.now();
                const response = await fetch(feedUrl, {
                    signal: connectionController.signal, credentials: 'same-origin', cache: 'no-store'
                });
                if (!response.ok || !response.body) throw new Error('Feed unavailable');
                const eventStream = (response.headers.get('Content-Type') || '').includes('text/event-stream');
                img.dataset.transport = eventStream ? 'sse' : 'mjpeg';
                const startedHeader = response.headers.get('X-Stream-Started-At');
                const streamStartedAt = startedHeader ? Number(startedHeader) : NaN;
                reader = response.body.getReader();
                let buffer = new Uint8Array(0), length = null, sequence = null, capturedAt = NaN;
                while (active && generation === run) {
                    const chunk = await reader.read();
                    if (chunk.done) throw new Error('Feed ended');
                    const next = new Uint8Array(buffer.length + chunk.value.length);
                    next.set(buffer); next.set(chunk.value, buffer.length); buffer = next;
                    if (buffer.length > 4 * 1024 * 1024) throw new Error('Invalid MJPEG frame size');
                    let latest = null;
                    while (true) {
                        if (eventStream) {
                            let end = -1;
                            for (let i = 0; i < buffer.length - 1; i++) {
                                if (buffer[i] === 10 && buffer[i+1] === 10) { end = i; break; }
                            }
                            if (end < 0) break;
                            const event = decoder.decode(buffer.subarray(0, end));
                            buffer = buffer.slice(end + 2);
                            const data = event.split('\n').find(line => line.startsWith('data: '));
                            if (!data) continue; // Initial SSE flush/comment.
                            const packet = JSON.parse(data.slice(6));
                            const seq = String(packet.sequence);
                            if (seq === img.dataset.frameSequence) continue;
                            const bytes = atob(packet.jpeg);
                            const frame = Uint8Array.from(bytes, byte => byte.charCodeAt(0));
                            if (!frame.length) throw new Error('Empty camera frame');
                            latest = {frame, sequence: seq, capturedAt: Number(packet.captured_at)};
                            continue;
                        }
                        if (length === null) {
                            let end = -1;
                            for (let i = 0; i < buffer.length - 3; i++) {
                                if (buffer[i] === 13 && buffer[i+1] === 10 && buffer[i+2] === 13 && buffer[i+3] === 10) { end = i; break; }
                            }
                            if (end < 0) break;
                            const header = decoder.decode(buffer.subarray(0, end));
                            const match = /Content-Length:\s*(\d+)/i.exec(header);
                            if (!match) throw new Error('Missing MJPEG length');
                            length = Number(match[1]);
                            if (length < 1 || length > 4 * 1024 * 1024) throw new Error('Invalid MJPEG length');
                            const seq = /X-Frame-Sequence:\s*(\d+)/i.exec(header);
                            sequence = seq ? seq[1] : null;
                            const captured = /X-Frame-Captured-At:\s*([\d.]+)/i.exec(header);
                            capturedAt = captured ? Number(captured[1]) : NaN;
                            buffer = buffer.slice(end + 4);
                        }
                        if (buffer.length < length) break;
                        const frame = buffer.slice(0, length);
                        buffer = buffer.slice(length); length = null;
                        if (sequence !== null && sequence === img.dataset.frameSequence) continue;
                        latest = {frame, sequence, capturedAt};
                    }
                    // A slow client should display the newest complete packet,
                    // not decode a backlog of old pictures from the same chunk.
                    if (latest) await renderPacket(latest, requestedAt, streamStartedAt);
                }
            } catch (error) {
                if (active && generation === run) {
                    console.warn('Camera reconnect', img.dataset.cameraId, error.name);
                    connectionController.abort();
                    schedule(error.name === 'StaleCameraFrame');
                }
            } finally {
                clearInterval(watchdog);
                if (reader) { await reader.cancel().catch(() => {}); reader.releaseLock(); }
            }
        }
        function resume() {
            if (!document.hidden && visible && !active) {
                active = true;
                delete img.dataset.frameSequence;
                setState('Reconnecting...'); connect();
            } else if ((document.hidden || !visible) && active) {
                stop(); setState('Paused');
            }
        }
        const observer = window.IntersectionObserver ? new IntersectionObserver(entries => {
            visible = entries[0].isIntersecting; resume();
        }, {rootMargin: '150px'}) : null;
        if (observer) { visible = false; observer.observe(img.parentElement); }
        document.addEventListener('visibilitychange', resume);
        window.addEventListener('pagehide', stop);
        window.addEventListener('pageshow', resume);
        img.addEventListener('camera:retry', () => { stop(); resume(); });
        resume();
    });
})();
