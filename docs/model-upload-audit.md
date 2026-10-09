# Machine-Learning Model Upload Audit

## Previous behavior

- The page submitted `FormData` with `fetch()`, which exposes no browser upload-progress events. Users only saw a disabled button until the complete request returned.
- Model validation allowed files up to 500 MB, while Django and both deployed Nginx configurations limited request bodies to 12 MB.
- Uploaded files were stored privately and were never automatically activated. RF-DETR activation loaded the candidate before replacing the active model, but other uploaded detector types did not receive the same final load check.

## Current behavior

- A small authenticated preflight checks filename, extension, declared size and protected-storage free space before transferring the model.
- The upload itself uses `XMLHttpRequest.upload` progress events. Displayed progress is based on bytes reported by the browser, with no timer or simulated percentage.
- Selected filename, file type and readable size are shown before upload. During transfer the component displays uploaded bytes, remaining bytes, percentage and current state.
- Connection errors, timeouts, HTTP 413, storage failures, validation errors and server errors produce bounded user-facing messages. Technical exceptions remain in server logs.
- The upload button and form controls are disabled while a request is active and restored after failure. Retry starts from zero because resumable/chunked upload is not implemented.
- Success is shown only after the backend confirms that the private stored file exists and has the same size as the received upload. The response truthfully reports `Uploaded (pending validation)` and `is_active=false`.
- Large files above Django's 2.5 MB in-memory threshold use `TemporaryUploadedFile`; protected storage writes do not call `read()` on the complete checkpoint.
- Validation now performs both static file checks and a detector load. Activation loads the candidate again before changing active records, so a failed candidate leaves the previous working model active.

## Deployment limits

| Layer | Limit / behavior |
|---|---|
| Model validator | 500 MB maximum |
| Nginx general routes | 12 MB |
| Nginx exact model-upload route | 512 MB; 30-minute body/send/read timeouts |
| Django request parser | 512 MB maximum request body |
| Django in-memory file threshold | 2.5 MB; larger files spool to temporary disk |
| Protected-model reserve | Uploaded size plus 256 MB free-space reserve |

The PDF/report changes and model-upload changes do not alter inference endpoints, model database schema, or Raspberry Pi device APIs.
