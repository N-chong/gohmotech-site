"""
MQTT Client for IoT Device Communication

This module handles MQTT communication with IoT devices:
- Camera feeds
- Sensors (temperature, humidity, motion)
- Feeders (automated feeding control)
- Actuators

MQTT Topics Structure:
- sensors/{device_id}/data -> Sensor readings
- cameras/{device_id}/snapshot -> Camera images
- feeders/{device_id}/feed -> Feed commands
- feeders/{device_id}/status -> Feeder status
- alerts/{device_id} -> Device alerts
"""

import paho.mqtt.client as mqtt
import json
import logging
from django.conf import settings
from django.utils import timezone
import cv2
import numpy as np

logger = logging.getLogger(__name__)


class GoatMonitoringMQTTClient:
    """MQTT Client for KaMoTech"""
    
    def __init__(self):
        self.client = mqtt.Client()
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_disconnect = self.on_disconnect
        
        # Get MQTT broker settings
        self.broker_host = getattr(settings, 'MQTT_BROKER_HOST', 'localhost')
        self.broker_port = getattr(settings, 'MQTT_BROKER_PORT', 1883)
        self.mqtt_username = getattr(settings, 'MQTT_USERNAME', None)
        self.mqtt_password = getattr(settings, 'MQTT_PASSWORD', None)
        
        # Set credentials if provided
        if self.mqtt_username and self.mqtt_password:
            self.client.username_pw_set(self.mqtt_username, self.mqtt_password)
        
        self.connected = False
    
    def connect(self):
        """Connect to MQTT broker"""
        try:
            self.client.connect(self.broker_host, self.broker_port, 60)
            self.client.loop_start()
            logger.info(f"Connected to MQTT broker at {self.broker_host}:{self.broker_port}")
        except Exception as e:
            logger.error(f"Failed to connect to MQTT broker: {e}")
    
    def disconnect(self):
        """Disconnect from MQTT broker"""
        self.client.loop_stop()
        self.client.disconnect()
        logger.info("Disconnected from MQTT broker")
    
    def on_connect(self, client, userdata, flags, rc):
        """Callback when connected to broker"""
        if rc == 0:
            self.connected = True
            logger.info("Successfully connected to MQTT broker")
            
            # Subscribe to all device topics
            self.client.subscribe("sensors/+/data")
            self.client.subscribe("cameras/+/snapshot")
            self.client.subscribe("feeders/+/status")
            self.client.subscribe("alerts/+")
            
            logger.info("Subscribed to device topics")
        else:
            logger.error(f"Connection failed with code {rc}")
    
    def on_disconnect(self, client, userdata, rc):
        """Callback when disconnected from broker"""
        self.connected = False
        if rc != 0:
            logger.warning(f"Unexpected disconnection from broker (code: {rc})")
    
    def on_message(self, client, userdata, msg):
        """Callback when message received"""
        try:
            topic = msg.topic
            payload = msg.payload
            
            # Route message to appropriate handler
            if topic.startswith("sensors/"):
                self.handle_sensor_data(topic, payload)
            elif topic.startswith("cameras/"):
                self.handle_camera_snapshot(topic, payload)
            elif topic.startswith("feeders/") and topic.endswith("/status"):
                self.handle_feeder_status(topic, payload)
            elif topic.startswith("alerts/"):
                self.handle_alert(topic, payload)
            else:
                logger.warning(f"Unknown topic: {topic}")
                
        except Exception as e:
            logger.error(f"Error processing MQTT message: {e}")
    
    def handle_sensor_data(self, topic, payload):
        """
        Handle sensor data message.
        
        Topic: sensors/{device_id}/data
        Payload: {"sensor_type": "temperature", "value": 25.5, "unit": "C"}
        """
        from .models import Device, SensorData
        
        try:
            # Extract device_id from topic
            parts = topic.split('/')
            device_id = parts[1]
            
            # Parse JSON payload
            data = json.loads(payload.decode('utf-8'))
            
            # Get or create device
            device, created = Device.objects.get_or_create(
                device_id=device_id,
                defaults={
                    'name': f'Sensor {device_id}',
                    'device_type': 'sensor',
                    'is_active': True
                }
            )
            
            # Keep health/offline detection independent of retained raw rows.
            device.last_sensor_received_at = timezone.now()
            device.save(update_fields=['last_sensor_received_at'])
            
            # Create sensor reading
            SensorData.objects.create(
                device=device,
                sensor_type=data.get('sensor_type', 'unknown'),
                value=data.get('value', 0),
                unit=data.get('unit', ''),
                metadata=data.get('metadata', {})
            )
            
            logger.info(f"Sensor data saved: {device_id} - {data.get('sensor_type')}: {data.get('value')}")
            
        except Exception as e:
            logger.error(f"Error handling sensor data: {e}")
    
    def handle_camera_snapshot(self, topic, payload):
        """
        Handle camera snapshot message.
        
        Topic: cameras/{device_id}/snapshot
        Payload: Raw image bytes (JPEG)
        """
        from .models import Device
        
        try:
            # Extract device_id from topic
            parts = topic.split('/')
            device_id = parts[1]
            
            # Get or create camera device
            device, created = Device.objects.get_or_create(
                device_id=device_id,
                defaults={
                    'name': f'Camera {device_id}',
                    'device_type': 'camera',
                    'is_active': True
                }
            )
            
            # Update last seen
            device.last_seen = timezone.now()
            device.save(update_fields=['last_seen'])
            
            # Decode image
            nparr = np.frombuffer(payload, np.uint8)
            image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            if image is not None:
                logger.info(f"Camera snapshot received from {device_id}")
            else:
                logger.error(f"Failed to decode image from {device_id}")
                
        except Exception as e:
            logger.error(f"Error handling camera snapshot: {e}")
    
    def handle_feeder_status(self, topic, payload):
        """
        Handle feeder status message.
        
        Topic: feeders/{device_id}/status
        Payload: {"feed_level": 5000, "status": "ready"}
        """
        from .models import Device
        from feeding.models import FeedLevel
        
        try:
            # Extract device_id from topic
            parts = topic.split('/')
            device_id = parts[1]
            
            # Parse JSON payload
            data = json.loads(payload.decode('utf-8'))
            
            # Get or create feeder device
            device, created = Device.objects.get_or_create(
                device_id=device_id,
                defaults={
                    'name': f'Feeder {device_id}',
                    'device_type': 'feeder',
                    'is_active': True
                }
            )
            
            # Update last seen
            device.last_seen = timezone.now()
            device.save(update_fields=['last_seen'])
            
            # Update feed level
            feed_level, created = FeedLevel.objects.get_or_create(
                feeder=device,
                defaults={'capacity_grams': 10000}
            )
            
            if 'feed_level' in data:
                feed_level.current_level_grams = data['feed_level']
                feed_level.save()
            
            logger.info(f"Feeder status updated: {device_id}")
            
        except Exception as e:
            logger.error(f"Error handling feeder status: {e}")
    
    def handle_alert(self, topic, payload):
        """
        Handle alert message from device.
        
        Topic: alerts/{device_id}
        Payload: {"severity": "high", "message": "Temperature too high"}
        """
        from .models import Device, Alert
        
        try:
            # Extract device_id from topic
            parts = topic.split('/')
            device_id = parts[1]
            
            # Parse JSON payload
            data = json.loads(payload.decode('utf-8'))
            
            # Get device
            device = Device.objects.get(device_id=device_id)
            
            # Create alert
            Alert.objects.create(
                device=device,
                severity=data.get('severity', 'medium'),
                message=data.get('message', 'Alert from device')
            )
            
            logger.warning(f"Alert received from {device_id}: {data.get('message')}")
            
        except Device.DoesNotExist:
            logger.error(f"Device {device_id} not found for alert")
        except Exception as e:
            logger.error(f"Error handling alert: {e}")
    
    def publish_feed_command(self, device_id: str, amount: int):
        """
        Publish feed command to feeder device.
        
        Args:
            device_id: Device ID of the feeder
            amount: Amount of feed in grams
        """
        topic = f"feeders/{device_id}/feed"
        payload = json.dumps({"amount": amount})
        
        self.client.publish(topic, payload)
        logger.info(f"Published feed command to {device_id}: {amount}g")


# Global MQTT client instance
mqtt_client = None


def get_mqtt_client():
    """Get or create global MQTT client"""
    global mqtt_client
    
    if mqtt_client is None:
        mqtt_client = GoatMonitoringMQTTClient()
        mqtt_client.connect()
    
    return mqtt_client


def start_mqtt_client():
    """Start MQTT client (call this from Django app ready)"""
    logger.info("Starting MQTT client...")
    client = get_mqtt_client()
    return client


def stop_mqtt_client():
    """Stop MQTT client"""
    global mqtt_client
    
    if mqtt_client:
        mqtt_client.disconnect()
        mqtt_client = None
        logger.info("MQTT client stopped")
