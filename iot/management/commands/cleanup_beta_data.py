"""Plan and, only after explicit approval, remove data from the web beta.

This command is intentionally tied to the isolated ``config.beta`` deployment.
It never treats device, automation, BLE, camera, ML, permission, or scheduler
configuration as disposable data.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections import OrderedDict
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone


PLAN_VERSION = 1
EXPECTED_SETTINGS = "config.beta"
EXPECTED_DATABASE = "gohmotech_beta"
FARM_OWNER_GROUP = "Farm Owners"
FARM_OPERATOR_GROUP = "Farm Operators"

# Dependency-safe explicit deletion order. Configuration models are deliberately
# absent. QuerySets are built in build_plan(), then frozen to exact primary keys.
DELETE_ORDER = (
    "marketplace.SupportAttachment",
    "marketplace.SupportMessage",
    "marketplace.SupportTicket",
    "marketplace.MarketplaceNotification",
    "marketplace.Favorite",
    "marketplace.MarketplaceReport",
    "marketplace.Reservation",
    "marketplace.Message",
    "marketplace.Conversation",
    "marketplace.MarketplaceActivity",
    "marketplace.MarketplaceListing",
    "marketplace.SellerProfile",
    "iot.GoatWeightMeasurement",
    "iot.GoatImage",
    "iot.GoatBehaviorLog",
    "iot.GoatDetectionHistory",
    "iot.MissingGoatAlert",
    "iot.NotificationLog",
    "iot.BLEObservation",
    "iot.BLETrackingState",
    "iot.GrassHealthLog",
    "iot.Alert",
    "iot.SensorData",
    "iot.SensorReading",
    "iot.ActuationLog",
    "ml_models.Detection",
    "security.PersonDetection",
    "security.Notification",
    "feeding.FeedLog",
    "analytics.Report",
    "sms.SmsLog",
    "sms.SmsRegistration",
    "marketplace.UserActivity",
    "marketplace.UserAccountState",
    "socialaccount.SocialToken",
    "socialaccount.SocialAccount",
    "account.EmailConfirmation",
    "account.EmailAddress",
    "sessions.Session",
    "iot.Goat",
    "auth.User",
)

PRESERVED_CONFIGURATION = (
    "auth.Group and auth.Permission",
    "django_migrations and django.contrib.contenttypes",
    "django-celery-beat schedules and django-celery-results history",
    "feeding.AutomatedFeedingConfig, FeedSchedule, and FeedLevel",
    "iot.Device, ActuatorState, AutomationRule, and IPCamera",
    "iot.BLEBeacon, BLEReceiver, and BLETrackingSettings",
    "ml_models.MLModel and protected model files",
    "sms.SmsSettings and SmsReminder",
    "socialaccount.SocialApp provider configuration",
    "admin.LogEntry audit history",
    "smart-farm Goat inventory records",
)


def _model(label):
    return apps.get_model(label)


def _ids(queryset):
    return list(queryset.order_by("pk").values_list("pk", flat=True))


def _canonical_payload(plan):
    payload = dict(plan)
    payload.pop("sha256", None)
    payload.pop("generated_at", None)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _plan_hash(plan):
    return hashlib.sha256(_canonical_payload(plan).encode("utf-8")).hexdigest()


class Command(BaseCommand):
    help = (
        "Safely plan cleanup of the isolated public beta database. "
        "Destructive execution requires an approved frozen plan and backup."
    )

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--dry-run", action="store_true")
        mode.add_argument("--confirm", action="store_true")
        parser.add_argument(
            "--preserve-user-id",
            action="append",
            type=int,
            default=[],
            help="Additional user ID to preserve (repeatable).",
        )
        parser.add_argument(
            "--remove-user-id",
            action="append",
            type=int,
            default=[],
            help=(
                "Explicitly reviewed user ID to remove (repeatable). Required "
                "to propose deletion of a Farm Operators account."
            ),
        )
        parser.add_argument(
            "--plan-out",
            help="Optional private path for the frozen dry-run JSON plan.",
        )
        parser.add_argument(
            "--approved-plan",
            help="Frozen JSON plan produced by --dry-run (required with --confirm).",
        )
        parser.add_argument(
            "--approved-sha256",
            help="Exact SHA-256 printed by the approved dry run.",
        )
        parser.add_argument(
            "--backup-reference",
            help="Existing non-empty backup file/directory (required with --confirm).",
        )
        parser.add_argument(
            "--quarantine-dir",
            help="Directory outside active storage to receive removed beta files.",
        )

    def handle(self, *args, **options):
        self._guard_environment()
        if options["dry_run"]:
            plan = self._build_plan(
                set(options["preserve_user_id"]), set(options["remove_user_id"])
            )
            self._print_plan(plan)
            if options["plan_out"]:
                self._write_plan(plan, Path(options["plan_out"]))
            return

        self._confirm(plan_path=options["approved_plan"],
                      approved_hash=options["approved_sha256"],
                      backup_reference=options["backup_reference"],
                      quarantine_dir=options["quarantine_dir"])

    def _guard_environment(self):
        settings_module = os.environ.get("DJANGO_SETTINGS_MODULE", "")
        database_name = settings.DATABASES["default"].get("NAME")
        if settings_module != EXPECTED_SETTINGS or database_name != EXPECTED_DATABASE:
            raise CommandError(
                "Refusing to run outside the isolated config.beta / "
                "gohmotech_beta environment."
            )
        if settings.DEBUG:
            raise CommandError("Refusing to run with DEBUG enabled.")

    def _preserved_user_ids(self, additional, explicit_remove):
        User = get_user_model()
        administrator_ids = set(
            User.objects.filter(Q(is_staff=True) | Q(is_superuser=True))
            .values_list("pk", flat=True)
        )
        forbidden = administrator_ids & explicit_remove
        if forbidden:
            raise CommandError(
                f"Administrator accounts can never be cleanup targets: {sorted(forbidden)}"
            )
        owner_ids = set(
            User.objects.filter(groups__name=FARM_OWNER_GROUP)
            .values_list("pk", flat=True)
        ) - explicit_remove
        existing_additional = set(
            User.objects.filter(pk__in=additional).values_list("pk", flat=True)
        )
        missing = additional - existing_additional
        if missing:
            raise CommandError(f"Unknown --preserve-user-id values: {sorted(missing)}")
        return administrator_ids | owner_ids | existing_additional

    def _build_plan(self, additional_preserve, explicit_remove=None):
        User = get_user_model()
        explicit_remove = set(explicit_remove or ())
        preserve_user_ids = self._preserved_user_ids(
            additional_preserve, explicit_remove
        )
        existing_explicit = set(
            User.objects.filter(pk__in=explicit_remove).values_list("pk", flat=True)
        )
        missing_explicit = explicit_remove - existing_explicit
        if missing_explicit:
            raise CommandError(f"Unknown --remove-user-id values: {sorted(missing_explicit)}")
        overlap = preserve_user_ids & explicit_remove
        if overlap:
            raise CommandError(f"Users cannot be both preserved and removed: {sorted(overlap)}")
        candidate_user_ids = set(
            User.objects.exclude(pk__in=preserve_user_ids).values_list("pk", flat=True)
        )
        operator_ids = set(
            User.objects.filter(groups__name=FARM_OPERATOR_GROUP)
            .exclude(pk__in=explicit_remove)
            .values_list("pk", flat=True)
        )
        candidate_user_ids -= operator_ids

        # A candidate that owns smart-farm inventory is ambiguous/operational and
        # is automatically moved to review instead of being proposed for deletion.
        Goat = _model("iot.Goat")
        protected_owner_ids = set(
            Goat.all_objects.filter(
                owner_id__in=candidate_user_ids, record_source="smart_farm"
            ).values_list("owner_id", flat=True)
        )
        candidate_user_ids -= protected_owner_ids
        review_user_ids = protected_owner_ids | operator_ids

        community_goat_ids = set(
            Goat.all_objects.filter(record_source="community").values_list("pk", flat=True)
        )

        targets = OrderedDict()
        # Marketplace/support data in this deliberately empty-at-install beta DB
        # is beta activity. Exact PKs make the approved scope immutable.
        for label in (
            "marketplace.SupportAttachment", "marketplace.SupportMessage",
            "marketplace.SupportTicket", "marketplace.MarketplaceNotification",
            "marketplace.Favorite", "marketplace.MarketplaceReport",
            "marketplace.Reservation", "marketplace.Message",
            "marketplace.Conversation", "marketplace.MarketplaceActivity",
            "marketplace.MarketplaceListing", "marketplace.SellerProfile",
        ):
            targets[label] = _ids(_model(label)._base_manager.all())

        for label in (
            "iot.GoatWeightMeasurement", "iot.GoatImage", "iot.GoatBehaviorLog",
            "iot.GoatDetectionHistory", "iot.MissingGoatAlert",
            "iot.NotificationLog", "iot.BLEObservation", "iot.BLETrackingState",
            "iot.GrassHealthLog", "iot.Alert", "iot.SensorData",
            "iot.SensorReading", "iot.ActuationLog", "ml_models.Detection",
            "security.PersonDetection", "security.Notification", "feeding.FeedLog",
            "analytics.Report",
        ):
            targets[label] = _ids(_model(label)._base_manager.all())

        SmsLog = _model("sms.SmsLog")
        targets["sms.SmsLog"] = _ids(
            SmsLog.objects.filter(Q(sms_type="test") | Q(provider="console"))
        )
        targets["sms.SmsRegistration"] = _ids(
            _model("sms.SmsRegistration").objects.filter(user_id__in=candidate_user_ids)
        )
        targets["marketplace.UserActivity"] = _ids(
            _model("marketplace.UserActivity").objects.filter(user_id__in=candidate_user_ids)
        )
        targets["marketplace.UserAccountState"] = _ids(
            _model("marketplace.UserAccountState").objects.filter(user_id__in=candidate_user_ids)
        )

        social_accounts = _model("socialaccount.SocialAccount").objects.filter(
            user_id__in=candidate_user_ids
        )
        targets["socialaccount.SocialToken"] = _ids(
            _model("socialaccount.SocialToken").objects.filter(account__in=social_accounts)
        )
        targets["socialaccount.SocialAccount"] = _ids(social_accounts)
        email_addresses = _model("account.EmailAddress").objects.filter(
            user_id__in=candidate_user_ids
        )
        targets["account.EmailConfirmation"] = _ids(
            _model("account.EmailConfirmation").objects.filter(email_address__in=email_addresses)
        )
        targets["account.EmailAddress"] = _ids(email_addresses)
        targets["sessions.Session"] = self._candidate_session_keys(candidate_user_ids)
        targets["iot.Goat"] = sorted(community_goat_ids)

        # User deletion is blocked when an unselected PROTECT relation remains.
        # The current protected roots are surfaced instead of bypassed.
        blockers = self._user_blockers(candidate_user_ids, community_goat_ids)
        blocked_user_ids = set(blockers)
        candidate_user_ids -= blocked_user_ids
        review_user_ids |= blocked_user_ids
        if blocked_user_ids:
            for label in (
                "sms.SmsRegistration", "marketplace.UserActivity",
                "marketplace.UserAccountState", "socialaccount.SocialAccount",
                "account.EmailAddress",
            ):
                model = _model(label)
                field = "user_id"
                targets[label] = _ids(model._base_manager.filter(**{f"{field}__in": candidate_user_ids}))
            # Rebuild children whose parent target changed.
            social_accounts = _model("socialaccount.SocialAccount").objects.filter(
                pk__in=targets["socialaccount.SocialAccount"]
            )
            targets["socialaccount.SocialToken"] = _ids(
                _model("socialaccount.SocialToken").objects.filter(account__in=social_accounts)
            )
            email_addresses = _model("account.EmailAddress").objects.filter(
                pk__in=targets["account.EmailAddress"]
            )
            targets["account.EmailConfirmation"] = _ids(
                _model("account.EmailConfirmation").objects.filter(email_address__in=email_addresses)
            )
            targets["sessions.Session"] = self._candidate_session_keys(candidate_user_ids)

        targets["auth.User"] = sorted(candidate_user_ids)
        targets = OrderedDict((label, targets.get(label, [])) for label in DELETE_ORDER)

        files, shared_files = self._file_references(targets)
        accounts = []
        for user in User.objects.order_by("pk"):
            if user.pk in preserve_user_ids:
                classification = "PRESERVE"
                reason = "staff/superuser or Farm Owners role"
            elif user.pk in candidate_user_ids:
                classification = "PROPOSED_REMOVE"
                reason = "beta account with beta dependents; no preserved smart-farm inventory"
            else:
                classification = "REQUIRES_REVIEW"
                reason = "owns or is protected by operational/ambiguous data"
            accounts.append({
                "id": user.pk,
                "username": user.get_username(),
                "groups": sorted(user.groups.values_list("name", flat=True)),
                "classification": classification,
                "reason": reason,
            })

        plan = {
            "version": PLAN_VERSION,
            "database": EXPECTED_DATABASE,
            "settings": EXPECTED_SETTINGS,
            "preserve_user_ids": sorted(preserve_user_ids),
            "explicit_remove_user_ids": sorted(explicit_remove),
            "review_user_ids": sorted(review_user_ids),
            "accounts": accounts,
            "targets": targets,
            "files": files,
            "shared_files_preserved": shared_files,
            "preserved_configuration": list(PRESERVED_CONFIGURATION),
            "blockers": {str(key): value for key, value in sorted(blockers.items())},
            "generated_at": timezone.now().isoformat(),
        }
        plan["sha256"] = _plan_hash(plan)
        return plan

    def _candidate_session_keys(self, candidate_user_ids):
        Session = _model("sessions.Session")
        keys = []
        for session in Session.objects.all():
            try:
                user_id = int(session.get_decoded().get("_auth_user_id", 0) or 0)
            except (TypeError, ValueError):
                user_id = 0
            if user_id in candidate_user_ids:
                keys.append(session.pk)
        return sorted(keys)

    def _user_blockers(self, user_ids, selected_community_goats):
        """Return remaining known PROTECT relationships for proposed users."""
        checks = (
            ("iot.Goat", "owner_id", Q(record_source="smart_farm")),
            ("marketplace.SellerProfile", "user_id", ~Q(pk__in=_ids(_model("marketplace.SellerProfile").objects.all()))),
            ("marketplace.MarketplaceListing", "seller_id", ~Q(pk__in=_ids(_model("marketplace.MarketplaceListing").objects.all()))),
            ("marketplace.Conversation", "buyer_id", ~Q(pk__in=_ids(_model("marketplace.Conversation").objects.all()))),
            ("marketplace.Message", "sender_id", ~Q(pk__in=_ids(_model("marketplace.Message").objects.all()))),
            ("marketplace.Reservation", "buyer_id", ~Q(pk__in=_ids(_model("marketplace.Reservation").objects.all()))),
            ("marketplace.MarketplaceReport", "reporter_id", ~Q(pk__in=_ids(_model("marketplace.MarketplaceReport").objects.all()))),
            ("marketplace.SupportTicket", "user_id", ~Q(pk__in=_ids(_model("marketplace.SupportTicket").objects.all()))),
            ("marketplace.SupportMessage", "sender_id", ~Q(pk__in=_ids(_model("marketplace.SupportMessage").objects.all()))),
            ("marketplace.UserAccountState", "user_id", ~Q(pk__in=_ids(_model("marketplace.UserAccountState").objects.all()))),
            ("marketplace.UserActivity", "user_id", ~Q(pk__in=_ids(_model("marketplace.UserActivity").objects.all()))),
        )
        blockers = {}
        for label, field, extra in checks:
            model = _model(label)
            ids = model._base_manager.filter(**{f"{field}__in": user_ids}).filter(extra)
            for user_id in ids.values_list(field, flat=True).distinct():
                blockers.setdefault(user_id, []).append(label)
        return blockers

    def _file_references(self, targets):
        selected_files = []
        all_references = {}
        selected_keys = {
            (label, str(pk)) for label, pks in targets.items() for pk in pks
        }

        # Index every database-backed upload by its resolved storage path. This
        # prevents a selected row from moving a file that a preserved row shares.
        for model in apps.get_models():
            file_fields = [
                field for field in model._meta.concrete_fields
                if field.get_internal_type() in {"FileField", "ImageField"}
            ]
            if not file_fields:
                continue
            label = model._meta.label
            for obj in model._base_manager.all():
                for field in file_fields:
                    value = getattr(obj, field.name)
                    if not value or not value.name:
                        continue
                    try:
                        path = str(Path(value.path).resolve())
                    except (NotImplementedError, ValueError):
                        path = ""
                    if path:
                        all_references.setdefault(path, []).append(
                            (label, str(obj.pk), field.name)
                        )

        for label, pks in targets.items():
            if not pks or label == "sessions.Session":
                continue
            model = _model(label)
            file_fields = [
                field for field in model._meta.concrete_fields
                if field.get_internal_type() in {"FileField", "ImageField"}
            ]
            if not file_fields:
                continue
            for obj in model._base_manager.filter(pk__in=pks):
                for field in file_fields:
                    value = getattr(obj, field.name)
                    if not value or not value.name:
                        continue
                    try:
                        path = str(Path(value.path).resolve())
                    except (NotImplementedError, ValueError):
                        path = ""
                    selected_files.append({
                        "model": label, "pk": obj.pk, "field": field.name,
                        "name": value.name, "path": path,
                    })
        exclusive = []
        shared = []
        for item in selected_files:
            preserved_refs = [
                ref for ref in all_references.get(item["path"], [])
                if (ref[0], ref[1]) not in selected_keys
            ]
            if preserved_refs:
                shared.append({
                    "model": item["model"], "pk": item["pk"],
                    "field": item["field"], "preserved_reference_count": len(preserved_refs),
                })
            else:
                exclusive.append(item)
        key = lambda item: (item["model"], str(item["pk"]), item["field"])
        return sorted(exclusive, key=key), sorted(shared, key=key)

    def _print_plan(self, plan):
        self.stdout.write("BETA CLEANUP DRY RUN — ZERO DATABASE CHANGES")
        self.stdout.write(f"Database: {plan['database']}")
        self.stdout.write("Accounts:")
        for account in plan["accounts"]:
            groups = ", ".join(account["groups"]) or "none"
            self.stdout.write(
                f"  [{account['classification']}] id={account['id']} "
                f"username={account['username']} groups={groups}"
            )
        self.stdout.write("Proposed database removals:")
        for label, pks in plan["targets"].items():
            self.stdout.write(f"  {label}: {len(pks)}")
        self.stdout.write(f"Files proposed for quarantine: {len(plan['files'])}")
        self.stdout.write(
            f"Shared files deliberately preserved: {len(plan['shared_files_preserved'])}"
        )
        if plan["review_user_ids"]:
            self.stdout.write(f"Users requiring review: {plan['review_user_ids']}")
        if plan["blockers"]:
            self.stdout.write(f"Deletion blockers: {plan['blockers']}")
        self.stdout.write("Preserved configuration:")
        for item in plan["preserved_configuration"]:
            self.stdout.write(f"  {item}")
        self.stdout.write(f"APPROVAL SHA256: {plan['sha256']}")

    def _write_plan(self, plan, path):
        path = path.resolve()
        if path.exists():
            raise CommandError(f"Refusing to overwrite existing plan: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(plan, stream, indent=2, sort_keys=True)
            stream.write("\n")
        self.stdout.write(f"Private frozen plan written to {path}")

    def _confirm(self, plan_path, approved_hash, backup_reference, quarantine_dir):
        if not all((plan_path, approved_hash, backup_reference, quarantine_dir)):
            raise CommandError(
                "--confirm requires --approved-plan, --approved-sha256, "
                "--backup-reference, and --quarantine-dir."
            )
        plan_path = Path(plan_path).resolve()
        with plan_path.open(encoding="utf-8") as stream:
            approved = json.load(stream)
        if approved.get("sha256") != approved_hash or _plan_hash(approved) != approved_hash:
            raise CommandError("Approved plan hash does not match the plan contents.")

        backup = Path(backup_reference).resolve()
        self._verify_backup(backup)

        current = self._build_plan(
            set(approved.get("preserve_user_ids", [])),
            set(approved.get("explicit_remove_user_ids", [])),
        )
        if _canonical_payload(current) != _canonical_payload(approved):
            raise CommandError(
                "Live beta data differs from the approved dry run; refusing cleanup. "
                "Generate and review a new plan."
            )

        quarantine = Path(quarantine_dir).resolve()
        active_roots = [
            Path(settings.MEDIA_ROOT).resolve(),
            Path(settings.PRIVATE_SUPPORT_ROOT).resolve(),
            Path(getattr(settings, "PROTECTED_MODELS_ROOT", settings.MEDIA_ROOT)).resolve(),
        ]
        if any(quarantine == root or root in quarantine.parents for root in active_roots):
            raise CommandError("Quarantine directory must be outside active storage roots.")
        if quarantine.exists():
            raise CommandError("Quarantine directory must not already exist.")

        with transaction.atomic():
            for label in DELETE_ORDER:
                pks = approved["targets"].get(label, [])
                if pks:
                    _model(label)._base_manager.filter(pk__in=pks).delete()

        quarantine.mkdir(parents=True, mode=0o700)
        moved = 0
        for item in approved["files"]:
            source = Path(item["path"])
            if not item["path"] or not source.is_file():
                continue
            destination = (
                quarantine / item["model"].replace(".", "_") /
                str(item["pk"]) / item["field"] / source.name
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
            moved += 1
        self.stdout.write(self.style.SUCCESS(
            f"Approved cleanup completed; {moved} files moved to quarantine."
        ))

    def _verify_backup(self, backup):
        manifest_path = backup / "backup.json"
        if not backup.is_dir() or not manifest_path.is_file():
            raise CommandError("Backup reference is not a recognized recovery package.")
        try:
            with manifest_path.open(encoding="utf-8") as stream:
                manifest = json.load(stream)
        except (OSError, ValueError) as exc:
            raise CommandError("Backup manifest cannot be read.") from exc
        if (
            manifest.get("format") != "gohmotech-production-transition-backup-v1"
            or manifest.get("database") != EXPECTED_DATABASE
        ):
            raise CommandError("Backup manifest has the wrong format or database.")
        required = {"database.sql", "uploads.tar.gz", "environment.env", "deployment-config.tar.gz"}
        artifacts = manifest.get("artifacts", {})
        if not required.issubset(artifacts):
            raise CommandError("Backup recovery package is missing required artifacts.")
        for name in required:
            path = (backup / name).resolve()
            if backup not in path.parents or not path.is_file() or path.stat().st_size == 0:
                raise CommandError(f"Backup artifact is missing or empty: {name}")
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            metadata = artifacts[name]
            if digest.hexdigest() != metadata.get("sha256") or path.stat().st_size != metadata.get("bytes"):
                raise CommandError(f"Backup checksum/size verification failed: {name}")
