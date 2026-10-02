<template>
  <ion-page><ion-header class="ion-no-border"><ion-toolbar><ion-title><span class="brand-title">GoHMoTech</span></ion-title><ion-button slot="end" fill="clear" aria-label="Notifications" router-link="/app/alerts"><ion-icon :icon="notificationsOutline" /></ion-button></ion-toolbar></ion-header>
  <ion-content><NetworkBanner /><ion-refresher slot="fixed" @ionRefresh="refresh"><ion-refresher-content /></ion-refresher>
    <main class="page-wrap"><section class="welcome"><div><p class="eyebrow">FARM OVERVIEW</p><h1>Good {{ greeting }}, {{ firstName }}</h1><p>{{ data ? `Updated ${relativeTime(data.generated_at)}` : 'Checking farm status…' }}</p></div><div class="system-orb" :class="data?.system.online ? 'online' : 'offline'"><span></span>{{ data?.system.online ? 'Online' : 'Offline' }}</div></section>
    <StatePanel v-if="loading && !data" loading title="Checking the goat house" message="Retrieving current farm conditions." />
    <StatePanel v-else-if="error && !data" tone="danger" title="Cannot connect to GoHMoTech server" :message="error" :retry="load" />
    <template v-else-if="data">
      <section class="metric-grid">
        <article class="metric-card"><div class="metric-icon blue"><ion-icon :icon="thermometerOutline" /></div><span>Temperature</span><strong>{{ value(data.environment.temperature, '°C') }}</strong></article>
        <article class="metric-card"><div class="metric-icon cyan"><ion-icon :icon="waterOutline" /></div><span>Humidity</span><strong>{{ value(data.environment.humidity, '%') }}</strong></article>
        <article class="metric-card"><div class="metric-icon green"><ion-icon :icon="nutritionOutline" /></div><span>Feed level</span><strong>{{ value(data.feed.percentage, '%') }}</strong><small :class="{ warning: data.feed.is_low }">{{ data.feed.is_low ? 'Refill soon' : 'Sufficient' }}</small></article>
        <article class="metric-card"><div class="metric-icon navy"><ion-icon :icon="pawOutline" /></div><span>Registered</span><strong>{{ data.goats.registered }}</strong><small>goats</small></article>
      </section>
      <section class="section-block"><div class="section-heading"><div><p class="eyebrow">OPERATIONS</p><h2>Goat house</h2></div><ion-button fill="clear" size="small" router-link="/automation">Controls</ion-button></div>
        <div class="status-list"><div><ion-icon :icon="hardwareChipOutline" /><span><strong>IoT controllers</strong><small>{{ data.system.iot_online }} of {{ data.system.iot_total }} online</small></span><b :class="data.system.controller_online ? 'ok' : 'bad'">{{ data.system.controller_online ? 'Connected' : 'Offline' }}</b></div><div><ion-icon :icon="enterOutline" /><span><strong>Door</strong><small>{{ data.automation.door?.mode || 'No controller' }}</small></span><b>{{ titleCase(data.automation.door?.state || 'unknown') }}</b></div><div><ion-icon :icon="bulbOutline" /><span><strong>Lighting</strong><small>{{ data.environment.light_level == null ? 'No light reading' : `${Math.round(data.environment.light_level)}% ambient` }}</small></span><b>{{ titleCase(data.automation.light?.state || 'unknown') }}</b></div></div>
      </section>
      <ion-button class="live-cta" expand="block" router-link="/app/live"><ion-icon slot="start" :icon="videocamOutline" />Open live monitoring<span>{{ data.system.cameras_online }}/{{ data.system.cameras_total }}</span></ion-button>
      <section v-if="data.alerts.length" class="section-block"><div class="section-heading"><div><p class="eyebrow">ATTENTION</p><h2>Important alerts</h2></div><ion-button fill="clear" size="small" router-link="/app/alerts">View all</ion-button></div><div class="alert-mini" v-for="alert in data.alerts.slice(0, 3)" :key="alert.id"><i :class="alert.severity"></i><div><strong>{{ alert.title }}</strong><small>{{ relativeTime(alert.created_at) }}</small></div></div></section>
    </template></main>
  </ion-content></ion-page>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'; import { IonButton, IonContent, IonHeader, IonIcon, IonPage, IonRefresher, IonRefresherContent, IonTitle, IonToolbar } from '@ionic/vue'; import { bulbOutline, enterOutline, hardwareChipOutline, notificationsOutline, nutritionOutline, pawOutline, thermometerOutline, videocamOutline, waterOutline } from 'ionicons/icons'; import NetworkBanner from '@/components/NetworkBanner.vue'; import StatePanel from '@/components/StatePanel.vue'; import { dashboardService } from '@/services/dashboard.service'; import { authState } from '@/stores/auth.store'; import type { DashboardData } from '@/types/api'; import { relativeTime, titleCase } from '@/utils/format'; import { FarmSocket } from '@/services/websocket.service';
const data = ref<DashboardData>(); const loading = ref(true); const error = ref(''); let socket: FarmSocket | undefined;
const firstName = computed(() => authState.user?.display_name.split(' ')[0] || 'Owner'); const greeting = computed(() => { const hour = new Date().getHours(); return hour < 12 ? 'morning' : hour < 18 ? 'afternoon' : 'evening'; });
const value = (item: number | null, suffix: string) => item == null ? '—' : `${Math.round(item)}${suffix}`;
async function load() { loading.value = true; error.value = ''; try { data.value = await dashboardService.get(); } catch (reason) { error.value = reason instanceof Error ? reason.message : 'Unable to retrieve farm status.'; } finally { loading.value = false; } }
async function refresh(event: CustomEvent) { await load(); (event.target as HTMLIonRefresherElement).complete(); }
onMounted(() => { void load(); socket = new FarmSocket('sensors', () => void load()); void socket.connect().catch(() => undefined); }); onBeforeUnmount(() => socket?.close());
</script>
