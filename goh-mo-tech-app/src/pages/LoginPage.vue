<template>
  <ion-page><ion-content :fullscreen="true" class="login-page">
    <main class="login-shell">
      <div class="brand-mark"><ion-icon :icon="leafOutline" /></div>
      <p class="eyebrow">SMART GOAT FARM</p><h1>GoHMoTech</h1><p class="login-copy">Your goat house, cameras, livestock, and alerts in one reliable mobile companion.</p>
      <form class="login-card" @submit.prevent="submit">
        <label>Username or email<ion-input v-model="username" autocomplete="username" fill="outline" placeholder="Farm account" /></label>
        <label>Password<ion-input v-model="password" type="password" autocomplete="current-password" fill="outline" placeholder="Password" /></label>
        <p v-if="error" class="form-error">{{ error }}</p>
        <ion-button expand="block" type="submit" :disabled="loading"><ion-spinner v-if="loading" name="crescent" />{{ loading ? 'Connecting…' : 'Sign in securely' }}</ion-button>
      </form>
      <p class="secure-note"><ion-icon :icon="shieldCheckmarkOutline" /> Uses your existing GoHMoTech farm account</p>
    </main>
  </ion-content></ion-page>
</template>
<script setup lang="ts">
import { ref } from 'vue'; import { useRoute, useRouter } from 'vue-router'; import { IonButton, IonContent, IonIcon, IonInput, IonPage, IonSpinner } from '@ionic/vue'; import { leafOutline, shieldCheckmarkOutline } from 'ionicons/icons'; import { authService } from '@/services/auth.service';
const username = ref(''); const password = ref(''); const loading = ref(false); const error = ref(''); const router = useRouter(); const route = useRoute();
async function submit() { error.value = ''; if (!username.value || !password.value) { error.value = 'Enter your username and password.'; return; } loading.value = true; try { await authService.login(username.value, password.value); await router.replace(typeof route.query.redirect === 'string' ? route.query.redirect : '/app/home'); } catch (reason) { error.value = reason instanceof Error ? reason.message : 'Unable to sign in.'; } finally { loading.value = false; } }
</script>
