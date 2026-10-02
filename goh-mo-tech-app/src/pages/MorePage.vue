<template><ion-page><ion-header class="ion-no-border"><ion-toolbar><ion-title>More</ion-title></ion-toolbar></ion-header><ion-content><main class="page-wrap">
  <section class="account-card"><div>{{ initials }}</div><span><strong>{{ authState.user?.display_name }}</strong><small>{{ titleCase(authState.user?.role || '') }}</small></span></section>
  <p class="eyebrow menu-label">FARM TOOLS</p><nav class="more-menu"><router-link v-for="item in tools" :key="item.path" :to="item.path"><span :class="item.color"><ion-icon :icon="item.icon" /></span><div><strong>{{ item.title }}</strong><small>{{ item.copy }}</small></div><ion-icon :icon="chevronForwardOutline" /></router-link></nav>
  <p class="eyebrow menu-label">ACCOUNT</p><nav class="more-menu"><button @click="logout"><span class="slate"><ion-icon :icon="logOutOutline" /></span><div><strong>Sign out</strong><small>End this mobile session</small></div></button></nav>
  <p class="version">GoHMoTech Mobile · Foundation release</p>
</main></ion-content></ion-page></template>
<script setup lang="ts">
import { computed } from 'vue'; import { useRouter } from 'vue-router'; import { IonContent, IonHeader, IonIcon, IonPage, IonTitle, IonToolbar } from '@ionic/vue'; import { barChartOutline, chevronForwardOutline, lockClosedOutline, logOutOutline, mapOutline, optionsOutline, storefrontOutline } from 'ionicons/icons'; import { authState } from '@/stores/auth.store'; import { authService } from '@/services/auth.service'; import { titleCase } from '@/utils/format';
const router = useRouter(); const initials = computed(() => authState.user?.display_name.split(/\s+/).map((part) => part[0]).join('').slice(0, 2).toUpperCase() || 'GF');
const tools = [{ path: '/automation', title: 'Automation', copy: 'Door, lighting, and feeding', icon: optionsOutline, color: 'green' }, { path: '/tracking', title: 'Goat tracking', copy: 'BLE proximity and last seen', icon: mapOutline, color: 'blue' }, { path: '/security', title: 'Security', copy: 'Detections and event details', icon: lockClosedOutline, color: 'navy' }, { path: '/reports', title: 'Reports', copy: 'Mobile farm summaries', icon: barChartOutline, color: 'cyan' }, { path: '/marketplace', title: 'Marketplace', copy: 'Listings and transactions', icon: storefrontOutline, color: 'gold' }];
async function logout() { await authService.logout(); await router.replace('/login'); }
</script>
