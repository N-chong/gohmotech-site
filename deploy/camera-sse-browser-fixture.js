/* Diagnostic only: exercise the actual monitoring script with fragmented SSE,
 * a stale capture timestamp, and latest-frame reconnect; never alters production. */
document.body.innerHTML = '<div style="width:320px;height:180px"><img data-live-camera data-camera-transport="sse" data-camera-id="fixture" data-feed-url="https://gohmotech.site/iot/camera/feed/1/?width=320&quality=50&fps=6" style="width:320px;height:180px"><div data-camera-state></div></div>';
window.fixtureStats = {connections: 0, active: 0, maxActive: 0};
window.fetch = async url => {
    const connection = ++window.fixtureStats.connections;
    const streamStarted = Date.now() / 1000;
    let timer, canceled = false, sequence = connection * 100;
    const canvas = document.createElement('canvas'); canvas.width = 320; canvas.height = 180;
    const ctx = canvas.getContext('2d');
    const encoder = new TextEncoder();
    if (window.fixtureJPEG) {
        window.fixtureStats.active++;
        window.fixtureStats.maxActive = Math.max(window.fixtureStats.maxActive, window.fixtureStats.active);
        await new Promise(resolve => setTimeout(resolve, 100));
        ctx.fillStyle = `rgb(${connection * 17 % 255},${connection * 43 % 255},${connection * 71 % 255})`;
        ctx.fillRect(0, 0, 320, 180);
        const jpeg = Uint8Array.from(atob(canvas.toDataURL('image/jpeg', .5).split(',')[1]), byte => byte.charCodeAt(0));
        window.fixtureStats.active--;
        return new Response(jpeg, {headers: {'Content-Type': 'image/jpeg', 'X-Stream-Started-At': String(streamStarted),
            'X-Frame-Captured-At': String(Date.now() / 1000 - (connection === 1 ? 6 : 0)), 'X-Frame-Sequence': String(sequence)}});
    }
    const close = () => {
        if (canceled) return;
        canceled = true; clearInterval(timer); window.fixtureStats.active--;
    };
    const body = new ReadableStream({
        start(controller) {
            window.fixtureStats.active++;
            window.fixtureStats.maxActive = Math.max(window.fixtureStats.maxActive, window.fixtureStats.active);
            controller.enqueue(encoder.encode(': camera stream\n\n'));
            timer = setInterval(() => {
                sequence++;
                ctx.fillStyle = `rgb(${sequence % 255},${sequence * 17 % 255},${sequence * 43 % 255})`;
                ctx.fillRect(0, 0, 320, 180);
                const packet = {sequence, captured_at: Date.now() / 1000 - (connection === 1 ? 6 : 0), jpeg: canvas.toDataURL('image/jpeg', .5).split(',')[1]};
                const data = encoder.encode(`event: frame\nid: ${sequence}\ndata: ${JSON.stringify(packet)}\n\n`);
                controller.enqueue(data.slice(0, 17));
                controller.enqueue(data.slice(17, 83));
                controller.enqueue(data.slice(83));
            }, 1000 / Number(new URL(url).searchParams.get('fps')));
        },
        cancel: close
    });
    return new Response(body, {headers: {'Content-Type': 'text/event-stream', 'X-Stream-Started-At': String(streamStarted)}});
};
if (window.fixtureJPEG) document.querySelector('[data-live-camera]').removeAttribute('data-camera-transport');
