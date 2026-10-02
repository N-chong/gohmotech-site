# GoHMoTech Capstone 2 Main Feature Source Code Reviewer/Guide

Repository reviewed: `/home/gohmotech/capstone`  
Review basis: current working tree on 2026-09-23, including uncommitted files currently used by the project.  
Status rule: **IMPLEMENTED** means the important layers are connected in code; **PARTIALLY IMPLEMENTED** means a meaningful layer is missing or incompatible; **EXPERIMENTAL** means the path is test/prototype-oriented; **NOT IMPLEMENTED** means the current active path does not contain the feature.

Security note: all credentials are represented as `<REDACTED>`. The current ESP32 sketches contain Wi-Fi credentials in source files. Their values are intentionally not reproduced here; move them to ignored per-device secret headers before sharing the repository.

Validation performed: Django's system check completed with no issues, and 201 focused isolated tests covering RBAC, controller status, automation, BLE, cameras, goat photos, weight integration, security, mobile APIs, analytics, SMS, and marketplace passed. Hardware-only behavior still requires a physical bench/live-network demonstration; passing server tests does not remove the limitations identified below.

---

## 1. USER AUTHENTICATION AND ROLE-BASED ACCESS

**STATUS: IMPLEMENTED**

### 1. Purpose

Django Allauth provides username/email login, logout, registration, password reset, and optional Google login. Django groups and staff flags determine whether a user is an administrator, Farm Owner, Farm Operator, approved marketplace seller, or ordinary marketplace account. Web sessions use secure cookies in production; the Ionic client uses an expiring DRF token.

### 2. Files Involved

```text
config/urls.py
config/settings.py
config/production.py
marketplace/auth.py
marketplace/decorators.py
marketplace/permissions.py
marketplace/forms.py
templates/registration/login.html
marketplace/templates/marketplace/register.html
mobile_api/authentication.py
mobile_api/views.py
```

### 3. System Flow

```text
Login or Google button
        ↓
django-allauth account URL/view
        ↓
Django authentication backend validates account
        ↓
Django session cookie is created
        ↓
dashboard_home_view checks has_farm_access()
        ↓
Decorator/DRF permission checks the role on every protected operation
        ↓
Admin → full management; Owner → farm management; Operator → read-only farm access;
ordinary account → marketplace only
```

Mobile flow: `LoginPage.vue → POST /api/mobile/auth/login/ → authenticate() → Token → Authorization: Token … → ExpiringTokenAuthentication`.

### 4. Important Source Code

File: `marketplace/auth.py`

```python
def get_system_role(user):
    if not getattr(user, "is_authenticated", False):
        return None
    if user.is_staff or user.is_superuser:
        return ROLE_ADMIN
    group_names = set(user.groups.values_list("name", flat=True))
    if FARM_OWNER_GROUP_NAME in group_names:
        return ROLE_FARM_OWNER
    if FARM_OPERATOR_GROUP_NAME in group_names:
        return ROLE_FARM_OPERATOR
    return ROLE_MARKETPLACE

def can_manage_farm(user):
    return get_system_role(user) in {ROLE_ADMIN, ROLE_FARM_OWNER}

def has_farm_access(user):
    return get_system_role(user) in {
        ROLE_ADMIN, ROLE_FARM_OWNER, ROLE_FARM_OPERATOR,
    }
```

File: `marketplace/decorators.py`

```python
def farm_owner_required(view_func):
    @login_required
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not can_manage_farm(request.user):
            raise PermissionDenied("You do not have permission to modify farm data.")
        return view_func(request, *args, **kwargs)
    return wrapped
```

File: `marketplace/permissions.py`

```python
class FarmRolePermission(BasePermission):
    """Admin/Owner may write; Operator may only issue safe requests."""
    def has_permission(self, request, view):
        if not has_farm_access(request.user):
            return False
        return request.method in SAFE_METHODS or can_manage_farm(request.user)
```

File: `config/settings.py`

```python
AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
]
ACCOUNT_LOGIN_METHODS = {'email', 'username'}
ACCOUNT_SIGNUP_FIELDS = ['email*', 'password1*', 'password2*']
ACCOUNT_SIGNUP_FORM_CLASS = 'marketplace.forms.MarketplaceSignupForm'
ACCOUNT_UNIQUE_EMAIL = True
ACCOUNT_PREVENT_ENUMERATION = True
SOCIALACCOUNT_STORE_TOKENS = False
SOCIALACCOUNT_PROVIDERS = {'google': {
    'SCOPE': ['profile', 'email'],
    'OAUTH_PKCE_ENABLED': True,
    'EMAIL_AUTHENTICATION': True,
}}
```

File: `mobile_api/views.py`

```python
class LoginView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [LoginThrottle]

    def post(self, request):
        user = authenticate(request=request,
                            username=str(request.data.get("username", "")).strip(),
                            password=str(request.data.get("password", "")))
        if user is None:
            return Response({"detail": "Invalid username or password."}, status=400)
        if not has_farm_access(user):
            return Response({"detail": "This account does not have farm access."}, status=403)
        token, _ = Token.objects.get_or_create(user=user)
        return Response({"token": token.key, "user": user_payload(user)})
```

### 5. Code Explanation

`get_system_role()` establishes one authoritative role order. `farm_access_required` allows all three farm roles into read pages; `farm_owner_required` permits mutations only for admin/owner; `staff_required` protects system administration. Allauth supplies password-reset URLs under `/accounts/`, and the login page links to `account_reset_password`. Google is shown only when OAuth environment configuration exists. The normal web login persists through Django's session cookie; there is no custom “Remember me” control in the current farm login template. The mobile token lasts up to `MOBILE_TOKEN_TTL_DAYS` but is intentionally kept only in memory, so it does not survive an app restart.

### 6. Database Tables / Models

- Django `auth_user`, `auth_group`, and membership tables store accounts and Farm Owner/Farm Operator groups.
- Allauth tables store email and social-account associations; OAuth access/refresh tokens are not retained.
- DRF `authtoken_token` stores one mobile API token per user.
- `marketplace.SellerProfile` controls seller approval independently of farm roles.

### 7. APIs / URLs

```text
GET/POST /accounts/login/
POST     /accounts/logout/
GET/POST /accounts/signup/
GET/POST /accounts/password/reset/
POST     /accounts/google/login/
POST     /api/mobile/auth/login/
POST     /api/mobile/auth/logout/
GET      /api/mobile/auth/me/
```

### 8. Hardware Involved

None. Browser and Ionic sessions communicate with Django over HTTPS.

### 9. Security / Safety

Passwords use Django hashing; forms use CSRF; Google uses PKCE; email enumeration is prevented; production session/CSRF cookies are secure and SameSite=Lax; mobile login is throttled; token sessions expire; authorization is rechecked server-side. UI hiding is not the permission boundary—the decorators and DRF permissions are.

### 10. Defense Explanation

**What I can say during the defense:**

“Authentication is handled by Django Allauth, so login, logout, registration, password reset, and Google authentication use an established authentication library. After login, my code maps the account to an admin, Farm Owner, Farm Operator, or marketplace role. Every protected view and API checks that role on the server. Owners and admins can change farm data, while operators have read-only access. The web uses Django sessions, and the mobile app uses a token with a configured expiration.”

---

## 2. DASHBOARD

**STATUS: IMPLEMENTED**

### 1. Purpose

The dashboard combines live environmental data, herd counts, actuator state, feeder level, device/camera/model status, alerts, BLE summaries, and recent real events. Admins use the modern dashboard; non-staff farm users are redirected to the role-aware owner dashboard. The Ionic dashboard has a smaller JSON aggregation endpoint optimized for mobile.

### 2. Files Involved

```text
dashboard/views.py
iot/views.py
iot/owner_views.py
iot/status_utils.py
iot/templates/iot/dashboard_modern.html
iot/templates/iot/owner_dashboard.html
static/js/dashboard-runtime.js
mobile_api/views.py
goh-mo-tech-app/src/pages/HomePage.vue
```

### 3. System Flow

```text
Authenticated user opens /
        ↓
dashboard_home_view chooses admin or owner dashboard
        ↓
Django aggregates SensorReading, Goat, FeedLevel, Alert, Detection,
ActuatorState, camera and BLE records
        ↓
Template renders initial state
        ↓
Polling/WebSocket updates camera, sensors, alerts and control summaries
```

### 4. Important Source Code

File: `dashboard/views.py`

```python
def dashboard_home_view(request):
    if not request.user.is_authenticated:
        return redirect('/marketplace/')
    if not has_farm_access(request.user):
        return redirect('/marketplace/')
    if request.user.is_staff or request.user.is_superuser:
        return redirect('/iot/')
    return redirect('/iot/owner/')
```

File: `iot/views.py`

```python
@farm_access_required
def dashboard_modern(request):
    if not is_admin(request.user):
        return redirect('iot:owner_dashboard')
    kamotech_device = Device.objects.filter(
        device_id=MAIN_CONTROLLER_DEVICE_ID
    ).first()
    latest_sensor_reading = (
        SensorReading.objects.filter(device=kamotech_device)
        .order_by('-timestamp').first() if kamotech_device else None
    )
    counts = Goat.objects.filter(is_active=True).aggregate(
        total=Count('id'),
        healthy=Count('id', filter=Q(health_status='healthy')),
        missing=Count('id', filter=Q(status='missing')),
    )
    sys_status = system_status()
    recent_activity = build_recent_activity()
```

File: `mobile_api/views.py`

```python
class DashboardView(APIView):
    permission_classes = [HasActiveFarmAccess]

    def get(self, request):
        controller = controller_status()
        latest = SensorReading.objects.select_related("device").order_by("-timestamp").first()
        feed = FeedLevel.objects.select_related("feeder").order_by("-updated_at").first()
        # response contains system, environment, feed, goats, automation and alerts
```

### 5. Code Explanation

`build_recent_activity()` merges `ActuationLog`, `FeedLog`, `Detection`, `Alert`, and `MissingGoatAlert` and sorts them by timestamp; it does not generate sample events. `system_status()` derives controller freshness, camera status, and the active goat model. `dashboard-runtime.js` periodically fetches the current page and replaces only dashboard sections, which is a pragmatic cross-process update path alongside WebSockets. CSS media queries and touch-size controls provide mobile web optimization.

### 6. Database Tables / Models

`Device`, `SensorReading`, `ActuatorState`, `Alert`, `Goat`, `FeedLevel`, `FeedLog`, `IPCamera`, `Detection`, `BLETrackingState`, and `MissingGoatAlert`.

### 7. APIs / URLs

```text
GET /iot/
GET /iot/owner/
GET /api/mobile/dashboard/
GET /iot/api/sensor-readings/latest/
GET /iot/api/actuators/
GET /iot/api/camera/status/
GET /iot/api/ble/tracking/
```

### 8. Hardware Involved

The dashboard displays information from both ESP32 controllers, the scale ESP32, BLE receiver/beacons, and IP camera, but it does not directly access GPIO hardware.

### 9. Security / Safety

Farm decorators protect web pages; `HasActiveFarmAccess` protects mobile data; admin-only alerts are excluded from the operator mobile response; camera credentials are never returned by dashboard APIs.

### 10. Defense Explanation

**What I can say during the defense:**

“The dashboard is an aggregation layer. It queries the latest real sensor readings and combines them with goat inventory counts, feeder state, actuators, alerts, camera status, BLE tracking, and ML detections. The page is initially rendered by Django and then refreshed through small API calls or page-section polling. The mobile dashboard uses a dedicated compact endpoint so it does not download the full web page. No fake recent activities are inserted; the activity feed is built from actual database logs.”

---

## 3. IOT DEVICE COMMUNICATION

**STATUS: IMPLEMENTED**

### 1. Purpose

ESP32 devices upload JSON sensor readings and poll JSON actuator commands. Django authenticates legacy device requests with a shared device-key header, creates/locates the `Device`, stores readings, and returns desired actuator states. The current door/light board uses public HTTPS with a pinned root CA; the environment/feeder board uses local plain HTTP and therefore has weaker transport protection.

### 2. Files Involved

```text
iot/device_authentication.py
iot/serializers.py
iot/views.py
iot/urls.py
iot/models.py
iot/status_utils.py
esp32 autofeeder/kamotech_esp32_door_light_ldr/kamotech_esp32_door_light_ldr.ino
esp32 autofeeder/kamotech_esp32_door_light_ldr/server_ca.h
esp32 autofeeder/kamotech_esp32_environment_feeder/kamotech_esp32_environment_feeder.ino
```

### 3. System Flow

```text
ESP32 sensor → Wi-Fi/network → POST JSON + X-GoHMotech-Device-Key
→ /iot/api/sensor-readings/ → SensorReadingSerializer → Device + SensorReading
→ dashboard/mobile query

Dashboard control → POST /iot/api/actuators/{id}/control/
→ desired ActuatorState saved → ESP32 GET esp32_commands every 5 s
→ JSON command → relay/servo GPIO → optional state sync back to Django
```

### 4. Important Source Code

File: `iot/device_authentication.py`

```python
def valid_device_key(request):
    expected = getattr(settings, "IOT_DEVICE_API_KEY", "").strip()
    presented = request.headers.get("X-GoHMotech-Device-Key", "").strip()
    if not expected or not presented:
        return False
    return secrets.compare_digest(expected, presented)
```

File: `iot/serializers.py`

```python
def create(self, validated_data):
    device_id = validated_data.pop('device_id', None)
    device_name = validated_data.pop('device_name', None)
    if validated_data.get('device') is None and device_id:
        device, created = Device.objects.get_or_create(
            device_id=device_id,
            defaults={'name': device_name or device_id,
                      'device_type': 'environmental_sensor', 'is_active': True}
        )
        validated_data['device'] = device
    return super().create(validated_data)
```

File: `iot/views.py`

```python
class SensorReadingViewSet(viewsets.ModelViewSet):
    def get_permissions(self):
        if self.action == 'create':
            return [HasLegacyDeviceKey()]
        return [FarmRolePermission()]

class ActuatorStateViewSet(viewsets.ModelViewSet):
    def get_permissions(self):
        if self.action in ['esp32_commands', 'esp32_sync_state']:
            return [HasLegacyDeviceKey()]
        return super().get_permissions()
```

File: `esp32 autofeeder/kamotech_esp32_door_light_ldr/kamotech_esp32_door_light_ldr.ino`

```cpp
WiFiClientSecure secureClient;

bool beginServerRequest(HTTPClient& http, const String& url) {
  if (!ensureClockReady()) return false;
  secureClient.setCACert(GOHMOTECH_ROOT_CA);
  secureClient.setHandshakeTimeout(8);
  return http.begin(secureClient, url);
}

void addDeviceHeaders(HTTPClient& http) {
  http.addHeader("X-GoHMotech-Device-Key", DEVICE_API_KEY);
}
```

### 5. Code Explanation

The sensor serializer performs device registration on first valid upload. Device status is not a separate heartbeat: the backend treats the latest `SensorReading`/legacy `SensorData` timestamp as last-seen. Commands are stored as desired state because the firmware polls; the main manual API truthfully returns `sent` or `queued`, not physical success. `esp32_sync_state` can record device-originated changes, although the current door/light sketch does not call it.

### 6. Database Tables / Models

- `Device`: stable `device_id`, display name/type/location, active flag.
- `SensorReading`: temperature, humidity, rain, light, MQ-135, feeder distance, timestamp.
- `ActuatorState`: desired state and manual/auto mode.
- `ActuationLog`: command source, result, actor, metadata, timestamp.

### 7. APIs / URLs

```text
POST /iot/api/sensor-readings/
GET  /iot/api/actuators/esp32_commands/?device_id=...
POST /iot/api/actuators/esp32_sync_state/
POST /iot/api/actuators/{id}/control/
```

### 8. Hardware Involved

ESP32 A (`gohmotech_esp32_002`) handles LDR, door relays, and light relay. ESP32 B (`kamotech_esp32_001`) handles DHT21, rain sensor, ultrasonic sensor, MQ-135, and feeder servo.

### 9. Security / Safety

The device key fails closed and is compared timing-safely. ESP32 A validates the server CA over HTTPS. ESP32 B sends the key over local HTTP, so anyone able to observe that network could capture it. Wi-Fi credentials are hardcoded in the current sketches and must not be shown during defense or committed to a public repository. Per-device revocable credentials are not yet implemented; devices share the compatibility key.

### 10. Defense Explanation

**What I can say during the defense:**

“The ESP32 does not connect directly to MySQL. It sends JSON through a protected Django REST endpoint, and Django validates a device key before storing the reading. For commands, the website changes a desired actuator state in the database, then the ESP32 polls that state every five seconds and controls the hardware. The main controller uses HTTPS and checks the server certificate. Online status is calculated from the newest sensor timestamp because the firmware does not provide a separate heartbeat.”

---

## 4. AUTOMATIC DOOR CONTROL

**STATUS: IMPLEMENTED**

### 1. Purpose

The door can be opened/closed manually or by schedules/sensor/AI rules. The main ESP32 drives two active-low relay inputs for actuator direction. Safety logic releases both relay channels before reversing and automatically stops the motor after ten seconds.

### 2. Files Involved

```text
iot/models.py
iot/views.py
iot/tasks.py
iot/ai_tasks.py
iot/templates/iot/automation_control.html
esp32 autofeeder/kamotech_esp32_door_light_ldr/kamotech_esp32_door_light_ldr.ino
```

### 3. System Flow

```text
Open/Close button → authenticated POST control API → ActuatorState desired state
→ ESP32 polls command → applyDoorCommand() → stop both relays → 150 ms dead time
→ energize IN2 for open or IN1 for close → 10 s safety timeout → both relays OFF
```

Automatic rules use the same `ActuatorState`, so manual and automatic commands share one hardware path.

### 4. Important Source Code

File: `iot/views.py`

```python
@action(detail=True, methods=['post'])
def control(self, request, pk=None):
    actuator = self.get_object()
    new_state = request.data.get('state')
    if new_state not in ['on', 'off', 'open', 'closed']:
        return Response({'error': 'Invalid state.'}, status=400)
    online = is_device_online(actuator.device)
    actuator.current_state = new_state
    actuator.mode = 'manual'
    actuator.last_triggered_by = request.user.get_username()
    actuator.save()
    result = 'sent' if online else 'queued'
```

File: `esp32 autofeeder/kamotech_esp32_door_light_ldr/kamotech_esp32_door_light_ldr.ino`

```cpp
#define DOOR_CLOSE_RELAY_PIN 26
#define DOOR_OPEN_RELAY_PIN 27
#define DOOR_MAX_RUN_TIME_MS 10000UL

void stopDoorMotor() {
  setRelay(DOOR_CLOSE_RELAY_PIN, false);
  setRelay(DOOR_OPEN_RELAY_PIN, false);
  doorMoving = false;
}

void startDoorMotor(bool opening) {
  stopDoorMotor();
  delay(150);
  setRelay(opening ? DOOR_OPEN_RELAY_PIN : DOOR_CLOSE_RELAY_PIN, true);
  doorMoving = true;
  doorStartedAt = millis();
}

if (doorMoving && now - doorStartedAt >= DOOR_MAX_RUN_TIME_MS) {
  stopDoorMotor();
}
```

File: `iot/tasks.py`

```python
state_map = {
    'open_door': 'open', 'close_door': 'closed',
    'turn_on_light': 'on', 'turn_off_light': 'off'
}
actuator_state, created = ActuatorState.objects.get_or_create(
    device=device, actuator_type=device_type,
    defaults={'current_state': new_state, 'mode': 'auto'}
)
```

### 5. Code Explanation

`lastDoorCommand` prevents the same persistent command from restarting the motor every poll. `stopDoorMotor()` is the electrical interlock. The AI task scheduled at 7:30 PM counts goats: it closes when all are present or holds the door open and creates a missing-goat alert. The database state is a desired state, not confirmation from a limit switch.

### 6. Database Tables / Models

`ActuatorState` stores `actuator_type='door'`, state, mode, actor and timestamp. `AutomationRule` stores time/sensor criteria. `ActuationLog` stores all requests. `MissingGoatAlert` records AI safety decisions.

### 7. APIs / URLs

```text
POST /iot/api/actuators/{id}/control/
GET  /iot/api/actuators/esp32_commands/?device_id=gohmotech_esp32_002
POST /iot/api/schedules/create/
POST /iot/api/rules/create/
```

### 8. Hardware Involved

ESP32; 4-channel active-low relay module; IN1/GPIO 26 closes; IN2/GPIO 27 opens; linear actuator/motor power circuit.

### 9. Security / Safety

Only admin/owner may issue control writes. Device polling requires the key. Both direction relays are released before a direction is energized; there is 150 ms dead time and a 10-second maximum run. Missing limitations: no door limit-switch input, obstacle sensor, current sensor, or hardware execution acknowledgement appears in the active sketch.

### 10. Defense Explanation

**What I can say during the defense:**

“When I press Open or Close, Django stores the requested state and records who issued it. The ESP32 polls for that command and uses two relays to reverse the linear actuator. Before changing direction, the code always turns both relays off and waits 150 milliseconds, so opening and closing cannot be energized together. It also stops the motor after ten seconds. The displayed state is the requested state because the current hardware has no limit-switch acknowledgement.”

---

## 5. AUTOMATIC LIGHTING SYSTEM

**STATUS: IMPLEMENTED**

### 1. Purpose

The lighting relay supports manual ON/OFF and server-side automatic rules based on time or LDR readings. The LDR is sampled and averaged on the main ESP32, calibrated to a percentage, uploaded to Django, and evaluated by Celery rules stored in the database.

### 2. Files Involved

```text
iot/models.py
iot/views.py
iot/tasks.py
iot/templates/iot/automation_control.html
esp32 autofeeder/kamotech_esp32_door_light_ldr/kamotech_esp32_door_light_ldr.ino
```

### 3. System Flow

```text
LDR GPIO 34 → averaged ADC + percentage → SensorReading
→ active light rule compares threshold → ActuatorState='on'/'off'
→ ESP32 command poll → GPIO 13 relay → lamp
```

### 4. Important Source Code

File: `esp32 autofeeder/kamotech_esp32_door_light_ldr/kamotech_esp32_door_light_ldr.ino`

```cpp
#define LDR_PIN 34
#define LIGHT_RELAY_PIN 13
#define LDR_DARK_ADC 3500
#define LDR_BRIGHT_ADC 300

void readLdr() {
  ldrRaw = readAveragedAdc(LDR_PIN);
  lightLevelPercentage = constrain(
    100.0f * (LDR_DARK_ADC - ldrRaw) / (LDR_DARK_ADC - LDR_BRIGHT_ADC),
    0.0f, 100.0f
  );
}

void setLight(bool on) {
  lightOn = on;
  setRelay(LIGHT_RELAY_PIN, on);
}
```

File: `iot/tasks.py`

```python
sensor_fields = {
    'temperature': 'temperature', 'humidity': 'humidity',
    'rain': 'rain_detected',
    'light_level_percentage': 'light_level_percentage',
    'light_raw': 'light_raw',
}
# criteria such as light_level_percentage < 20 are evaluated, then the
# corresponding light ActuatorState is written in mode='auto'.
```

### 5. Code Explanation

Manual control changes mode to `manual`. Celery's `check_and_execute_schedules()` and `check_and_execute_rules()` set mode to `auto`. The threshold is not hardcoded in Django; it is saved in `AutomationRule.criteria`, for example `{"light_level_percentage": "<20"}`. Firmware calibration endpoints (`LDR_DARK_ADC`, `LDR_BRIGHT_ADC`) must be measured for the installed voltage divider.

### 6. Database Tables / Models

`SensorReading.light_raw`, `light_level_percentage`; `ActuatorState` for current desired light state; `AutomationRule.criteria`; `ActuationLog`.

### 7. APIs / URLs

```text
POST /iot/api/sensor-readings/
POST /iot/api/actuators/{id}/control/
GET  /iot/api/actuators/esp32_commands/?device_id=gohmotech_esp32_002
POST /iot/api/rules/create/
```

### 8. Hardware Involved

ESP32 A, LDR/voltage divider on GPIO 34, relay IN3 on GPIO 13, lighting load.

### 9. Security / Safety

Owner/admin authorization protects control and rule changes. Device uploads/polls require the key. Active-low relay polarity is centralized in `setRelay()`, and startup writes inactive levels before configuring outputs to reduce relay chatter.

### 10. Defense Explanation

**What I can say during the defense:**

“The LDR is read through the ESP32 ADC and converted to a calibrated light percentage. That reading is sent to Django. In manual mode, the owner directly requests ON or OFF. In automatic mode, Celery compares the latest LDR value with a threshold stored in an automation rule, then writes the desired light state. The ESP32 receives it on the normal command poll and controls relay IN3.”

---

## 6. ENVIRONMENTAL MONITORING

**STATUS: IMPLEMENTED**

### 1. Purpose

The environment controller reads DHT21 temperature/humidity, a digital rain sensor, an ultrasonic feeder-distance sensor, and MQ-135 ADC voltage. It uploads one combined JSON reading every 30 seconds. Django stores the fields and supplies dashboard/history/report views; automation thresholds can consume these measurements.

### 2. Files Involved

```text
esp32 autofeeder/kamotech_esp32_environment_feeder/kamotech_esp32_environment_feeder.ino
iot/models.py
iot/serializers.py
iot/views.py
iot/tasks.py
iot/templates/iot/monitoring_dashboard.html
analytics/report_data.py
```

### 3. System Flow

```text
DHT21/Rain/Ultrasonic/MQ-135 → ESP32 read every 10 s
→ combined JSON every 30 s → authenticated POST
→ SensorReading row → dashboard/history/report
→ optional sensor automation rule → actuator desired state
```

### 4. Important Source Code

File: `esp32 autofeeder/kamotech_esp32_environment_feeder/kamotech_esp32_environment_feeder.ino`

```cpp
#define DHT_PIN 14
#define DHT_TYPE DHT21
#define RAIN_SENSOR_PIN 17
#define ULTRASONIC_TRIG_PIN 18
#define ULTRASONIC_ECHO_PIN 19
#define MQ135_PIN 35
#define SENSOR_READ_INTERVAL_MS 10000UL
#define SENSOR_SEND_INTERVAL_MS 30000UL

void readSensors() {
  temperatureC = dht.readTemperature();
  humidityPercent = dht.readHumidity();
  raining = digitalRead(RAIN_SENSOR_PIN) == LOW;
  feederDistanceCm = readUltrasonicDistance();
  airQualityRaw = readAveragedAdc(MQ135_PIN);
  airQualityVoltage = airQualityRaw / 4095.0f * 3.3f;
}
```

File: `iot/models.py`

```python
class SensorReading(models.Model):
    temperature = models.FloatField(null=True, blank=True)
    humidity = models.FloatField(null=True, blank=True)
    light_raw = models.PositiveSmallIntegerField(null=True, blank=True)
    light_level_percentage = models.FloatField(null=True, blank=True)
    air_quality_raw = models.PositiveSmallIntegerField(null=True, blank=True)
    air_quality_voltage = models.FloatField(null=True, blank=True)
    air_quality_ppm = models.FloatField(null=True, blank=True)
    air_quality_calibrated = models.BooleanField(default=False)
    rain_detected = models.BooleanField(null=True, blank=True, default=False)
    feeder_level = models.FloatField(null=True, blank=True)
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
```

### 5. Code Explanation

The sketch keeps the last valid DHT values when a read returns NaN. The MQ-135 posts raw ADC and voltage; PPM is only sent when `MQ135_R0_KOHMS > 0`, and the current value is `0.0`, so the UI must treat PPM as uncalibrated. Environmental warning generation is not a direct step in `SensorReadingViewSet.create`; thresholds are presently used mainly through automation rules and feeding logic.

### 6. Database Tables / Models

`Device` identifies the controller. `SensorReading` stores the combined snapshot. `AutomationRule` stores threshold expressions. `Alert` stores anomalies created by other paths; it is not automatically created for every sensor threshold in this POST view.

### 7. APIs / URLs

```text
POST /iot/api/sensor-readings/
GET  /iot/api/sensor-readings/latest/
GET  /iot/api/sensor-readings/device_history/?device_id=...&hours=24
GET  /iot/monitoring/
GET  /analytics/environmental/
```

### 8. Hardware Involved

DHT21 GPIO 14; rain digital input GPIO 17; ultrasonic TRIG 18/ECHO 19; MQ-135 ADC GPIO 35; environment ESP32.

### 9. Security / Safety

Device key authentication protects writes and farm RBAC protects reads. Serializer ranges constrain ADC and percentage data. The controller is local HTTP, so transport confidentiality is incomplete. MQ-135 input must remain at or below the ESP32's 3.3 V ADC limit.

### 10. Defense Explanation

**What I can say during the defense:**

“One ESP32 reads all environmental sensors every ten seconds and uploads a combined JSON snapshot every thirty seconds. Django validates the device key, links the reading to the controller, and stores each sensor field with a timestamp. The dashboard and reports query those rows. The MQ-135 currently reports trustworthy raw ADC and voltage values, while PPM remains disabled until the installed sensor is calibrated.”

---

## 7. AUTOMATED FEEDING SYSTEM

**STATUS: PARTIALLY IMPLEMENTED**

### 1. Purpose

The current hardware path can receive a feeder actuator command, open a servo for two seconds, close it, and sync OFF. Models and APIs support schedules, manual pending logs, feed levels, and duplicate-prevention windows. However, automated feeding is not fully consistent: one scheduled Celery path writes obsolete `FeedLog` field names, the legacy task logs success without sending hardware, and the ML/environment decision engine still has a TODO instead of an actuator command.

### 2. Files Involved

```text
feeding/models.py
feeding/views.py
feeding/tasks.py
feeding/automated_feeding.py
iot/tasks.py
iot/models.py
iot/templates/iot/automation_control.html
esp32 autofeeder/kamotech_esp32_environment_feeder/kamotech_esp32_environment_feeder.ino
```

### 3. System Flow

Working actuator path:

```text
Owner feeder command / actuator state ON → ESP32 B polls every 5 s
→ command changed? → servo 0° to 180° → wait 2 s without blocking loop
→ servo back to 0° → POST feeder OFF sync
```

Incomplete scheduled/intelligent path:

```text
Celery schedule/decision → creates log or attempts actuator update
→ inconsistent FeedLog fields or TODO hardware send
→ not reliable end-to-end for every automatic mode
```

### 4. Important Source Code

File: `esp32 autofeeder/kamotech_esp32_environment_feeder/kamotech_esp32_environment_feeder.ino`

```cpp
#define SERVO_PIN 25
#define FEED_DURATION_MS 2000UL
#define SERVO_CLOSED_ANGLE 0
#define SERVO_OPEN_ANGLE 180

void startFeeding() {
  if (feeding) return;
  feederServo.write(SERVO_OPEN_ANGLE);
  feeding = true;
  feedingStartedAt = millis();
}

void updateFeeding(unsigned long now) {
  if (!feeding || now - feedingStartedAt < FEED_DURATION_MS) return;
  feederServo.write(SERVO_CLOSED_ANGLE);
  feeding = false;
  syncFeederOff();
}
```

File: `feeding/views.py`

```python
@action(detail=False, methods=['post'])
def manual_feed(self, request):
    feed_log = FeedLog.objects.create(
        feeder=feeder,
        amount_dispensed=amount,
        scheduled=False,
        feeding_mode='manual',
        trigger_reason='manual_override',
        status='pending'
    )
```

File: `feeding/automated_feeding.py`

```python
def _send_feeder_command(self, feeder_device, amount_grams):
    """Send command to physical feeder via MQTT
    TODO: Implement MQTT publishing
    """
    pass
```

File: `iot/tasks.py`

```python
# Current defect in execute_scheduled_feeding(): FeedLog has
# amount_dispensed/timestamp, but this task uses obsolete names.
FeedLog.objects.create(
    feeder=feeder,
    amount_grams=schedule.amount_grams,
    schedule=schedule,
    fed_at=now
)
```

### 5. Code Explanation

`feeding` prevents repeat servo activation using both `feeding` and `lastFeederCommand`. `manual_feed()` prevents the same pending log from being returned after 60 seconds and confirmation endpoints can mark it successful. `check_feeding_schedules()` also dispatches by minute, but its `execute_feeding()` contains a TODO MQTT line and records success without hardware proof. These are why the status is partial.

### 6. Database Tables / Models

- `AutomatedFeedingConfig`: global enable toggle.
- `FeedSchedule`: time, days, grams, feeder, active flag.
- `FeedLevel`: grams/capacity/threshold plus ultrasonic distance/percentage.
- `FeedLog`: amount, mode, trigger, environmental/ML snapshot, status.
- `ActuatorState(actuator_type='feeder')`: actual command-polled path.

### 7. APIs / URLs

```text
POST /feeding/api/logs/manual_feed/
GET  /feeding/api/logs/esp32_pending/?feeder_id=...
POST /feeding/api/logs/{id}/confirm_executed/
GET  /feeding/api/logs/servo-commands/?feeder_id=...
POST /feeding/api/logs/servo-confirm/
POST /feeding/api/levels/update/
GET  /iot/api/actuators/esp32_commands/?device_id=kamotech_esp32_001
```

### 8. Hardware Involved

ESP32 B; servo on GPIO 25; ultrasonic TRIG 18/ECHO 19; feed container/dispenser.

### 9. Security / Safety

Device endpoints require the key, owner/admin controls require farm write permission, servo activation is non-reentrant, and it closes after two seconds. Feed grams are estimated/logged rather than measured at the outlet. Scheduled duplication is checked by time/log windows in some paths but is not unified across the two scheduling implementations.

### 10. Defense Explanation

**What I can say during the defense:**

“The physical feeder command path works by setting a feeder actuator state. The ESP32 sees the new ON command, opens the servo for two seconds, closes it, and synchronizes OFF. The system also has feed schedules, levels, and logs. I classify the whole automated feeding feature as partial because the project currently has two scheduling implementations: one does not send hardware and another uses old field names. The environment/ML decision engine also records a decision but its hardware-send function is still a TODO.”

---

## 8. GOAT INVENTORY MANAGEMENT

**STATUS: IMPLEMENTED**

### 1. Purpose

Farm owners can add and edit goat identity, physical, health, vaccination, status, weight, tracker, and image data. Goats are archived operationally using status and `is_active` rather than being routinely deleted. Standard front, left, right, rear, and optional face images are validated and stored by angle.

### 2. Files Involved

```text
iot/goat_models.py
iot/forms.py
iot/goat_photos.py
iot/views.py
iot/goat_views.py
iot/urls.py
iot/templates/iot/add_goat.html
iot/templates/iot/goat_inventory.html
iot/templates/iot/goat_detail_enhanced.html
static/js/goat-photo-capture.js
```

### 3. System Flow

```text
Owner submits GoatForm + optional BLE form + angle photos
→ Django validates all fields/photos first
→ atomic Goat creation/update
→ one GoatImage per standard angle
→ media storage path goat_images/YYYY/MM/DD
→ inventory/detail pages query profile, gallery and history
```

### 4. Important Source Code

File: `iot/goat_models.py`

```python
class Goat(models.Model):
    goat_id = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=100, blank=True)
    tag_number = models.CharField(max_length=50, blank=True)
    breed = models.CharField(max_length=50, choices=BREED_CHOICES)
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES)
    date_of_birth = models.DateField(null=True, blank=True)
    weight_kg = models.FloatField(null=True, blank=True,
                                  validators=[MinValueValidator(0)])
    health_status = models.CharField(max_length=20,
                                     choices=HEALTH_STATUS_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES,
                              default='active', db_index=True)
    is_active = models.BooleanField(default=True)
```

File: `iot/goat_models.py`

```python
class GoatImage(models.Model):
    FRONT, LEFT, RIGHT, REAR, FACE = 'front', 'left', 'right', 'rear', 'face'
    ANGLE_CHOICES = [
        (FRONT, 'Front View'), (LEFT, 'Left Side View'),
        (RIGHT, 'Right Side View'), (REAR, 'Rear View'),
        (FACE, 'Face Close-up'),
    ]
    goat = models.ForeignKey(Goat, on_delete=models.CASCADE,
                              related_name='images')
    image = models.ImageField(upload_to='goat_images/%Y/%m/%d/')
    angle = models.CharField(max_length=10, choices=ANGLE_CHOICES,
                             null=True, blank=True, db_index=True)
```

File: `iot/goat_photos.py`

```python
MAX_GOAT_IMAGE_BYTES = 5 * 1024 * 1024
MIN_GOAT_IMAGE_WIDTH = 480
MIN_GOAT_IMAGE_HEIGHT = 360

def validated_goat_image(upload, *, check_quality=False):
    if not upload or upload.size > MAX_GOAT_IMAGE_BYTES:
        raise ValidationError('Goat photos must be 5 MB or smaller.')
    if upload.content_type not in {'image/jpeg', 'image/png', 'image/webp'}:
        raise ValidationError('Upload a valid JPG, PNG, or WebP image.')
    # Pillow verifies content, dimensions, brightness and blur before optimization.
```

### 5. Code Explanation

`GoatForm` maps presentation fields such as “Sex” to the model's `gender`. `prepared_standard_photos()` validates every submitted angle before changing the goat. `save_standard_photo()` uses a transaction and replaces the existing photo for the same angle, preventing duplicates. `update_goat_status()` supports active/sold/dead/missing and resolves linked missing alerts when a goat returns to active.

### 6. Database Tables / Models

`Goat` is the profile; `GoatImage` stores gallery/angle media; `GoatWeightMeasurement` stores history; `BLEBeacon` assigns a tracker; `GoatOwnership` migrations support farm ownership history.

### 7. APIs / URLs

```text
GET/POST /iot/goats/add/
GET      /iot/inventory/
GET/POST /iot/inventory/{goat_id}/
POST     /iot/inventory/{goat_id}/upload-image/
POST     /iot/inventory/{goat_id}/update-status/
POST     /iot/inventory/{goat_id}/image/{image_id}/delete/
```

### 8. Hardware Involved

Optional browser/device camera for reference photos; optional BLE beacon assignment. Inventory itself is a Django/database feature.

### 9. Security / Safety

All inventory reads require farm access; writes require owner/admin. File type, decoded image content, dimensions, size, brightness, and blur are validated. Community marketplace goats require an owner and remain separated by `record_source`.

### 10. Defense Explanation

**What I can say during the defense:**

“A goat is registered manually with a unique goat ID and its breed, sex, birth date, weight, health, vaccination, and notes. Images are stored in a separate table so one goat can have several views. My upload helper verifies that the file is a real image, limits its size and resolution, and checks photo quality. Standard angles are unique per goat, so replacing the left photo does not create duplicate left views. Removal is normally handled through inventory status so the history is preserved.”

---

## 9. GOAT WEIGHT MONITORING

**STATUS: PARTIALLY IMPLEMENTED**

### 1. Purpose

A dedicated scale ESP32 reads an HX711/load-cell platform, applies tare/calibration, filters near-zero values, calculates stability across ten samples, and posts a transient snapshot. The farmer explicitly selects a goat and saves only a stable reading, creating history and updating the goat's current weight. The current firmware upload is incompatible with the protected endpoint because it does not send `X-GoHMotech-Device-Key`, and it uses plain HTTP.

### 2. Files Involved

```text
esp32 load cell/kamotech_load_cell_esp32/kamotech_load_cell_esp32.ino
iot/goat_views.py
iot/goat_models.py
iot/urls.py
iot/templates/iot/goat_detail_enhanced.html
iot/test_weight_integration.py
```

### 3. System Flow

```text
Four load cells → HX711 → ESP32 continuous samples
→ zero deadband + ten-sample variation test
→ POST transient scale state → Django cache (15 s)
→ selected goat page polls live state
→ owner presses Save → validation + idempotency UUID
→ GoatWeightMeasurement + Goat.weight_kg updated atomically
```

The POST currently receives 403 until the firmware adds the required device-key header.

### 4. Important Source Code

File: `esp32 load cell/kamotech_load_cell_esp32/kamotech_load_cell_esp32.ino`

```cpp
#define HX711_DOUT_PIN 19
#define HX711_SCK_PIN 18
const float HX711_CALIBRATION_FACTOR = 696.0f;
const float SCALE_ZERO_DEADBAND_KG = 0.10f;
const float SCALE_STABILITY_TOLERANCE_KG = 0.15f;
const int SCALE_STABILITY_SAMPLE_COUNT = 10;

loadCell.begin();
loadCell.start(SCALE_STABILIZING_TIME_MS, true); // tare at startup
loadCell.setCalFactor(HX711_CALIBRATION_FACTOR);

variationKg = maximumWeight - minimumWeight;
weightStable = variationKg <= SCALE_STABILITY_TOLERANCE_KG;
```

File: `iot/goat_views.py`

```python
@csrf_exempt
@device_key_required
@require_POST
def scale_reading_ingest(request):
    # validates the fixed device ID and sensor values
    cache.set(_scale_cache_key(device_id), snapshot,
              SCALE_CACHE_TTL_SECONDS)
    return JsonResponse({'ok': True}, status=202)

@farm_owner_required
@require_POST
def save_goat_weight(request, goat_id):
    if source == GoatWeightMeasurement.SOURCE_LOAD_CELL:
        scale = _current_scale_state()
        if not scale.get('connected') or not scale.get('stable'):
            return JsonResponse({'ok': False,
                'error': 'Wait until the weight is stable before saving.'}, status=409)
    with transaction.atomic():
        measurement = GoatWeightMeasurement.objects.create(...)
        goat.weight_kg = float(weight_kg)
        goat.save(update_fields=['weight_kg', 'last_updated'])
```

### 5. Code Explanation

The ESP32 never chooses the goat, preventing accidental association. The latest scale state is cache-only and expires after 15 seconds; the page treats it offline after five seconds. A unique `request_id` makes repeated Save requests idempotent. `HX711_CALIBRATION_FACTOR = 696.0` is explicitly a value to verify against the completed platform, not proof of final physical calibration.

### 6. Database Tables / Models

`GoatWeightMeasurement`: goat, decimal kilograms, load-cell/manual source, measured/recorded timestamps, user, device ID, unique request ID. `Goat.weight_kg` is the current summary value.

### 7. APIs / URLs

```text
POST /iot/api/scale/readings/
GET  /iot/inventory/{goat_id}/weight/live/
POST /iot/inventory/{goat_id}/weight/save/
```

### 8. Hardware Involved

Dedicated ESP32; HX711 DOUT GPIO 19/SCK GPIO 18; four load cells/platform; status LED GPIO 2.

### 9. Security / Safety

The server requires a device key and owner confirmation, bounds weight to 0.10–300.00 kg, requires a live valid stable reading, and prevents duplicate saves. The firmware must be fixed to add the key header and should move from local HTTP to HTTPS before this can be called fully connected.

### 10. Defense Explanation

**What I can say during the defense:**

“The HX711 library continuously samples the load cells. The firmware tares on startup, applies a calibration factor, ignores near-zero readings, and considers weight stable only when ten samples vary by no more than 0.15 kilograms. Django keeps this live value temporarily; it does not automatically assign it to a goat. The farmer selects the goat and confirms Save, which creates a history row and updates current weight atomically. The remaining integration issue is that the current scale sketch must add the device authentication header required by Django.”

---

## 10. BLE/IBEACON GOAT TRACKING

**STATUS: IMPLEMENTED**

### 1. Purpose

A Raspberry Pi/Linux scanner listens for BLE advertisements without pairing, authenticates as a provisioned receiver, and posts iBeacon identity plus RSSI. Django associates the beacon with a goat, smooths/classifies signal strength, tracks receiver freshness, stores throttled history, and drives list/radar/find interfaces. It estimates proximity only—not GPS coordinates, direction, or exact distance.

### 2. Files Involved

```text
ble_scanner.py
ble_scanner.env.example
iot/ble_authentication.py
iot/ble_api.py
iot/ble_services.py
iot/ble_views.py
iot/goat_models.py
iot/templates/iot/ble_tracking_dashboard.html
goh-mo-tech-app/src/pages/TrackingPage.vue
```

### 3. System Flow

```text
Goat iBeacon advertisement → Raspberry Pi Bluetooth scan
→ rolling RSSI + receiver API key → heartbeat/observation APIs
→ match UUID+major+minor (or registered MAC)
→ BLETrackingState + throttled BLEObservation
→ status aging: detected → possibly lost → out of range
→ web radar/find page and Ionic proximity list
```

### 4. Important Source Code

File: `iot/ble_services.py`

```python
def classify_proximity(smoothed_rssi, config):
    if smoothed_rssi >= config.very_near_min_rssi:
        return 'very_near'
    if smoothed_rssi >= config.near_min_rssi:
        return 'near'
    if smoothed_rssi >= config.medium_min_rssi:
        return 'medium'
    return 'far'

def refresh_tracking_statuses(now=None):
    # ages records using possibly_lost_timeout_seconds and
    # out_of_range_timeout_seconds, and ages receivers offline.
```

File: `iot/goat_models.py`

```python
class BLEReceiver(models.Model):
    api_key_hash = models.CharField(max_length=128, blank=True, editable=False)
    def set_api_key(self, raw_api_key):
        self.api_key_hash = make_password(raw_api_key)
    def check_api_key(self, raw_api_key):
        return check_password(raw_api_key, self.api_key_hash)
```

File: `iot/ble_services.py`

```python
state.current_rssi = observation['rssi']
state.smoothed_rssi = smoothed_rssi
state.proximity = classify_proximity(smoothed_rssi, config)
state.status = 'detected'
state.last_seen = received_at
state.sample_count += 1
```

### 5. Code Explanation

Complete iBeacon identity is preferred over MAC because some platforms randomize addresses. A mismatch between identity and MAC is rejected. Raw credentials are never stored—only Django password hashes. History is written only after a configured interval or proximity change to avoid one database row per advertisement. The radar places markers in signal bands; its angle is visual distribution, not measured direction.

### 6. Database Tables / Models

`BLEBeacon` associates UUID/major/minor/MAC to one goat. `BLEReceiver` identifies the scanning gateway. `BLETrackingState` is the latest state per beacon/receiver. `BLEObservation` is history. `BLETrackingSettings` contains smoothing, RSSI bands, timeouts and retention.

### 7. APIs / URLs

```text
POST /iot/api/ble/heartbeat/
POST /iot/api/ble/observations/
GET  /iot/api/ble/tracking/
GET  /iot/tracking/
GET  /iot/tracking/find/{goat_id}/
GET  /api/mobile/tracking/
```

### 8. Hardware Involved

DX-CP101-compatible iBeacon on each goat; Raspberry Pi 5 Bluetooth adapter/receiver. No pairing or GPS module is used.

### 9. Security / Safety

Each receiver has a separate hashed API key; observation identity conflicts are rejected; server receipt time prevents scanner clock drift; farm login protects viewing. RSSI is deliberately labelled approximate.

### 10. Defense Explanation

**What I can say during the defense:**

“Each goat can be assigned an iBeacon identified by UUID, major, and minor. The Raspberry Pi scans advertisements without pairing and sends the signal strength to Django using its own receiver credential. Django smooths RSSI and classifies it as very near, near, medium, or far. If updates stop, the state changes to possibly lost and then out of range. This is proximity tracking around a receiver, not GPS location or exact meters.”

---

## 11. IP/RTSP CAMERA MONITORING

**STATUS: IMPLEMENTED**

### 1. Purpose

The Raspberry Pi/Django process opens configured RTSP or HTTP streams with OpenCV/FFmpeg, continuously drains the source in a background thread, keeps the latest frame, reconnects after failures, and exposes browser-compatible MJPEG. Camera status and errors are persisted without exposing stream credentials.

### 2. Files Involved

```text
iot/goat_models.py
iot/camera_utils.py
iot/views.py
iot/urls.py
iot/templates/iot/camera_detail.html
static/js/live-camera.js
mobile_api/views.py
goh-mo-tech-app/src/services/camera.service.ts
goh-mo-tech-app/src/pages/LivePage.vue
```

### 3. System Flow

```text
IP camera RTSP/HTTP + credentials → Raspberry Pi OpenCV/FFmpeg capture thread
→ newest in-memory frame + reconnect/status logic
→ Django StreamingHttpResponse multipart JPEG
→ Nginx/Cloudflare public HTTPS
→ browser <img> or Ionic ticketed stream
```

### 4. Important Source Code

File: `iot/camera_utils.py`

```python
self.capture = cv2.VideoCapture(
    self.stream_url, cv2.CAP_FFMPEG,
    [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 8000,
     cv2.CAP_PROP_READ_TIMEOUT_MSEC, 8000]
)
self.capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)

grabbed = self.capture.grab()
ret, frame = self.capture.retrieve() if grabbed else (False, None)
if ret and frame is not None:
    self._publish_frame(frame)
elif time.time() - self.last_frame_time > self.frame_timeout:
    self.capture.release()
    self.capture = None  # reconnect loop
```

File: `iot/views.py`

```python
@farm_access_required
def camera_feed(request, camera_id):
    # validates quality/fps/width, gets the shared CameraStream and returns
    # StreamingHttpResponse(generate_mjpeg_stream(...),
    #                       content_type='multipart/x-mixed-replace; boundary=frame')
```

### 5. Code Explanation

`CameraStreamManager` shares one upstream camera capture among viewers. `get_jpeg_packet()` caches the encoded JPEG per source frame/quality, avoiding repeated encoding. Delivery FPS and width are bounded per request. MAC-based IP resolution can update a DHCP-changed camera host. The mobile API exchanges the bearer token for a 60-second signed camera ticket so the token is not placed in the image URL.

### 6. Database Tables / Models

`IPCamera`: ID, type, MAC/IP/port, username/password, stream URLs, location, status, last connection/error, detection settings.

### 7. APIs / URLs

```text
GET  /iot/camera/feed/{camera_id}/
GET  /iot/camera/snapshot/{camera_id}/
POST /iot/api/camera/start/{camera_id}/
POST /iot/api/camera/stop/{camera_id}/
GET  /iot/api/camera/status/{camera_id}/
GET  /api/mobile/cameras/
GET  /api/mobile/cameras/{camera_id}/stream/?ticket=...
```

### 8. Hardware Involved

Network IP camera supporting RTSP or HTTP/MJPEG; Raspberry Pi 5 network interface and CPU for decoding/encoding.

### 9. Security / Safety

All streams require farm access or a short-lived signed mobile ticket. Logs use `describe_stream_url()` so credentials/query values are not logged. The public endpoint is HTTPS through the reverse proxy. Important design risk: `IPCamera.password` is a normal database string, not field-level encrypted.

### 10. Defense Explanation

**What I can say during the defense:**

“The browser cannot normally play RTSP directly, so the Raspberry Pi opens the RTSP stream through OpenCV and FFmpeg. A background thread continuously keeps only the latest frame to reduce delay. Django converts that frame to JPEG and sends an MJPEG stream that browsers and the Ionic app can display over HTTPS. If frames stop, the capture is closed, camera status becomes offline/error, and the reconnect loop tries again.”

---

## 12. AI / ML GOAT DETECTION

**STATUS: IMPLEMENTED**

### 1. Purpose

The active implementation loads an Ultralytics YOLOv8 `.pt` model, receives camera frames or uploads, runs inference, extracts confidence and boxes, optionally performs goat re-identification, and stores detection history. ONNX files are allowed by the upload validator but no ONNX inference class is implemented; the repository's active weights are `.pt` files. Live page detection is on-demand while that page is open, not an always-on service.

### 2. Files Involved

```text
ml_models/models.py
ml_models/ml_utils.py
ml_models/views.py
ml_models/feature_extraction.py
ml_models/reid_service.py
ml_models/urls.py
ml_models/templates/ml_models/detection_feed.html
ml_models/weights/goat_yolov8n_best.pt
iot/ai_tasks.py
```

### 3. System Flow

```text
MJPEG frame drawn to browser canvas → JPEG POST /ml/api/detect/
→ active goat MLModel → YOLOv8Detector.detect(image)
→ bounding boxes/confidence/count → optional re-identification
→ Detection + GoatDetectionHistory → JSON response
→ UI count/history; security person model runs separately if active
```

### 4. Important Source Code

File: `ml_models/ml_utils.py`

```python
class YOLOv8Detector(BaseDetector):
    def __init__(self, model_path, confidence_threshold=0.5,
                 use_gpu=False, **_unused):
        from ultralytics import YOLO
        self.model = YOLO(model_path)
        self.device = 'cuda' if use_gpu and torch.cuda.is_available() else 'cpu'

    def detect(self, image):
        results = self.model.predict(
            image, conf=self.confidence_threshold,
            device=self.device, verbose=False
        )
        # boxes.xyxy, boxes.conf and boxes.cls become bbox dictionaries
```

File: `ml_models/views.py`

```python
@api_view(['POST'])
@api_permission_classes([IsFarmOwnerOrAdmin])
def detect_goats_api(request):
    image = cv2.imdecode(
        np.frombuffer(request.FILES['image'].read(), np.uint8),
        cv2.IMREAD_COLOR
    )
    detector = get_active_detector()
    result = detect_and_identify_goats(image=image, detector=detector,
                                       camera=ip_camera,
                                       enable_reid=enable_reid)
    Detection.objects.create(
        model=active_model, camera=device,
        goat_count=result['detection_count'],
        confidence=result['confidence'],
        bounding_boxes=result['detections'], processed=True
    )
```

File: `ml_models/templates/ml_models/detection_feed.html`

```javascript
ctx.drawImage(feedImg, 0, 0, canvas.width, canvas.height);
canvas.toBlob(function(blob) {
    const formData = new FormData();
    formData.append('image', blob, 'camera_frame.jpg');
    fetch('/ml/api/detect/', { method: 'POST', body: formData,
                               headers: {'X-CSRFToken': getCsrfToken()} });
}, 'image/jpeg', 0.85);
```

### 5. Code Explanation

The ML part is model loading plus `predict()` and box/confidence extraction. Normal application logic validates the request, selects the active model, resolves camera records, saves rows, and returns JSON. Camera processing captures/decodes frames. Re-identification is a separate feature-extraction/similarity layer and does not automatically register new goats in the current inventory workflow.

### 6. Database Tables / Models

`MLModel` stores category/type/version/private file/status. `Detection` stores per-frame count/confidence/boxes. `GoatDetectionHistory` stores individual boxes, confidence, optional embedding/match and crop.

### 7. APIs / URLs

```text
POST /ml/api/detect/
GET  /ml/api/detections/recent/?hours=24
GET  /ml/api/detections/stats/?hours=24
GET  /ml/detection/
GET  /ml/detection/history/
```

### 8. Hardware Involved

IP camera; Raspberry Pi CPU (or configured GPU where available). No ESP32 is involved in inference.

### 9. Security / Safety

Detection calls require owner/admin; model writes are staff-only; uploaded weights are stored outside public media and validated before activation. Errors return a generic client message. Closing the live detection page stops its periodic inference; server-side `start_realtime_detection` exists as a task but is not scheduled as the default continuous path.

### 10. Defense Explanation

**What I can say during the defense:**

“The machine-learning component is a YOLOv8 PyTorch model loaded through Ultralytics. The live page captures the latest camera frame and sends it to Django, where the model returns boxes, class labels, confidence, and a goat count. Django stores the result as detection history and sends it back to the page. Camera decoding and database storage are normal application logic; only the model inference and optional feature matching are ML. ONNX is not the active implementation in this project.”

---

## 13. SECURITY / PERSON DETECTION

**STATUS: IMPLEMENTED**

### 1. Purpose

When a separate active `person` model exists, the same submitted camera frame also runs through that detector. Person boxes above the configured threshold become a `PersonDetection`, snapshot, linked notification, WebSocket event, and optional SMS. It detects a person but does not perform face recognition or identify an individual.

### 2. Files Involved

```text
ml_models/views.py
security/models.py
security/services.py
security/views.py
security/urls.py
templates/security/security_dashboard.html
templates/security/person_detection_detail.html
```

### 3. System Flow

```text
Camera frame → active person-category detector → person boxes ≥ threshold
→ record_person_detection() cooldown/dedup
→ PersonDetection + JPEG snapshot
→ Notification linked to event
→ WebSocket alerts group + conditional SMS task
→ Security dashboard/mobile security list
```

### 4. Important Source Code

File: `ml_models/views.py`

```python
person_detector = get_active_detector('person')
if person_detector is not None:
    pres = person_detector.detect(image)
    persons = _extract_persons(person_detector, pres)
    persons = [p for p in persons
               if p.get('confidence', 0) >= settings.PERSON_CONFIDENCE_THRESHOLD]
    if persons:
        person_det, created = record_person_detection(
            camera=ip_camera,
            confidence=max(p['confidence'] for p in persons),
            bounding_boxes=persons,
            snapshot_bytes=jpg.tobytes(),
            detection_type='person',
        )
```

File: `security/services.py`

```python
recent_qs = PersonDetection.objects.filter(
    detection_type=detection_type, status='new',
    review_state='unreviewed', detected_at__gte=window_start,
)
if recent is not None:
    recent.confidence = confidence
    recent.bounding_boxes = bounding_boxes
    recent.detected_at = now
    recent.save(...)
    notify_person_detection(recent, broadcast=False)
else:
    detection.save()
    notify_person_detection(detection, broadcast=True)
```

### 5. Code Explanation

`_extract_persons()` keeps the `person` class from a multi-class model or all boxes from a dedicated one-class model. The default 30-second cooldown folds repeated live frames from the same camera into one open event to prevent alert spam. Review state and resolution remain auditable.

### 6. Database Tables / Models

`PersonDetection`: camera/source, type, snapshot, confidence, boxes, status, review fields, notification FK, detected time. `Notification` is the unified user-facing alert row.

### 7. APIs / URLs

```text
POST /ml/api/detect/                 (person detection is additive)
GET  /security/
GET  /security/api/detections/
POST /security/api/detections/{id}/review/
GET  /security/detections/{id}/
```

### 8. Hardware Involved

IP camera and Raspberry Pi inference server.

### 9. Security / Safety

Owner/admin permissions protect events and reviews; snapshots are accessed through authenticated pages/API paths; cooldown limits alert floods. No identity/face-recognition data is stored. The feature only runs when a validated active person model is configured.

### 10. Defense Explanation

**What I can say during the defense:**

“Person detection uses a separate model category from goat detection, so the two models can be active together. When a person box exceeds the confidence threshold, Django saves the event and snapshot, creates one linked alert, and broadcasts it. Repeated frames within the cooldown update the same event instead of generating many alerts. This is person-presence detection only; it does not recognize who the person is.”

---

## 14. NOTIFICATIONS AND ALERTS

**STATUS: PARTIALLY IMPLEMENTED**

### 1. Purpose

The unified inbox links user-facing notifications to source events such as device/sensor alerts, missing goats, and person detections. It supports WebSocket broadcast, read/unread, resolve/reopen, filtering and mobile display. Coverage is partial: notifications are global to farm managers rather than targeted per user, and there are no connected automatic notification creators specifically for camera-offline or door-problem events.

### 2. Files Involved

```text
security/models.py
security/services.py
security/signals.py
security/views.py
security/serializers.py
iot/models.py
iot/goat_models.py
iot/consumers.py
templates/base_modern.html
goh-mo-tech-app/src/pages/AlertsPage.vue
```

### 3. System Flow

```text
IoT Alert / MissingGoatAlert / PersonDetection saved
→ signal or service calls create_or_update_notification()
→ unique source relation prevents duplicates
→ alerts WebSocket group + optional SMS task
→ bell/mobile inbox
→ owner marks read or resolves
```

### 4. Important Source Code

File: `security/models.py`

```python
class Notification(models.Model):
    title = models.CharField(max_length=200)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES)
    notification_type = models.CharField(max_length=30, choices=TYPE_CHOICES)
    source_content_type = models.ForeignKey(ContentType, null=True,
                                             on_delete=models.CASCADE)
    source_object_id = models.PositiveIntegerField(null=True, blank=True)
    is_read = models.BooleanField(default=False, db_index=True)
    is_resolved = models.BooleanField(default=False, db_index=True)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=['source_content_type', 'source_object_id'],
            name='uniq_notification_per_source')]
```

File: `security/signals.py`

```python
@receiver(post_save, sender='iot.Alert')
def bridge_iot_alert(sender, instance, created, **kwargs):
    notification, _ = create_or_update_notification(
        title=instance.message.splitlines()[0][:120],
        description=instance.message,
        severity=instance.severity,
        notification_type='device_anomaly',
        source=instance.device.name,
        source_object=instance,
        broadcast=created,
    )
```

File: `security/views.py`

```python
@action(detail=True, methods=['post'])
def mark_read(self, request, pk=None):
    notification = self.get_object()
    notification.mark_read()
    return Response(self.get_serializer(notification).data)

@action(detail=True, methods=['post'])
def resolve(self, request, pk=None):
    notification = self.get_object()
    notification.resolve(user=request.user,
                         notes=request.data.get('resolution_notes', ''))
```

### 5. Code Explanation

The generic source relation lets one inbox point to different event tables. `get_or_create` plus the unique constraint prevents duplicate inbox rows for the same event. Source resolution is synchronized downward. Device-offline presentation is implemented elsewhere, but it does not currently create an `Alert`; feed-low uses `iot.Alert`, missing goats use `MissingGoatAlert`, and persons use `PersonDetection`.

### 6. Database Tables / Models

`security.Notification`, `iot.Alert`, `iot.MissingGoatAlert`, `security.PersonDetection`, and legacy `iot.NotificationLog` for the older multi-channel missing-goat service.

### 7. APIs / URLs

```text
GET  /security/api/notifications/
POST /security/api/notifications/{id}/mark_read/
POST /security/api/notifications/mark_all_read/
POST /security/api/notifications/{id}/resolve/
POST /security/api/notifications/{id}/reopen/
GET  /security/api/notifications/unread_count/
WS   /ws/alerts/
```

### 8. Hardware Involved

Indirect sources include ESP32 sensors/feeder, BLE/camera detection, and camera/person detection.

### 9. Security / Safety

Only owner/admin can use the notification REST API. WebSockets require a logged-in farm role or a short-lived mobile ticket and validate origins in production. Notifications are not recipient-scoped, so all authorized farm managers see the same farm inbox.

### 10. Defense Explanation

**What I can say during the defense:**

“My system keeps the original event in its domain table and creates one linked inbox notification. That means a person event, missing-goat event, or sensor alert can all appear consistently without duplicating the original data. The unique database constraint prevents two notifications for one event. Users can mark alerts read and resolve them, and new events can be pushed over WebSockets. The current limitation is that the farm inbox is shared rather than individually targeted, and camera-offline and door-fault alert creation are not yet wired.”

---

## 15. SMS NOTIFICATION SYSTEM

**STATUS: IMPLEMENTED**

### 1. Purpose

The SMS subsystem supports a safe console backend and live Semaphore v4 sending selected by environment configuration. It can send high-severity eligible alerts, a daily system summary, scheduled reminders, and test messages. Every attempt is normalized, logged, and protected by toggles, severity/type rules, and cooldowns.

### 2. Files Involved

```text
sms/models.py
sms/providers.py
sms/services.py
sms/tasks.py
sms/summaries.py
sms/views.py
sms/urls.py
config/settings.py
config/production.py
config/celery.py
security/services.py
```

### 3. System Flow

```text
New Notification → enqueue send_alert_sms(notification_id)
→ SmsSettings checks master switch/type/severity/cooldown
→ send_sms() normalizes recipient and creates pending SmsLog
→ SemaphoreSmsClient POSTs provider request
→ SmsLog becomes sent/failed with provider response

Celery Beat every minute → daily/reminder tasks self-check configured time/day
```

### 4. Important Source Code

File: `sms/providers.py`

```python
class SemaphoreSmsClient:
    def __init__(self):
        self.api_key = getattr(settings, 'SEMAPHORE_API_KEY', '<REDACTED>')
        self.sender_name = getattr(settings, 'SEMAPHORE_SENDER_NAME', '')
        self.api_url = getattr(settings, 'SEMAPHORE_API_URL',
                               'https://api.semaphore.co/api/v4/messages')

    def send(self, number, message):
        payload = {'apikey': '<REDACTED>',
                   'number': number, 'message': message}
        if self.sender_name:
            payload['sendername'] = self.sender_name
        resp = requests.post(self.api_url, data=payload, timeout=15)
```

File: `sms/models.py`

```python
def should_send_alert(self, notification_type, severity):
    if not (self.enabled and self.alerts_enabled):
        return False
    if notification_type not in (self.alert_types or []):
        return False
    weight = Notification.SEVERITY_WEIGHT
    return weight.get(severity, 0) >= weight.get(self.alert_min_severity, 0)
```

File: `sms/tasks.py`

```python
@shared_task
def send_alert_sms(notification_id):
    notification = Notification.objects.get(pk=notification_id)
    settings_obj = SmsSettings.get_config()
    if not settings_obj.should_send_alert(
            notification.notification_type, notification.severity):
        return "Alert not eligible for SMS"
    cache_key = f"sms_alert_cooldown:{notification.notification_type}"
    # shared-cache cooldown then send_sms(..., notification=notification)
```

### 5. Code Explanation

Secrets come from settings/environment, never the database or frontend. `normalize_ph_number()` accepts common Philippine formats and converts them to `09XXXXXXXXX`. `SmsLog` stores the recipient, message, type, provider, message ID, provider JSON, error and timestamps. The repository defaults production to `console`; live Semaphore is active only when `PRODUCTION_SMS_BACKEND=semaphore`, credentials exist, and the database master switch is enabled. Repository evidence cannot prove the private production environment currently selects it.

### 6. Database Tables / Models

`SmsSettings`, `SmsReminder`, `SmsRegistration`, `SmsLog`, plus the source `Notification`.

### 7. APIs / URLs

```text
GET/POST /sms/api/settings/
POST     /sms/api/test/
GET      /sms/api/balance/
GET      /sms/api/reminders/
GET      /sms/api/logs/
GET/POST /sms/registration/
```

### 8. Hardware Involved

No local GSM module. Django uses the external Semaphore HTTPS API to reach the recipient's mobile network.

### 9. Security / Safety

Semaphore keys/tokens stay in environment variables and are redacted here. Operational APIs are staff-only; user registrations are self-scoped. Provider calls have a timeout, failures are logged, and alert cooldown prevents repeated SMS bursts. The console backend avoids spending credits during development.

### 10. Defense Explanation

**What I can say during the defense:**

“All outgoing SMS passes through one service so every attempt is logged the same way. A new high-priority eligible notification queues a Celery task, which checks the SMS master switch, alert type, severity, and cooldown before calling Semaphore. Daily summaries and reminders are checked every minute but send only at their configured time. API keys are read from private environment variables and are never returned to the browser or stored in the SMS tables.”

---

## 16. REPORTS AND ANALYTICS

**STATUS: PARTIALLY IMPLEMENTED**

### 1. Purpose

The analytics module builds date-filtered operational reports and charts from the live Django models. Inventory, vaccination, health, feeding, door, lighting, environment, ML detection and marketplace reports are connected; weight-history and dedicated security-event reports are not present. CSV and XLSX exports are server-generated, while “PDF” uses the browser print dialog rather than a server PDF library.

### 2. Files Involved

```text
analytics/urls.py
analytics/views.py
analytics/report_data.py
analytics/exports.py
analytics/models.py
analytics/templates/analytics/report_detail.html
analytics/templates/analytics/report_print.html
```

### 3. System Flow

```text
User selects report and filters → analytics URL/view checks farm access
→ build_report() selects a report builder → ORM filters and aggregates rows
→ JSON/chart descriptor renders the table and Chart.js chart
→ optional CSV/XLSX response, or browser print-to-PDF
```

### 4. Important Source Code

File: `analytics/report_data.py`

```python
def build_report(report_type, get):
    if report_type == "inventory":
        return build_inventory(
            status=get.get("status", "all"),
            breed=get.get("breed", "all"),
            gender=get.get("gender", "all"),
            health=get.get("health", "all"),
            vaccination=get.get("vaccination", "all"),
            search=get.get("search", "").strip(),
        )
    if report_type == "vaccination":
        return build_vaccination(vaccination=get.get("vaccination", "all"))
    if report_type == "health":
        return build_health(health=get.get("health", "all"))
    if report_type == "feeder":
        return build_feeder(days=_int_days(get))
    if report_type == "door":
        return build_door(days=_int_days(get))
    if report_type == "lighting":
        return build_lighting(days=_int_days(get))
    if report_type == "environmental":
        return build_environmental(days=_int_days(get))
    if report_type == "detection":
        return build_detection(days=_int_days(get))
    if report_type == "marketplace":
        return build_marketplace(
            days=_int_days(get, default=30),
            status=get.get("status", "all"),
            search=get.get("search", "").strip(),
        )
    raise ValueError(f"Unknown report type: {report_type}")
```

File: `analytics/exports.py`

```python
def export_report(data, fmt):
    if fmt == "csv":
        return export_csv(data)
    if fmt == "xlsx":
        return export_xlsx(data)
    raise ValueError("Unsupported export format")
```

File: `analytics/templates/analytics/report_print.html`

```html
<button onclick="window.print()">🖨 Print / Save as PDF</button>
```

### 5. Code Explanation

`build_report()` is the shared dispatcher, so the page and exports use the same query logic. Each builder returns report metadata, columns, rows, summary cards and chart data. QuerySets perform date/status/search filtering and Django aggregations; Chart.js only visualizes the already prepared values.

### 6. Database Tables / Models

`SavedReport` stores saved report configuration. Report builders read `Goat`, `VaccinationRecord`, `HealthRecord`, `FeedLog`, `ActuationLog`, `SensorReading`, `GoatDetectionHistory`, `MarketplaceListing`, `Conversation` and `Reservation`; reports do not copy these records into a second reporting table.

### 7. APIs / URLs

```text
GET /analytics/
GET /analytics/<report_type>/
GET /analytics/<report_type>/print/
GET /analytics/<report_type>/export/?format=csv|xlsx
```

### 8. Hardware Involved

No direct hardware. Reports consume records previously produced by ESP32 devices, cameras, operators and marketplace users.

### 9. Security / Safety

Analytics views require authenticated farm access. The report type is allow-listed through the builder registry and export formats are explicitly checked. Spreadsheet cells are sanitized against formula injection before export.

### 10. Defense Explanation

**What I can say during the defense:**

“Reports do not use fabricated sample values. A report builder queries the same operational tables used by the dashboard, applies the selected date and status filters, and returns both table rows and chart values. The shared builder also feeds CSV and Excel exports, which keeps displayed and exported totals consistent. The current PDF option is browser printing, and there is not yet a separate weight-history or security report, so I classify the overall reporting feature as partial.”

---

## 17. MARKETPLACE

**STATUS: IMPLEMENTED**

### 1. Purpose

The marketplace lets approved sellers publish inventory goats with photographs and a price, and lets buyers request a reservation for pickup. It enforces Draft, Available, Reserved and Sold listing states and a buyer/seller confirmation flow. Completed sales mark both the listing and linked goat sold.

### 2. Files Involved

```text
marketplace/models.py
marketplace/forms.py
marketplace/services.py
marketplace/views.py
marketplace/urls.py
marketplace/decorators.py
marketplace/templates/marketplace/listing_*.html
marketplace/templates/marketplace/reservation_*.html
goats/models.py
```

### 3. System Flow

```text
Approved seller selects own active goat + price → Draft listing
→ seller publishes after photo/profile validation → Available
→ buyer requests reservation → seller accepts → Reserved
→ buyer/seller propose and the other party confirms pickup
→ seller completes sale → listing Sold + goat Sold
```

### 4. Important Source Code

File: `marketplace/models.py`

```python
class MarketplaceListing(models.Model):
    DRAFT = "draft"
    AVAILABLE = "available"
    RESERVED = "reserved"
    SOLD = "sold"
    goat = models.OneToOneField(
        "iot.Goat", on_delete=models.PROTECT, related_name="marketplace_listing"
    )
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="marketplace_listings",
    )
    price = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(0.01)]
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=DRAFT)

class Reservation(models.Model):
    listing = models.ForeignKey(MarketplaceListing, on_delete=models.PROTECT)
    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING)
    pickup_datetime = models.DateTimeField(null=True, blank=True)
    pickup_status = models.CharField(max_length=20, choices=PICKUP_STATUS_CHOICES)
    pickup_location = models.CharField(max_length=500, blank=True)
```

File: `marketplace/services.py`

```python
@transaction.atomic
def accept_reservation(reservation_id, actor, expires_at=None, pickup_location=""):
    reservation = Reservation.objects.select_for_update().select_related("listing").get(pk=reservation_id)
    listing = MarketplaceListing.objects.select_for_update().get(pk=reservation.listing_id)
    # permission/state checks omitted here only for presentation
    reservation.status = Reservation.ACCEPTED
    listing.status = MarketplaceListing.RESERVED
    reservation.save()
    listing.save(update_fields=["status", "updated_at"])

@transaction.atomic
def complete_sale(reservation_id, actor):
    # requires accepted reservation and confirmed pickup
    reservation.status = Reservation.COMPLETED
    listing.status = MarketplaceListing.SOLD
    goat.status = "sold"
```

### 5. Code Explanation

The `OneToOneField` prevents the same goat from having two listings. `select_for_update()` and atomic transactions serialize competing reservation changes. Pickup is deliberately a two-party agreement: the person who proposes a schedule cannot confirm their own proposal.

### 6. Database Tables / Models

`SellerProfile`, `MarketplaceListing`, `Reservation`, `MarketplaceActivity`, `MarketplaceNotification` and the linked `goats.Goat`/`GoatImage`. Seller review and marketplace report/audit models support moderation.

### 7. APIs / URLs

```text
GET  /marketplace/
GET  /marketplace/goats/
GET  /marketplace/listing/<pk>/
POST /marketplace/seller/listings/add/
POST /marketplace/seller/listings/<pk>/publication/
POST /marketplace/conversation/<pk>/reserve/
POST /marketplace/reservation/<pk>/pickup/
POST /marketplace/reservation/<pk>/action/
```

These are server-rendered Django form routes, not a public REST listing API.

### 8. Hardware Involved

None. Goat images are uploaded through the browser and stored as Django media.

### 9. Security / Safety

Only approved sellers can publish, seller actions are ownership-checked, and buyer/seller reservation actions are participant-checked. Transactions and row locks prevent double acceptance. Private pickup details are visible only to transaction participants; public listings exclude Draft/Sold records and inactive goats.

### 10. Defense Explanation

**What I can say during the defense:**

“A marketplace listing is linked one-to-one to an inventory goat, so a goat cannot be listed twice. Only an approved seller can publish a listing, and public users see only available active goats. Reservation transitions run inside database transactions with row locks to prevent two buyers from reserving the same goat at the same time. The sale is pickup-only: one participant proposes the schedule, the other confirms it, and completion changes both the listing and the inventory goat to sold.”

---

## 18. MARKETPLACE MESSAGING / INQUIRY

**STATUS: IMPLEMENTED**

### 1. Purpose

Marketplace inquiries are private listing-specific conversations between a buyer and seller. Messages have timestamps and read state, and participant checks protect every thread. This is separate from the customer-support ticket models and pages.

### 2. Files Involved

```text
marketplace/models.py
marketplace/forms.py
marketplace/views.py
marketplace/urls.py
marketplace/templates/marketplace/conversation_detail.html
marketplace/templates/marketplace/inbox.html
```

### 3. System Flow

```text
Buyer opens eligible listing → starts/opens inquiry thread
→ unique listing+buyer conversation is found or created
→ buyer/seller POSTs message → participant validation → Message saved
→ recipient opens thread → unread messages marked read
```

### 4. Important Source Code

File: `marketplace/models.py`

```python
class Conversation(models.Model):
    listing = models.ForeignKey(MarketplaceListing, on_delete=models.CASCADE)
    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=OPEN)
    class Meta:
        constraints = [models.UniqueConstraint(
            fields=["listing", "buyer"], name="uniq_listing_buyer_conversation"
        )]

class Message(models.Model):
    conversation = models.ForeignKey(Conversation, related_name="messages", on_delete=models.CASCADE)
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    body = models.TextField()
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    is_read = models.BooleanField(default=False)
```

File: `marketplace/views.py`

```python
viewer_is_buyer = conversation.buyer_id == request.user.id
viewer_is_seller = can_manage_listing(request.user, conversation.listing)
if not (request.user.is_staff or viewer_is_buyer or viewer_is_seller):
    messages.error(request, "You do not have access to that conversation.")
    return redirect("marketplace:my_inquiries")

conversation.messages.exclude(sender=request.user).filter(is_read=False).update(is_read=True)
```

### 5. Code Explanation

The database uniqueness constraint gives each buyer one thread per listing. `sender` identifies message direction, while `is_read` supplies unread counts. A buyer or approved listing manager can message; staff may review a thread read-only unless they are also a participant.

### 6. Database Tables / Models

`Conversation` and `Message`, linked to `MarketplaceListing` and Django `User`. Customer support instead uses `SupportTicket` and `SupportMessage` and is not part of this transaction conversation.

### 7. APIs / URLs

```text
POST     /marketplace/listing/<pk>/inquire/
GET/POST /marketplace/conversation/<pk>/
POST     /marketplace/conversation/<pk>/status/
GET      /marketplace/inquiries/
GET      /marketplace/seller/messages/
```

These are authenticated HTML form endpoints, not WebSockets.

### 8. Hardware Involved

None.

### 9. Security / Safety

Authentication, participant authorization, seller ownership and listing eligibility are checked server-side. Closed conversations reject new messages. Form validation limits and cleans the message body; unread updates never mark the current user's own messages.

### 10. Defense Explanation

**What I can say during the defense:**

“Marketplace messaging has its own Conversation and Message tables and is different from customer support. The database permits one inquiry thread for each buyer and listing. Every request checks that the logged-in user is either that buyer or the listing seller before displaying or saving messages. When a participant opens the thread, only messages sent by the other participant are marked read.”

---

## 19. DEVICE OFFLINE PROTECTION

**STATUS: PARTIALLY IMPLEMENTED**

### 1. Purpose

The server infers ESP32 availability from recent sensor traffic because the hardware has no separate heartbeat field. The Django web automation page disables Door, Light and Feeder buttons when their controller is stale. Protection is partial because the actuator API still accepts/queues a desired state while offline, and the Ionic control page does not currently disable controls from device availability.

### 2. Files Involved

```text
iot/status_utils.py
iot/views.py
iot/templates/iot/automation_control.html
mobile_api/views.py
goh-mo-tech-app/src/pages/AutomationPage.vue
goh-mo-tech-app/src/services/automation.service.ts
```

### 3. System Flow

```text
ESP32 stops posting → latest SensorReading becomes older than 90 seconds
→ is_device_online() returns false → Django attaches is_online=false
→ web template renders disabled control buttons and offline notice

Limitation: direct API/Ionic request → command may still be stored
→ ESP32 can consume that desired state when it reconnects
```

### 4. Important Source Code

File: `iot/status_utils.py`

```python
DEFAULT_ONLINE_WINDOW_SECONDS = 90
MAIN_CONTROLLER_DEVICE_ID = "gohmotech_esp32_002"

def is_device_online(device, window_seconds=DEFAULT_ONLINE_WINDOW_SECONDS):
    last = device_last_seen(device)
    if last is None:
        return False
    return (timezone.now() - last).total_seconds() <= window_seconds
```

File: `iot/templates/iot/automation_control.html`

```html
<button onclick="controlActuator({{ actuator.id }}, 'open', ...)"
        {% if not actuator.is_online %}disabled{% endif %}>Open</button>
{% if not actuator.is_online %}
  <div>Controls are disabled while the device is offline.</div>
{% endif %}
```

File: `goh-mo-tech-app/src/pages/AutomationPage.vue`

```html
<!-- device_online is not part of Actuator and therefore is not checked here -->
<ion-button :disabled="!canManage || busy === item.id || item.current_state === onState(item)"
            @click="confirmControl(item, onState(item))">
```

### 5. Code Explanation

`device_last_seen()` checks current and legacy sensor tables and returns the newest timestamp. Ninety seconds permits three missed 30-second posts before declaring offline. The web page's HTML `disabled` attribute is useful UX protection, but it is not a security boundary and is not enforced by the POST endpoint.

### 6. Database Tables / Models

`Device`, `SensorReading`, legacy `SensorData`, `Actuator` and `ActuationLog`. There is no stored `last_seen` field on `Device`; it is derived from sensor rows.

### 7. APIs / URLs

```text
GET  /iot/api/actuators/esp32_status/?device_id=<database_device_id>
GET  /iot/api/sensor-readings/latest/
POST /iot/api/actuators/<id>/control/
GET  /api/mobile/dashboard/
```

### 8. Hardware Involved

Both ESP32 controllers. Their periodic sensor POST acts as the online signal.

### 9. Security / Safety

The web UI fails closed visually when freshness is unknown. A complete safety implementation should also reject actuator POSTs while stale and expose/consume `device_online` in Ionic; the present code does neither consistently. A dormant health task also refers to a nonexistent `Device.last_seen` field, so it is not the active offline mechanism.

### 10. Defense Explanation

**What I can say during the defense:**

“The server treats an ESP32 as online only when it has posted sensor data within 90 seconds. The web automation page receives this computed state and disables its physical-control buttons when the device is stale. This avoids presenting controls that appear immediately usable while hardware is disconnected. However, backend rejection and Ionic disabling are not yet complete, so I honestly classify offline protection as partial rather than fully implemented.”

---

## 20. MANUAL PHYSICAL BUTTONS

**STATUS: NOT IMPLEMENTED**

### 1. Purpose

Physical buttons would allow Door, Light and Feeder operation without the website. Prototype/older sketches contain button pins and debounce logic, but the currently traced split controller firmware explicitly excludes physical buttons. Therefore this is not part of the active, connected implementation.

### 2. Files Involved

```text
esp32 autofeeder/kamotech_esp32_door_light_ldr/kamotech_esp32_door_light_ldr.ino  (current; no buttons)
esp32 autofeeder/kamotech_esp32_environment_feeder/kamotech_esp32_environment_feeder.ino (current; no buttons)
esp32 autofeeder/kamotech_esp32_complete/kamotech_esp32_complete.ino             (older prototype)
iot/views.py                                                                    (legacy sync endpoint)
feeding/views.py                                                                (legacy physical-feed log endpoint)
```

### 3. System Flow

```text
Current production-style split firmware → no button GPIO setup/read → no active flow

Older prototype only:
button LOW → 200 ms debounce → local actuator action
→ attempt to POST physical_button state/log to Django
```

### 4. Important Source Code

File: `esp32 autofeeder/kamotech_esp32_door_light_ldr/kamotech_esp32_door_light_ldr.ino`

```cpp
/* This controller intentionally does not own ... feeder servo,
 * or physical control buttons. */
```

File: `esp32 autofeeder/kamotech_esp32_complete/kamotech_esp32_complete.ino` (prototype, not active split firmware)

```cpp
#define DOOR_BUTTON 32
#define LIGHT_BUTTON 33
#define SERVO_BUTTON 15
#define BUTTON_DEBOUNCE 200

pinMode(DOOR_BUTTON, INPUT_PULLUP);
pinMode(LIGHT_BUTTON, INPUT_PULLUP);
pinMode(SERVO_BUTTON, INPUT_PULLUP);
```

### 5. Code Explanation

The prototype uses active-low momentary inputs with internal pull-ups and time-based debounce. Its door button cycles motion/stop and uses a long press for close; Light toggles and Feeder starts a servo cycle. Those functions cannot be presented as current because the active Door/Light/LDR and Environment/Feeder sketches do not configure or poll these pins.

### 6. Database Tables / Models

Prototype synchronization targets `Actuator`/`ActuationLog` and `FeedLog`, but this does not establish a live current path.

### 7. APIs / URLs

Legacy/prototype endpoints exist for physical actuator synchronization and physical-feed logging in the IoT/feeding URL modules. They are not called by the active split firmware.

### 8. Hardware Involved

Planned/prototype: three momentary buttons on GPIO 32, 33 and 15 using `INPUT_PULLUP`. These pin assignments must not be copied to the current boards without resolving conflicts with their present pin maps.

### 9. Security / Safety

The prototype works locally during network loss, but its old server URLs/authentication do not match the current hardened device flow. Reintroducing it safely requires board-specific pins, individual debouncing, motor interlock and authenticated state synchronization.

### 10. Defense Explanation

**What I can say during the defense:**

“There is physical-button code in an older combined prototype, including pull-up inputs and debounce logic. The current system was separated into a Door/Light controller and an Environment/Feeder controller, and those current sketches do not include buttons. For that reason I will not claim physical buttons as implemented in the present system. The prototype is evidence of earlier work, but it needs safe pin reassignment and current API authentication before deployment.”

---

## 21. RASPBERRY PI SERVER / PRODUCTION DEPLOYMENT

**STATUS: IMPLEMENTED**

### 1. Purpose

The deployment files run Django as an ASGI service on the Raspberry Pi, proxy public HTTPS traffic through Nginx, and use MariaDB, Redis and Celery for persistence, WebSockets/cache and background work. Services start automatically and restart after failure. A Cloudflare Tunnel is consistent with the loopback-only Nginx origin design, but its credentials/unit are intentionally external to this repository.

### 2. Files Involved

```text
config/production.py
config/production_urls.py
config/asgi.py
config/routing.py
config/celery.py
deploy/nginx-production.conf
deploy/gohmotech-production.service
deploy/gohmotech-celery-worker.service
deploy/gohmotech-celery-beat.service
deploy/install_production.sh
deploy/prepare_production.py
```

### 3. System Flow

```text
Browser / Ionic / ESP32 HTTPS
→ public HTTPS ingress (Cloudflare configuration outside repo)
→ Nginx 127.0.0.1:8080
→ Daphne ASGI 127.0.0.1:8010
→ Django HTTP views or Channels WebSockets
→ MariaDB + Redis
→ Celery worker/beat for scheduled/background tasks
```

### 4. Important Source Code

File: `deploy/gohmotech-production.service`

```ini
Environment=DJANGO_SETTINGS_MODULE=config.production
Environment=PRODUCTION_ENV_FILE=/home/gohmotech/.config/gohmotech/production.env
ExecStart=/home/gohmotech/capstone/.venv/bin/daphne --bind 127.0.0.1 --port 8010 config.asgi:application
Restart=on-failure
```

File: `deploy/nginx-production.conf`

```nginx
listen 127.0.0.1:8080;
location /static/ { alias /var/www/gohmotech-production/static/; }
location / {
    proxy_pass http://127.0.0.1:8010;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $gohmotech_connection_upgrade;
    proxy_buffering off;
}
```

File: `config/production.py`

```python
DATABASES = {"default": {"ENGINE": "django.db.backends.mysql", ...}}
CHANNEL_LAYERS = {"default": {
    "BACKEND": "channels_redis.core.RedisChannelLayer", "CONFIG": {"hosts": [_redis]}
}}
CELERY_BROKER_URL = os.environ.get("PRODUCTION_CELERY_BROKER_URL", "redis://127.0.0.1:6379/3")
```

### 5. Code Explanation

Daphne is used rather than Gunicorn because the application serves both normal HTTP and Channels WebSockets. Nginx serves collected static files and proxies dynamic/streaming traffic with WebSocket upgrade headers and buffering disabled. The worker executes queued tasks; beat emits scheduled checks such as SMS and automation jobs.

### 6. Database Tables / Models

Production Django models reside in MariaDB/MySQL. Redis is transient infrastructure for channel messages, cache and Celery brokerage; it is not the system of record. `django-celery-results` stores task results in the database.

### 7. APIs / URLs

All application endpoints share the public HTTPS domain. Internal origins bind only to `127.0.0.1:8080` (Nginx) and `127.0.0.1:8010` (Daphne). WebSocket routes are declared in `config/routing.py`.

### 8. Hardware Involved

Raspberry Pi/server host, local storage, network interface and attached LAN devices. Cameras and ESP32 units connect over the network, not directly through Pi GPIO in this project.

### 9. Security / Safety

Secrets are required from a root/user-protected environment file and are not shown here. Production enables secure cookies, HSTS, host/origin checks and strict database mode. Daphne and Nginx origins are loopback-only; systemd applies restart and hardening directives. Nginx trusts the HTTPS forwarded header only because Daphne is not publicly exposed.

### 10. Defense Explanation

**What I can say during the defense:**

“On the Raspberry Pi, Nginx receives origin traffic and forwards it to Daphne, which runs Django's ASGI application. ASGI supports normal pages, APIs, camera streaming and WebSockets in one deployment. MariaDB stores permanent records, Redis supports real-time channels, cache and the Celery queue, and separate worker and beat services run background schedules. Systemd starts these services automatically and restarts failures, while passwords and tokens live in a protected environment file outside the source repository.”

---

## 22. IONIC MOBILE APPLICATION INTEGRATION

**STATUS: PARTIALLY IMPLEMENTED**

### 1. Purpose

The Ionic Vue app provides token-authenticated mobile access to dashboard, automation, cameras, goats, BLE tracking, security events and notifications. The API handles concurrent users independently through Django authentication tokens and per-request permission checks. Session persistence, mobile reports, marketplace REST integration, feeder control and consistent offline-control disabling remain incomplete.

### 2. Files Involved

```text
goh-mo-tech-app/src/services/api.ts
goh-mo-tech-app/src/stores/auth.store.ts
goh-mo-tech-app/src/router/index.ts
goh-mo-tech-app/src/pages/LoginPage.vue
goh-mo-tech-app/src/pages/HomePage.vue
goh-mo-tech-app/src/pages/AutomationPage.vue
goh-mo-tech-app/src/pages/CamerasPage.vue
goh-mo-tech-app/src/pages/GoatsPage.vue
goh-mo-tech-app/src/pages/NotificationsPage.vue
goh-mo-tech-app/src/pages/ReportsPage.vue
goh-mo-tech-app/src/pages/MarketplacePage.vue
mobile_api/urls.py
mobile_api/views.py
mobile_api/serializers.py
mobile_api/websocket.py
```

### 3. System Flow

```text
User logs in → POST mobile login → Django returns unique auth token + permissions
→ token held in Vue memory → apiRequest adds Authorization: Token ...
→ DRF authenticates request and enforces farm role
→ JSON populates Ionic page
→ 401 clears the in-memory session
```

### 4. Important Source Code

File: `goh-mo-tech-app/src/stores/auth.store.ts`

```typescript
const mutable = reactive<AuthState>({ token: null, user: null });
// Memory-only until native secure storage is installed.
export function setSession(token: string, user: MobileUser) {
  mutable.token = token; mutable.user = user;
}
export function clearSession() { mutable.token = null; mutable.user = null; }
```

File: `goh-mo-tech-app/src/services/api.ts`

```typescript
export const API_BASE = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '');
if (authState.token) headers.set('Authorization', `Token ${authState.token}`);
const response = await fetch(`${API_BASE}${path}`, { ...init, headers });
if (response.status === 401) clearSession();
```

File: `mobile_api/views.py`

```python
class DashboardView(APIView):
    permission_classes = [IsAuthenticated, FarmRolePermission]
    def get(self, request):
        # returns environment, goat, feed, system, automation and alert summaries
        ...
```

File: `goh-mo-tech-app/src/pages/MarketplacePage.vue`

```html
<p>The existing marketplace has complete Django workflows but no REST API.</p>
<ion-button disabled>Marketplace API not yet available</ion-button>
```

### 5. Code Explanation

`apiRequest()` centralizes base URL, JSON headers, token attachment, network errors and logout on 401. The server returns explicit permissions so the client hides/disables owner-only actions, while the backend repeats authorization. The token is intentionally memory-only; closing/reloading the app logs the user out until native secure storage is added.

### 6. Database Tables / Models

Django `User`, `authtoken.Token` and the same feature tables used by the web application. The Ionic app has no separate client database and does not share one global session among users.

### 7. APIs / URLs

```text
POST /api/mobile/auth/login/
POST /api/mobile/auth/logout/
GET  /api/mobile/auth/me/
GET  /api/mobile/dashboard/
GET  /api/mobile/cameras/
GET  /api/mobile/goats/
GET  /security/api/notifications/
POST /api/mobile/auth/realtime-ticket/
plus protected IoT/BLE/security endpoints used by feature services
```

### 8. Hardware Involved

Android/iOS device or browser, Raspberry Pi server, ESP32 controllers and IP cameras. The phone talks to Django APIs; it does not connect directly to relays or RTSP.

### 9. Security / Safety

Tokens are per user, requests use HTTPS in production, and DRF permissions provide server-side isolation. Short-lived signed tickets authorize camera/WebSocket URLs that cannot attach HTTP token headers normally. Concurrent requests are isolated by their tokens and database transactions. Current gaps are no secure persistent login and no mobile offline actuator guard.

### 10. Defense Explanation

**What I can say during the defense:**

“The Ionic app is a separate Vue client that calls Django's JSON APIs. After login it attaches the logged-in user's token to each request, so simultaneous users are authenticated and authorized independently. The mobile client already supports the main dashboard, inventory, camera, tracking, security, alert and Door/Light views, and server permissions are still enforced even if someone modifies the app. Reports and marketplace are honest placeholders, feeder controls are hidden, and login is currently memory-only, so the total mobile integration is partial.”

---

# GoHMoTech Main Feature Code Index

| # | Main Feature | Status | Main Backend File | Frontend File | ESP32/Hardware Code | Database Model |
|---:|---|---|---|---|---|---|
| 1 | Authentication and roles | Implemented | `marketplace/auth.py`, `config/settings.py` | `templates/registration/login.html`, `marketplace/templates/marketplace/register.html` | — | Django `User`, `Group`, `Token` |
| 2 | Dashboard | Implemented | `iot/views.py`, `mobile_api/views.py` | `iot/templates/iot/dashboard_modern.html`, `goh-mo-tech-app/src/pages/HomePage.vue` | Sensor/camera sources below | `SensorReading`, `Actuator`, `Alert`, `Goat` |
| 3 | IoT communication | Implemented | `iot/views.py`, `iot/device_authentication.py` | `iot/templates/iot/automation_control.html` | `esp32 autofeeder/kamotech_esp32_door_light_ldr/kamotech_esp32_door_light_ldr.ino`, `esp32 autofeeder/kamotech_esp32_environment_feeder/kamotech_esp32_environment_feeder.ino` | `Device`, `SensorReading`, `Actuator`, `ActuationLog` |
| 4 | Door control | Implemented | `iot/views.py` | `iot/templates/iot/automation_control.html` | `esp32 autofeeder/kamotech_esp32_door_light_ldr/kamotech_esp32_door_light_ldr.ino` | `Actuator`, `ActuationLog` |
| 5 | Lighting | Implemented | `iot/views.py`, `iot/tasks.py` | `iot/templates/iot/automation_control.html` | `esp32 autofeeder/kamotech_esp32_door_light_ldr/kamotech_esp32_door_light_ldr.ino` | `Actuator`, `AutomationRule`, `SensorReading` |
| 6 | Environmental monitoring | Implemented | `iot/views.py`, `iot/serializers.py` | `iot/templates/iot/dashboard_modern.html` | `esp32 autofeeder/kamotech_esp32_environment_feeder/kamotech_esp32_environment_feeder.ino` | `SensorReading`, `Device` |
| 7 | Automated feeding | Partially implemented | `feeding/views.py`, `feeding/tasks.py`, `iot/tasks.py` | `iot/templates/iot/automation_control.html` | `esp32 autofeeder/kamotech_esp32_environment_feeder/kamotech_esp32_environment_feeder.ino` | `FeedingSchedule`, `FeedLog`, `FeedLevel`, `Actuator` |
| 8 | Goat inventory | Implemented | `iot/goat_views.py`, `iot/goat_models.py` | `iot/templates/iot/goat_inventory.html` | — | `Goat`, `GoatImage`, health/vaccination records |
| 9 | Weight monitoring | Partially implemented | `iot/goat_views.py`, `iot/goat_models.py` | `iot/templates/iot/goat_detail_enhanced.html` | `esp32 load cell/kamotech_load_cell_esp32/kamotech_load_cell_esp32.ino` | `GoatWeightMeasurement`, `Goat` |
| 10 | BLE/iBeacon tracking | Implemented | `iot/ble_views.py`, `iot/ble_services.py` | `iot/templates/iot/ble_tracking_dashboard.html` | `ble_scanner.py` on Raspberry Pi | `BLEBeacon`, `BLEReceiver`, `BLEObservation`, `BLETrackingState` |
| 11 | IP/RTSP cameras | Implemented | `iot/camera_utils.py`, `iot/views.py` | `iot/templates/iot/camera_detail.html` | IP camera + Pi/OpenCV | `IPCamera` |
| 12 | AI/ML goat detection | Implemented | `ml_models/ml_utils.py`, `ml_models/views.py` | `ml_models/templates/ml_models/detection_feed.html` | Pi CPU/GPU + camera | `MLModel`, `GoatDetectionHistory` |
| 13 | Security/person detection | Implemented | `ml_models/views.py`, `security/services.py` | `templates/security/security_dashboard.html` | Pi + camera | `PersonDetection`, `MLModel`, `Notification` |
| 14 | Notifications and alerts | Partially implemented | `security/services.py`, `security/signals.py` | `templates/security/security_dashboard.html` | Event sources above | `Notification`, `Alert`, `MissingGoatAlert`, `PersonDetection` |
| 15 | SMS notifications | Implemented | `sms/services.py`, `sms/tasks.py` | `sms/templates/sms/` | External Semaphore API | `SmsSettings`, `SmsReminder`, `SmsRegistration`, `SmsLog` |
| 16 | Reports and analytics | Partially implemented | `analytics/report_data.py`, `analytics/exports.py` | `analytics/templates/analytics/report_detail.html` | — | Reads feature models; `Report` |
| 17 | Marketplace | Implemented | `marketplace/services.py`, `marketplace/views.py` | `marketplace/templates/marketplace/` | — | `MarketplaceListing`, `Reservation`, `SellerProfile` |
| 18 | Marketplace inquiry | Implemented | `marketplace/views.py` | `marketplace/templates/marketplace/conversation_detail.html` | — | `Conversation`, `Message` |
| 19 | Offline protection | Partially implemented | `iot/status_utils.py`, `iot/views.py` | `iot/templates/iot/automation_control.html` | Periodic sensor posts from both ESP32s | Derived from `SensorReading` |
| 20 | Physical buttons | Not implemented (current firmware) | legacy sync views in `iot/views.py`, `feeding/views.py` | — | older `esp32 autofeeder/kamotech_esp32_complete/kamotech_esp32_complete.ino`; absent from current split sketches | prototype targets `ActuationLog`, `FeedLog` |
| 21 | Pi production deployment | Implemented | `config/production.py`, `config/asgi.py` | Nginx/static assets | Raspberry Pi, MariaDB, Redis | all production Django tables |
| 22 | Ionic integration | Partially implemented | `mobile_api/views.py` | `goh-mo-tech-app/src/` | Indirect ESP32/camera access through Django | Django `Token` plus feature models |

# Top Features to Demonstrate During Capstone Defense

These are grouped by working implementation rather than assigned a subjective rank.

### IoT Control

- Door Open/Close/Stop from the Django page through the command API to the Door/Light ESP32.
- Manual and automatic lighting using LDR readings, automation rules and the relay.
- Manual feeder servo cycle and live ultrasonic feed-level measurement. Present scheduling as partial until its duplicate task paths are repaired and unified.

### Monitoring

- Live DHT21 temperature/humidity, rain, LDR, MQ-135 raw air reading and feed level from the two ESP32 controllers.
- RTSP camera converted to authenticated browser MJPEG with reconnect behavior.
- Load-cell live reading and explicit goat-weight save, while disclosing the current scale device-auth mismatch.
- Dashboard cards and recent activity assembled from live database sources.

### Intelligent Features

- YOLOv8 goat detection with confidence, boxes, count and detection history.
- Person detection becoming a cooldown-controlled security event and unified notification.
- BLE tag scanning, receiver RSSI, proximity zone and missing-goat history. Describe it as proximity, not GPS coordinates.

### Management

- Goat add/edit/archive/profile workflow with validated multi-angle images.
- Marketplace listing, inquiry, locked reservation, two-party pickup confirmation and completed sale.
- Date-filtered analytics with charts and CSV/XLSX export, while noting the missing dedicated weight/security reports.

### Safety and Operations

- Role-based Owner/Operator/Admin restrictions on both page and API actions.
- Web offline-state calculation and disabled controls; disclose that backend/mobile enforcement is still partial.
- Unified alert inbox/WebSocket updates and Semaphore-capable SMS with cooldown and logs.
- Raspberry Pi Nginx → Daphne/ASGI → Django → MariaDB/Redis/Celery production architecture.

## Defense-Critical Limitations to State Clearly

1. Actuator `current_state` is the latest requested state; the present command protocol has no hardware completion acknowledgement or door limit-switch feedback.
2. The active ESP32 Door/Light sketch uses pinned HTTPS, but the Environment/Feeder and Scale sketches use local HTTP. Wi-Fi/device credentials found in firmware must be removed from source and provisioned securely.
3. Scheduled feeding has competing/incomplete execution paths: one uses obsolete `FeedLog` field names, one logs success without issuing the hardware command, and the intelligent feeder dispatch is a stub.
4. The scale backend has strong idempotence/stability handling, but its current firmware does not send the required device-key header.
5. MQ-135 voltage/raw readings are usable, but ppm conversion is not calibrated while the configured R0 value is zero.
6. Web offline controls are disabled at 90 seconds, but the command API does not fail closed and Ionic does not consume device-online state.
7. Physical button logic belongs to older prototype sketches and is absent from the active split firmware.
8. Ionic login is memory-only; mobile Reports and Marketplace explicitly declare API gaps.
9. Camera credentials are protected from responses but stored as model fields; deployment/database access must therefore be tightly protected.
10. Cloudflare Tunnel configuration and credentials are outside the repository; the repository proves the loopback Nginx origin and HTTPS assumptions, not the private tunnel token.
