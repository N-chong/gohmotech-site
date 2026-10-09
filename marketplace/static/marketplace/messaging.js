(() => {
  const search = document.querySelector('[data-conversation-search]');
  const searchForm = document.querySelector('[data-conversation-search-form]');
  const rows = [...document.querySelectorAll('[data-conversation-row]')];
  const searchEmpty = document.querySelector('[data-client-search-empty]');
  if (search && rows.length) {
    const filterRows = () => {
      const query = search.value.trim().toLocaleLowerCase();
      let matches = 0;
      rows.forEach((row) => {
        const visible = !query || (row.dataset.searchText || '').toLocaleLowerCase().includes(query);
        row.hidden = !visible;
        if (visible) matches += 1;
      });
      if (searchEmpty) searchEmpty.hidden = matches !== 0;
    };
    search.addEventListener('input', filterRows);
    filterRows();
  }
  if (searchForm) searchForm.addEventListener('submit', () => {
    if (search) search.value = search.value.trim();
  });

  const messageRows = [...document.querySelectorAll('[data-message-row]')];
  messageRows.forEach((row, index) => {
    if (index && messageRows[index - 1].dataset.sender === row.dataset.sender) row.classList.add('grouped');
  });

  const thread = document.querySelector('[data-message-thread]');
  const messengerShell = document.querySelector('.messenger-shell');
  const visualViewport = window.visualViewport;
  const currentViewportHeight = () => visualViewport
    ? Math.min(visualViewport.height, window.innerHeight)
    : window.innerHeight;
  let largestViewportHeight = currentViewportHeight();
  const syncMobileViewport = () => {
    const viewportHeight = currentViewportHeight();
    largestViewportHeight = Math.max(largestViewportHeight, viewportHeight);
    document.documentElement.style.setProperty('--messenger-viewport-height', `${viewportHeight}px`);
    if (messengerShell) {
      messengerShell.classList.toggle('keyboard-open', largestViewportHeight - viewportHeight > 120);
    }
  };
  syncMobileViewport();
  if (visualViewport) {
    visualViewport.addEventListener('resize', syncMobileViewport);
    visualViewport.addEventListener('scroll', syncMobileViewport);
  } else {
    window.addEventListener('resize', syncMobileViewport);
  }
  if (thread) {
    const scrollKey = `gohmotech-message-scroll:${window.location.pathname}`;
    const navigation = performance.getEntriesByType && performance.getEntriesByType('navigation')[0];
    const saved = sessionStorage.getItem(scrollKey);
    if (navigation && navigation.type === 'back_forward' && saved !== null) {
      thread.scrollTop = Number(saved);
    } else {
      thread.scrollTop = thread.scrollHeight;
    }
    window.addEventListener('pagehide', () => sessionStorage.setItem(scrollKey, String(thread.scrollTop)));
  }

  document.querySelectorAll('[data-inquiry-image]').forEach((button) => {
    const image = button.querySelector('img');
    if (!image) return;
    const finish = () => button.classList.add('loaded');
    if (image.complete && image.naturalWidth) finish();
    else image.addEventListener('load', finish, { once: true });
    image.addEventListener('error', () => button.classList.add('failed'), { once: true });
  });

  const input = document.querySelector('.message-image-input');
  const preview = document.querySelector('[data-image-preview]');
  const previewImage = document.querySelector('[data-preview-image]');
  const previewName = document.querySelector('[data-preview-name]');
  const removeButton = document.querySelector('[data-remove-image]');
  const status = document.querySelector('[data-upload-status]');
  const form = document.querySelector('[data-message-form]');
  const sendButton = document.querySelector('[data-send-button]');
  const textarea = form && form.querySelector('textarea');
  let previewUrl = '';
  let sending = false;
  const defaultStatus = 'Images are private to this conversation · 2,000 character limit';
  const setStatus = (message, isError = false) => {
    if (!status) return;
    status.textContent = message;
    status.style.color = isError ? '#a33731' : '';
  };
  const resetPreview = () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = '';
    if (input) input.value = '';
    if (preview) preview.hidden = true;
    if (previewImage) previewImage.removeAttribute('src');
    setStatus(defaultStatus);
  };
  if (input) input.addEventListener('change', () => {
    const file = input.files && input.files[0];
    if (!file) return resetPreview();
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
      resetPreview();
      setStatus('Select a JPG, PNG, or WebP image.', true);
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      resetPreview();
      setStatus('Image is too large. Select an image up to 5 MB.', true);
      return;
    }
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = URL.createObjectURL(file);
    if (previewImage) previewImage.src = previewUrl;
    if (previewName) previewName.textContent = file.name;
    if (preview) preview.hidden = false;
    setStatus('Image ready to send');
  });
  if (removeButton) removeButton.addEventListener('click', resetPreview);
  if (textarea) {
    textarea.rows = 1;
    const resize = () => {
      textarea.style.height = 'auto';
      textarea.style.height = `${Math.min(textarea.scrollHeight, 120)}px`;
    };
    textarea.addEventListener('input', resize);
    textarea.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        if (form.requestSubmit) form.requestSubmit();
      }
    });
    textarea.addEventListener('focus', () => {
      window.setTimeout(() => {
        syncMobileViewport();
        if (thread) thread.scrollTop = thread.scrollHeight;
      }, 250);
    });
    resize();
  }
  if (form) form.addEventListener('submit', (event) => {
    if (sending) {
      event.preventDefault();
      return;
    }
    const hasBody = textarea && textarea.value.trim();
    const hasImage = input && input.files && input.files.length;
    if (!hasBody && !hasImage) {
      event.preventDefault();
      setStatus('Write a message or attach an image.', true);
      if (textarea) textarea.focus();
      return;
    }
    sending = true;
    if (sendButton) {
      sendButton.disabled = true;
      sendButton.classList.add('sending');
    }
    setStatus(hasImage ? 'Uploading image…' : 'Sending message…');
  });

  const viewer = document.querySelector('[data-image-viewer]');
  const viewerImage = document.querySelector('[data-viewer-image]');
  const viewerName = document.querySelector('[data-viewer-name]');
  document.querySelectorAll('[data-inquiry-image]').forEach((button) => button.addEventListener('click', () => {
    if (!viewer || !viewerImage) return;
    viewerImage.src = button.dataset.inquiryImage;
    viewerImage.alt = button.dataset.imageName;
    if (viewerName) viewerName.textContent = button.dataset.imageName;
    if (viewer.showModal) viewer.showModal(); else viewer.setAttribute('open', '');
  }));
  const closeViewer = () => {
    if (!viewer) return;
    if (viewer.close && viewer.open) viewer.close();
    else viewer.removeAttribute('open');
  };
  const closeButton = document.querySelector('[data-image-viewer-close]');
  if (closeButton) closeButton.addEventListener('click', closeViewer);
  if (viewer) {
    viewer.addEventListener('click', (event) => { if (event.target === viewer) closeViewer(); });
    viewer.addEventListener('close', () => { if (viewerImage) viewerImage.removeAttribute('src'); });
  }
})();
