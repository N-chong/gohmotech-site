(function () {
    const MAX_CAPTURE_DIMENSION = 1280;
    const CAPTURE_JPEG_QUALITY = .8;
    const angle = document.body.dataset.cameraAngle;
    const stage = document.querySelector('[data-camera-stage]');
    const frame = document.querySelector('[data-camera-frame]');
    const video = document.querySelector('[data-camera-video]');
    const canvas = document.querySelector('[data-camera-canvas]');
    const shutter = document.querySelector('[data-camera-shutter]');
    const message = document.querySelector('[data-camera-message]');
    const nativeCameraButton = document.querySelector('[data-native-camera-button]');
    const nativeCamera = document.querySelector('[data-native-camera]');
    const verification = document.querySelector('[data-visual-verification]');
    const capturedPreview = document.querySelector('[data-captured-preview]');
    const retake = document.querySelector('[data-photo-retake]');
    const confirm = document.querySelector('[data-photo-confirm]');
    const captureOnly = [document.querySelector('.capture-window-head'), stage, message, document.querySelector('.capture-actions'), nativeCameraButton];
    const cameraChannel = typeof window.BroadcastChannel === 'function' ? new BroadcastChannel('goat-photo-capture') : null;
    const returnToken = new URLSearchParams(window.location.search).get('return_token');
    let stream = null;
    let pendingDataUrl = null;
    let isConfirming = false;

    function drawCapture(source, width, height) {
        const scale = Math.min(1, MAX_CAPTURE_DIMENSION / Math.max(width, height));
        canvas.width = Math.max(1, Math.round(width * scale));
        canvas.height = Math.max(1, Math.round(height * scale));
        canvas.getContext('2d').drawImage(source, 0, 0, canvas.width, canvas.height);
    }

    function qualityMessage(targetCanvas) {
        if (Math.min(targetCanvas.width, targetCanvas.height) < 360 || Math.max(targetCanvas.width, targetCanvas.height) < 480) {
            return 'Photo resolution is too low. Use at least 480 × 360 pixels.';
        }
        const sample = document.createElement('canvas');
        const scale = Math.min(1, 180 / Math.max(targetCanvas.width, targetCanvas.height));
        sample.width = Math.max(1, Math.round(targetCanvas.width * scale));
        sample.height = Math.max(1, Math.round(targetCanvas.height * scale));
        const context = sample.getContext('2d', {willReadFrequently: true});
        context.drawImage(targetCanvas, 0, 0, sample.width, sample.height);
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

    function fitPreview() {
        if (!video.videoWidth || !video.videoHeight) return;
        const ratio = video.videoWidth / video.videoHeight;
        const availableWidth = stage.clientWidth;
        const availableHeight = stage.clientHeight;
        if (!availableWidth || !availableHeight) return;
        let width = availableWidth;
        let height = width / ratio;
        if (height > availableHeight) {
            height = availableHeight;
            width = height * ratio;
        }
        frame.style.width = `${Math.floor(width)}px`;
        frame.style.height = `${Math.floor(height)}px`;
        frame.style.aspectRatio = `${video.videoWidth} / ${video.videoHeight}`;
    }

    function stopCamera() {
        if (stream) stream.getTracks().forEach((track) => track.stop());
        stream = null;
        video.srcObject = null;
    }

    function closeWindow() {
        stopCamera();
        if (returnToken && !isConfirming) {
            try {
                window.localStorage.removeItem(`goat-camera-pending-${returnToken}`);
            } catch (error) { /* localStorage is an optional return path */ }
        }
        window.close();
        if (!window.closed) history.back();
    }

    function sendToOpener(payload) {
        const result = {...payload, returnToken};
        if (returnToken) {
            try {
                window.localStorage.setItem(`goat-camera-result-${returnToken}`, JSON.stringify(result));
            } catch (error) { /* optional fallback */ }
        }
        let delivered = false;
        if (window.opener && !window.opener.closed) {
            window.opener.postMessage(result, window.location.origin);
            delivered = true;
        }
        if (cameraChannel) {
            cameraChannel.postMessage(result);
            delivered = true;
        }
        return delivered;
    }

    function showVerification(dataUrl) {
        pendingDataUrl = dataUrl;
        capturedPreview.src = dataUrl;
        captureOnly.forEach((element) => { element.hidden = true; });
        verification.hidden = false;
        video.pause();
        retake.focus();
    }

    function showCamera() {
        pendingDataUrl = null;
        nativeCamera.value = '';
        capturedPreview.removeAttribute('src');
        verification.hidden = true;
        captureOnly.forEach((element) => { element.hidden = element === nativeCameraButton; });
        message.textContent = 'Opening rear camera…';
        message.classList.remove('error');
        shutter.disabled = true;
        if (stream) {
            video.play().then(() => {
                fitPreview();
                shutter.disabled = false;
                message.textContent = 'Keep the complete goat inside the guide.';
                shutter.focus();
            }).catch(() => openCamera());
        } else {
            openCamera();
        }
    }

    async function openCamera() {
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            message.textContent = 'Live preview is unavailable. Use your phone camera instead.';
            message.classList.add('error');
            nativeCameraButton.hidden = false;
            return;
        }
        try {
            stream = await navigator.mediaDevices.getUserMedia({
                video: {facingMode: {ideal: 'environment'}, width: {ideal: 1600}, height: {ideal: 1200}},
                audio: false
            });
            video.srcObject = stream;
            await video.play();
            fitPreview();
            shutter.disabled = false;
            message.textContent = 'Keep the complete goat inside the guide.';
            shutter.focus();
        } catch (error) {
            message.textContent = 'Camera unavailable. Returning to the phone camera option…';
            message.classList.add('error');
            nativeCameraButton.hidden = false;
        }
    }

    shutter.addEventListener('click', () => {
        if (!video.videoWidth || !video.videoHeight) return;
        drawCapture(video, video.videoWidth, video.videoHeight);
        const issue = qualityMessage(canvas);
        if (issue) {
            message.textContent = issue;
            message.classList.add('error');
            return;
        }
        const dataUrl = canvas.toDataURL('image/jpeg', CAPTURE_JPEG_QUALITY);
        if (!/^data:image\/jpeg;base64,/.test(dataUrl)) return;
        showVerification(dataUrl);
    });

    nativeCamera.addEventListener('change', () => {
        const file = nativeCamera.files[0];
        if (!file) return;
        const image = new Image();
        const source = URL.createObjectURL(file);
        image.onload = () => {
            drawCapture(image, image.naturalWidth, image.naturalHeight);
            URL.revokeObjectURL(source);
            const issue = qualityMessage(canvas);
            if (issue) {
                nativeCamera.value = '';
                message.textContent = issue;
                message.classList.add('error');
                return;
            }
            showVerification(canvas.toDataURL('image/jpeg', CAPTURE_JPEG_QUALITY));
        };
        image.onerror = () => {
            URL.revokeObjectURL(source);
            nativeCamera.value = '';
            message.textContent = 'The selected photo could not be read.';
            message.classList.add('error');
        };
        image.src = source;
    });

    retake.addEventListener('click', showCamera);
    confirm.addEventListener('click', () => {
        if (!pendingDataUrl || isConfirming) return;
        isConfirming = true;
        confirm.disabled = true;
        if (!sendToOpener({type: 'goat-camera-captured', angle, dataUrl: pendingDataUrl})) {
            isConfirming = false;
            confirm.disabled = false;
            verification.querySelector('p').textContent = 'Return to Goat Inventory and open this angle again.';
            return;
        }
        setTimeout(closeWindow, 150);
    });

    document.querySelectorAll('[data-camera-close]').forEach((button) => button.addEventListener('click', closeWindow));
    video.addEventListener('loadedmetadata', fitPreview);
    if ('ResizeObserver' in window) new ResizeObserver(fitPreview).observe(stage);
    window.addEventListener('resize', fitPreview);
    window.addEventListener('orientationchange', fitPreview);
    window.addEventListener('pagehide', stopCamera);
    window.addEventListener('pagehide', () => cameraChannel?.close());
    openCamera();
})();
