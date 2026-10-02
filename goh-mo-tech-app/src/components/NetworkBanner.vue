<template><div v-if="!online" class="network-banner"><ion-icon :icon="cloudOfflineOutline" /> No internet connection — showing only loaded information.</div></template>
<script setup lang="ts">
import { IonIcon } from '@ionic/vue'; import { cloudOfflineOutline } from 'ionicons/icons'; import { useNetworkStatus } from '@/composables/useNetworkStatus';
const { online } = useNetworkStatus();
</script>
