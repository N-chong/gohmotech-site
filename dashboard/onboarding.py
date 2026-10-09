"""Read-only tours of existing pages; no farm or marketplace actions are invoked."""
import json

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from marketplace.auth import get_system_role, is_approved_seller
from .models import OnboardingProgress

REPLAY_KEY = "onboarding_replay"


def tutorial_role(user):
    if not user.is_authenticated or not user.is_active:
        return None
    role = get_system_role(user)
    if role == "farm_owner":
        return role
    if role == "marketplace" and is_approved_seller(user):
        return "seller"
    return None


def tutorial_steps(role):
    def step(title, text, page, target=None, mascot="goat_information.png"):
        return {"title": title, "text": text, "url": reverse(page), "target": target, "mascot": mascot}

    if role == "farm_owner":
        home = "iot:owner_dashboard"
        steps = [
            step("Welcome to GoHMoTech!", "Let's take a quick tour of your Farm Owner dashboard and learn where the important monitoring and management tools are located.", home, mascot="goat_welcome_clipboard.png"),
            step("Find your way around", "Use the navigation to open your farm tools, monitoring, records, and Help & Settings.", home, ".mobile-menu-toggle, #app-sidebar .sidebar-nav-group > summary", mascot="point_auto"),
            step("Your farm at a glance", "Check your goat totals and farm status here. Scroll down for environment readings, recent activity, and alerts.", home, ".owner-stat-card, .owner-stat-grid > :first-child", mascot="goat_laptop_system.png"),
            step("Manage your goats", "View your goats here. Search their records, check their status, or use Add Goat to register one.", "iot:goat_inventory", ".inv-page-header", mascot="goat_checklist_tasks.png"),
            step("Farm monitoring", "View camera feeds and the latest farm readings on this page.", "iot:monitoring_dashboard", ".page-header", mascot="goat_information.png"),
            step("Alerts and notifications", "Use this bell to open Security & Alerts and review important farm and security notifications.", home, '.header-actions a[title="Notifications"]', mascot="goat_warning_attention.png"),
            step("Reports and history", "Open Reports to review recorded farm information. Detection History is also available under Records in the navigation.", "analytics:dashboard", ".rc-page-header", mascot="goat_checklist_tasks.png"),
            step("Farm controls", "Find feeding schedules and farm equipment controls here. Review the current status before making changes.", "iot:automation_control", ".page-header", mascot="goat_laptop_system.png"),
            step("You're all set!", "You've completed the GoHMoTech Farm Owner tutorial. You can now start monitoring and managing your farm. Find Take Tour Again under Help & Settings whenever you need it.", home, mascot="goat_celebration_finish.png"),
        ]
    else:
        home = "marketplace:seller_dashboard"
        steps = [
            step("Welcome to GoHMoTech!", "Let's take a quick tour of the Verified Seller features.", home, mascot="goat_welcome_clipboard.png"),
            step("Your seller navigation", "Use these links to open My Goats, My Listings, Messages, Reservations, and Sales History.", home, ".seller-dashboard-actions", mascot="point_auto"),
            step("Your seller dashboard", "Check your goat and listing totals, pending requests, sales, and unread messages here.", home, ".seller-metrics > :first-child", mascot="goat_laptop_system.png"),
            step("Marketplace", "Browse goats available in the marketplace. My Listings takes you back to the listings you manage.", "marketplace:list", ".marketplace-tabs", mascot="goat_search_magnifier.png"),
            step("Your goats", "Add a goat and manage its details and photos here before creating a listing.", "marketplace:seller_goats", ".section-heading", mascot="goat_checklist_tasks.png"),
            step("Your listings", "Create a listing with a price and description. Use its menu to edit, publish, or unpublish it when available.", "marketplace:seller_listings", ".section-heading", mascot="goat_checklist_tasks.png"),
            step("Reservations", "Review buyer reservation requests and arrange pickups here.", "marketplace:seller_reservations", ".section-heading", mascot="goat_checklist_tasks.png"),
            step("Messages", "Read inquiries and talk with buyers about your goats here.", "marketplace:seller_messages", ".section-heading", mascot="goat_information.png"),
            step("Notifications", "Open Notifications for marketplace updates and account notices.", "marketplace:notifications", ".notification-nav-button, main h1", mascot="goat_warning_attention.png"),
            step("Sales history", "Review your completed marketplace sales here.", "marketplace:seller_sales_history", ".section-heading", mascot="goat_checklist_tasks.png"),
            step("You're all set!", "You've completed the GoHMoTech Verified Seller tutorial. Find Help · Take Tour Again in your account menu whenever you need it.", home, mascot="goat_celebration_finish.png"),
        ]
    return steps


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def tutorial_state(request):
    role = tutorial_role(request.user)
    if role is None:
        return JsonResponse({"detail": "This account does not have a tutorial."}, status=403)
    steps = tutorial_steps(role)
    payload = {}
    if request.method == "POST":
        try:
            payload = json.loads(request.body)
        except (ValueError, UnicodeDecodeError):
            return JsonResponse({"detail": "Invalid tutorial request."}, status=400)
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("action"), str)
            or payload["action"] not in {"step", "finish", "skip", "replay"}
        ):
            return JsonResponse({"detail": "Invalid tutorial action."}, status=400)
        if payload["action"] == "step" and (
            type(payload.get("step")) is not int or not 0 <= payload["step"] < len(steps)
        ):
            return JsonResponse({"detail": "Invalid tutorial step."}, status=400)

    with transaction.atomic():
        progress, _ = OnboardingProgress.objects.get_or_create(user=request.user, defaults={"role": role})
        progress = OnboardingProgress.objects.select_for_update().get(pk=progress.pk)
        if progress.role != role:
            progress.role, progress.step = role, 0
            progress.save(update_fields=["role", "step"])
        replay = request.session.get(REPLAY_KEY)
        if replay and replay.get("role") != role:
            request.session.pop(REPLAY_KEY, None)
            replay = None
        action = payload.get("action")
        if action == "replay":
            replay = {"role": role, "step": 0}
            request.session[REPLAY_KEY] = replay
        elif action == "step":
            if replay:
                replay = {"role": role, "step": payload["step"]}
                request.session[REPLAY_KEY] = replay
            elif not progress.has_completed_tutorial:
                progress.step = payload["step"]
                progress.save(update_fields=["step"])
        elif action in {"finish", "skip"}:
            current = replay["step"] if replay else progress.step
            if action == "finish" and current != len(steps) - 1:
                return JsonResponse({"detail": "Please reach the last step before finishing."}, status=400)
            if not progress.has_completed_tutorial:
                progress.has_completed_tutorial = True
                progress.completed_at = timezone.now()
                progress.completion_reason = "finished" if action == "finish" else "skipped"
                progress.save(update_fields=["has_completed_tutorial", "completed_at", "completion_reason"])
            request.session.pop(REPLAY_KEY, None)
            replay = None
        return JsonResponse({
            "role": role, "completed": progress.has_completed_tutorial,
            "active": bool(replay) or not progress.has_completed_tutorial,
            "step": replay["step"] if replay else min(progress.step, len(steps) - 1),
            "steps": steps,
        })
