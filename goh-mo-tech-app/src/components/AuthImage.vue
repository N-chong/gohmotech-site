<template><div class="auth-image" :class="{ loaded }"><img v-if="objectUrl" :src="objectUrl" :alt="alt"><ion-icon v-else :icon="pawOutline" /></div></template>
<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'; import { IonIcon } from '@ionic/vue'; import { pawOutline } from 'ionicons/icons'; import { authenticatedImageUrl } from '@/services/api';
const props = defineProps<{ src: string | null; alt: string }>(); const objectUrl = ref(''); const loaded = ref(false);
watch(() => props.src, async (value) => { if (objectUrl.value) URL.revokeObjectURL(objectUrl.value); objectUrl.value = ''; loaded.value = false; if (!value) return; try { objectUrl.value = await authenticatedImageUrl(value); loaded.value = true; } catch { /* fallback icon */ } }, { immediate: true });
onBeforeUnmount(() => { if (objectUrl.value) URL.revokeObjectURL(objectUrl.value); });
</script>
