(function () {
    const managers = document.querySelectorAll('[data-goat-photo-manager]');
    if (!managers.length) return;
    const MAX_CAPTURE_DIMENSION = 1280;
    const CAPTURE_JPEG_QUALITY = .8;

    function drawCapture(targetCanvas, source, width, height) {
        const scale = Math.min(1, MAX_CAPTURE_DIMENSION / Math.max(width, height));
        targetCanvas.width = Math.max(1, Math.round(width * scale));
        targetCanvas.height = Math.max(1, Math.round(height * scale));
        targetCanvas.getContext('2d').drawImage(source, 0, 0, targetCanvas.width, targetCanvas.height);
    }

    function qualityMessage(canvas) {
        if (Math.min(canvas.width, canvas.height) < 360 || Math.max(canvas.width, canvas.height) < 480) {
            return 'Photo resolution is too low. Use at least 480 × 360 pixels.';
        }
        const sample = document.createElement('canvas');
        const scale = Math.min(1, 180 / Math.max(canvas.width, canvas.height));
        sample.width = Math.max(1, Math.round(canvas.width * scale));
        sample.height = Math.max(1, Math.round(canvas.height * scale));
        const context = sample.getContext('2d', {willReadFrequently: true});
        context.drawImage(canvas, 0, 0, sample.width, sample.height);
        const pixels = context.getImageData(0, 0, sample.width, sample.height).data;
        let total = 0;
        for (let index = 0; index < pixels.length; index += 4) {
            total += .299 * pixels[index] + .587 * pixels[index + 1] + .114 * pixels[index + 2];
        }
        const mean = total / (pixels.length / 4);
        if (mean < 24) return 'This photo is too dark. Retake it in better light.';
        if (mean > 235) return 'This photo is too bright. Retake it away from glare.';
        return '';
    }

    managers.forEach((manager) => {
        let captures = {};
        const field = manager.querySelector('[data-captured-photos]');
        const camera = manager.querySelector('[data-guided-camera]');
        const video = manager.querySelector('[data-camera-video]');
        const cameraStage = manager.querySelector('.camera-preview-stage');
        const cameraFrame = manager.querySelector('.camera-frame');
        const canvas = manager.querySelector('[data-camera-canvas]');
        const title = manager.querySelector('[data-camera-title]');
        const guidance = manager.querySelector('[data-camera-guidance]');
        const cameraMessage = manager.querySelector('[data-camera-message]');
        const cameraShutter = camera && camera.querySelector('[data-camera-shutter]');
        const verification = manager.querySelector('[data-photo-verification]');
        const verificationTitle = manager.querySelector('[data-verification-title]');
        const verificationImage = manager.querySelector('[data-verification-image]');
        const verificationRetake = manager.querySelector('[data-verification-retake]');
        const verificationUse = manager.querySelector('[data-verification-use]');
        let stream = null;
        let activeAngle = null;
        let returnFocus = null;
        let pendingCapture = null;
        const pendingCameraTokens = new Map();

        function fitCameraFrame() {
            if (!cameraStage || !cameraFrame || !video.videoWidth || !video.videoHeight) return;
            const ratio = video.videoWidth / video.videoHeight;
            cameraFrame.style.setProperty('--camera-aspect', `${video.videoWidth} / ${video.videoHeight}`);
            const availableWidth = cameraStage.clientWidth;
            const availableHeight = cameraStage.clientHeight;
            if (!availableWidth || !availableHeight) return;

            let previewWidth = availableWidth;
            let previewHeight = previewWidth / ratio;
            if (previewHeight > availableHeight) {
                previewHeight = availableHeight;
                previewWidth = previewHeight * ratio;
            }
            cameraFrame.style.width = `${Math.floor(previewWidth)}px`;
            cameraFrame.style.height = `${Math.floor(previewHeight)}px`;
        }

        function stopCamera() {
            if (stream) stream.getTracks().forEach((track) => track.stop());
            stream = null;
            video.srcObject = null;
            camera.hidden = true;
            document.documentElement.classList.remove('guided-camera-open');
            if (returnFocus) returnFocus.focus();
            returnFocus = null;
        }

        function setMessage(angle, message, success) {
            const target = manager.querySelector(`[data-quality="${angle}"]`);
            if (!target) return;
            target.textContent = message;
            target.classList.toggle('error', Boolean(message) && !success);
            target.classList.toggle('success', Boolean(message) && Boolean(success));
        }

        function setPreview(angle, source) {
            const preview = manager.querySelector(`[data-preview="${angle}"]`);
            if (!preview) return;
            const image = document.createElement('img');
            image.src = source;
            image.alt = `Selected ${angle} view`;
            preview.replaceChildren(image);
        }

        function closeVerification() {
            pendingCapture = null;
            verification.hidden = true;
            verificationImage.removeAttribute('src');
            verificationImage.alt = '';
            document.documentElement.classList.remove('photo-verification-open');
        }

        function showVerification(angle, dataUrl) {
            const card = manager.querySelector(`[data-photo-card="${angle}"]`);
            const label = card?.querySelector('strong')?.textContent?.trim() || angle;
            pendingCapture = {angle, dataUrl};
            verificationTitle.textContent = label;
            verificationImage.src = dataUrl;
            verificationImage.alt = `Captured ${label}`;
            verification.hidden = false;
            document.documentElement.classList.add('photo-verification-open');
            verificationUse.focus();
        }

        function commitCapture(angle, dataUrl) {
            captures[angle] = dataUrl;
            field.value = JSON.stringify(captures);
            const upload = manager.querySelector(`[data-upload-angle="${angle}"]`);
            if (upload) upload.value = '';
            const nativeCapture = manager.querySelector(`[data-native-capture-angle="${angle}"]`);
            if (nativeCapture) nativeCapture.value = '';
            setPreview(angle, dataUrl);
            setMessage(angle, 'Captured photo ready. Save changes to keep it.', true);
        }

        function cameraResultKey(token) {
            return `goat-camera-result-${token}`;
        }

        function cameraPendingKey(token) {
            return `goat-camera-pending-${token}`;
        }

        function forgetCameraResult(token) {
            pendingCameraTokens.delete(token);
            try {
                window.localStorage.removeItem(cameraResultKey(token));
                window.localStorage.removeItem(cameraPendingKey(token));
            } catch (error) { /* localStorage is an optional return path */ }
        }

        function acceptCameraResult(result) {
            if (!result || result.type !== 'goat-camera-captured' ||
                typeof result.returnToken !== 'string' || !result.returnToken ||
                typeof result.angle !== 'string' ||
                typeof result.dataUrl !== 'string' ||
                !/^data:image\/jpeg;base64,/.test(result.dataUrl)) return false;

            let expectedAngle = pendingCameraTokens.get(result.returnToken);
            if (!expectedAngle) {
                try {
                    const pending = JSON.parse(window.localStorage.getItem(cameraPendingKey(result.returnToken)) || 'null');
                    expectedAngle = pending?.angle;
                } catch (error) { return false; }
            }
            if (!expectedAngle || expectedAngle !== result.angle ||
                !manager.querySelector(`[data-capture-angle="${result.angle}"]`)) return false;

            commitCapture(result.angle, result.dataUrl);
            forgetCameraResult(result.returnToken);
            manager.querySelector(`[data-capture-angle="${result.angle}"]`)?.focus();
            return true;
        }

        function collectStoredCameraResults() {
            try {
                const keys = [];
                for (let index = 0; index < window.localStorage.length; index += 1) {
                    const key = window.localStorage.key(index);
                    if (key?.startsWith('goat-camera-result-')) keys.push(key);
                }
                keys.forEach((key) => {
                    try {
                        acceptCameraResult(JSON.parse(window.localStorage.getItem(key) || 'null'));
                    } catch (error) { /* ignore malformed or unrelated stored data */ }
                });
            } catch (error) { /* localStorage may be unavailable in private mode */ }
        }

        function openDedicatedCamera(angle) {
            const template = manager.dataset.cameraUrlTemplate;
            if (!template) return false;
            const token = (window.crypto && typeof window.crypto.randomUUID === 'function')
                ? window.crypto.randomUUID()
                : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
            const separator = template.includes('?') ? '&' : '?';
            const url = `${template.replace('__angle__', encodeURIComponent(angle))}${separator}return_token=${encodeURIComponent(token)}`;
            pendingCameraTokens.set(token, angle);
            try {
                window.localStorage.setItem(cameraPendingKey(token), JSON.stringify({angle, createdAt: Date.now()}));
            } catch (error) { /* opener messaging can still return the photo */ }
            const cameraWindow = window.open(url, '_blank');
            if (!cameraWindow) {
                forgetCameraResult(token);
                return false;
            }
            cameraWindow.focus();
            setMessage(angle, 'Camera opened. Confirm the photo there to return it here.', true);
            return true;
        }

        function usePendingCapture() {
            if (!pendingCapture) return;
            const {angle, dataUrl} = pendingCapture;
            commitCapture(angle, dataUrl);
            const button = manager.querySelector(`[data-capture-angle="${angle}"]`);
            closeVerification();
            button?.focus();
        }

        manager.querySelectorAll('[data-angle-view]').forEach((button) => {
            button.addEventListener('click', () => {
                manager.querySelector('#angle-viewer-image').src = button.dataset.src;
                manager.querySelector('#angle-viewer-label').textContent = button.dataset.label;
                manager.querySelectorAll('[data-angle-view]').forEach((item) => item.classList.remove('active'));
                button.classList.add('active');
            });
        });

        if (!field || !camera || !video || !canvas || !cameraShutter || !verification ||
            !verificationTitle || !verificationImage || !verificationRetake || !verificationUse) return;

        try {
            const storedCaptures = JSON.parse(field.value || '{}');
            if (storedCaptures && typeof storedCaptures === 'object' && !Array.isArray(storedCaptures)) {
                captures = storedCaptures;
            }
        } catch (error) { captures = {}; }

        const cameraChannel = typeof window.BroadcastChannel === 'function'
            ? new BroadcastChannel('goat-photo-capture')
            : null;
        if (cameraChannel) cameraChannel.addEventListener('message', (event) => acceptCameraResult(event.data));
        window.addEventListener('message', (event) => {
            if (event.origin === window.location.origin) acceptCameraResult(event.data);
        });
        window.addEventListener('storage', (event) => {
            if (event.key?.startsWith('goat-camera-result-') && event.newValue) collectStoredCameraResults();
        });
        window.addEventListener('focus', collectStoredCameraResults);
        window.addEventListener('pageshow', collectStoredCameraResults);
        document.addEventListener('visibilitychange', () => {
            if (!document.hidden) collectStoredCameraResults();
        });
        collectStoredCameraResults();

        // Keep the viewport-fixed camera out of transformed cards. On touch devices,
        // a card's sticky :hover transform otherwise becomes the modal's containing block.
        document.body.appendChild(camera);
        document.body.appendChild(verification);

        manager.querySelectorAll('[data-upload-angle], [data-native-capture-angle]').forEach((input) => {
            input.addEventListener('change', () => {
                const file = input.files[0];
                if (!file) return;
                const angle = input.dataset.uploadAngle || input.dataset.nativeCaptureAngle;
                const image = new Image();
                const source = URL.createObjectURL(file);
                image.onload = () => {
                    const check = document.createElement('canvas');
                    drawCapture(check, image, image.naturalWidth, image.naturalHeight);
                    const issue = qualityMessage(check);
                    if (issue) {
                        input.value = '';
                        URL.revokeObjectURL(source);
                        setMessage(angle, issue, false);
                        return;
                    }
                    if (input.dataset.nativeCaptureAngle) {
                        URL.revokeObjectURL(source);
                        showVerification(angle, check.toDataURL('image/jpeg', CAPTURE_JPEG_QUALITY));
                        return;
                    }
                    delete captures[angle];
                    field.value = JSON.stringify(captures);
                    manager.querySelectorAll(`[data-upload-angle="${angle}"], [data-native-capture-angle="${angle}"]`).forEach((other) => {
                        if (other !== input) other.value = '';
                    });
                    setPreview(angle, source);
                    setMessage(angle, 'Photo ready. Save changes to upload it.', true);
                };
                image.onerror = () => {
                    input.value = '';
                    URL.revokeObjectURL(source);
                    setMessage(angle, 'This image could not be read.', false);
                };
                image.src = source;
            });
        });

        manager.querySelectorAll('[data-capture-angle]').forEach((button) => {
            button.addEventListener('click', async () => {
                returnFocus = button;
                activeAngle = button.dataset.captureAngle;
                if (openDedicatedCamera(activeAngle)) return;
                camera.dataset.angle = activeAngle;
                const card = button.closest('[data-photo-card]');
                title.textContent = card.querySelector('strong').textContent;
                guidance.textContent = card.querySelector('p').textContent;
                cameraMessage.textContent = '';
                const nativeCapture = card.querySelector('[data-native-capture-angle]');
                if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
                    setMessage(activeAngle, 'Live preview is unavailable. Opening your phone camera instead.', true);
                    nativeCapture?.click();
                    return;
                }
                try {
                    stream = await navigator.mediaDevices.getUserMedia({
                        video: {facingMode: {ideal: 'environment'}, width: {ideal: 1600}, height: {ideal: 1200}},
                        audio: false
                    });
                    video.srcObject = stream;
                    camera.hidden = false;
                    document.documentElement.classList.add('guided-camera-open');
                    await video.play();
                    requestAnimationFrame(fitCameraFrame);
                    cameraShutter.focus();
                } catch (error) {
                    stopCamera();
                    setMessage(activeAngle, 'Opening your phone camera instead.', true);
                    nativeCapture?.click();
                }
            });
        });

        cameraShutter.addEventListener('click', () => {
            if (!activeAngle || !video.videoWidth) return;
            drawCapture(canvas, video, video.videoWidth, video.videoHeight);
            const issue = qualityMessage(canvas);
            if (issue) {
                cameraMessage.textContent = issue;
                cameraMessage.className = 'photo-quality-message error';
                return;
            }
            const dataUrl = canvas.toDataURL('image/jpeg', CAPTURE_JPEG_QUALITY);
            const capturedAngle = activeAngle;
            stopCamera();
            showVerification(capturedAngle, dataUrl);
        });

        verificationUse.addEventListener('click', usePendingCapture);
        verificationRetake.addEventListener('click', () => {
            if (!pendingCapture) return;
            const angle = pendingCapture.angle;
            const nativeCapture = manager.querySelector(`[data-native-capture-angle="${angle}"]`);
            if (nativeCapture) nativeCapture.value = '';
            closeVerification();
            manager.querySelector(`[data-capture-angle="${angle}"]`)?.click();
        });
        verification.addEventListener('keydown', (event) => {
            if (event.key === 'Escape') verificationRetake.click();
        });

        camera.querySelectorAll('[data-camera-close]').forEach((button) => button.addEventListener('click', stopCamera));
        video.addEventListener('loadedmetadata', fitCameraFrame);
        if ('ResizeObserver' in window && cameraStage) {
            new ResizeObserver(fitCameraFrame).observe(cameraStage);
        }
        window.addEventListener('resize', fitCameraFrame);
        window.addEventListener('orientationchange', fitCameraFrame);
        camera.addEventListener('keydown', (event) => {
            if (event.key === 'Escape') stopCamera();
        });
        manager.querySelectorAll('[data-delete-image]').forEach((button) => {
            button.addEventListener('click', async () => {
                if (!window.confirm('Delete this angle photo?')) return;
                const template = manager.dataset.deleteTemplate;
                const csrf = document.querySelector('[name=csrfmiddlewaretoken]');
                if (!template || !csrf) return;
                const url = template.replace('/0/', `/${button.dataset.deleteImage}/`);
                const response = await fetch(url, {
                    method: 'POST',
                    headers: {'X-CSRFToken': csrf.value, 'X-Requested-With': 'XMLHttpRequest'}
                });
                if (response.ok) window.location.reload();
                else setMessage(button.closest('[data-photo-card]').dataset.photoCard, 'Photo could not be deleted.', false);
            });
        });
        window.addEventListener('beforeunload', stopCamera);
        window.addEventListener('beforeunload', closeVerification);
        window.addEventListener('pagehide', () => cameraChannel?.close());
    });
})();
