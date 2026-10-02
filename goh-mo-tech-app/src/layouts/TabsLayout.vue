<template>
  <ion-tabs>
    <ion-router-outlet />
    <ion-tab-bar slot="bottom">
      <ion-tab-button tab="home" href="/app/home"><ion-icon :icon="homeOutline" /><ion-label>Home</ion-label></ion-tab-button>
      <ion-tab-button tab="live" href="/app/live"><ion-icon :icon="videocamOutline" /><ion-label>Live</ion-label></ion-tab-button>
      <ion-tab-button tab="goats" href="/app/goats"><ion-icon :icon="pawOutline" /><ion-label>Goats</ion-label></ion-tab-button>
      <ion-tab-button tab="alerts" href="/app/alerts"><ion-icon :icon="notificationsOutline" /><ion-label>Alerts</ion-label></ion-tab-button>
      <ion-tab-button tab="more" href="/app/more"><ion-icon :icon="gridOutline" /><ion-label>More</ion-label></ion-tab-button>
    </ion-tab-bar>
  </ion-tabs>
</template>
<script setup lang="ts">
import { IonIcon, IonLabel, IonRouterOutlet, IonTabBar, IonTabButton, IonTabs } from '@ionic/vue'; import { gridOutline, homeOutline, notificationsOutline, pawOutline, videocamOutline } from 'ionicons/icons';
</script>
