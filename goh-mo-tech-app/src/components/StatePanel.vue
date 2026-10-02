<template>
  <div class="state-panel" :class="tone">
    <ion-spinner v-if="loading" name="crescent" />
    <ion-icon v-else :icon="icon" />
    <strong>{{ title }}</strong><p>{{ message }}</p>
    <ion-button v-if="retry && !loading" fill="outline" size="small" @click="retry">Try again</ion-button>
  </div>
</template>
<script setup lang="ts">
import { computed } from 'vue'; import { IonButton, IonIcon, IonSpinner } from '@ionic/vue'; import { alertCircleOutline, leafOutline } from 'ionicons/icons';
const props = defineProps<{ loading?: boolean; title: string; message: string; retry?: () => void; tone?: 'neutral' | 'danger' }>();
const icon = computed(() => props.tone === 'danger' ? alertCircleOutline : leafOutline);
</script>
