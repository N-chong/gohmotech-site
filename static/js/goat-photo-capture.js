(function () {
    const managers = document.querySelectorAll('[data-goat-photo-manager]');
    if (!managers.length) return;

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
        const captures = {};
        const field = manager.querySelector('[data-captured-photos]');
        const camera = manager.querySelector('[data-guided-camera]');
        const video = manager.querySelector('[data-camera-video]');
        const canvas = manager.querySelector('[data-camera-canvas]');
        const title = manager.querySelector('[data-camera-title]');
        const guidance = manager.querySelector('[data-camera-guidance]');
        const cameraMessage = manager.querySelector('[data-camera-message]');
        let stream = null;
        let activeAngle = null;
        let returnFocus = null;

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
            preview.innerHTML = `<img src="${source}" alt="Selected ${angle} view">`;
        }

        manager.querySelectorAll('[data-angle-view]').forEach((button) => {
            button.addEventListener('click', () => {
                manager.querySelector('#angle-viewer-image').src = button.dataset.src;
                manager.querySelector('#angle-viewer-label').textContent = button.dataset.label;
                manager.querySelectorAll('[data-angle-view]').forEach((item) => item.classList.remove('active'));
                button.classList.add('active');
            });
        });

        if (!field || !camera || !video || !canvas) return;

        manager.querySelectorAll('[data-upload-angle]').forEach((input) => {
            input.addEventListener('change', () => {
                const file = input.files[0];
                if (!file) return;
                const image = new Image();
                const source = URL.createObjectURL(file);
                image.onload = () => {
                    const check = document.createElement('canvas');
                    check.width = image.naturalWidth;
                    check.height = image.naturalHeight;
                    check.getContext('2d').drawImage(image, 0, 0);
                    const issue = qualityMessage(check);
                    if (issue) {
                        input.value = '';
                        URL.revokeObjectURL(source);
                        setMessage(input.dataset.uploadAngle, issue, false);
                        return;
                    }
                    delete captures[input.dataset.uploadAngle];
                    field.value = JSON.stringify(captures);
                    setPreview(input.dataset.uploadAngle, source);
                    setMessage(input.dataset.uploadAngle, 'Photo ready. Save changes to upload it.', true);
                };
                image.onerror = () => {
                    input.value = '';
                    URL.revokeObjectURL(source);
                    setMessage(input.dataset.uploadAngle, 'This image could not be read.', false);
                };
                image.src = source;
            });
        });

        manager.querySelectorAll('[data-capture-angle]').forEach((button) => {
            button.addEventListener('click', async () => {
                returnFocus = button;
                activeAngle = button.dataset.captureAngle;
                camera.dataset.angle = activeAngle;
                const card = button.closest('[data-photo-card]');
                title.textContent = card.querySelector('strong').textContent;
                guidance.textContent = card.querySelector('p').textContent;
                cameraMessage.textContent = '';
                if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
                    card.querySelector('[data-upload-angle]').click();
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
                    video.play().catch(() => {});
                    manager.querySelector('[data-camera-shutter]').focus();
                } catch (error) {
                    stopCamera();
                    setMessage(activeAngle, 'Camera unavailable. Use Upload to choose a photo instead.', false);
                }
            });
        });

        manager.querySelector('[data-camera-shutter]').addEventListener('click', () => {
            if (!activeAngle || !video.videoWidth) return;
            const scale = Math.min(1, 1600 / video.videoWidth);
            canvas.width = Math.round(video.videoWidth * scale);
            canvas.height = Math.round(video.videoHeight * scale);
            canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
            const issue = qualityMessage(canvas);
            if (issue) {
                cameraMessage.textContent = issue;
                cameraMessage.className = 'photo-quality-message error';
                return;
            }
            const dataUrl = canvas.toDataURL('image/jpeg', .86);
            captures[activeAngle] = dataUrl;
            field.value = JSON.stringify(captures);
            const upload = manager.querySelector(`[data-upload-angle="${activeAngle}"]`);
            if (upload) upload.value = '';
            setPreview(activeAngle, dataUrl);
            setMessage(activeAngle, 'Captured photo ready. Save changes to keep it.', true);
            stopCamera();
        });

        manager.querySelectorAll('[data-camera-close]').forEach((button) => button.addEventListener('click', stopCamera));
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
    });
})();
