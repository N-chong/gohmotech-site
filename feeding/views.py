from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from marketplace.permissions import FarmRolePermission
from marketplace.decorators import farm_owner_required
from django.shortcuts import redirect
from django.utils import timezone
from django.db import models
from .models import FeedSchedule, FeedLevel, FeedLog, AutomatedFeedingConfig
from .serializers import (FeedScheduleSerializer, FeedLevelSerializer, 
                          FeedLogSerializer, AutomatedFeedingConfigSerializer)
from iot.models import Device
from iot.device_authentication import HasLegacyDeviceKey
from iot.status_utils import device_last_seen, is_device_online
import logging

logger = logging.getLogger(__name__)


class AutomatedFeedingConfigViewSet(viewsets.ModelViewSet):
    """ViewSet for Automated Feeding Configuration"""
    queryset = AutomatedFeedingConfig.objects.all()
    serializer_class = AutomatedFeedingConfigSerializer
    permission_classes = [FarmRolePermission]
    
    @action(detail=False, methods=['post'])
    def toggle(self, request):
        """Toggle automated feeding on/off"""
        config = AutomatedFeedingConfig.get_config()
        config.is_enabled = not config.is_enabled
        config.updated_by = request.user.username if request.user.is_authenticated else 'anonymous'
        config.save()
        
        return Response({
            'status': 'success',
            'is_enabled': config.is_enabled,
            'message': f"Automated feeding {'enabled' if config.is_enabled else 'disabled'}"
        })
    
    @action(detail=False, methods=['get'])
    def status(self, request):
        """Get current status"""
        config = AutomatedFeedingConfig.get_config()
        serializer = self.get_serializer(config)
        return Response(serializer.data)


class FeedScheduleViewSet(viewsets.ModelViewSet):
    """ViewSet for Feed Schedule CRUD"""
    queryset = FeedSchedule.objects.all()
    serializer_class = FeedScheduleSerializer
    filterset_fields = ['feeder', 'is_active']
    permission_classes = [FarmRolePermission]
    
    @action(detail=True, methods=['post'])
    def toggle_active(self, request, pk=None):
        """Toggle schedule active status"""
        schedule = self.get_object()
        schedule.is_active = not schedule.is_active
        schedule.save()
        
        serializer = self.get_serializer(schedule)
        return Response(serializer.data)


class FeedLevelViewSet(viewsets.ModelViewSet):
    """ViewSet for Feed Level monitoring"""
    queryset = FeedLevel.objects.all()
    serializer_class = FeedLevelSerializer
    permission_classes = [FarmRolePermission]

    def get_permissions(self):
        if self.action == 'update_from_esp32':
            return [HasLegacyDeviceKey()]
        return super().get_permissions()
    
    @action(detail=True, methods=['post'])
    def refill(self, request, pk=None):
        """Mark feeder as refilled"""
        feed_level = self.get_object()
        amount = request.data.get('amount', feed_level.capacity_grams)
        
        feed_level.current_level_grams = amount
        feed_level.last_refilled_at = timezone.now()
        feed_level.save()
        
        return Response({
            'status': 'Refilled',
            'current_level': feed_level.current_level_grams,
            'percentage_full': feed_level.percentage_full
        })
    
    @action(detail=False, methods=['get'])
    def low_levels(self, request):
        """Get feeders with low feed levels"""
        low_feeders = FeedLevel.objects.filter(
            current_level_grams__lt=models.F('low_level_threshold')
        )
        serializer = self.get_serializer(low_feeders, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['post'], url_path='update')
    def update_from_esp32(self, request):
        """Update feed level from ESP32 ultrasonic sensor"""
        try:
            feeder_id = request.data.get('feeder_id')
            distance_cm = float(request.data.get('distance_cm', 0))
            percentage = int(request.data.get('percentage', 0))
            
            if not feeder_id:
                return Response(
                    {'error': 'feeder_id is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Get or create feeder device
            feeder = Device.objects.filter(id=feeder_id, device_type='feeder').first()
            if not feeder:
                # Create default feeder if it doesn't exist
                feeder = Device.objects.create(
                    id=feeder_id,
                    device_id=f'ESP32_FEEDER_{feeder_id}',
                    name=f'Default Feeder {feeder_id}',
                    device_type='feeder',
                    is_active=True
                )
                logger.info(f"Created default feeder device: {feeder.name}")
            
            # Get or create feed level record
            feed_level, created = FeedLevel.objects.get_or_create(
                feeder=feeder,
                defaults={
                    'capacity_grams': 10000,  # Default 10kg capacity
                    'low_level_threshold': 2000,  # Default 2kg threshold
                }
            )
            
            # Update ultrasonic sensor data
            feed_level.distance_cm = distance_cm
            feed_level.percentage = percentage
            
            # Calculate current level in grams based on percentage
            feed_level.current_level_grams = int((percentage / 100.0) * feed_level.capacity_grams)
            feed_level.save()
            
            logger.info(f"Feed level updated for {feeder.name}: {percentage}% ({distance_cm}cm)")
            
            return Response({
                'status': 'success',
                'message': 'Feed level updated',
                'feeder_id': feeder_id,
                'feeder_name': feeder.name,
                'distance_cm': distance_cm,
                'percentage': percentage,
                'current_level_grams': feed_level.current_level_grams,
                'capacity_grams': feed_level.capacity_grams,
                'is_low': feed_level.is_low
            })
            
        except Exception:
            logger.exception("Error updating feed level from ESP32")
            return Response(
                {'error': 'Feed-level update failed.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class FeedLogViewSet(viewsets.ModelViewSet):
    """ViewSet for Feed Log operations"""
    queryset = FeedLog.objects.all()
    serializer_class = FeedLogSerializer
    filterset_fields = ['feeder', 'scheduled', 'status']
    permission_classes = [FarmRolePermission]
    
    def get_permissions(self):
        """
        Require the compatibility device key for existing ESP32 endpoints.
        """
        if self.action in ['servo_commands', 'servo_confirm', 'esp32_pending', 'confirm_executed', 'physical_button_feed']:
            return [HasLegacyDeviceKey()]
        return super().get_permissions()
    
    @action(detail=False, methods=['post'])
    def manual_feed(self, request):
        """Trigger manual feeding"""
        feeder_id = request.data.get('feeder_id')
        try:
            amount = int(request.data.get('amount', 500))
        except (TypeError, ValueError):
            return Response(
                {'error': 'amount must be a whole number between 1 and 10000 grams'},
                status=status.HTTP_400_BAD_REQUEST
            )
        if amount < 1 or amount > 10000:
            return Response(
                {'error': 'amount must be between 1 and 10000 grams'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            feeder = Device.objects.get(id=feeder_id, device_type='feeder')
            if not is_device_online(feeder):
                return Response({
                    'error': 'Feeder controller is offline. No feed command was created.',
                    'code': 'FEEDER_OFFLINE',
                    'device_online': False,
                    'device_last_seen': device_last_seen(feeder),
                }, status=status.HTTP_409_CONFLICT)

            # Create feed log
            feed_log = FeedLog.objects.create(
                feeder=feeder,
                amount_dispensed=amount,
                scheduled=False,
                feeding_mode='manual',
                trigger_reason='manual_override',
                status='pending'  # Mark as pending until ESP32 confirms
            )
            
            # Update feed level
            try:
                feed_level = FeedLevel.objects.get(feeder=feeder)
                feed_level.current_level_grams = max(0, feed_level.current_level_grams - amount)
                feed_level.save()
            except FeedLevel.DoesNotExist:
                pass
            
            serializer = self.get_serializer(feed_log)
            return Response({
                **serializer.data,
                'device_online': True,
                'result': 'sent',
                'confirmation': 'pending_device_confirmation',
            })
            
        except Device.DoesNotExist:
            return Response(
                {'error': 'Feeder not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception:
            logger.exception("Manual feed request failed")
            return Response(
                {'error': 'Manual feed request failed.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['get'])
    def esp32_pending(self, request):
        """
        Get pending feed commands for ESP32
        Query params: feeder_id (integer)
        Returns: Pending feed commands from last 60 seconds
        """
        feeder_id = request.query_params.get('feeder_id')
        
        if not feeder_id:
            return Response(
                {'error': 'feeder_id parameter required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get recent pending commands (last 60 seconds)
        recent_time = timezone.now() - timezone.timedelta(seconds=60)
        pending_logs = FeedLog.objects.filter(
            feeder__id=feeder_id,
            status='pending',
            timestamp__gte=recent_time
        ).order_by('-timestamp')
        
        if not pending_logs.exists():
            return Response({
                'has_pending': False,
                'pending_commands': []
            })
        
        serializer = self.get_serializer(pending_logs, many=True)
        return Response({
            'has_pending': True,
            'pending_commands': serializer.data
        })
    
    @action(detail=True, methods=['post'])
    def confirm_executed(self, request, pk=None):
        """
        Mark feed command as executed by ESP32
        POST by ESP32 after successfully dispensing feed
        """
        feed_log = self.get_object()
        feed_log.status = 'success'
        feed_log.save()
        
        return Response({
            'message': 'Feed command marked as executed',
            'log_id': feed_log.id
        })
    
    @action(detail=False, methods=['get'], url_path='servo-commands')
    def servo_commands(self, request):
        """
        Get pending feed commands for Servo Feeder ESP32
        Query params: feeder_id (integer)
        Returns: Single most recent pending command
        """
        feeder_id = request.query_params.get('feeder_id', 1)
        
        try:
            # Get most recent pending command (last 60 seconds)
            recent_time = timezone.now() - timezone.timedelta(seconds=60)
            pending_log = FeedLog.objects.filter(
                feeder__id=feeder_id,
                status='pending',
                timestamp__gte=recent_time
            ).order_by('-timestamp').first()
            
            if not pending_log:
                return Response({
                    'has_command': False,
                    'message': 'No pending commands'
                })
            
            return Response({
                'has_command': True,
                'feed_log_id': pending_log.id,
                'amount': pending_log.amount_dispensed,
                'mode': pending_log.feeding_mode,
                'timestamp': pending_log.timestamp.isoformat()
            })
            
        except Exception:
            logger.exception("Servo command lookup failed")
            return Response({
                'has_command': False,
                'error': 'Unable to retrieve pending commands.'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['post'], url_path='servo-confirm')
    def servo_confirm(self, request):
        """
        Confirm servo feeding completion
        POST body: {"feed_log_id": 123, "status": "completed", "device_id": "feeder_servo_001"}
        """
        feed_log_id = request.data.get('feed_log_id')
        status_val = request.data.get('status', 'success')
        device_id = request.data.get('device_id')
        
        if not feed_log_id:
            return Response(
                {'error': 'feed_log_id required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            feed_log = FeedLog.objects.get(id=feed_log_id)
            feed_log.status = status_val
            feed_log.save()
            
            logger.info(f"Servo feeder {device_id} confirmed feeding: Log ID {feed_log_id}")
            
            return Response({
                'message': 'Feeding confirmed successfully',
                'feed_log_id': feed_log.id,
                'status': feed_log.status
            })
            
        except FeedLog.DoesNotExist:
            return Response(
                {'error': 'Feed log not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception:
            logger.exception("Servo confirmation failed")
            return Response(
                {'error': 'Unable to confirm the feed command.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['post'], url_path='physical-button-feed')
    def physical_button_feed(self, request):
        """
        Log feeding triggered by physical button on ESP32
        POST body: {
            "device_id": "kamotech_esp32_001",
            "feeder_id": 1,
            "amount": 500
        }
        """
        device_id = request.data.get('device_id')
        feeder_id = request.data.get('feeder_id', 1)
        amount = int(request.data.get('amount', 500))
        
        try:
            feeder = Device.objects.get(id=feeder_id, device_type='feeder')

            # Create feed log with physical button trigger
            feed_log = FeedLog.objects.create(
                feeder=feeder,
                amount_dispensed=amount,
                scheduled=False,
                feeding_mode='manual',
                trigger_reason='physical_button',
                status='success'  # Physical button immediately dispenses
            )
            
            # Update feed level
            try:
                feed_level = FeedLevel.objects.get(feeder=feeder)
                feed_level.current_level_grams = max(0, feed_level.current_level_grams - amount)
                feed_level.save()
            except FeedLevel.DoesNotExist:
                pass
            
            logger.info(f"Physical button feed logged: {amount}g from device {device_id}")
            
            return Response({
                'message': 'Physical button feeding logged successfully',
                'feed_log_id': feed_log.id,
                'amount': amount,
                'feeder': feeder.name
            })
            
        except Device.DoesNotExist:
            return Response(
                {'error': 'Feeder not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception:
            logger.exception("Physical button feed logging failed")
            return Response(
                {'error': 'Unable to record the physical feed event.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# Django Template Views (HTML Pages)

@farm_owner_required
def feeding_dashboard_view(request):
    """Redirect to automation control page (feeding is now part of automation)"""
    return redirect('/iot/automation/')


@farm_owner_required
def schedule_list_view(request):
    """Redirect to automation control page (feeding is now part of automation)"""
    return redirect('/iot/automation/')


@farm_owner_required
def feed_logs_view(request):
    """Redirect to automation control page (feeding is now part of automation)"""
    return redirect('/iot/automation/')
