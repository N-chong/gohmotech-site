<template><ion-page><ion-header class="ion-no-border"><ion-toolbar><ion-title>Live monitoring</ion-title></ion-toolbar></ion-header><ion-content><NetworkBanner /><main class="page-wrap">
  <div v-if="cameras.length > 1" class="camera-chips"><button v-for="camera in cameras" :key="camera.id" :class="{ active: camera.id === selected?.id }" @click="select(camera)">{{ camera.name }}</button></div>
  <StatePanel v-if="loading" loading title="Connecting to cameras" message="Requesting current camera status." />
  <StatePanel v-else-if="error" tone="danger" title="Camera unavailable" :message="error" :retry="load" />
  <template v-else-if="selected"><section class="camera-stage" :class="{ offline: selected.status !== 'active' }"><img v-if="streamUrl" :src="streamUrl" :alt="`${selected.name} live feed`" @load="playing = true" @error="streamFailed"><div v-if="!playing" class="camera-overlay"><ion-spinner v-if="selected.status === 'active'" /><ion-icon v-else :icon="videocamOffOutline" /><strong>{{ selected.status === 'active' ? 'Starting live feed…' : 'Camera offline' }}</strong></div><button v-if="playing" class="fullscreen-button" aria-label="Fullscreen" @click="fullscreen"><ion-icon :icon="scanOutline" /></button></section>
  <div class="camera-meta"><div><span class="live-dot" :class="selected.status"></span><div><strong>{{ selected.name }}</strong><small>{{ selected.location }}</small></div></div><span>{{ titleCase(selected.status) }}</span></div>
  <div class="info-note"><ion-icon :icon="informationCircleOutline" /><p>The current backend delivers server-transcoded MJPEG at a mobile-conscious 8 fps. It is compatible and stable, but WebRTC is the recommended later upgrade for lower latency and bandwidth.</p></div>
  <ion-button v-if="selected.status !== 'active' || !playing" expand="block" fill="outline" @click="connect(selected)"><ion-icon slot="start" :icon="refreshOutline" />Reconnect</ion-button></template>
  <StatePanel v-else title="No cameras configured" message="Add an active camera in the GoHMoTech web administration." />
</main></ion-content></ion-page></template>
<script setup lang="ts">
import { onMounted, ref } from 'vue'; import { IonButton, IonContent, IonHeader, IonIcon, IonPage, IonSpinner, IonTitle, IonToolbar } from '@ionic/vue'; import { informationCircleOutline, refreshOutline, scanOutline, videocamOffOutline } from 'ionicons/icons'; import NetworkBanner from '@/components/NetworkBanner.vue'; import StatePanel from '@/components/StatePanel.vue'; import { cameraService } from '@/services/camera.service'; import type { Camera } from '@/types/api'; import { titleCase } from '@/utils/format';
const cameras = ref<Camera[]>([]); const selected = ref<Camera>(); const streamUrl = ref(''); const loading = ref(true); const error = ref(''); const playing = ref(false);
async function connect(camera: Camera) { playing.value = false; streamUrl.value = ''; if (camera.status !== 'active') return; try { streamUrl.value = await cameraService.streamUrl(camera.id); } catch (reason) { error.value = reason instanceof Error ? reason.message : 'Unable to start camera.'; } }
async function select(camera: Camera) { selected.value = camera; error.value = ''; await connect(camera); }
async function load() { loading.value = true; error.value = ''; try { const result = await cameraService.list(); cameras.value = result.results; if (cameras.value.length) await select(cameras.value[0]); } catch (reason) { error.value = reason instanceof Error ? reason.message : 'Unable to retrieve cameras.'; } finally { loading.value = false; } }
function streamFailed() { playing.value = false; error.value = 'The camera stream stopped. Check the camera connection and try again.'; }
async function fullscreen() { const stage = document.querySelector('.camera-stage') as HTMLElement | null; await stage?.requestFullscreen?.(); }
onMounted(load);
</script>
